# RouteResilience — Architecture

## 1. System overview

```
 southern-zone-*.osm.pbf ──(one-time scan, pyosmium + disk location index)──► .cache/routeresilience/osm_roads.sqlite
                                                                              (ways + R*Tree + places, per extent)
                                         │ bbox query (< 0.5 s)
 app/geo/network.py   RoadNetwork: segments (way:k), directed edges (one-way rules), SciPy CSR,
                      Dijkstra routing, components, cut-off analysis, sampled OD metrics, sampled betweenness
 app/geo/service.py   region cache (LRU 4), background analysis jobs, GeoJSON, search
 app/services/runs.py saved runs (server re-evaluates every step) + CSV/Markdown reports
 app/services/lab.py  DeepGlobe split reproduction + DeepLabV3+ inference (checkpoint compatibility gate)
 app/routes/geo.py, workspace.py  (FastAPI, Pydantic validation, structured errors)
                                         │ JSON / GeoJSON / PNG / CSV / Markdown
 frontend/  React + Vite + TypeScript + Tailwind + MapLibre GL + Recharts
            state/workspace.tsx (region, failures, timeline, O/D)  ·  map/MapView.tsx (layers, feature-state)
            pages/MapWorkspace · Lab · Reports
```

| Concern | Module | Notes |
|---|---|---|
| Geographic ingestion | `geo/osm_index.py` | PBF → SQLite, extent-scoped, progress via `IndexJob`; CLI `python -m app.geo.cli` |
| Graph construction | `geo/network.py` `split_ways`, `RoadNetwork.__post_init__` | segment IDs are the shared key between map features and graph edges |
| Routing + failure simulation | `RoadNetwork.evaluate` | stateless: failures are passed per request, so no server state can drift |
| Resilience metrics | `RoadNetwork.evaluate`, `sampled_betweenness`, `service.undirected_structure` | exact vs sampled values are labelled separately |
| Model inference | `services/lab.py`, `services/checkpoints.py` | strict-load gate, warm-up, Phase I preprocessing |
| Map rendering | `frontend/src/map/*` | one GeoJSON source + feature-state for selected/failed/affected/regained/criticality |
| Simulation state + reports | `frontend/src/state/workspace.tsx`, `services/runs.py` | client keeps the timeline; saving re-evaluates server-side |

## 2. OSM ingestion

* `osmium.FileProcessor(pbf).with_locations(sparse_file_array).with_filter(KeyFilter("highway","place"))`.
  The location handler runs before the tag filter, so every way gets resolved coordinates. Node
  locations live in a memory-mapped temporary file (~1.3 GB for this PBF), deleted afterwards.
* Kept: `highway` in {motorway…tertiary (+ _link), unclassified, residential, living_street, service, road}, minus
  `service` in {parking_aisle, driveway, drive-through} and `access` in {no, private}. Each way intersecting the
  extent is stored **whole** (node IDs + lon/lat as packed arrays), with its bounding box in an R*Tree.
* Named places (`place` = city…locality) inside the extent are stored for search and region labels.
* Measured: central-Chennai extent (18 × 23 km) → 42,392 ways and 439 places in 396 s, 9 MB index.
* Several extents can be added. Each scan reads the whole file. A region loads only the ways that
  intersect its box. Its `coverage` is `full` when an indexed extent contains it, `partial` otherwise.

## 3. Road graph and routing

* **Segments:** each way is cut at nodes shared with another way, at its endpoints, and at repeated nodes;
  a closed loop piece is split in the middle (no self-loops). ID = `"{way_id}:{k}"`.
* **Direction:** `oneway=yes|true|1` → forward, `-1|reverse` → backward, `no|reversible|alternating` → both
  (reversible treated as two-way), `junction=roundabout|circular` → forward,
  `highway=motorway|motorway_link` → forward unless `oneway=no`.
* **Weight:** haversine length of the segment polyline in metres. Routing = SciPy `dijkstra` on a CSR matrix of
  the active directed edges. **Parallel edges are reduced to the minimum length** (lexsort + first-of-group)
  before the matrix is built, because SciPy would sum duplicate entries. The segment that realizes each
  hop is kept, so a path maps back to segment IDs and to geometry in travel direction.
* **Snapping:** origin and destination snap to the nearest node of the intact network's largest strongly
  connected component (KD-tree, local equirectangular projection). The snap distance is reported.

## 4. Failure, recovery and metrics

`evaluate(failed, origin, destination)` is a pure function of its inputs, so recovery is exact:
`failed=[]` returns the cached baseline, and tests assert equality after fail → restore.

