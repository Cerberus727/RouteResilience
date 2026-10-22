import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Analysis, BBox, Evaluation, LngLat, Region, RoadFeature, SavedRun } from "../api/types";

export type StepAction = "baseline" | "fail" | "restore" | "reset";
export interface Step {
  n: number;
  action: StepAction;
  sid?: string;
  label?: string;
  failed: string[];
  ev: Evaluation;
}
export type Selection = { kind: "segment"; sid: string } | { kind: "node"; nid: number } | null;
export type Basemap = "dark" | "streets" | "satellite" | "none";
export interface Layers {
  roads: boolean;
  intersections: boolean;
  criticality: boolean;
  criticalNodes: boolean;
  affected: boolean;
  extents: boolean;
}

interface Ctx {
  region: Region | null;
  roads: Map<string, RoadFeature>;
  roadsVersion: number;
  loading: string | null; // human-readable activity, null when idle
  error: ApiError | null;
  clearError: () => void;
  loadRegion: (bbox?: BBox) => Promise<Region | null>;
  failed: string[];
  steps: Step[];
  current: Evaluation | null;
  regained: string[];
  origin: LngLat | null;
  destination: LngLat | null;
  setEndpoints: (o: LngLat | null, d: LngLat | null) => Promise<void>;
  fail: (sid: string) => Promise<void>;
  restore: (sid: string) => Promise<void>;
  resetFailures: () => Promise<void>;
  selection: Selection;
  select: (s: Selection) => void;
  analysis: Analysis | null;
  setAnalysis: (a: Analysis | null) => void;
  layers: Layers;
  setLayer: (k: keyof Layers, v: boolean) => void;
  basemap: Basemap;
  setBasemap: (b: Basemap) => void;
  saveRun: (name: string) => Promise<SavedRun | null>;
  lastSaved: SavedRun | null;
  roadLabel: (sid: string) => string;
}

