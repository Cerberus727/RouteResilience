# RouteResilience — Artifact Audit

Audit date: 2026-10-13. Everything below was checked against the files on disk
(`D:\routeresilience`) and the saved outputs inside the three notebooks. No
artifact was modified during the audit.

Legend: **usable** = the web app can read and use it as is; **historical** = a
value printed or saved by a notebook run, shown in the app labeled as such;
**recomputed** = the app computes it again from the artifacts.

---

## 1. Directory layout (actual names)

```
D:\routeresilience\
├── phase1_unified (1).ipynb            4.2 MB   segmentation training + inference + SAM repair
├── phase2_unified_(1) (2).ipynb       56 MB    skeleton -> graph -> healing
├── phase3_unified_(1).ipynb           86 MB    betweenness + node-removal ablation
├── checkpoints-20261012T165525Z-1-001\checkpoints\
│   ├── best_road_model_deeplabv3.pth           87.8 MB
│   ├── best_road_model_denseddsspp.pth         94.5 MB
│   ├── best_road_model_unext.pth                5.8 MB
│   ├── predictions_deeplabv3.png                (1440x1920 figure: satellite | GT | prediction, 4 tiles)
│   ├── predictions_denseddsspp_deeplab.png      (same layout)
│   ├── predictions_unext.png                    (same layout)
│   ├── training_curves_denseddsspp_deeplab.png  (loss + IoU curves, 30 epochs, image only)
│   └── training_curves_unext.png                (image only)
└── outputs-20261012T170249Z-1-001\outputs\
    ├── masks_deeplab\            44 x {id}_pred.png      1024x1024, values {0,255}
    ├── masks_denseddsspp\      1250 x {id}_pred.png      1024x1024, values {0,255}
    ├── masks_unext\               4 x {id}_pred.png      1024x1024, values {0,255}
    ├── masks_sam_repaired\        8 x {id}_pred.png + sam_repair_comparison.png
    ├── graphs_deeplabv3\         44 x {id}_graph.json
    ├── graphs_sam_repaired\      44 x {id}_graph.json
    ├── visualizations_deeplabv3\     44 x {id}_phase2.png
    ├── visualizations_sam_repaired\  44 x {id}_phase2.png
    ├── synthetic_tests_sam_repaired\ 44 x {id}_synth.png + 422265_sweep_grid.png
    ├── analysis_deeplabv3\       44 x {id}_criticality.json + deeplabv3_criticality_metrics.csv
    └── analysis_viz_deeplabv3\   44 x {id}_criticality.png + 21 x {id}_criticality_metrics.png
```

The names in the brief (`best_road_model_densed dssp...pth`, `masks_densed dssp...`)
are really `best_road_model_denseddsspp.pth` and `masks_denseddsspp`.

**There is no satellite imagery and no ground-truth mask anywhere in the
repository.** The notebooks downloaded DeepGlobe (`balraj98/deepglobe-road-extraction-dataset`)
to temporary Colab storage, so those files are gone. Satellite tiles and ground truth
appear only inside the composite PNG figures.

---

## 2. Notebooks

All three notebooks were run on Colab with Google Drive mounted at
`/content/drive/MyDrive/RouteResilience`. Every path in them is a Colab path.

### Phase I — `phase1_unified (1).ipynb` (30 cells)
* One notebook covers several model families, chosen with `MODEL_NAME`: `deeplabv3`, `unetpp`,
  `unext`, `segformer`, `dinov2`, `mfuser`. **The saved outputs are from the
  `deeplabv3` run only.**
* DeepGlobe split: seed 42, 80/20, 4980 train / 1246 val (printed).
* Loss: 0.4·BCE + 0.6·Dice. Metrics: IoU/Dice at threshold 0.5. Each IoU is averaged
  per batch and then over batches.
* **DeepLabV3+ training log is in the cell output** (cell 20): 30 epochs of train
  loss, train IoU, val loss and val IoU. Best val IoU **0.5856** (epoch 30). Trainable params
  22,437,457. The app parses this log from the notebook (historical).
* The curves cell (cell 23) failed with `NameError: name 'history' is not defined`,
  so **`training_curves_deeplabv3.png` was never written**. The numbers exist only in
  the log.
* Inference wrote 4 demo tiles + `val_ids[:40]` = 44 masks to `masks_deeplab`, which matches
  the 44 files on disk.
* SAM repair (cell 29) ran on 4 demo tiles (`493626, 477671, 422265, 194764`) and
  printed component counts before and after (e.g. `493626 | components 17->11`).
  **The `masks_sam_repaired` folder has 8 masks.** The other 4 (`109889, 127572,
  161528, 188924`) come from a run whose output is not in the notebook.
