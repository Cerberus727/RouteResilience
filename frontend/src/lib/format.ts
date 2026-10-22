/** Formatting helpers. `null`/`undefined` always render as an explicit "n/a". */

export const NA = "n/a";

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return NA;
  if (!Number.isFinite(v)) return NA;
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  const abs = Math.abs(v);
  if (abs !== 0 && abs < 10 ** -digits) return v.toExponential(2);
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
