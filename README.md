# RouteResilience

An interactive road-network resilience workspace. Explore real OpenStreetMap roads on a map,
select a road, close it, see how routes and connectivity change, restore it, and compare the
network states. The research pipeline's DeepGlobe road-segmentation model runs in a separate
Segmentation Lab.

**Demo journey:** Explore the map → select a road → close it → inspect the disruption → find an
alternate route → restore the road → compare resilience across steps (and save the run).

> Every number in the app is computed from the loaded data (OSM graph, DeepGlobe images,
> checkpoints) or read from a labelled notebook artifact. Estimates are labelled as estimates.
> When something is missing, the UI says what and why. There are no mock values.

---

## What's inside

| Workspace | What it does |
|---|---|
| **Map** (home) | MapLibre map of drivable OSM roads at their real coordinates. Search, layers and legend, fit/reset/zoom, road and intersection inspection, A→B routing, close and restore roads (multiple at once), detour and disconnection analysis, cut-off and regained roads, a failure/recovery timeline with chart, critical-road ranking (sampled betweenness, bridges, articulation points), save runs, PNG map export |
| **Segmentation Lab** | Browse local DeepGlobe images (Phase I split reproduced exactly). Run DeepLabV3+ inference with the Phase I checkpoint, view overlay (with opacity), side-by-side and error map. See IoU/Dice/precision/recall when ground truth exists (held-out vs in-sample labelled), and agreement with the mask the notebook saved. Incompatible checkpoints show why they can't run |
| **Reports** | Saved runs (inputs + server-recomputed metrics per step), charts, step tables, JSON/CSV/Markdown export, the unsaved current session, and the historical notebook pipeline runs |

## Requirements

* Windows 10/11 (also macOS/Linux), Python **3.10+** (tested 3.11.4), Node.js **18+** (tested 24.15)
* `southern-zone-261011.osm.pbf` (or any .osm.pbf) in the repository root
* Optional: `deepgloberoad/` (DeepGlobe Road Extraction dataset) and `checkpoints-*/checkpoints/*.pth` for the Segmentation Lab
* Internet is needed only for basemap tiles. Without it, roads still render on a plain background.

## Install (PowerShell)

```powershell
cd D:\routeresilience

# Backend — core (map, routing, simulation, reports)
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Backend — Segmentation Lab (optional, ~1 GB, CPU wheels)
.\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt
cd ..

# Frontend
cd frontend
npm install
npm run build
cd ..
```

## One-time: build the road index

The PBF covers all of Southern India (~560 MB). It is **never** loaded into the browser or into
memory as a whole. A one-time scan stores the drivable roads of a configurable extent (central
Chennai by default) in a small SQLite + R-tree index (`.cache/routeresilience/osm_roads.sqlite`).
Map regions are then loaded from that index in under a second.

```powershell
cd D:\routeresilience\backend
.\.venv\Scripts\python.exe -m app.geo.cli index            # default extent: 80.15,12.95 → 80.32,13.16 (~6–7 min)
.\.venv\Scripts\python.exe -m app.geo.cli status           # list indexed extents
.\.venv\Scripts\python.exe -m app.geo.cli index --bbox 80.10,12.90,80.14,12.94   # add another area
```

You can also skip this step. On first start the Map shows a **Build road index** button that
runs the same scan in the background with progress, and **Index this view** adds the area you
are looking at.

## Run

**Single process (recommended):** the backend serves the built frontend.