* The notebook has no code for **DenseDSSPP** and none for a UNeXt training run.

### Phase II — `phase2_unified_(1) (2).ipynb` (16 cells)
* Pipeline: morphological close, `remove_small_objects(80)`, skeletonize, then pixel-graph
  tracing (nodes are skeleton pixels with degree ≠ 2), `prune_spurs(15)`, then `heal_graph`.
* `heal_graph` in its current form **removed the UnionFind check** ("to allow
  intra-component loop healing"). A bridge can now join endpoints that are already in the same
  component, so healing can add loops as well as join components. The candidate rule:
  endpoint distance ≤ 40 px and angle ≤ 35°; weight = `dist + 0.5·angle`; each endpoint gets at most one bridge.
* **Important inconsistency:** the saved run has `MODEL_NAME = "sam_repaired"` but
  `MASK_DIR` is hard-coded to `.../outputs/masks_deeplab` (cell 8 output confirms
  `Mask dir : .../masks_deeplab`). **So `graphs_sam_repaired/` and
  `visualizations_sam_repaired/` were built from DeepLabV3+ masks, not SAM-repaired masks.**
  This also follows from the counts: 44 graphs but only 8 SAM-repaired masks. The
  app shows this graph set as *"sam_repaired (label) — built from masks_deeplab"*.
* `graphs_deeplabv3/` was written by an earlier run of the code that is not in the
  notebook. Node sets differ (e.g. 493626 has 194 nodes in `graphs_deeplabv3` and 250 in
  `graphs_sam_repaired`, and all 194 coordinates appear in the larger set).
* The synthetic occlusion test (cell 11) printed `Original/Broken/Healed` connectivity and
  bridge counts for **39 tiles**. The last one (188924) printed its stats but no figure,
  so the run looks interrupted. `synthetic_tests_sam_repaired/` nevertheless holds 44 PNGs,
  so 5 of them come from a run that is not logged. The app parses the 39 logged rows as
  historical data.
* The sweep (cell 12) printed "31/44 tiles (70.5%) needed at least one bridge; avg
  connectivity 0.263 -> 0.392" (historical).
* The final results table ends with `Avg connectivity: ` and no values. The averages were never printed.
* Some cells with outputs have `execution_count = null` (cells 8 and 11), so their
  outputs may come from an earlier kernel state.

### Phase III — `phase3_unified_(1).ipynb` (12 cells)
* Run with `MODEL_NAME = "deeplabv3"` on 44 graphs, analyzing **only the largest
  connected component** of each graph.
* Betweenness: `nx.betweenness_centrality(G, weight="weight", normalized=True)`.
* Ablation: removes each of the top-5 nodes one at a time and recomputes the average weighted shortest path
  over *reachable* pairs.
* **Resilience index (as implemented):** `R = L_baseline / L_perturbed`, and `R = 0`
  when `L_perturbed` is 0 or infinite. This is **not a sound degradation measure**:
  * when removing a node splits the network, the average over the remaining reachable pairs
    usually *drops* (only short within-island paths are left), so R goes *up*.
    109889: removing `n86` splits the LCC into 2 islands and gives R = 1.83.
  * graphs with 2 nodes get R = 0.0 (perturbed L = 0), the same value as "fully
    destroyed".
  * the docstring says "values > 1 mean network degraded". That is true only by accident of the
    effect above, and nothing bounds it.
  * the figures (`*_criticality_metrics.png`) call it "Resilience Index (APLS
    baseline)", but it is not APLS.
  The app shows these values as **historical** and uses its own documented metrics
  (see `ARCHITECTURE.md` §5).
* `analysis_viz_deeplabv3/*_criticality_metrics.png` (21 files) comes from code that is
  not in the notebook (an earlier version).
* The CSV `deeplabv3_criticality_metrics.csv` has 44 rows (+ header):
  `Network ID, Total Nodes, Total Edges, Baseline Path Length (L), Vulnerable Node ID,
  Max Centrality Score, Resilience Index, Islands After Failure`. Node/edge counts there
  are for the **largest component**, not the whole graph.

---

## 3. JSON schemas (checked on every file)

