/**
 * Sparkline — the period series of one KPI, DESIGN.md §6 "Sparklines".
 *
 * Hand-rolled SVG rather than a Recharts chart: eight of these sit on the page
 * and none needs axes, tooltips or a resize observer. The SVG stretches to its
 * box (preserveAspectRatio="none") with a non-scaling 2px stroke, and the end
 * dot is an HTML element positioned in percent, so it stays a true 8px circle
 * whatever the card width (a circle inside a stretched SVG becomes an ellipse).
 *
 * Decorative to assistive tech (aria-hidden): the sr-only sentence carries the
 * same numbers ("7-day trend: 0, 0, 2, 6, 14, 0, 0").
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import type { Granularity, SeriesPoint, Unit } from "@/types/dashboard";
import { ROLE_COLOR, formatterFor, svgSafeId, trendNoun } from "./shared";

export interface SparklineProps {
  /** The KPI's period series, oldest first (7, 30 or 13 points). */
  points: readonly SeriesPoint[];
  /** Picks the role colour: count → Electric Blue, currency → violet series step. */
  unit: Unit;
  currency?: string;
  granularity: Granularity;
  /** Plot height in px (multiple of 8). */
  height?: 32 | 40 | 48;
  className?: string;
}

/** viewBox units; the SVG is stretched to the box, so only proportions matter. */
const VB_W = 100;
const VB_H = 100;
/** Head-room so the end dot (8px + 2px ring) is never clipped at the top. */
const PAD_TOP = 14;
const PAD_BOTTOM = 6;

interface Geometry {
  xs: number[];
  ys: number[];
  flatZero: boolean;
}

function geometry(values: readonly number[]): Geometry {
  const n = values.length;
  const flatZero = values.every((v) => v === 0);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo;
  const usable = VB_H - PAD_TOP - PAD_BOTTOM;
  const xs = values.map((_, i) => (n <= 1 ? VB_W / 2 : (i / (n - 1)) * VB_W));
  const ys = values.map((v) => {
    // A constant non-zero series draws mid-height rather than pinned to the top.
    if (span === 0) return flatZero ? VB_H - PAD_BOTTOM : PAD_TOP + usable / 2;
    return PAD_TOP + (1 - (v - lo) / span) * usable;
  });
  return { xs, ys, flatZero };
}

export function Sparkline({
  points,
  unit,
  currency,
  granularity,
  height = 40,
  className,
}: SparklineProps): React.JSX.Element {
  const gradientId = svgSafeId(`fps-spark-${React.useId()}`);
  const values = points.map((p) => (Number.isFinite(p.value) ? p.value : 0));
  const color = ROLE_COLOR[unit];
  const format = formatterFor(unit, currency, true);
  const lastPartial = points.length > 0 && Boolean(points[points.length - 1].partial);

  const summary = `${trendNoun(points.length, granularity)}: ${values.map(format).join(", ")}${
    lastPartial ? ` (last ${granularity === "week" ? "week" : "day"} so far)` : ""
  }.`;

  if (values.length === 0) {
    return (
      <div className={cn("flex items-end", className)} style={{ height }}>
        <span className="text-xs leading-4 text-ink-muted">No data for this period</span>
      </div>
    );
  }

  const { xs, ys, flatZero } = geometry(values);

  if (flatZero) {
    return (
      <div className={cn("relative", className)} style={{ height }}>
        <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-px bg-axis" />
        <span className="absolute bottom-2 left-0 text-xs leading-4 text-ink-muted">No activity in this period</span>
      </div>
    );
  }

  const line = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${ys[i].toFixed(2)}`).join(" ");
  const area = `${line} L${xs[xs.length - 1].toFixed(2)},${VB_H} L${xs[0].toFixed(2)},${VB_H} Z`;
  const lastX = xs[xs.length - 1];
  const lastY = ys[ys.length - 1];

  return (
    <div className={cn("relative", className)} style={{ height }}>
      <svg
        aria-hidden="true"
        focusable="false"
        className="absolute inset-0 size-full overflow-visible"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        preserveAspectRatio="none"
      >
        <defs>
          {/* The wash: 18% → 0% of the line colour (DESIGN.md §6), never a solid block. */}
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.18} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradientId})`} stroke="none" />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {/* End dot: 8px, ringed in the surface colour; hollow when the bucket is still filling. */}
      <span
        aria-hidden="true"
        className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          left: `${(lastX / VB_W) * 100}%`,
          top: `${(lastY / VB_H) * 100}%`,
          background: lastPartial ? "var(--fps-surface-solid)" : color,
          border: lastPartial ? `2px solid ${color}` : undefined,
          boxShadow: "0 0 0 2px var(--fps-surface-solid)",
        }}
      />
      <span className="sr-only">{summary}</span>
    </div>
  );
}