```powershell
cd D:\routeresilience\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. API docs are at http://127.0.0.1:8000/docs.

**Development (hot reload, two terminals):**

```powershell
# 1 — API
cd D:\routeresilience\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# 2 — UI (proxies /api to :8000)
cd D:\routeresilience\frontend
npm run dev          # http://localhost:5173
```

## Using the map

1. The default region (Alwarpet · Gopalapuram · Kodambakkam, ~5.4 × 5 km, ~7,800 road segments) loads automatically. Pan elsewhere inside the indexed extent and press **Load roads in view** to change areas (up to 0.25° × 0.25°).
2. **Set A** and **Set B** (toolbar or Simulate tab), then click the map. Points snap to the nearest intersection of the main network.
3. Click a road to inspect it, or pick one from **Roads on this route**, a search result, or the **Critical** ranking. Then press **Close road**.
4. Read the result: the green alternate route against the dashed baseline, the detour in m and %, or **No route** when the destination becomes unreachable. Violet roads are cut off from the main network.
5. **Restore** a road (teal shows regained connectivity) or **Restore all**. The timeline chart and table track every step.
6. **Save run**: the server recomputes every step from the stored actions. Export JSON/CSV/Markdown from the panel or from Reports.

### Map styling

| Style | Meaning |
|---|---|
| Grey roads (brightness/width by OSM class) | normal road segments; arrows = one-way (zoom ≥ 16) |
| Cyan | selected road / intersection |
| Red | closed (failed) road |
| Dashed white | baseline route on the intact network |
| Green | current (alternate) route |
| Amber dots | critical intersections (top-25 sampled betweenness; white ring = articulation point) |
| Yellow → red ramp | road criticality layer (sampled betweenness) |
| Violet | cut off from the main network, or unreachable from A |
| Teal | connectivity regained after a restore |

## Methods (short)

* **Graph:** OSM ways with motor-vehicle `highway` classes are split at shared nodes into **segments** (`way_id:k`, stable IDs shared by map features and graph edges). Directed edges follow `oneway`, roundabouts and motorway rules. Parallel roads stay separate segments.
* **Routing:** Dijkstra on the directed graph. The edge weight is the great-circle **length in metres**. There are no travel times, so routes are *shortest*, not *fastest*.
* **Cut-off nodes:** nodes of the intact network's largest strongly connected component that can no longer both reach and be reached from it. Exact, whole region.
* **Reachable from A:** intersections reachable from A by a legal route. Exact.
* **Sampled reachability / efficiency (estimates):** 24 fixed random origins × 400 targets (seed 7). Efficiency = Σ 1/d relative to the intact network, with 1/∞ = 0.
* **Critical roads:** share of shortest paths from 160 sampled origins that cross each segment (Brandes accumulation on shortest-path trees). The top 15 also get an exact single-closure impact. Bridges and articulation points come from the undirected graph. This is structural importance, **not** traffic.

Full details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Data audit: [docs/ARTIFACT_AUDIT.md](docs/ARTIFACT_AUDIT.md).

## Configuration

Copy `.env.example` to `.env` (repository root). All settings are optional:
`ROUTERESILIENCE_OSM_PBF`, `_CACHE_DIR`, `_OSM_EXTENT`, `_DEFAULT_REGION`, `_MAX_REGION_SEGMENTS`,
`_DEEPGLOBE_DIR`, `_CHECKPOINTS_DIR`, `_OUTPUTS_DIR`, `_STATE_DIR`, `_DATA_DIR`, `_CORS_ORIGINS`.

## API (main endpoints)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/geo/status` | PBF, index extents, index-build job progress |
| POST | `/api/geo/index` | start an index build `{bbox?}` (background, one at a time) |
| POST | `/api/geo/regions` | load a region `{bbox?}` → id, summary, named places |
| GET | `/api/geo/regions/{id}/roads` · `/intersections` | GeoJSON (real lon/lat) |
| GET | `/api/geo/regions/{id}/segments/{sid}` · `/nodes/{nid}` | inspection |
| POST | `/api/geo/regions/{id}/evaluate` | `{failed[], origin?, destination?}` → network, sampled, route results |
| POST/GET | `/api/geo/regions/{id}/analysis` | critical-road analysis job / result |
| GET | `/api/geo/search?q=&region_id=` | road names in the region and OSM places in the index |
| POST/GET/DELETE | `/api/runs`, `/api/runs/{id}` | save (server recomputes), list, get, delete runs |
| GET | `/api/runs/{id}/export?format=json\|csv\|md` | run export / report |
| GET | `/api/lab/samples`, `/api/lab/models` | DeepGlobe images; checkpoint compatibility |
| POST | `/api/lab/infer` | `{model_id, image_id}` → metrics + mask/overlay/error PNGs |
| GET | `/api/health`, `/api/experiments` | status; historical notebook runs (plus the earlier pixel-graph API, see ARCHITECTURE) |

Errors are `{"detail", "code"}`, for example `not_indexed`, `index_missing`, `region_too_large`,
`region_not_loaded`, `checkpoint_incompatible`, `dataset_missing`, and 422 validation errors.

## Tests

```powershell
cd D:\routeresilience\backend
.\.venv\Scripts\python.exe -m pytest          # 86 tests; real-data checks skip if data is absent
cd ..\frontend
npm test                                      # unit/component tests
npm run typecheck
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| "The OSM road index has not been built yet" | Run `python -m app.geo.cli index`, or press **Build road index** in the Region card. |
| "This area is outside every indexed extent" | Press **Index this view**, or `cli index --bbox …`. |
| "Region spans more than 0.25°" / too many segments | Zoom in and press **Load roads in view** again. |
| Basemap warning / grey background | Tiles are offline or blocked. Roads and all analysis still work. Pick **None** for a clean background. |
| Segmentation Lab: "PyTorch is not installed" | Install the optional ML requirements (see Install). |
| DenseDSSPP / UNeXt "not loadable" | Expected: their architecture code is not in the repository (see docs/ARTIFACT_AUDIT.md). |
| Map image export fails | The selected basemap blocks canvas export. Switch to **Dark** or **None**. |
| `Activate.ps1 cannot be loaded` | No activation needed: call `.\.venv\Scripts\python.exe` directly. |
| Port in use | `--port 8010`, and for dev `$env:VITE_API_PROXY="http://127.0.0.1:8010"; npm run dev`. |

## Known limitations

* **Distance-based routing only.** OSM has no reliable travel times here. Turn restrictions, access tags beyond `access=no/private`, and capacity are not modelled.
* A region includes the OSM ways that intersect its box. Alternate routes that leave the box are not seen, so "no route" means no route *within the loaded region*.
* Network-wide reachability and efficiency figures are **sampled estimates**. Cut-off nodes, routes and reachability from A are exact.
* No repair times, costs or traffic impacts are modelled. Restoring a road just puts the segment back in the graph.
* Basemaps: CARTO tiles now require an API key, so the keyless Esri Dark Gray Canvas is used (native to z16, over-zoomed above). OSM Standard and Esri imagery are optional.
* The DeepGlobe tiles carry no georeference, so the Segmentation Lab is intentionally separate from the OSM map. Only DeepLabV3+ can run inference. App inference agrees with the notebook's saved masks at ~96% IoU (interpolation differences), not bit-for-bit.
* The old pixel-graph artifact dashboard was retired from the UI. Its API remains for the historical runs listed in Reports.
