import { ArrowRightLeft, Ban, ExternalLink, Focus, MousePointerClick, RotateCcw } from "lucide-react";
import { api } from "../api/client";
import type { LngLat } from "../api/types";
import { useApi } from "../api/useApi";
import { Badge, EmptyState, ErrorState, Hint, Loading } from "../components/ui";
import { fmtNum } from "../lib/format";
import { useWorkspace } from "../state/workspace";

export function InspectTab({ onZoom }: { onZoom: (p: LngLat) => void }) {
  const ws = useWorkspace();
  const sel = ws.selection;
  if (!ws.region) return <EmptyState title="No region loaded" />;
  if (!sel) {
    return (
      <EmptyState title="Select a road on the map" icon={<MousePointerClick size={20} />}>
        Click any road segment to see its attributes and close it. At zoom 15+ you can also click intersections.
      </EmptyState>
    );
  }
  return sel.kind === "segment" ? <SegmentInfo sid={sel.sid} onZoom={onZoom} /> : <NodeInfo nid={sel.nid} onZoom={onZoom} />;
}

function SegmentInfo({ sid, onZoom }: { sid: string; onZoom: (p: LngLat) => void }) {
  const ws = useWorkspace();
  const rid = ws.region!.region_id;
  const d = useApi(() => api.segment(rid, sid), [rid, sid, ws.analysis?.state]);
  const isFailed = ws.failed.includes(sid);
  const isAffected = !isFailed && !!ws.current?.network.affected_segment_ids.includes(sid);
  if (d.loading && !d.data) return <Loading label="Loading segment" />;
  if (d.error) return <ErrorState error={d.error} what="load this segment" onRetry={d.reload} />;
  const s = d.data!;
  const name = s.tags.name || s.tags.ref || s.highway.replace("_", " ");
  const mid = s.endpoints[0].lonlat;
  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] font-semibold text-slate-50">{name}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge tone="cyan">{s.highway.replace("_", " ")}</Badge>
              <Badge>{s.direction}</Badge>
              {isFailed && <Badge tone="red">■ closed</Badge>}
              {isAffected && <Badge tone="violet">cut off</Badge>}
              {s.is_bridge && <Badge tone="amber" title="Removing it disconnects the undirected road graph">graph bridge</Badge>}
            </div>
          </div>
          <button className="icon-btn" title="Zoom to segment" aria-label="Zoom to segment" onClick={() => onZoom(mid)}><Focus size={15} /></button>
        </div>
      </div>

      <div className="flex gap-2">
        {isFailed ? (
          <button className="btn btn-success flex-1" onClick={() => ws.restore(sid)} disabled={!!ws.loading}><RotateCcw size={13} /> Restore road</button>
        ) : (
          <button className="btn btn-danger flex-1" onClick={() => ws.fail(sid)} disabled={!!ws.loading}><Ban size={13} /> Close road</button>
        )}
      </div>

      <dl className="kv">
        <dt>Segment id</dt><dd className="font-mono text-[11px]">{s.sid}</dd>
        <dt>Length</dt><dd>{fmtNum(s.length_m, 0)} m</dd>
        <dt>OSM way</dt><dd><a className="inline-flex items-center gap-1 text-cyan-300 hover:underline" href={s.osm_url} target="_blank" rel="noreferrer">{s.way_id}<ExternalLink size={11} /></a></dd>
        {["lanes", "maxspeed", "surface", "bridge", "tunnel", "junction", "ref"].filter((k) => s.tags[k]).map((k) => (
          <div key={k} className="contents"><dt className="capitalize">{k}</dt><dd>{s.tags[k]}</dd></div>
        ))}
        <dt className="flex items-center gap-1">Path share <Hint text="Sampled betweenness: share of sampled shortest (distance) paths that use this segment. Structural importance only; it is not traffic volume." /></dt>
        <dd>{s.betweenness_share === null ? <span className="text-slate-500">run analysis</span> : `${(s.betweenness_share * 100).toFixed(2)}%`}</dd>
      </dl>

      <div>
        <div className="section-title mb-1.5">Connected intersections</div>
        <div className="space-y-1.5">
          {s.endpoints.map((e, i) => (
            <button key={e.nid} onClick={() => ws.select({ kind: "node", nid: e.nid })}
              className="flex w-full items-center gap-2 rounded-md border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-left hover:border-white/15">
              <span className="font-mono text-[10.5px] text-slate-500">{i === 0 ? "from" : "to"}</span>
              <span className="flex-1 font-mono text-[11px] text-slate-200">node {e.nid}</span>
              <span className="text-[10.5px] text-slate-400">{e.degree} road{e.degree === 1 ? " (dead end)" : "s"}</span>
            </button>
          ))}
        </div>
        {s.parallel_segments.length > 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-400"><ArrowRightLeft size={12} /> {s.parallel_segments.length} parallel segment(s) join the same intersections; they stay separate edges.</p>
        )}
      </div>
    </div>
  );
}

function NodeInfo({ nid, onZoom }: { nid: number; onZoom: (p: LngLat) => void }) {
  const ws = useWorkspace();
  const rid = ws.region!.region_id;
  const d = useApi(() => api.node(rid, nid), [rid, nid, ws.analysis?.state]);
  if (d.loading && !d.data) return <Loading label="Loading intersection" />;
  if (d.error) return <ErrorState error={d.error} what="load this intersection" onRetry={d.reload} />;
  const n = d.data!;
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold text-slate-50">Intersection</h3>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge>{n.degree}-way</Badge>
            {n.critical_rank && <Badge tone="amber">critical #{n.critical_rank}</Badge>}
            {n.is_articulation && <Badge tone="amber" title="Removing this intersection disconnects the undirected graph">articulation point</Badge>}
            {!n.in_main_network && <Badge tone="violet">outside main network</Badge>}
          </div>
        </div>
        <button className="icon-btn" aria-label="Zoom to intersection" title="Zoom to intersection" onClick={() => onZoom(n.lonlat)}><Focus size={15} /></button>
      </div>
      <dl className="kv">
        <dt>OSM node</dt><dd><a className="inline-flex items-center gap-1 text-cyan-300 hover:underline" href={n.osm_url} target="_blank" rel="noreferrer">{n.nid}<ExternalLink size={11} /></a></dd>
        <dt className="flex items-center gap-1">Outgoing / incoming <Hint text="Directed edges after applying one-way rules." /></dt><dd>{n.out_edges} / {n.in_edges}</dd>
        <dt>Location</dt><dd className="font-mono text-[10.5px]">{n.lonlat[1].toFixed(5)}, {n.lonlat[0].toFixed(5)}</dd>
      </dl>
      <div>
        <div className="section-title mb-1.5">Roads at this intersection</div>
        <div className="space-y-1">
          {n.segments.map((s) => (
            <button key={s.sid} onClick={() => ws.select({ kind: "segment", sid: s.sid })}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/[0.05]">
              <span className={`h-2 w-2 rounded-full ${ws.failed.includes(s.sid) ? "bg-red-500" : "bg-slate-500"}`} />
              <span className="min-w-0 flex-1 truncate text-xs text-slate-200">{s.name || s.highway.replace("_", " ")}</span>
              <span className="text-[10.5px] text-slate-500">{fmtNum(s.length_m, 0)} m</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