### `graphs_*/{id}_graph.json`
```jsonc
{
  "image_id": "109889",
  "model": "deeplabv3" | "sam_repaired",           // tag only, see the inconsistency above
  "nodes": [{"id": "n4", "x": 786, "y": 986, "degree": 2}],
  "edges": [{
    "id": "e4_50", "source": "n4", "target": "n50",
    "weight": 30.0,          // traced pixel-path length (len(path)); healed: dist + 0.5*angle
    "healed": false,         // true = bridge added by heal_graph
    "coords": [[row, col], ...]   // NOTE [y, x] order (row, col), not [x, y]
  }],
  "stats": {"num_nodes", "num_edges", "connectivity_before", "connectivity_after", "bridges_added"}
}
```
Results across all 88 graph files:
* no dangling edges, duplicate edges, duplicate edge IDs or isolated nodes;
* the `degree` field matches the recomputed degree for every node;
* `stats.num_nodes/num_edges` match the arrays; the count of `healed=true` edges = `bridges_added`;
* **recomputed `connectivity_before` (graph minus healed edges) and
  `connectivity_after` match the stored values on 88/88 files.** So the per-edge healing
  provenance is complete, and the app can rebuild the pre-healing graph exactly.
* the first and last `coords` points match the endpoint nodes' `(y, x)` on every edge;
* coordinates are pixel coordinates in the 1024x1024 mask frame (matching the
  mask PNGs). There is no georeferencing (no CRS or geotransform), so **a geographic map is not
  possible**. The app draws graphs in pixel space on top of the mask.

| Graph set | Files | Nodes (sum) | Edges (sum) | Healed edges | Graphs with >1 component | Max nodes |
|---|---|---|---|---|---|---|
| `graphs_deeplabv3` | 44 | 1778 | 1506 | 568 | 36 | 194 |
| `graphs_sam_repaired` | 44 | 2128 | 1639 | 512 | 37 | 250 |

### `analysis_deeplabv3/{id}_criticality.json`
```jsonc
{
  "image_id": "109889",
  "gatekeepers": [{"id": "n86", "betweenness": 0.5385, "rank": 1, "x": 889, "y": 402}],   // top-5 (fewer if LCC small)
  "edges": [{"id", "source", "target", "criticality", "healed", "coords"}],  // LCC edges; criticality = mean endpoint betweenness
  "metrics": {"baseline_avg_path_length", "perturbed_avg_path_length", "resilience_index",
              "baseline_connected_components", "connected_components"},
  "ablation_study": [{"removed_node", "avg_path_length", "connected_components",
                      "resilience_index", "rank", "betweenness"}]
}
```
* Recomputing betweenness on the LCC of `graphs_deeplabv3` **reproduces every
  stored gatekeeper score (44/44 files, tolerance 1e-3)**, and LCC edge counts match.
* There is no criticality analysis for `graphs_sam_repaired`. The app computes it on request.

---

## 4. Model checkpoints

All three are plain `state_dict` files (`OrderedDict` of tensors) that load with
`torch.load(..., weights_only=True)`. Trainable parameter counts below leave out BN running stats.

| Checkpoint | Keys | Parameters | Architecture (from key layout) | Code to rebuild it | Loadable with existing code? |
|---|---|---|---|---|---|
| `best_road_model_deeplabv3.pth` | 277 | 22,437,457 | `smp.DeepLabV3Plus(resnet34, os=16, atrous=(12,24,36))` | Phase I `build_model()` | **Yes, if `segmentation-models-pytorch` is installed** (not installed on this machine by default). The app tries a strict `load_state_dict`. |
| `best_road_model_unext.pth` | 101 | 1,471,921 | UNeXt (`encoder1..3`, `block1/2`, `patch_embed3/4`, `final`) | needs the external `UNeXt-pytorch/archs.py` repo, which Phase I clones and patches | **No** with the repository alone: the architecture code is not here. The app reports this. |
| `best_road_model_denseddsspp.pth` | 364 | 24,081,900 | Xception-style backbone (`backbone.body.block1..12`), dense depthwise-separable ASPP (`aspp.dense_branches.0..3`, input channels 2048→2432), SE block, DeepLabV3+-style decoder | **not present anywhere** (no notebook defines it) | **No.** The architecture definition is missing. The app reports this. |

DeepLabV3+ was verified during the audit: in an isolated venv with
`segmentation-models-pytorch==0.5.0`, `load_state_dict(strict=True)` reported
"All keys matched", and the model has 22,437,457 parameters (same as the notebook log). Without satellite tiles the app cannot run new
inference on real imagery. It can measure CPU forward-pass latency on a synthetic
512x512 input when the architecture loads, and labels that measurement as such.

---

## 5. Metrics: available vs. missing

