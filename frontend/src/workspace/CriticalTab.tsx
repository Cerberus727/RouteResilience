import { Ban, Play, Undo2 } from "lucide-react";
import { useEffect } from "react";
import { api } from "../api/client";
import type { LngLat } from "../api/types";
import { Badge, Callout, EmptyState, ErrorState, Hint, Spinner } from "../components/ui";
import { fmtNum } from "../lib/format";
import { useWorkspace } from "../state/workspace";

export function CriticalTab({ onZoom }: { onZoom: (p: LngLat) => void }) {
  const ws = useWorkspace();
  const rid = ws.region?.region_id;
  const a = ws.analysis;

  // Poll while the background job runs.
  useEffect(() => {
    if (!rid || a?.state !== "running") return;
    const t = setInterval(() => api.analysis(rid).then((x) => {
      ws.setAnalysis(x);
      if (x.state === "done") { ws.setLayer("criticality", true); ws.setLayer("criticalNodes", true); }
    }).catch(() => undefined), 700);
    return () => clearInterval(t);
  }, [rid, a?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ws.region) return <EmptyState title="No region loaded" />;
  const start = async () => {
    try {
      await api.startAnalysis(rid!);
      const full = await api.analysis(rid!); // includes the result when the job had already finished
      ws.setAnalysis(full);
      if (full.state === "done") { ws.setLayer("criticality", true); ws.setLayer("criticalNodes", true); }
    } catch (e) {
      ws.setAnalysis({ state: "error", progress: 0, phase: "", error: (e as Error).message, elapsed_s: null });
    }
  };

  return (
    <div className="space-y-4">
      <Callout>
        Ranks roads by how many sampled shortest paths cross them (structural <em>betweenness</em>). A high rank means many routes depend on the road
        in this graph. It is not a measure of traffic, and it inherits any gaps in the OSM data.
      </Callout>
      {(!a || a.state === "idle") && (
        <button className="btn btn-primary w-full" onClick={start}><Play size={13} /> Analyze critical roads in this region</button>
      )}
      {a?.state === "running" && (
        <div className="rounded-lg border border-white/[0.07] p-3">
          <div className="flex items-center gap-2 text-xs text-slate-200"><Spinner /> {a.phase || "starting"}</div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-cyan-400 transition-[width] duration-500" style={{ width: `${Math.round(a.progress * 100)}%` }} />
          </div>
        </div>
      )}
      {a?.state === "error" && <ErrorState error={a.error ?? "Analysis failed"} what="analyze this region" onRetry={start} />}
      {a?.state === "done" && a.result && (
        <>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5">
              <div className="flex items-center gap-1 text-[10.5px] uppercase tracking-wider text-slate-500">Graph bridges <Hint text={String(a.result.method.bridges)} /></div>
              <div className="mt-0.5 text-[15px] font-semibold tabular-nums">{fmtNum(a.result.bridge_count)}</div>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5">
              <div className="flex items-center gap-1 text-[10.5px] uppercase tracking-wider text-slate-500">Articulation pts <Hint text={String(a.result.method.articulation)} /></div>
              <div className="mt-0.5 text-[15px] font-semibold tabular-nums">{fmtNum(a.result.articulation_count)}</div>
            </div>
          </div>
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <h4 className="section-title">Most critical roads</h4>
              <Hint text={`${a.result.method.betweenness} Single-closure impact is computed exactly for the top 15.`} />
            </div>
            <ol className="space-y-1">
              {a.result.roads.slice(0, 25).map((r) => {
                const closed = ws.failed.includes(r.sid);
                return (
                  <li key={r.sid} className={`group rounded-lg border px-2.5 py-2 ${ws.selection?.kind === "segment" && ws.selection.sid === r.sid ? "border-cyan-400/50 bg-cyan-400/[0.06]" : "border-white/[0.06] bg-white/[0.02]"}`}>
                    <div className="flex items-center gap-2">
                      <span className="w-5 text-right font-mono text-[11px] text-amber-300">{r.rank}</span>
                      <button className="min-w-0 flex-1 truncate text-left text-xs font-medium text-slate-100 hover:underline"
                        onClick={() => { ws.select({ kind: "segment", sid: r.sid }); onZoom(r.midpoint); }}>
                        {r.name || r.highway.replace("_", " ")}
                      </button>
                      <span className="font-mono text-[11px] tabular-nums text-slate-300" title="Share of sampled shortest paths using this segment">{(r.betweenness_share * 100).toFixed(1)}%</span>
                      {closed ? (
                        <button className="icon-btn h-6 w-6 text-emerald-300" title="Restore road" aria-label={`Restore ${r.name}`} onClick={() => ws.restore(r.sid)}><Undo2 size={13} /></button>
                      ) : (
                        <button className="icon-btn h-6 w-6 text-red-300" title="Close this road" aria-label={`Close ${r.name}`} onClick={() => ws.fail(r.sid)} disabled={!!ws.loading}><Ban size={13} /></button>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 pl-7">
                      <span className="font-mono text-[10px] text-slate-500" title="Segment id (way:index). Dual carriageways appear as separate segments.">{r.sid}</span>
                      <Badge>{r.highway.replace("_", " ")}</Badge>
                      {r.is_bridge && <Badge tone="amber">bridge</Badge>}
                      {r.impact && (
                        <Badge tone={r.impact.cut_off_nodes ? "violet" : "neutral"} title="Exact result of closing only this road">
                          if closed: {r.impact.cut_off_nodes} nodes cut off · eff. {r.impact.efficiency_retention !== null ? `${(r.impact.efficiency_retention * 100).toFixed(2)}%` : "n/a"}
                        </Badge>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
          <p className="text-[10.5px] text-slate-500">{fmtNum(Number(a.result.method.paths_counted))} shortest paths counted · computed in {a.elapsed_s?.toFixed(1)} s.</p>
        </>
      )}
    </div>
  );
}