| Metric | Definition | Exact / estimate |
|---|---|---|
| Weak / strong components | SciPy `connected_components` on the directed graph | exact |
| Cut-off nodes | nodes of the baseline largest SCC that are not in the current SCC with the largest overlap with it | exact |
| Affected segments / km | non-failed segments with a cut-off endpoint | exact |
| Route baseline / current, detour m and % | Dijkstra distance A→B on intact vs failed graph | exact |
| Reachable from A, unreachable segments | finite-distance nodes from A; segments whose ends both became unreachable | exact |
| Sampled reachability | share of 24 × 400 fixed (seed 7) origin→target pairs with a finite distance | estimate |
| Sampled efficiency retention | Σ 1/d_after ÷ Σ 1/d_baseline over those pairs (1/∞ = 0) | estimate |
| Mean / max detour | mean of d_after / d_baseline − 1 over pairs reachable in both states | estimate |
| Road criticality | Brandes accumulation over shortest-path trees from 160 sampled origins (seed 11), normalised by paths counted | estimate |
| Single-closure impact (top 15) | full `evaluate([sid])` | exact |
| Bridges / articulation points | NetworkX on the undirected simple graph; node pairs joined by parallel segments are not bridges | exact |

Measured on the default region (7,794 segments, 5,947 nodes): load 0.4 s, evaluate 20–70 ms, criticality job 3.4 s.

## 5. Runs and reports

The client keeps the timeline (each step holds a full evaluation). **Saving** sends only the inputs
(bbox, A/B, ordered fail/restore/reset actions). The server reloads the region and re-evaluates every
step, so stored results cannot contain browser-side values. Runs are JSON files in `backend/state/runs/`
(atomic writes). Exports: JSON, CSV (one row per step), and a Markdown report with parameters, results,
metric definitions and limitations.

## 6. Segmentation lab

* Dataset index: `deepgloberoad/{train,valid,test}`. Only `train/` has masks. The Phase I split is reproduced
  (sorted paired IDs, `random.seed(42)`, shuffle, 80/20) and checked against the 44 masks Phase I wrote
  (`val_ids[:40]` + 4 demo tiles): **match confirmed**.
* Inference: strict-loaded smp `DeepLabV3Plus(resnet34)`, one warm-up pass, bilinear resize to 512²,
  ImageNet normalisation, sigmoid > 0.5, nearest resize back. Outputs are cached in memory (LRU 24).
* Metrics (TP/FP/FN, IoU, Dice, precision, recall) only where ground truth exists, labelled *held-out*
  or *in-sample*. A reproducibility check reports IoU against the Phase I saved mask (~96%).
* DenseDSSPP and UNeXt fail the compatibility gate with explicit diagnostics (architecture code missing).

## 7. Frontend

* `MapView` creates one MapLibre map. Setup runs on `style.load`, so roads and interaction never wait for
  basemap tiles. Road state is applied through **feature-state** diffs (no GeoJSON re-uploads).
* Basemaps (keyless): Esri Dark Gray Canvas (+ labels), OSM Standard, Esri World Imagery, or none. CARTO was
  evaluated and rejected because its tiles now require an API key. Tile failures show a warning, and the
  OSM road layer keeps working.
* `WorkspaceProvider` serialises backend operations. User actions are disabled while one runs, and A/B changes
  are queued and recompute the whole timeline for the new pair.

## 8. Testing

* `tests/test_geo.py`: one-way semantics, splitting and stable IDs, loop splitting, exact detour arithmetic,
  exact restore, disconnection reporting, one-way routing, parallel-edge minimum (not sum), unknown IDs,
  betweenness bottleneck, API (region / evaluate / search / validation / errors / analysis / runs / exports /
  missing index), and a real Chennai fail-and-restore check.
* `tests/test_lab.py`: confusion-metric arithmetic, split reproduction, error codes, real inference vs the Phase I mask.
* Earlier suites (`test_analysis`, `test_graph_io`, `test_api`, `test_real_artifacts`) cover the legacy pipeline API.
* Frontend (Vitest): API client errors; the workspace state machine (fail / restore / regained, rejected steps
  keep state, no duplicate closures); Reports and Lab empty, error and compatibility states.
* End-to-end runs (Playwright against the running app with real data) covered the full journey, blocked basemap
  tiles, an evaluate outage, an area outside the index, and tablet/phone layouts.

---

## Appendix: legacy pixel-graph pipeline API

The first version of this app explored the notebooks' pixel-space graphs (Phase II/III outputs). Its
dashboard UI has been retired. The API (`/api/graphs/*`, `/api/models/*`, `/api/experiments`, `/api/figures/*`)
remains, because Reports lists the historical notebook runs and the audit relies on it. Its original
design notes follow.

