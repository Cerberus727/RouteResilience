// Shapes returned by the backend (backend/app/routes/geo.py, workspace.py, system.py).

export type BBox = [number, number, number, number];
export type LngLat = [number, number];

export interface IndexJob {
  state: "idle" | "running" | "done" | "error";
  extent: BBox | null;
  phase: string;
  ways_seen: number;
  roads_kept: number;
  places_kept: number;
  elapsed_s: number | null;
  error: string | null;
  log: string[];
}

export interface GeoStatus {
  pbf: { path: string | null; exists: boolean; size_mb: number | null };
  index_path: string;
  index_exists: boolean;
  index_error?: string;
  extents: { id: number; bbox: BBox; built_at: string; source: string; roads: number; places: number; seconds: number }[];
  default_extent: BBox;
  default_region: BBox;
  job: IndexJob;
}

export interface RegionSummary {
  segments: number;
  nodes: number;
  directed_edges: number;
  total_km: number;
  oneway_segments: number;
  weak_components: number;
  strong_components: number;
  main_scc_nodes: number;
  main_scc_share: number | null;
  intersections: number;
  dead_ends: number;
  highway_classes: Record<string, number>;
}

export interface Region {
  region_id: string;
  bbox: BBox;
  coverage: "full" | "partial";
  built_seconds: number;
  summary: RegionSummary;
  analysis_state: string;
  places: { name: string; kind: string; lon: number; lat: number }[];
}

export interface RoadProps { sid: string; way: number; hw: string; name: string; ow: number; len: number }
export interface RoadFeature { type: "Feature"; id: number; geometry: { type: "LineString"; coordinates: LngLat[] }; properties: RoadProps }
export interface RoadCollection { type: "FeatureCollection"; features: RoadFeature[] }

export interface SegmentDetail {
  sid: string;
  way_id: number;
  osm_url: string;
  highway: string;
  tags: Record<string, string>;
  length_m: number;
  direction: string;
  endpoints: { nid: number; lonlat: LngLat; degree: number; segments: string[] }[];
  parallel_segments: string[];
  betweenness_share: number | null;
  is_bridge: boolean | null;
}

export interface NodeDetail {
  nid: number;
  osm_url: string;
  lonlat: LngLat;
  degree: number;
  out_edges: number;
  in_edges: number;
  segments: { sid: string; name: string; highway: string; length_m: number }[];
  in_main_network: boolean;
  critical_rank: number | null;
  is_articulation: boolean | null;
}

export interface RouteResult {
  available: boolean;
  length_m: number | null;
  segments: string[];
  coords: LngLat[];
  reachable_nodes: number;
}

export interface Evaluation {
  failed: string[];
  network: {
    segments_total: number;
    segments_failed: number;
    weak_components: number;
    strong_components: number;
    baseline_weak_components: number;
    baseline_strong_components: number;
    main_nodes_baseline: number;
    main_nodes: number;
    cut_off_nodes: number;
    affected_segments: number;
    affected_km: number;
    affected_segment_ids: string[];
    affected_truncated: boolean;
  };
  sampled: {
    sources: number;
    targets: number;
    pairs: number;
    reachable_fraction_baseline: number;
    reachable_fraction: number;
    pairs_disconnected: number;
    mean_detour_pct: number | null;
    max_detour_pct: number | null;
    efficiency_retention: number | null;
  } | null;
  route: {
    origin: { node: number; lonlat: LngLat; snap_m: number };
    destination: { node: number; lonlat: LngLat; snap_m: number };
    baseline: RouteResult;
    current: RouteResult;
    uses_failed_segment: boolean;
    detour_m: number | null;
    detour_pct: number | null;
    reachable_from_origin_baseline: number;
    reachable_from_origin: number;
    unreachable_from_origin_segment_ids: string[];
    weight: string;
  } | null;
}

export interface CriticalRoad {
  rank: number;
  sid: string;
  name: string;
  highway: string;
  length_m: number;
  betweenness_share: number;
  is_bridge: boolean;
  midpoint: LngLat;
  impact: { cut_off_nodes: number; affected_segments: number; strong_components: number; efficiency_retention: number | null; reachable_fraction: number | null } | null;
}

export interface Analysis {
  state: "idle" | "running" | "done" | "error";
  progress: number;
  phase: string;
  error: string | null;
  elapsed_s: number | null;
  result?: {
    method: Record<string, string | number>;
    roads: CriticalRoad[];
    intersections: { rank: number; nid: number; lonlat: LngLat; betweenness_share: number; is_articulation: boolean }[];
    segment_scores: Record<string, number>;
    bridge_count: number;
    articulation_count: number;
    bridges: string[];
  };
}

export interface SearchHit {
  name: string;
  kind: string;
  lon: number;
  lat: number;
  bbox?: BBox;
  segment_ids?: string[];
  source: string;
}

export interface RunStepMetrics {
  failed_count: number;
  strong_components: number;
  weak_components: number;
  cut_off_nodes: number;
  affected_segments: number;
  affected_km: number;
  sampled_reachable_fraction: number | null;
  sampled_efficiency_retention: number | null;
  sampled_mean_detour_pct: number | null;
  route_available: boolean | null;
  route_length_m: number | null;
  baseline_route_length_m: number | null;
  detour_m: number | null;
  detour_pct: number | null;
  reachable_from_origin: number | null;
}

export interface SavedRun {
  id: string;
  name: string;
  created_at: string;
  region: { bbox: BBox; region_id: string; segments: number; nodes: number; coverage: string; source: string };
  origin: LngLat | null;
  destination: LngLat | null;
  routing_weight: string;
  steps: { step: number; action: string; segment_id: string | null; segment_name?: string | null; failed: string[]; metrics: RunStepMetrics }[];
  limitations: string[];
  provenance: string;
}

export interface RunListItem {
  id: string;
  name: string;
  created_at?: string;
  bbox?: BBox;
  steps?: number;
  final_failed?: number;
  final_efficiency_retention?: number | null;
  error?: boolean;
}

export interface LabSample { image_id: string; folder: string; phase1_subset: "train" | "val" | null; has_ground_truth: boolean; has_phase1_mask: boolean }
export interface LabSamples {
  total: number;
  offset: number;
  limit: number;
  items: LabSample[];
  dataset: { root: string; paired_train: number; phase1_train: number; phase1_val: number; valid_images: number; test_images: number;
    split_check: { phase1_saved_masks: number; matches_val_ids_first40_plus_demo: boolean } };
}
export interface LabModel { model_id: string; checkpoint: string; loadable: boolean; family: string | null; diagnostic: string | null }
export interface LabResult {
  result_id: string;
  model_id: string;
  image_id: string;
  folder: string;
  phase1_subset: "train" | "val" | null;
  size: [number, number];
  input_size: number;
  threshold: number;
  latency_ms: number;
  device: string;
  road_fraction: number;
  mean_road_probability: number | null;
  metrics: { tp: number; fp: number; fn: number; tn: number; iou: number | null; dice: number | null; precision: number | null; recall: number | null; evaluation: string } | null;
  phase1_agreement: { iou_with_saved_mask: number | null; pixels_differing: number; note: string } | null;
  urls: Record<"mask" | "overlay" | "errors" | "ground_truth", string>;
}

export interface Experiment { id: string; kind: string; phase: string; title: string; provenance: string; source: string; summary: Record<string, unknown>; warning?: string | null }
export interface Health { status: string; version: string; optional_features: Record<string, boolean>; counts: Record<string, number> }