const WorkspaceCtx = createContext<Ctx | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [region, setRegion] = useState<Region | null>(null);
  const [roads, setRoads] = useState<Map<string, RoadFeature>>(new Map());
  const [roadsVersion, setRoadsVersion] = useState(0);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [regained, setRegained] = useState<string[]>([]);
  const [origin, setOrigin] = useState<LngLat | null>(null);
  const [destination, setDestination] = useState<LngLat | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [layers, setLayers] = useState<Layers>({ roads: true, intersections: true, criticality: false, criticalNodes: true, affected: true, extents: true });
  const [basemap, setBasemap] = useState<Basemap>("dark");
  const [lastSaved, setLastSaved] = useState<SavedRun | null>(null);
  const busy = useRef(false);
  const lastOp = useRef<Promise<void>>(Promise.resolve());
  const stepsRef = useRef<Step[]>([]);
  stepsRef.current = steps;

  const current = steps.length ? steps[steps.length - 1].ev : null;
  const failed = steps.length ? steps[steps.length - 1].failed : [];

  /** Runs one backend operation at a time. User actions issued while busy are ignored (their buttons are
   *  disabled), except `queue` operations (route endpoint changes), which wait for the running one. */
  const wrap = useCallback(async <T,>(label: string, fn: () => Promise<T>, queue = false): Promise<T | null> => {
    if (busy.current && !queue) return null;
    const prev = lastOp.current;
    let release!: () => void;
    lastOp.current = new Promise<void>((r) => { release = r; });
    await prev;
    busy.current = true;
    setLoading(label);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      return null;
    } finally {
      busy.current = false;
      setLoading(null);
      release();
    }
  }, []);

  const roadLabel = useCallback((sid: string) => {
    const f = roads.get(sid);
    return f ? (f.properties.name || f.properties.hw.replace("_", " ")) : sid;
  }, [roads]);

  const loadRegion = useCallback((bbox?: BBox) => wrap("Loading road network", async () => {
    const r = await api.loadRegion(bbox);
    const fc = await api.roads(r.region_id);
    const m = new Map<string, RoadFeature>();
    fc.features.forEach((f) => m.set(f.properties.sid, f));
    const base = await api.evaluate(r.region_id, [], null, null);
    setRegion(r);
    setRoads(m);
    setRoadsVersion((v) => v + 1);
    setSteps([{ n: 0, action: "baseline", failed: [], ev: base }]);
    setRegained([]);
    setOrigin(null);
    setDestination(null);
    setSelection(null);
    setAnalysis(r.analysis_state === "done" || r.analysis_state === "running" ? await api.analysis(r.region_id) : null);
    setLastSaved(null);
    return r;
  }), [wrap]);

  const push = useCallback(async (action: StepAction, nextFailed: string[], sid?: string) => {
    if (!region) return;
    await wrap(action === "fail" ? "Closing road and recomputing network" : action === "restore" ? "Restoring road and recomputing network" : "Restoring all roads", async () => {
      const ev = await api.evaluate(region.region_id, nextFailed, origin, destination);
      const prevAffected = new Set([...(current?.network.affected_segment_ids ?? []), ...(current?.route?.unreachable_from_origin_segment_ids ?? [])]);
      const nowAffected = new Set([...ev.network.affected_segment_ids, ...(ev.route?.unreachable_from_origin_segment_ids ?? [])]);
      setRegained(action === "fail" ? [] : [...prevAffected].filter((s) => !nowAffected.has(s) && !nextFailed.includes(s)));
      setSteps((st) => [...st, { n: st.length, action, sid, label: sid ? roadLabel(sid) : undefined, failed: nextFailed, ev }]);
    });
  }, [region, origin, destination, current, wrap, roadLabel]);

  const fail = useCallback((sid: string) => (failed.includes(sid) ? Promise.resolve() : push("fail", [...failed, sid], sid)), [failed, push]);
  const restore = useCallback((sid: string) => (failed.includes(sid) ? push("restore", failed.filter((x) => x !== sid), sid) : Promise.resolve()), [failed, push]);
  const resetFailures = useCallback(() => (failed.length ? push("reset", []) : Promise.resolve()), [failed, push]);

  /** Changing origin/destination recomputes every step of the timeline for the new pair. */
  const setEndpoints = useCallback(async (o: LngLat | null, d: LngLat | null) => {
    setOrigin(o);
    setDestination(d);
    if (!region || !stepsRef.current.length) return;
    const routeOn = !!(o && d);
    const hadRoute = stepsRef.current.some((s) => s.ev.route !== null);
    if (!routeOn && !hadRoute) return; // a single endpoint changes nothing on the server
    await wrap(routeOn ? "Routing across all timeline steps" : "Updating", async () => {
      const out: Step[] = [];
      for (const s of stepsRef.current) out.push({ ...s, ev: await api.evaluate(region.region_id, s.failed, routeOn ? o : null, routeOn ? d : null) });
      setSteps(out);
      setRegained([]);
    }, true);
  }, [region, wrap]);

  const saveRun = useCallback((name: string) => wrap("Saving run (server recomputes every step)", async () => {
    if (!region) return null;
    const actions = steps.slice(1).map((s) => ({ action: s.action, segment_id: s.action === "reset" ? null : s.sid ?? null }));
    const run = await api.saveRun({ name, bbox: region.bbox, origin: origin && destination ? origin : null, destination: origin && destination ? destination : null, actions });
    setLastSaved(run);
    return run;
  }), [wrap, region, steps, origin, destination]);

  const value = useMemo<Ctx>(() => ({
    region, roads, roadsVersion, loading, error, clearError: () => setError(null), loadRegion, failed, steps, current, regained,
    origin, destination, setEndpoints, fail, restore, resetFailures, selection, select: setSelection, analysis, setAnalysis,
    layers, setLayer: (k, v) => setLayers((l) => ({ ...l, [k]: v })), basemap, setBasemap, saveRun, lastSaved, roadLabel,
  }), [region, roads, roadsVersion, loading, error, loadRegion, failed, steps, current, regained, origin, destination, setEndpoints,
    fail, restore, resetFailures, selection, analysis, layers, basemap, saveRun, lastSaved, roadLabel]);

  return <WorkspaceCtx.Provider value={value}>{children}</WorkspaceCtx.Provider>;
}

export function useWorkspace(): Ctx {
  const c = useContext(WorkspaceCtx);
  if (!c) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return c;
}
