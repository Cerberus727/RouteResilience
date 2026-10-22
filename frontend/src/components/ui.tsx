import { AlertTriangle, Info, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";

type Tone = "neutral" | "cyan" | "amber" | "red" | "green" | "violet";
const TONES: Record<Tone, string> = {
  neutral: "border-white/10 bg-white/[0.04] text-slate-300",
  cyan: "border-cyan-400/30 bg-cyan-400/10 text-cyan-100",
  amber: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  red: "border-red-400/30 bg-red-400/10 text-red-100",
  green: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
  violet: "border-violet-400/30 bg-violet-400/10 text-violet-100",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-[10.5px] font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

/** Small (i) with an accessible hover/focus explanation. */
export function Hint({ text, className = "" }: { text: string; className?: string }) {
  return (
    <span className={`group relative inline-flex align-middle ${className}`}>
      <button type="button" aria-label={text} className="text-slate-500 hover:text-slate-300 focus:text-slate-300">
        <Info size={12} />
      </button>
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 hidden w-60 -translate-x-1/2 rounded-md border border-white/10 bg-ink-950 px-2.5 py-2 text-[11px] font-normal normal-case leading-snug tracking-normal text-slate-300 shadow-xl group-hover:block group-focus-within:block">
        {text}
      </span>
    </span>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div role="status" className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-white/10 px-4 py-6 text-center">
      {icon && <div className="text-slate-500">{icon}</div>}
      <p className="text-xs font-medium text-slate-300">{title}</p>
      {children && <div className="max-w-xs text-[11.5px] leading-relaxed text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, what }: { error: ApiError | Error | string; onRetry?: () => void; what?: string }) {
  const msg = typeof error === "string" ? error : error.message;
  const code = error instanceof ApiError ? error.code : undefined;
  return (
    <div role="alert" className="rounded-lg border border-red-400/25 bg-red-500/[0.07] px-3 py-2.5 text-xs">
      <div className="flex items-center gap-2 font-medium text-red-100">
        <AlertTriangle size={14} className="shrink-0 text-red-300" />
        {what ? `Could not ${what}` : "Request failed"}
        {code && <span className="font-mono text-[10.5px] text-red-300/70">{code}</span>}
      </div>
      <p className="mt-1 leading-relaxed text-red-100/80">{msg}</p>
      {onRetry && <button className="btn mt-2" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Spinner({ size = 14, className = "" }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={`animate-spin text-cyan-300 ${className}`} aria-hidden />;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 px-1 py-4 text-xs text-slate-400">
      <Spinner /> {label}…
    </div>
  );
}

export function Callout({ tone = "info", children, title }: { tone?: "info" | "warn" | "critical" | "success"; children: ReactNode; title?: string }) {
  const cls = tone === "warn" ? "border-amber-400/25 bg-amber-400/[0.06] text-amber-50/90"
    : tone === "critical" ? "border-red-400/25 bg-red-500/[0.07] text-red-50/90"
    : tone === "success" ? "border-emerald-400/25 bg-emerald-400/[0.06] text-emerald-50/90"
    : "border-sky-400/20 bg-sky-400/[0.05] text-slate-300";
  return (
    <div className={`rounded-lg border px-3 py-2 text-[11.5px] leading-relaxed ${cls}`}>
      {title && <span className="font-semibold">{title} </span>}{children}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, ariaLabel, size = "sm" }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; ariaLabel: string; size?: "sm" | "xs";
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="inline-flex rounded-md border border-white/[0.08] bg-ink-950/60 p-0.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} title={o.title} onClick={() => onChange(o.value)}
          className={`inline-flex items-center gap-1 rounded px-2 ${size === "xs" ? "py-0.5 text-[10.5px]" : "py-1 text-[11px]"} font-medium transition-colors ${value === o.value ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-200"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, tone, hint }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "red" | "amber" | "green" | "cyan" | "violet"; hint?: string }) {
  const c = tone === "red" ? "text-red-300" : tone === "amber" ? "text-amber-300" : tone === "green" ? "text-emerald-300" : tone === "cyan" ? "text-cyan-200" : tone === "violet" ? "text-violet-300" : "text-slate-50";
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-[10.5px] font-medium uppercase tracking-wider text-slate-500">{label}{hint && <Hint text={hint} />}</div>
      <div className={`mt-0.5 truncate text-[15px] font-semibold tabular-nums ${c}`}>{value}</div>
      {sub && <div className="truncate text-[10.5px] text-slate-500">{sub}</div>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, swatch, disabled, hint }: {
  checked: boolean; onChange: (v: boolean) => void; label: ReactNode; swatch?: ReactNode; disabled?: boolean; hint?: string;
}) {
  return (
    <label className={`flex cursor-pointer items-center gap-2 py-1 text-xs ${disabled ? "cursor-not-allowed opacity-40" : ""}`}>
      <input type="checkbox" className="peer sr-only" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="relative h-3.5 w-6 shrink-0 rounded-full bg-white/10 transition-colors after:absolute after:left-0.5 after:top-0.5 after:h-2.5 after:w-2.5 after:rounded-full after:bg-slate-400 after:transition-transform peer-checked:bg-cyan-500/50 peer-checked:after:translate-x-2.5 peer-checked:after:bg-white peer-focus-visible:ring-2 peer-focus-visible:ring-cyan-400/60" />
      {swatch}
      <span className="text-slate-300">{label}</span>
      {hint && <Hint text={hint} className="ml-auto" />}
    </label>
  );
}
