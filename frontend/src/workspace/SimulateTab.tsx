import { Ban, CheckCircle2, Crosshair, ExternalLink, RotateCcw, Save, Undo2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Evaluation } from "../api/types";
import { SERIES, SeriesLines } from "../components/charts";
import { Badge, Callout, EmptyState, Hint, Stat } from "../components/ui";
import type { MapMode } from "../map/MapView";
import { fmtNum } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const km = (m: number | null | undefined) => (m === null || m === undefined ? "n/a" : m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(d)}%`);

export function SimulateTab({ mode, setMode, onZoomSegment }: { mode: MapMode; setMode: (m: MapMode) => void; onZoomSegment: (sid: string) => void }) {
  const ws = useWorkspace();
  const [runName, setRunName] = useState("");
  if (!ws.region) return <EmptyState title="No region loaded" />;
  const ev = ws.current;
  const base = ws.steps[0]?.ev;

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------ route */}
      <section>
        <div className="mb-2 flex items-center gap-1.5">
          <h4 className="section-title">Route</h4>
          <Hint text="Shortest path by distance along the road geometry, respecting one-way rules. No travel-time or traffic data is used." />
        </div>
        <div className="grid grid-cols-2 gap-2">
          {(["origin", "destination"] as const).map((k) => {
            const p = ws[k];
            const active = mode === k;
            return (
              <button key={k} onClick={() => setMode(active ? "select" : k)} aria-pressed={active}
                className={`rounded-lg border px-2.5 py-2 text-left transition-colors ${active ? "border-cyan-400/60 bg-cyan-400/10" : "border-white/[0.08] bg-white/[0.02] hover:border-white/20"}`}>
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-200">
                  <span className={`grid h-4 w-4 place-items-center rounded-full text-[9px] font-bold text-ink-950 ${k === "origin" ? "bg-slate-100" : "bg-emerald-500"}`}>{k === "origin" ? "A" : "B"}</span>
                  {k === "origin" ? "Origin" : "Destination"}
                  <Crosshair size={12} className="ml-auto text-slate-500" />
                </div>
                <div className="mt-1 truncate font-mono text-[10.5px] text-slate-400">{active ? "click the map…" : p ? `${p[1].toFixed(5)}, ${p[0].toFixed(5)}` : "not set"}</div>
              </button>
            );
          })}
        </div>
        {(ws.origin || ws.destination) && (
          <button className="btn mt-2 w-full" onClick={() => { setMode("select"); ws.setEndpoints(null, null); }}><X size={13} /> Clear route</button>
        )}
        {ev?.route && <RouteSummary ev={ev} />}
        {ev?.route?.current.available && <RouteRoads segments={ev.route.current.segments} onZoomSegment={onZoomSegment} />}
        {!ev?.route && ws.origin && !ws.destination && <p className="mt-2 text-[11px] text-slate-500">Now set destination B.</p>}
      </section>

      {/* ------------------------------------------------ failures */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="section-title">Closed roads ({ws.failed.length})</h4>
          {ws.failed.length > 0 && (
            <button className="btn px-2 py-1 text-[11px]" onClick={ws.resetFailures} disabled={!!ws.loading}><RotateCcw size={12} /> Restore all</button>
          )}
        </div>
        {ws.failed.length === 0 ? (
          <p className="rounded-lg border border-dashed border-white/10 px-3 py-3 text-[11.5px] text-slate-500">
            No roads closed. Select a road on the map and press <span className="text-red-300">Close road</span>, or close a top-ranked road from the Critical tab.
          </p>
        ) : (
          <ul className="space-y-1">
            {ws.failed.map((sid) => (
              <li key={sid} className="flex items-center gap-2 rounded-md border border-red-400/20 bg-red-500/[0.06] px-2.5 py-1.5">
                <Ban size={12} className="shrink-0 text-red-300" />
                <button className="min-w-0 flex-1 truncate text-left text-xs text-slate-100 hover:underline" onClick={() => { ws.select({ kind: "segment", sid }); onZoomSegment(sid); }}>
                  {ws.roadLabel(sid)} <span className="font-mono text-[10px] text-slate-500">{sid}</span>
                </button>
                <button className="btn btn-success px-2 py-0.5 text-[11px]" onClick={() => ws.restore(sid)} disabled={!!ws.loading}><Undo2 size={11} /> Restore</button>
              </li>
            ))}
          </ul>
        )}
        {ws.regained.length > 0 && (
          <div className="mt-2"><Callout tone="success" title="Recovery:">{fmtNum(ws.regained.length)} road segment(s) regained connectivity (teal on the map).</Callout></div>
        )}
      </section>

      {/* ------------------------------------------------ disruption */}
      {ev && base && (
        <section>
          <h4 className="section-title mb-2">Network disruption</h4>
          <div className="grid grid-cols-2 gap-x-3 gap-y-3 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
            <Stat label="Cut-off nodes" value={fmtNum(ev.network.cut_off_nodes)} tone={ev.network.cut_off_nodes ? "violet" : undefined}
              sub={`${fmtNum(ev.network.affected_segments)} roads · ${ev.network.affected_km.toFixed(2)} km`}
              hint="Intersections of the intact main network that can no longer both reach and be reached from it (one-way rules respected). Computed exactly on the whole region." />
            <Stat label="Strong components" value={`${ev.network.baseline_strong_components} → ${ev.network.strong_components}`}
              tone={ev.network.strong_components > ev.network.baseline_strong_components ? "amber" : undefined}
              hint="Groups of nodes that are mutually reachable. More components means a more fragmented network." />
            <Stat label="Sampled reachability" value={pct(ev.sampled?.reachable_fraction)}
              sub={ev.sampled ? `${fmtNum(ev.sampled.pairs_disconnected)} of ${fmtNum(ev.sampled.pairs)} pairs lost` : undefined}
              hint="Estimate: share of sampled origin→target pairs (24 origins × 400 targets, fixed seed) that still have a route." />
            <Stat label="Sampled efficiency" value={pct(ev.sampled?.efficiency_retention)}
              tone={ev.sampled?.efficiency_retention !== null && (ev.sampled?.efficiency_retention ?? 1) < 0.99 ? "amber" : undefined}
              sub={ev.sampled?.mean_detour_pct ? `mean detour +${ev.sampled.mean_detour_pct.toFixed(2)}%` : "relative to intact network"}
              hint="Estimate: Σ 1/distance over the sampled pairs, relative to the intact network (unreachable pairs contribute 0). 100% = no effect." />
          </div>
        </section>
      )}

      {/* ------------------------------------------------ timeline */}
      {ws.steps.length > 1 && (
        <section>
          <div className="mb-2 flex items-center gap-1.5">
            <h4 className="section-title">Failure & recovery timeline</h4>
            <Hint text="Each step is a fresh backend computation. When A/B change, every step is recomputed for the new route." />
          </div>
          <div className="h-36 rounded-lg border border-white/[0.06] bg-white/[0.02] p-1.5">
            <SeriesLines x="step" xLabel="" yDomain={[0, 100]} valueFmt={(v) => `${v.toFixed(2)}%`}
              data={ws.steps.map((s) => ({ step: s.n, eff: (s.ev.sampled?.efficiency_retention ?? 0) * 100, reach: (s.ev.sampled?.reachable_fraction ?? 0) * 100 }))}
              series={[{ key: "eff", name: "Sampled efficiency", color: SERIES[0] }, { key: "reach", name: "Sampled reachability", color: SERIES[1], dashed: true }]} />
          </div>
          <div className="mt-2 max-h-48 overflow-auto rounded-lg border border-white/[0.06]">
            <table className="table-dense">
              <thead><tr><th>#</th><th>Action</th><th>Closed</th><th>Cut off</th><th>Route</th></tr></thead>
              <tbody>
                {ws.steps.map((s) => (
                  <tr key={s.n}>
                    <td>{s.n}</td>
                    <td className="max-w-[130px] truncate" title={s.label}>
                      <span className={s.action === "fail" ? "text-red-300" : s.action === "baseline" ? "text-slate-400" : "text-emerald-300"}>{s.action}</span>
                      {s.label ? <span className="text-slate-400"> · {s.label}</span> : null}
                    </td>
                    <td>{s.failed.length}</td>
                    <td>{fmtNum(s.ev.network.cut_off_nodes)}</td>
                    <td>{s.ev.route ? (s.ev.route.current.available ? km(s.ev.route.current.length_m) : <span className="text-red-300">none</span>) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ------------------------------------------------ save */}
      <section>
        <h4 className="section-title mb-2">Save & export</h4>
        <div className="flex gap-2">
          <input className="input min-w-0 flex-1" placeholder="Run name" value={runName} maxLength={120} onChange={(e) => setRunName(e.target.value)} aria-label="Run name" />
          <button className="btn btn-primary" disabled={ws.steps.length < 2 || !!ws.loading} onClick={() => ws.saveRun(runName)}
            title={ws.steps.length < 2 ? "Close at least one road first" : "The server recomputes every step before saving"}><Save size={13} /> Save run</button>
        </div>
        <p className="mt-1.5 text-[10.5px] text-slate-500">This simulation is unsaved until you save it. Saved runs are recomputed server-side and listed in Reports.</p>
        {ws.lastSaved && (
          <div className="mt-2 rounded-lg border border-emerald-400/25 bg-emerald-400/[0.05] p-2.5 text-[11.5px]">
            <div className="flex items-center gap-1.5 font-medium text-emerald-100"><CheckCircle2 size={13} /> Saved {ws.lastSaved.name}</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {(["json", "csv", "md"] as const).map((f) => <a key={f} className="btn px-2 py-0.5 text-[11px]" href={api.runExportUrl(ws.lastSaved!.id, f)}>{f.toUpperCase()}</a>)}
              <Link className="btn px-2 py-0.5 text-[11px]" to={`/reports?run=${ws.lastSaved.id}`}>Open report <ExternalLink size={11} /></Link>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

/** Named roads along the current route, in travel order — the quickest way to test a detour. */
function RouteRoads({ segments, onZoomSegment }: { segments: string[]; onZoomSegment: (sid: string) => void }) {
  const ws = useWorkspace();
  const groups: { name: string; sids: string[] }[] = [];
  for (const sid of segments) {
    const name = ws.roadLabel(sid);
    const last = groups[groups.length - 1];
    if (last && last.name === name) last.sids.push(sid);
    else groups.push({ name, sids: [sid] });
  }
  const shown = groups.filter((g) => g.sids.length >= 2 || groups.length <= 8).slice(0, 8);
  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <h4 className="section-title">Roads on this route</h4>
        <Hint text="Close one segment of a road the route uses to see the detour. The middle segment of that stretch is closed." />
      </div>
      <ul className="space-y-1">
        {shown.map((g, i) => {
          const target = g.sids[Math.floor(g.sids.length / 2)];
          return (
            <li key={`${g.name}-${i}`} className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-white/[0.04]">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
              <button className="min-w-0 flex-1 truncate text-left text-xs text-slate-200 hover:underline"
                onClick={() => { ws.select({ kind: "segment", sid: target }); onZoomSegment(target); }}>{g.name}</button>
              <span className="text-[10.5px] text-slate-500">{g.sids.length} seg.</span>
              <button className="btn btn-danger px-1.5 py-0.5 text-[10.5px]" disabled={!!ws.loading} aria-label={`Close ${g.name} on route`}
                onClick={() => ws.fail(target)}><Ban size={11} /> Close</button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RouteSummary({ ev }: { ev: Evaluation }) {
  const r = ev.route!;
  const failedOnRoute = r.uses_failed_segment;
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-2 gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
        <Stat label="Baseline route" value={km(r.baseline.length_m)} sub={`${r.baseline.segments.length} segments · intact network`} />
        <Stat label={ev.failed.length ? "Current route" : "Route"} value={r.current.available ? km(r.current.length_m) : "No route"}
          tone={!r.current.available ? "red" : r.detour_m && r.detour_m > 0 ? "amber" : "green"}
          sub={r.current.available ? `${r.current.segments.length} segments` : "destination unreachable"} />
        {ev.failed.length > 0 && r.current.available && (
          <Stat label="Detour" value={r.detour_m && r.detour_m > 0.5 ? `+${km(r.detour_m)}` : "none"}
            sub={r.detour_pct && r.detour_m && r.detour_m > 0.5 ? `+${r.detour_pct.toFixed(1)}% vs baseline` : failedOnRoute ? "equal-length alternative" : "closures are off this route"}
            tone={r.detour_m && r.detour_m > 0.5 ? "amber" : "green"} />
        )}
        <Stat label="Reachable from A" value={fmtNum(r.reachable_from_origin)}
          sub={r.reachable_from_origin < r.reachable_from_origin_baseline ? `−${fmtNum(r.reachable_from_origin_baseline - r.reachable_from_origin)} intersections` : "of the intersections in the region"}
          tone={r.reachable_from_origin < r.reachable_from_origin_baseline ? "violet" : undefined}
          hint="Intersections reachable from origin A by a legal route. Computed exactly on the whole region." />
      </div>
      <div className="flex flex-wrap gap-1.5 text-[10.5px] text-slate-500">
        <Badge>A snapped {Math.round(r.origin.snap_m)} m</Badge><Badge>B snapped {Math.round(r.destination.snap_m)} m</Badge>
        {!r.current.available && <Badge tone="red">no alternate route exists in this region</Badge>}
      </div>
    </div>
  );
}
