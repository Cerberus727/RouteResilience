import { FileJson, FileSpreadsheet, FileText, History, Map as MapIcon, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { SavedRun } from "../api/types";
import { useApi } from "../api/useApi";
import { SERIES, SeriesLines } from "../components/charts";
import { Badge, Callout, EmptyState, ErrorState, Loading } from "../components/ui";
import { fmtNum } from "../lib/format";
import { useWorkspace } from "../state/workspace";
import { bboxKm } from "../workspace/RegionCard";

const km = (m: number | null) => (m === null ? "n/a" : m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`);
const pct = (v: number | null) => (v === null ? "n/a" : `${(v * 100).toFixed(2)}%`);

export function Reports() {
  const ws = useWorkspace();
  const [params, setParams] = useSearchParams();
  const runs = useApi(() => api.runs(), []);
  const selected = params.get("run");
  const run = useApi(() => api.run(selected!), [selected], !!selected);
  const exps = useApi(() => api.experiments(), []);
  const [delErr, setDelErr] = useState<Error | null>(null);

  useEffect(() => {
    if (!selected && runs.data?.length && !runs.data[0].error) setParams({ run: runs.data[0].id }, { replace: true });
  }, [runs.data, selected, setParams]);

  const remove = async (id: string) => {
    if (!window.confirm("Delete this saved run? This cannot be undone.")) return;
    try {
      await api.deleteRun(id);
      setParams({}, { replace: true });
      runs.reload();
    } catch (e) {
      setDelErr(e as Error);
    }
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 lg:grid-cols-[320px_minmax(0,1fr)] lg:overflow-hidden">
      <div className="flex min-h-0 flex-col gap-3">
        <div className="panel p-3">
          <h2 className="section-title mb-2">Current session (unsaved)</h2>
          {ws.region && ws.steps.length > 1 ? (
            <div className="space-y-2 text-xs">
              <div className="text-slate-200">{ws.steps.length - 1} action(s) · {ws.failed.length} road(s) closed now</div>
              <div className="text-[11px] text-slate-500">Not stored yet. Save it from the Simulate panel so the server recomputes and archives every step.</div>
              <Link to="/" className="btn w-full"><MapIcon size={13} /> Back to the map</Link>
            </div>
          ) : <p className="text-[11.5px] text-slate-500">No unsaved simulation. Close a road on the map to start one.</p>}
        </div>
        <div className="panel flex min-h-0 flex-1 flex-col">
          <h2 className="section-title border-b border-white/[0.06] px-3 py-2.5">Saved runs</h2>
          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {runs.loading ? <Loading /> : runs.error ? <ErrorState error={runs.error} what="list saved runs" onRetry={runs.reload} /> : !runs.data?.length ? (
              <EmptyState title="No saved runs yet" icon={<History size={18} />}>Simulate a closure on the map and press “Save run”.</EmptyState>
            ) : (
              <ul className="space-y-0.5">
                {runs.data.map((r) => (
                  <li key={r.id}>
                    <button onClick={() => setParams({ run: r.id })} disabled={r.error}
                      className={`w-full rounded-md px-2.5 py-2 text-left ${r.id === selected ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"}`}>
                      <div className="truncate text-xs font-medium text-slate-100">{r.name}</div>
                      <div className="mt-0.5 text-[10.5px] text-slate-500">
                        {r.error ? "unreadable file" : `${r.created_at?.replace("T", " ").slice(0, 16)} UTC · ${r.steps} steps · ${r.final_failed} closed at end`}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <div className="min-h-0 space-y-3 overflow-y-auto">
        {delErr && <ErrorState error={delErr} what="delete the run" />}
        {!selected ? (
          <div className="panel p-6"><EmptyState title="Select a saved run" /></div>
        ) : run.loading ? <div className="panel p-4"><Loading /></div> : run.error ? <ErrorState error={run.error} what="load the run" /> : run.data && (
          <RunDetail run={run.data} onDelete={() => remove(run.data!.id)} />
        )}
        <div className="panel">
          <div className="flex items-center gap-2 border-b border-white/[0.06] px-3 py-2.5">
            <h2 className="section-title">Research pipeline runs (historical)</h2>
            <Badge tone="violet">notebook artifacts</Badge>
          </div>
          {exps.loading ? <div className="p-3"><Loading /></div> : exps.error ? <div className="p-3"><ErrorState error={exps.error} what="list pipeline runs" /></div> : (
            <ul className="divide-y divide-white/[0.05]">
              {exps.data!.map((e) => (
                <li key={e.id} className="flex items-start gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-slate-200">{e.title}</div>
                    <div className="truncate font-mono text-[10.5px] text-slate-500">{e.phase} · {e.source}</div>
                    {e.warning && <div className="mt-0.5 text-[10.5px] text-amber-300/80">{e.warning}</div>}
                  </div>
                  <a className="btn px-2 py-0.5 text-[11px]" href={`/api/experiments/${encodeURIComponent(e.id)}`} target="_blank" rel="noreferrer">JSON</a>
                </li>
              ))}
            </ul>
          )}
          <p className="px-3 pb-3 text-[10.5px] text-slate-500">Results of the Phase I–III notebooks (pixel-space graphs from satellite masks). They are not geographically aligned with the OSM map. See docs/ARTIFACT_AUDIT.md.</p>
        </div>
      </div>
    </div>
  );
}

function RunDetail({ run, onDelete }: { run: SavedRun; onDelete: () => void }) {
  const b = run.region.bbox;
  const [w, h] = bboxKm(b);
  const hasRoute = run.origin !== null;
  const last = run.steps[run.steps.length - 1].metrics;
  return (
    <div className="panel">
      <div className="flex flex-wrap items-start gap-3 border-b border-white/[0.06] p-4">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold text-slate-50">{run.name}</h2>
          <p className="mt-0.5 text-[11px] text-slate-500">{run.created_at.replace("T", " ")} · {run.id}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge tone="cyan">{w.toFixed(1)} × {h.toFixed(1)} km</Badge>
            <Badge>{fmtNum(run.region.segments)} segments</Badge>
            <Badge>{run.routing_weight}</Badge>
            <Badge tone="green">server-recomputed</Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <a className="btn" href={api.runExportUrl(run.id, "md")}><FileText size={13} /> Report</a>
          <a className="btn" href={api.runExportUrl(run.id, "csv")}><FileSpreadsheet size={13} /> CSV</a>
          <a className="btn" href={api.runExportUrl(run.id, "json")}><FileJson size={13} /> JSON</a>
          <button className="btn btn-danger" onClick={onDelete} aria-label="Delete run"><Trash2 size={13} /></button>
        </div>
      </div>
      <div className="grid gap-4 p-4 xl:grid-cols-2">
        <dl className="kv content-start">
          <dt>Bounding box</dt><dd className="font-mono text-[10.5px]">{b.map((x) => x.toFixed(4)).join(", ")}</dd>
          <dt>Origin A</dt><dd className="font-mono text-[10.5px]">{run.origin ? `${run.origin[1].toFixed(5)}, ${run.origin[0].toFixed(5)}` : "not set"}</dd>
          <dt>Destination B</dt><dd className="font-mono text-[10.5px]">{run.destination ? `${run.destination[1].toFixed(5)}, ${run.destination[0].toFixed(5)}` : "not set"}</dd>
          <dt>Steps</dt><dd>{run.steps.length - 1}</dd>
          <dt>Final cut-off nodes</dt><dd>{fmtNum(last.cut_off_nodes)}</dd>
          <dt>Final sampled efficiency</dt><dd>{pct(last.sampled_efficiency_retention)}</dd>
          {hasRoute && <><dt>Baseline route</dt><dd>{km(last.baseline_route_length_m)}</dd></>}
          {hasRoute && <><dt>Final route</dt><dd>{last.route_available ? km(last.route_length_m) : <span className="text-red-300">no route</span>}</dd></>}
        </dl>
        <div className="h-44 rounded-lg border border-white/[0.06] bg-white/[0.02] p-1.5">
          <SeriesLines x="step" xLabel="" yDomain={[0, 100]} valueFmt={(v) => `${v.toFixed(2)}%`}
            data={run.steps.map((s) => ({ step: s.step, eff: (s.metrics.sampled_efficiency_retention ?? 0) * 100, reach: (s.metrics.sampled_reachable_fraction ?? 0) * 100 }))}
            series={[{ key: "eff", name: "Sampled efficiency", color: SERIES[0] }, { key: "reach", name: "Sampled reachability", color: SERIES[1], dashed: true }]} />
        </div>
      </div>
      <div className="max-h-[360px] overflow-auto border-t border-white/[0.06]">
        <table className="table-dense">
          <thead><tr><th>#</th><th>Action</th><th>Road</th><th>Closed</th><th>Strong comp.</th><th>Cut-off nodes</th><th>Affected</th><th>Efficiency</th>{hasRoute && <><th>Route</th><th>Detour</th></>}</tr></thead>
          <tbody>
            {run.steps.map((s) => (
              <tr key={s.step}>
                <td>{s.step}</td>
                <td className={s.action === "fail" ? "text-red-300" : s.action === "baseline" ? "text-slate-400" : "text-emerald-300"}>{s.action}</td>
                <td className="max-w-[200px] truncate" title={s.segment_id ?? ""}>{s.segment_name ?? "—"} {s.segment_id && <span className="font-mono text-[10px] text-slate-500">{s.segment_id}</span>}</td>
                <td>{s.metrics.failed_count}</td>
                <td>{s.metrics.strong_components}</td>
                <td>{fmtNum(s.metrics.cut_off_nodes)}</td>
                <td>{fmtNum(s.metrics.affected_segments)} · {s.metrics.affected_km.toFixed(2)} km</td>
                <td>{pct(s.metrics.sampled_efficiency_retention)}</td>
                {hasRoute && <><td>{s.metrics.route_available ? km(s.metrics.route_length_m) : <span className="text-red-300">none</span>}</td>
                  <td>{s.metrics.detour_m === null ? "—" : `${s.metrics.detour_m >= 0 ? "+" : ""}${km(s.metrics.detour_m)}`}</td></>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-1 border-t border-white/[0.06] p-4">
        <h3 className="section-title mb-1.5">Limitations</h3>
        {run.limitations.map((l) => <p key={l} className="text-[11px] leading-relaxed text-slate-400">• {l}</p>)}
        <div className="pt-2"><Callout>{run.provenance}</Callout></div>
      </div>
    </div>
  );
}
