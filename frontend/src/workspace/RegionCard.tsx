import { ChevronDown, Database, Download, ScanSearch } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { BBox, GeoStatus } from "../api/types";
import { Badge, Callout, ErrorState, Hint, Spinner } from "../components/ui";
import { fmtNum } from "../lib/format";
import { useWorkspace } from "../state/workspace";

export function bboxKm(b: BBox): [number, number] {
  const midLat = ((b[1] + b[3]) / 2) * (Math.PI / 180);
  return [(b[2] - b[0]) * 111.32 * Math.cos(midLat), (b[3] - b[1]) * 110.57];
}

const MAX_SPAN = 0.25;

export function RegionCard({ getView, onLoaded }: { getView: () => BBox | null; onLoaded: (b: BBox) => void }) {
  const ws = useWorkspace();
  const [status, setStatus] = useState<GeoStatus | null>(null);
  const [statusErr, setStatusErr] = useState<ApiError | null>(null);
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  const [pendingIndex, setPendingIndex] = useState<BBox | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(() => api.geoStatus().then((s) => { setStatus(s); setStatusErr(null); return s; })
    .catch((e) => { setStatusErr(e); return null; }), []);

  // first load: default region when the index exists
  useEffect(() => {
    refresh().then((s) => {
      if (s?.index_exists && s.extents.length && !ws.region) ws.loadRegion().then((r) => r && onLoaded(r.bbox));
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // poll while an index build is running
  useEffect(() => {
    if (status?.job.state !== "running") return;
    const t = setInterval(async () => {
      const s = await refresh();
      if (s && s.job.state === "done") {
        const target = pendingIndex;
        setPendingIndex(null);
        const r = await ws.loadRegion(target ? viewToRegion(target) : undefined);
        if (r) onLoaded(r.bbox);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [status?.job.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const viewToRegion = (v: BBox): BBox => {
    const cx = (v[0] + v[2]) / 2, cy = (v[1] + v[3]) / 2;
    const hw = Math.min(MAX_SPAN, v[2] - v[0]) / 2, hh = Math.min(MAX_SPAN, v[3] - v[1]) / 2;
    return [cx - hw, cy - hh, cx + hw, cy + hh];
  };

  const loadView = async () => {
    const v = getView();
    if (!v) return;
    const b = viewToRegion(v);
    setNotice(v[2] - v[0] > MAX_SPAN || v[3] - v[1] > MAX_SPAN ? `View is larger than ${MAX_SPAN}°; loading the central ${MAX_SPAN}° × ${MAX_SPAN}° instead.` : null);
    const r = await ws.loadRegion(b);
    if (r) onLoaded(r.bbox);
  };

  const indexView = async (whole = false) => {
    const v = whole ? undefined : viewToRegion(getView() ?? status!.default_extent);
    try {
      await api.buildIndex(v);
      setPendingIndex(v ?? null);
      ws.clearError();
      await refresh();
    } catch (e) {
      setStatusErr(e as ApiError);
    }
  };

  const r = ws.region;
  const job = status?.job;
  const needsIndex = ws.error?.code === "not_indexed" || ws.error?.code === "index_missing" || (status && !status.index_exists);
  const km = r ? bboxKm(r.bbox) : null;

  return (
    <div className="glass overflow-hidden">
      <button className="flex w-full items-center gap-2 px-3 py-2.5 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Database size={14} className="text-cyan-300" />
        <span className="min-w-0 flex-1">
          <span className="block text-[12.5px] font-semibold text-slate-100">{r ? (r.places.slice(0, 3).map((p) => p.name).join(" · ") || "Loaded region") : "No region loaded"}</span>
          <span className="block text-[10.5px] text-slate-500">{r && km ? `${km[0].toFixed(1)} × ${km[1].toFixed(1)} km · ${fmtNum(r.summary.segments)} segments · ${fmtNum(r.summary.total_km, 0)} km of road` : "OpenStreetMap road network"}</span>
        </span>
        <ChevronDown size={14} className={`text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-white/[0.06] px-3 py-3">
          {statusErr && <ErrorState error={statusErr} what="read the road index status" onRetry={refresh} />}
          {r && (
            <dl className="kv">
              <dt>Bounding box</dt><dd className="font-mono text-[10.5px]">{r.bbox.map((x) => x.toFixed(3)).join(", ")}</dd>
              <dt>Nodes / segments</dt><dd>{fmtNum(r.summary.nodes)} / {fmtNum(r.summary.segments)}</dd>
              <dt>One-way segments</dt><dd>{fmtNum(r.summary.oneway_segments)}</dd>
              <dt className="flex items-center gap-1">Main network <Hint text="Largest strongly connected component: every node in it can reach every other node while obeying one-way rules." /></dt>
              <dd>{((r.summary.main_scc_share ?? 0) * 100).toFixed(1)}% of nodes</dd>
              <dt>Components (weak / strong)</dt><dd>{r.summary.weak_components} / {r.summary.strong_components}</dd>
              <dt>Source</dt><dd className="max-w-[150px] truncate" title={status?.pbf.path ?? ""}>{status?.pbf.path?.split(/[\\/]/).pop() ?? "—"}</dd>
            </dl>
          )}
          {r?.coverage === "partial" && <Callout tone="warn">This area extends beyond the indexed extent, so roads outside it are missing. Index this view for full coverage.</Callout>}
          {notice && <Callout tone="info">{notice}</Callout>}

          <div className="flex flex-wrap gap-1.5">
            <button className="btn btn-primary" onClick={loadView} disabled={!!ws.loading || !status?.index_exists}>
              <ScanSearch size={13} /> Load roads in view
            </button>
            {(needsIndex || status?.extents.length === 0) && job?.state !== "running" && status?.pbf.exists && (
              <button className="btn" onClick={() => indexView(!status?.index_exists)} title="One-time scan of the .pbf for this area (several minutes)">
                <Download size={13} /> {status?.index_exists ? "Index this view" : "Build road index"}
              </button>
            )}
          </div>

          {job?.state === "running" && (
            <div className="rounded-lg border border-cyan-400/20 bg-cyan-400/[0.05] p-2.5 text-[11.5px]">
              <div className="flex items-center gap-2 font-medium text-cyan-100"><Spinner /> Indexing OSM roads</div>
              <div className="mt-1 text-slate-400">{job.phase}</div>
              <div className="mt-1 font-mono text-[10.5px] text-slate-500">{fmtNum(job.ways_seen)} ways scanned · {fmtNum(job.roads_kept)} kept · {Math.round(job.elapsed_s ?? 0)} s</div>
              <div className="mt-1 text-[10.5px] text-slate-500">A full scan of the {status?.pbf.size_mb ?? "?"} MB file takes several minutes; the map loads automatically when it finishes.</div>
            </div>
          )}
          {job?.state === "error" && <ErrorState error={job.error ?? "Index build failed"} what="build the road index" />}
          {status && !status.pbf.exists && <Callout tone="warn">No .osm.pbf file found. Set ROUTERESILIENCE_OSM_PBF to build an index.</Callout>}
          {status && status.extents.length > 0 && (
            <div className="text-[10.5px] leading-relaxed text-slate-500">
              Indexed extents (dashed grey on the map): {status.extents.map((e) => (
                <span key={e.id} className="mr-1 inline-block"><Badge>{bboxKm(e.bbox).map((x) => x.toFixed(0)).join("×")} km · {fmtNum(e.roads)} ways</Badge></span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