### L1. Overview

```
 notebooks (Colab, unchanged) ──► timestamped artifact folders on disk (read-only)
                                        │
                     backend/app/registry.py  (discovery + ID→path map)
                                        │
          graph_io.py (schema adapter) ─┼─ services/notebooks.py (historical log parser)
                                        │
            analysis.py (NetworkX metrics, copy-only simulation)
                                        │
          services/*  (views, criticality, simulation, healing, exports, reviews)
                                        │
                  routes/* (FastAPI, Pydantic validation, /api/…)
                                        │  JSON / PNG / CSV / Markdown
                     frontend/ (React + Vite + Tailwind + Recharts + SVG network view)
```

* The **notebook pipeline is never touched**. The app only reads its outputs.
* The **backend** owns all file access and computation. The browser receives normalized
  JSON, PNGs served by ID, and download files.
* The **frontend** is a single-page app. In development Vite proxies `/api` to the backend.
  In "production" (local single-process mode) FastAPI serves `frontend/dist`.

### L2. Backend layout (`backend/app`)

| Module | Responsibility |
|---|---|
| `config.py` | Settings from `ROUTERESILIENCE_*` env vars / `.env`, plus limits. Default data dir = repo root. |
| `registry.py` | Finds `outputs*/` and `checkpoints*/` folders (newest timestamp wins) and indexes `graphs_*`, `masks_*`, `analysis_*`, figures, checkpoints and notebooks. IDs must match `^[A-Za-z0-9_]+$`; files with other names are ignored with a warning. |
| `graph_io.py` | Schema adapter: Phase II JSON and NetworkX node-link JSON → immutable `GraphDoc`; detects `[row,col]` vs `[x,y]`; healing provenance `recorded/partial/unavailable`; length fallbacks; frozen `nx.Graph` builder; RDP polyline simplification. |
| `analysis.py` | Metrics, betweenness, component membership, removal impact, sequential/adaptive removal. Pure functions; inputs are never mutated. |
| `definitions.py` | Metric definitions served at `/api/definitions` and embedded in reports. |
| `services/graphs.py` | Cache of loaded graphs keyed by `(path, mtime_ns, size)`. Cached graphs are **frozen** (`nx.freeze`) and derived values are returned as copies. |
| `services/notebooks.py` | Regex extraction of values literally printed in notebook outputs (training log, SAM repair log, synthetic test, sweep, Phase II config). |
| `services/views.py` | Graph payload (nodes with betweenness/rank/component, simplified polylines, mask underlay, provenance). |
| `services/criticality.py` | Ranked junctions + per-node removal impact, side by side with the historical Phase III values. |
| `services/simulation.py` | Failure scenarios (single, sequential, top-k static/adaptive) on `G.copy()`. |
| `services/healing.py` | Pre-healing vs healed comparison, SAM mask comparison, review state. |
| `services/reviews.py` | Persistent bridge reviews in `state/healing_reviews.json` (atomic write, lock, refuses to overwrite a corrupt store). |
| `services/checkpoints.py` | `torch.load(weights_only=True)` inspection, key-layout family detection, strict load (DeepLabV3+ via smp), CPU latency on synthetic input. torch is optional. |
| `services/exports.py` | CSV/JSON exports, Markdown report, minimal Markdown→HTML. |
| `services/experiments.py` | Experiment history from artifacts + notebook logs. |
| `routes/*` | HTTP layer. Expensive work runs in the thread pool (`run_in_threadpool` or sync endpoints). |

### Safety

* **No path parameters reach the filesystem.** Every served file comes from a registry
  dictionary lookup on IDs that match a strict pattern. Graph IDs are `<set>-<image>`.
* Request bodies use `extra="forbid"` Pydantic models with ID patterns, list caps
  (500), duplicate checks and `k ≤ 100`. Service limits: `max_removals=200`,
  `max_sequential_steps=50`, `max_graph_nodes=5000` (HTTP 413 above that).
* Error mapping: unknown graph → 404 `graph_not_found`; corrupt or invalid artifact → 422
  `artifact_invalid_json` / `artifact_invalid_schema`; bad targets → 400
  `invalid_target`; too large → 413; corrupt review store → 500 `review_store_error`.
* Checkpoints are only opened with `weights_only=True`, so no pickled code runs.

### L3. Frontend layout (retired) (`frontend/src`)