| Metric | Status |
|---|---|
| DeepLabV3+ per-epoch train/val loss & IoU (30 epochs) | **historical** (parsed from Phase I log) |
| DenseDSSPP, UNeXt training curves | image only (PNG). No numbers exist, so none are made up |
| Validation Dice / precision / recall for any model | **missing** (Dice was computed but never printed; precision/recall never computed) |
| IoU/Dice/precision/recall on displayed samples | **not computable**: no ground-truth masks on disk |
| Checkpoint size, parameter count | **recomputed** by the app from the files |
| Inference latency | measured by the app only if the architecture loads (synthetic input, CPU) |
| Graph node/edge/component counts, degree, betweenness, efficiency, path lengths | **recomputed** by the app with NetworkX |
| Healing: bridges added, connectivity before/after | **historical** (graph `stats`) and **recomputed** (they match) |
| SAM repair: components before/after (4 tiles) | **historical** (Phase I log). Mask component counts for all 8 tiles are **recomputed** |
| Phase III resilience index | **historical**, flagged as unsound (§2) |
| Synthetic occlusion test (39 logged tiles; 44 figures) | **historical** (Phase II log) |

## 6. Counts summary

* Usable masks: deeplab 44, denseddsspp 1250, unext 4, sam_repaired 8. Tiles that have
  masks from all three segmentation models: 4 (`194764, 422265, 477671, 493626`).
* Usable graphs: 88 (44 per set, same 44 image IDs as `masks_deeplab`).
* Analyzed junctions (Phase III gatekeepers): 44 files with up to 5 ranked nodes each.
  All 44 analyses wrote output (`44/44` rows in the CSV), but **11 of them have a 2-node
  LCC** with zero betweenness and resilience index 0.0, so they carry no criticality
  information: `127572 194764 375903 597644 616654 632438 642961 774511 919932 920694 961236`.
  33 analyses are non-trivial.
* Successful experiments with saved outputs: DeepLabV3+ training (1 run), Phase II
  graph extraction (2 runs), synthetic occlusion test (1 run), Phase III criticality (1 run),
  SAM repair (1 logged run of 4 tiles + 4 more masks without a log).

## 7. Missing items and how the app handles them

| Missing | Effect | App behaviour |
|---|---|---|
| Satellite tiles, GT masks | no satellite overlay, no accuracy metrics | overlay on predicted mask; GT/metric panels show an explicit "unavailable" state |
| DenseDSSPP + UNeXt architecture code | checkpoints cannot be loaded | diagnostic card in Segmentation Lab |
| `training_curves_deeplabv3.png` | — | numeric curves from the log instead |
| Graphs from real SAM-repaired masks | the healing review cannot compare SAM-mask graphs | mask-level SAM comparison for 8 tiles; graph-level healing review uses recorded `healed` edges |
| Criticality analysis of `graphs_sam_repaired` | — | computed live on request |
| DenseDSSPP/UNeXt graphs | — | not offered (no artifacts) |

---

## 8. Update — 2026-10-13: new local data

Two new sources were added to the repository after the first audit. Sections 1, 5 and 7 above describe
the state *before* these were added.

| Item | Contents (checked) | Use in the app |
|---|---|---|
| `deepgloberoad/` | `train/` 6,226 `_sat.jpg` + `_mask.png` pairs; `valid/` 1,243 and `test/` 1,101 satellite images **without** masks; `metadata.csv`, `class_dict.csv` (road = 255) | Segmentation Lab. Ground truth now exists for `train/` tiles, and the Phase I validation split is drawn from `train/` |
| `southern-zone-261011.osm.pbf` | 558 MB OpenStreetMap extract (Southern India) | Map workspace: road index → road graphs |
| `archive.zip` (4.1 GB) | not unpacked or used (likely the DeepGlobe archive) | — |

Verified facts:

* **Phase I split reproduction:** sorted paired IDs of `train/`, `random.seed(42)`, shuffle, 80/20 → 4,980 / 1,246
  (same as the notebook log). The set `val_ids[:40]` + the 4 demo tiles equals the 44 files in `masks_deeplab`
  exactly, so the reproduction is correct. One demo tile (`194764`) is in the **training** subset, so
  metrics on it are in-sample, and the UI says so.
* **DeepLabV3+ inference in the app** reproduces the notebook's saved masks at ~96% IoU (e.g. 109889, 44614).
  The remaining difference comes from resize implementations (torch/PIL vs OpenCV).
* Accuracy is now computable per tile (IoU, Dice, precision, recall). No dataset-wide score is shown,
  because the app evaluates one tile at a time.
* The satellite tiles carry **no georeference**, so they cannot be aligned with the OSM map. The two workspaces
  stay separate.
* **OSM index (central Chennai, 80.15–80.32 E, 12.95–13.16 N):** 42,392 drivable ways, 439 named places,
  396 s scan. Spot checks: Anna Nagar 80.207 E 13.088 N, Ashok Nagar 80.215 E 13.036 N.
