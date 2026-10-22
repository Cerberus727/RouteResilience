import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtNum } from "../lib/format";

const AXIS = { stroke: "var(--grid)", tick: { fill: "var(--axis-text)", fontSize: 10 }, tickLine: false } as const;
export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

function TooltipBox({ active, payload, label, labelPrefix, valueFmt }: {
  active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string | number; labelPrefix?: string; valueFmt?: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-ink-600 bg-ink-900/95 px-2 py-1.5 font-mono text-2xs text-slate-200 shadow-lg">
      <div className="mb-0.5 text-slate-400">{labelPrefix}{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />
          <span className="text-slate-400">{p.name}</span>
          <span className="ml-auto pl-3 text-slate-100">{valueFmt ? valueFmt(p.value) : fmtNum(p.value, 4)}</span>
        </div>
      ))}
    </div>
  );
}

export function SeriesLines({ data, x, series, xLabel, yDomain, valueFmt }: {
  data: Record<string, number>[]; x: string; series: { key: string; name: string; color: string; dashed?: boolean }[];
  xLabel?: string; yDomain?: [number | "auto", number | "auto"]; valueFmt?: (v: number) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 6, right: 10, bottom: xLabel ? 14 : 0, left: -14 }}>
        <CartesianGrid vertical={false} stroke="var(--grid)" strokeOpacity={0.6} />
        <XAxis dataKey={x} {...AXIS} type="number" domain={["dataMin", "dataMax"]} allowDecimals={false}
          label={xLabel ? { value: xLabel, position: "insideBottom", offset: -8, fill: "var(--axis-text)", fontSize: 10 } : undefined} />
        <YAxis {...AXIS} domain={yDomain ?? ["auto", "auto"]} width={46} tickFormatter={(v: number) => fmtNum(v, 2)} />
        <Tooltip cursor={{ stroke: "#64748b", strokeDasharray: "3 3" }} content={<TooltipBox labelPrefix={xLabel ? `${xLabel} ` : ""} valueFmt={valueFmt} />} />
        {series.length > 1 && <Legend iconType="plainline" verticalAlign="top" align="right" height={20} wrapperStyle={{ fontSize: 10, color: "var(--axis-text)" }} />}
        {series.map((s) => (
          <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} dot={data.length <= 12 ? { r: 3, strokeWidth: 0, fill: s.color } : false}
            activeDot={{ r: 4, stroke: "#0a0f1a", strokeWidth: 2 }} strokeDasharray={s.dashed ? "5 3" : undefined} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
