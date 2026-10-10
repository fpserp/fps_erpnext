/**
 * Pure helpers shared by the trend chart, the drawer chart and the sparkline.
 * No React, no DOM: everything here is deterministic so the chart geometry is
 * the same in every frame and on every machine (DESIGN.md §7: a number must be
 * correct in every frame, executives screenshot these).
 */

export interface NiceScale {
  domain: [number, number];
  ticks: number[];
}

/** 1, 2, 2.5, 5 or 10 × 10^n — the step a person would pick for an axis. */
function niceStep(rough: number, integer: boolean): number {
  if (!Number.isFinite(rough) || rough <= 0) return 1;
  const exponent = Math.floor(Math.log10(rough));
  const base = 10 ** exponent;
  const fraction = rough / base;
  // 2.5 makes fractional ticks for small integer ranges (0, 2.5, 5…), so counts skip it.
  const steps = integer ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10];
  const nice = steps.find((s) => fraction <= s) ?? 10;
  const step = nice * base;
  return integer ? Math.max(1, Math.round(step)) : step;
}

/** Strip binary-float noise (0.30000000000000004) from tick values. */
function clean(n: number): number {
  return Number.parseFloat(n.toPrecision(12));
}

/**
 * A zero-anchored, clean-tick linear scale for [min, max]. Bars and areas grow
 * from a zero baseline, so 0 is always inside the domain; an all-zero series
 * gets [0, 1] so the baseline still sits at the bottom of the plot.
 */
export function niceScale(minValue: number, maxValue: number, opts?: { ticks?: number; integer?: boolean }): NiceScale {
  const target = Math.max(2, opts?.ticks ?? 4);
  const integer = opts?.integer ?? false;
  let lo = Math.min(0, Number.isFinite(minValue) ? minValue : 0);
  let hi = Math.max(0, Number.isFinite(maxValue) ? maxValue : 0);
  if (hi === lo) hi = lo + 1;
  const step = niceStep((hi - lo) / target, integer);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = lo, guard = 0; v <= hi + step / 2 && guard < 50; v += step, guard += 1) ticks.push(clean(v));
  return { domain: [clean(lo), clean(hi)], ticks };
}

/** Rough rendered width of tabular 12px Inter text, for reserving label room. */
export function approxTextWidth(text: string, fontSizePx = 12): number {
  return Math.ceil(text.length * fontSizePx * 0.62);
}

/** Suffix of the helper series that draws the still-filling last bucket. */
export const PARTIAL_SUFFIX = "__partial";

/** One row of chart data. `raw` always holds the true numbers (tooltip, table, labels). */
export interface ChartRow {
  /** Category value on the x axis (ISO date / week start). Unique per row. */
  x: string;
  /** Human label for ticks and tooltips ("6 Oct"). */
  label: string;
  partial: boolean;
  raw: Record<string, number>;
  [dataKey: string]: unknown;
}

/**
 * Area-chart data where the last bucket is still filling (today / this week).
 *
 * Each series is split in two dataKeys: `<key>` holds every complete bucket and
 * stops at the last complete one; `<key>__partial` holds only the final
 * segment (last complete → partial), which the chart draws dimmed with a
 * hollow end-dot. Keeping the dimmed segment a separate series is the only
 * approach that stays correct for flat lines: an objectBoundingBox stroke
 * gradient is ignored on a zero-height path, so an all-zero series would
 * vanish. Tooltips and tables read `raw`, never the split keys.
 */
export function buildRows(
  points: ReadonlyArray<{ x: string; label: string; partial: boolean; values: Record<string, number> }>,
  keys: readonly string[],
): { rows: ChartRow[]; split: boolean } {
  const n = points.length;
  const split = n >= 2 && points[n - 1].partial;
  const rows = points.map((p, i): ChartRow => {
    const row: ChartRow = { x: p.x, label: p.label, partial: p.partial, raw: {} };
    for (const key of keys) {
      const value = Number.isFinite(p.values[key]) ? p.values[key] : 0;
      row.raw[key] = value;
      if (!split) {
        row[key] = value;
        continue;
      }
      row[key] = i <= n - 2 ? value : null;
      row[`${key}${PARTIAL_SUFFIX}`] = i >= n - 2 ? value : null;
    }
    return row;
  });
  return { rows, split };
}

/** Largest and smallest raw value across rows and keys (0 when empty). */
export function rawExtent(rows: readonly ChartRow[], keys: readonly string[]): [number, number] {
  let min = 0;
  let max = 0;
  for (const row of rows) {
    for (const key of keys) {
      const v = row.raw[key] ?? 0;
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  return [min, max];
}
