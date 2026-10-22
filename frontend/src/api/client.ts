import type {
  Analysis, BBox, Evaluation, Experiment, GeoStatus, Health, IndexJob, LabModel, LabResult, LabSamples, LngLat, NodeDetail,
  Region, RoadCollection, RunListItem, SavedRun, SearchHit, SegmentDetail,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/** Error carrying the HTTP status and the backend's machine-readable code. */
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map((e) => (e && typeof e === "object" && "msg" in e
        ? `${(e as { loc?: unknown[] }).loc?.slice(-1)[0] ?? ""}: ${(e as { msg: string }).msg}` : String(e))).join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      ...init,
      headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the RouteResilience API. Is the backend running on port 8000?", "network");
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    const code = body && typeof body === "object" && "code" in body ? String((body as { code: unknown }).code) : undefined;
    throw new ApiError(res.status, detailMessage(body, `${res.status} ${res.statusText}`), code);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const ll = (p: LngLat | null) => (p ? { lon: p[0], lat: p[1] } : null);

export const api = {
  health: () => request<Health>("/api/health"),
  geoStatus: () => request<GeoStatus>("/api/geo/status"),
  buildIndex: (bbox?: BBox) => request<IndexJob>("/api/geo/index", post({ bbox: bbox ?? null })),
  loadRegion: (bbox?: BBox) => request<Region>("/api/geo/regions", post({ bbox: bbox ?? null })),
  roads: (rid: string) => request<RoadCollection>(`/api/geo/regions/${enc(rid)}/roads`),
  intersections: (rid: string) => request<GeoJSON.FeatureCollection>(`/api/geo/regions/${enc(rid)}/intersections`),
  segment: (rid: string, sid: string) => request<SegmentDetail>(`/api/geo/regions/${enc(rid)}/segments/${enc(sid)}`),
  node: (rid: string, nid: number) => request<NodeDetail>(`/api/geo/regions/${enc(rid)}/nodes/${nid}`),
  evaluate: (rid: string, failed: string[], origin: LngLat | null, destination: LngLat | null) =>
    request<Evaluation>(`/api/geo/regions/${enc(rid)}/evaluate`, post({
      failed, ...(origin && destination ? { origin: ll(origin), destination: ll(destination) } : {}),
    })),
  startAnalysis: (rid: string) => request<Analysis>(`/api/geo/regions/${enc(rid)}/analysis`, { method: "POST" }),
  analysis: (rid: string) => request<Analysis>(`/api/geo/regions/${enc(rid)}/analysis`),
  search: (q: string, rid?: string | null) => request<SearchHit[]>(`/api/geo/search?q=${enc(q)}${rid ? `&region_id=${enc(rid)}` : ""}`),
  saveRun: (body: { name: string; bbox: BBox; origin: LngLat | null; destination: LngLat | null; actions: { action: string; segment_id?: string | null }[] }) =>
    request<SavedRun>("/api/runs", post(body)),
  runs: () => request<RunListItem[]>("/api/runs"),
  run: (id: string) => request<SavedRun>(`/api/runs/${enc(id)}`),
  deleteRun: (id: string) => request<{ deleted: string }>(`/api/runs/${enc(id)}`, { method: "DELETE" }),
  runExportUrl: (id: string, format: "json" | "csv" | "md") => `${API_BASE}/api/runs/${enc(id)}/export?format=${format}`,
  labSamples: (subset: string, offset: number, limit: number, q?: string) =>
    request<LabSamples>(`/api/lab/samples?subset=${enc(subset)}&offset=${offset}&limit=${limit}${q ? `&q=${enc(q)}` : ""}`),
  labModels: () => request<LabModel[]>("/api/lab/models"),
  labImageUrl: (id: string, kind: "sat" | "gt") => `${API_BASE}/api/lab/images/${enc(id)}/${kind}`,
  labInfer: (model_id: string, image_id: string) => request<LabResult>("/api/lab/infer", post({ model_id, image_id })),
  experiments: () => request<Experiment[]>("/api/experiments"),
};
