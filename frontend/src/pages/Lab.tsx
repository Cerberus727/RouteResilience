import { CheckCircle2, Cpu, ImageOff, Play, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LabResult } from "../api/types";
import { useApi } from "../api/useApi";
import { Badge, Callout, EmptyState, ErrorState, Hint, Loading, Segmented, Spinner, Stat } from "../components/ui";
import { fmtNum } from "../lib/format";

type Subset = "phase1_saved" | "phase1_val" | "phase1_train" | "valid" | "test";
type View = "overlay" | "compare" | "errors";
const SUBSETS: { value: Subset; label: string; title: string }[] = [
  { value: "phase1_saved", label: "Phase I tiles", title: "The 44 validation tiles Phase I wrote masks for" },
  { value: "phase1_val", label: "Held-out", title: "Phase I validation subset (20%, has ground truth)" },
  { value: "phase1_train", label: "Train subset", title: "Phase I training subset: metrics are in-sample" },
  { value: "valid", label: "valid/", title: "DeepGlobe valid folder: no ground truth" },
  { value: "test", label: "test/", title: "DeepGlobe test folder: no ground truth" },
];
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(1)}%`);

export function Lab() {
  const models = useApi(() => api.labModels(), []);
  const [modelId, setModelId] = useState<string | null>(null);
  const [subset, setSubset] = useState<Subset>("phase1_saved");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [imageId, setImageId] = useState<string | null>(null);
  const [view, setView] = useState<View>("overlay");
  const [opacity, setOpacity] = useState(0.65);
  const [result, setResult] = useState<LabResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<Error | null>(null);
  const [imgError, setImgError] = useState(false);
  const PAGE = 60;
  const samples = useApi(() => api.labSamples(subset, page * PAGE, PAGE, q), [subset, page, q]);

  useEffect(() => {
    if (!modelId && models.data?.length) setModelId(models.data.find((m) => m.loadable)?.model_id ?? models.data[0].model_id);
  }, [models.data, modelId]);
  useEffect(() => {
    if (samples.data?.items.length && !samples.data.items.some((s) => s.image_id === imageId)) setImageId(samples.data.items[0].image_id);
  }, [samples.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setResult(null); setErr(null); setImgError(false); }, [imageId, modelId]);

  const model = models.data?.find((m) => m.model_id === modelId);
  const sample = samples.data?.items.find((s) => s.image_id === imageId);

  const run = async () => {
    if (!modelId || !imageId) return;
    setRunning(true);
    setErr(null);
    try {
      setResult(await api.labInfer(modelId, imageId));
    } catch (e) {
      setErr(e as Error);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 lg:grid-cols-[300px_minmax(0,1fr)_320px] lg:overflow-hidden">
      {/* ------------------------------------------------ browser */}
      <div className="panel flex min-h-0 flex-col">
        <div className="space-y-2.5 border-b border-white/[0.06] p-3">
          <h2 className="text-[13px] font-semibold text-slate-100">DeepGlobe samples</h2>
          <div className="flex flex-wrap gap-1">
            {SUBSETS.map((s) => (
              <button key={s.value} title={s.title} onClick={() => { setSubset(s.value); setPage(0); }}
                className={`rounded-md border px-2 py-0.5 text-[11px] ${subset === s.value ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-100" : "border-white/[0.08] text-slate-400 hover:text-slate-200"}`}>{s.label}</button>
            ))}
          </div>
          <input className="input w-full font-mono" placeholder="Filter by image id" value={q} aria-label="Filter images"
            onChange={(e) => { setQ(e.target.value.replace(/[^A-Za-z0-9_]/g, "")); setPage(0); }} />
          {samples.data && (
            <p className="text-[10.5px] leading-relaxed text-slate-500">
              {fmtNum(samples.data.total)} images. Phase I split reproduced (seed 42, 80/20 of {fmtNum(samples.data.dataset.paired_train)} train pairs):{" "}
              {samples.data.dataset.split_check.matches_val_ids_first40_plus_demo
                ? <span className="text-emerald-300">matches the 44 masks Phase I wrote ✓</span>
                : <span className="text-amber-300">could not be confirmed against Phase I masks</span>}
            </p>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {samples.loading ? <Loading /> : samples.error ? <div className="p-2"><ErrorState error={samples.error} what="list DeepGlobe images" /></div> : !samples.data?.items.length ? (
            <EmptyState title="No images">Nothing matches this filter.</EmptyState>
          ) : (
            <ul>
              {samples.data.items.map((s) => (
                <li key={s.image_id}>
                  <button onClick={() => setImageId(s.image_id)}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${s.image_id === imageId ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"}`}>
                    <img src={api.labImageUrl(s.image_id, "sat")} alt="" loading="lazy" className="h-9 w-9 shrink-0 rounded object-cover" />
                    <span className="min-w-0 flex-1">
                      <span className="block font-mono text-xs text-slate-100">{s.image_id}</span>
                      <span className="block text-[10.5px] text-slate-500">{s.phase1_subset ? `Phase I ${s.phase1_subset}` : `${s.folder}/`}{s.has_ground_truth ? " · GT" : " · no GT"}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {samples.data && samples.data.total > PAGE && (
          <div className="flex items-center justify-between border-t border-white/[0.06] p-2 text-[11px] text-slate-500">
            <button className="btn px-2 py-0.5" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
            {page * PAGE + 1}–{Math.min((page + 1) * PAGE, samples.data.total)}
            <button className="btn px-2 py-0.5" disabled={(page + 1) * PAGE >= samples.data.total} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        )}
      </div>

      {/* ------------------------------------------------ viewer */}
      <div className="panel flex min-h-[480px] flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-3 py-2">
          <span className="font-mono text-xs text-slate-200">{imageId ?? "—"}</span>
          {sample?.phase1_subset === "val" && <Badge tone="green">held-out</Badge>}
          {sample?.phase1_subset === "train" && <Badge tone="amber">training subset</Badge>}
          {sample && !sample.has_ground_truth && <Badge>no ground truth</Badge>}
          <div className="ml-auto flex items-center gap-2">
            <Segmented ariaLabel="View" size="xs" value={view} onChange={setView}
              options={[{ value: "overlay", label: "Overlay" }, { value: "compare", label: "Side by side" }, { value: "errors", label: "Errors" }]} />
            {view !== "compare" && (
              <label className="flex items-center gap-1.5 text-[11px] text-slate-400">Opacity
                <input type="range" min={0} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(+e.target.value)} className="w-20 accent-cyan-400" aria-label="Overlay opacity" />
              </label>
            )}
          </div>
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center p-3">
          {!imageId ? <EmptyState title="Select an image" /> : imgError ? (
            <EmptyState title="Image could not be loaded" icon={<ImageOff size={20} />}>The file exists in the index but the server could not read it.</EmptyState>
          ) : view === "compare" ? (
            <div className="grid w-full max-w-5xl grid-cols-2 gap-2 xl:grid-cols-4">
              <Frame label="Satellite image"><img src={api.labImageUrl(imageId, "sat")} alt="Satellite" className="h-full w-full object-cover" onError={() => setImgError(true)} /></Frame>
              <Frame label="Ground truth">{sample?.has_ground_truth ? <img src={api.labImageUrl(imageId, "gt")} alt="Ground truth" className="h-full w-full object-cover" /> : <Missing text="Not available for this image" />}</Frame>
              <Frame label="Predicted mask">{result ? <img src={result.urls.mask} alt="Prediction" className="h-full w-full object-cover" /> : <Missing text="Run inference" />}</Frame>
              <Frame label="Overlay">{result ? <div className="relative h-full w-full"><img src={api.labImageUrl(imageId, "sat")} alt="" className="h-full w-full object-cover" /><img src={result.urls.overlay} alt="Overlay" className="absolute inset-0 h-full w-full object-cover opacity-70" /></div> : <Missing text="Run inference" />}</Frame>
            </div>
          ) : (
            <div className="relative aspect-square h-full max-h-[calc(100vh-190px)] max-w-full overflow-hidden rounded-lg border border-white/[0.08] bg-black">
              <img src={api.labImageUrl(imageId, "sat")} alt={`Satellite image ${imageId}`} className="absolute inset-0 h-full w-full object-cover" onError={() => setImgError(true)} />
              {result && view === "overlay" && <img src={result.urls.overlay} alt="Predicted roads" className="absolute inset-0 h-full w-full object-cover" style={{ opacity }} />}
              {result && view === "errors" && result.urls.errors && <img src={result.urls.errors} alt="Error map" className="absolute inset-0 h-full w-full object-cover" style={{ opacity }} />}
              {view === "errors" && result && !result.urls.errors && (
                <div className="absolute inset-x-3 bottom-3"><Callout tone="warn">No ground truth for this image, so an error map cannot be computed.</Callout></div>
              )}
              {!result && !running && <div className="absolute inset-x-0 bottom-3 text-center text-[11px] text-slate-300/80">Showing the original image. Run inference to overlay the predicted roads.</div>}
              {running && <div className="absolute inset-0 grid place-items-center bg-black/40"><div className="glass flex items-center gap-2 px-3 py-2 text-xs"><Spinner /> Running inference on CPU…</div></div>}
            </div>
          )}
        </div>
        {view === "errors" && result?.urls.errors && (
          <div className="flex items-center gap-4 border-t border-white/[0.06] px-3 py-2 text-[11px] text-slate-400">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-green-500" /> correct road (TP)</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-red-500" /> false road (FP)</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-amber-500" /> missed road (FN)</span>
          </div>
        )}
      </div>

      {/* ------------------------------------------------ model & results */}
      <div className="panel min-h-0 space-y-4 overflow-y-auto p-3">
        <div>
          <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-slate-100"><Cpu size={14} className="text-cyan-300" /> Model</h2>
          {models.loading ? <Loading label="Checking checkpoints" /> : models.error ? <ErrorState error={models.error} what="check the checkpoints" onRetry={models.reload} /> : (
            <div className="space-y-1.5">
              {models.data!.map((m) => (
                <button key={m.model_id} onClick={() => setModelId(m.model_id)}
                  className={`w-full rounded-lg border px-2.5 py-2 text-left ${m.model_id === modelId ? "border-cyan-400/50 bg-cyan-400/[0.06]" : "border-white/[0.07] hover:border-white/15"}`}>
                  <div className="flex items-center gap-2">
                    {m.loadable ? <CheckCircle2 size={13} className="text-emerald-400" /> : <XCircle size={13} className="text-red-400" />}
                    <span className="text-xs font-medium text-slate-100">{m.model_id}</span>
                    <span className="ml-auto text-[10.5px] text-slate-500">{m.loadable ? "ready" : "not loadable"}</span>
                  </div>
                  <div className="mt-0.5 truncate pl-5 font-mono text-[10px] text-slate-500">{m.checkpoint}</div>
                </button>
              ))}
            </div>
          )}
          {model && !model.loadable && <div className="mt-2"><Callout tone="warn" title="Cannot run:">{model.diagnostic}</Callout></div>}
          <button className="btn btn-primary mt-3 w-full" disabled={!model?.loadable || !imageId || running} onClick={run}>
            {running ? <><Spinner /> Running…</> : <><Play size={13} /> Run inference</>}
          </button>
          <p className="mt-1.5 text-[10.5px] leading-relaxed text-slate-500">Uses Phase I preprocessing: resize to 512², ImageNet normalisation, sigmoid &gt; 0.5, nearest-neighbour resize back to 1024².</p>
        </div>
        {err && <ErrorState error={err} what="run inference" />}
        {result && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Latency" value={`${fmtNum(result.latency_ms, 0)} ms`} sub={`${result.device}, forward pass only`} />
              <Stat label="Road pixels" value={pct(result.road_fraction)} sub={`threshold ${result.threshold}`} />
            </div>
            <div>
              <div className="mb-1.5 flex items-center gap-1.5">
                <h3 className="section-title">Accuracy vs ground truth</h3>
                <Hint text="Pixel-level metrics against the DeepGlobe mask for this single image. They describe this tile only, not the model overall." />
              </div>
              {result.metrics ? (
                <>
                  <div className="mb-2"><Badge tone={result.phase1_subset === "val" ? "green" : "amber"}>{result.metrics.evaluation}</Badge></div>
                  <div className="grid grid-cols-2 gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
                    <Stat label="IoU" value={pct(result.metrics.iou)} tone="cyan" />
                    <Stat label="Dice / F1" value={pct(result.metrics.dice)} />
                    <Stat label="Precision" value={pct(result.metrics.precision)} />
                    <Stat label="Recall" value={pct(result.metrics.recall)} />
                  </div>
                </>
              ) : <Callout>No ground-truth mask for this image ({result.folder}/ has none), so accuracy cannot be measured.</Callout>}
            </div>
            {result.phase1_agreement && (
              <div>
                <h3 className="section-title mb-1.5">Reproducibility check</h3>
                <dl className="kv">
                  <dt>IoU with Phase I saved mask</dt><dd>{pct(result.phase1_agreement.iou_with_saved_mask)}</dd>
                  <dt>Differing pixels</dt><dd>{fmtNum(result.phase1_agreement.pixels_differing)}</dd>
                </dl>
                <p className="mt-1 text-[10.5px] text-slate-500">{result.phase1_agreement.note}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Frame({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <figure className="overflow-hidden rounded-lg border border-white/[0.08] bg-black">
      <div className="aspect-square">{children}</div>
      <figcaption className="bg-ink-900 px-2 py-1 text-[11px] text-slate-400">{label}</figcaption>
    </figure>
  );
}
const Missing = ({ text }: { text: string }) => <div className="checker grid h-full w-full place-items-center text-[11px] text-slate-500">{text}</div>;