| Path | Responsibility |
|---|---|
| `api/client.ts`, `api/types.ts` | Typed fetch client; `ApiError` carries status + backend `code`. |
| `api/useApi.ts` | Small data hook (loading / error / reload, ignores stale responses). |
| `context/Selection.tsx` | Global graph selection, synced to `?graph=` and localStorage; never exposes an unknown ID. |
| `components/NetworkView.tsx` | SVG network renderer with pan, zoom, hit targets, tooltips, mask underlay, highlight layers (selection, neighbors, path, removed, component membership). |
| `components/charts.tsx` | Recharts wrappers with tooltips and a chart/table toggle. |
| `components/ui.tsx` | Panels, KPI tiles, provenance badges, empty and error states. |
| `pages/*` | Overview, Segmentation Lab, Network Explorer, Critical Junctions, Failure Simulation, Healing Review, Experiments & Reports. |

**Why a custom SVG renderer instead of Cytoscape/Sigma:** the graphs are small (≤ 250
nodes, ≤ 213 edges per tile), and their edges are real road polylines in pixel space that
must line up with the mask image underneath. A plain SVG `viewBox` gives exact image
alignment, polyline edges, and pan/zoom in about 300 lines, with no extra dependency.
For much larger graphs, swap in a WebGL renderer (Sigma.js) behind the same props.

### L4. Data flow and provenance labels

Every value shown in the UI carries one of these labels:

* **Notebook artifact** (historical): read from a saved file or a printed notebook output.
* **Recomputed**: computed by the backend from the artifacts on each request (cached by file version).
* **Measured by app**: measured live (checkpoint inspection, CPU latency).

When something is missing, the UI shows an explicit empty state that says why (for example
no ground truth, no healing provenance, or architecture code not in the repository). No placeholder values are ever shown.

### L5. Metric definitions

N₀ = node count of the **baseline** graph. d(i,j) = shortest-path length along the edge
attribute `length` (pixels; Phase II `weight`), and d = ∞ for disconnected pairs or removed nodes.

| Metric | Formula | Disconnected pairs |
|---|---|---|
| Components | number of connected components (isolates count) | — |
| LCC fraction | \|LCC\| / N₀ | — |
| Reachable pair fraction | Σ_C \|C\|(\|C\|−1)/2 ÷ N₀(N₀−1)/2 | count as unreachable |
| Avg shortest path | mean d(i,j) over pairs with d < ∞ | **excluded** (None if no finite pair) |
| Global efficiency E | 1/(N₀(N₀−1)) · Σ_{i≠j} 1/d(i,j) | contribute 0 |
| **Resilience score ρ** | E_after / E_baseline ∈ [0, 1] | via E |
| Degradation | 1 − ρ | — |
| Pair connectivity retention | reachable_pair_fraction_after / …_baseline | — |
| Betweenness | NetworkX, `weight="length"`, `normalized=True`; scope `full` (default) or `lcc` (Phase III) | pairs in different components contribute nothing |

Why ρ instead of the Phase III index: removing a node or edge can only lengthen or break
shortest paths, so every 1/d term shrinks or vanishes. With the normalization fixed at N₀, ρ is
therefore bounded in [0, 1] and monotone non-increasing under removals. Both properties
are covered by unit tests. The Phase III index `L_baseline / L_perturbed` has neither: on
a 5-node path, removing the middle node lowers the reachable-pair average path from 2.0 to 1.0,
so the legacy index *doubles* while ρ falls to 0.31 (`tests/test_analysis.py`).

### L6. Caching and immutability

* `LoadedGraph` objects are cached (LRU 64), keyed by file path + mtime + size, so an edited
  file is reloaded automatically.
* Both graph variants (`healed`, `original` = healed edges removed) are frozen.
  Simulations call `G.copy()`, which returns a new, mutable graph. Tests assert that the
  source graph is unchanged and that mutating a cached graph raises.
* Derived values (metrics, betweenness, membership) are memoized per `(graph, version, variant)`
  and handed out as copies.

### L7. Testing

* `backend/tests/test_analysis.py`: formulas on a path graph, a star, two triangles joined
  by a bridge, and disconnected graphs (exact hand-computed values); immutability;
  sequential and adaptive removal; limits.
* `backend/tests/test_graph_io.py`: schema adapter, coordinate order, attribute
  preservation, provenance states, corrupt and invalid files, RDP.
* `backend/tests/test_api.py`: every endpoint family, validation, error codes, path
  traversal, exports checked against API values, review persistence, corrupt review store,
  missing outputs folder.
* `backend/tests/test_real_artifacts.py`: when the real artifacts are present, checks that all 88
  graphs reproduce their stored connectivity stats and that the Phase III betweenness values are
  reproduced.
* `frontend/src/test/*`: API client error handling, formatters, CSV helpers, and page empty
  and error states with a mocked API.
