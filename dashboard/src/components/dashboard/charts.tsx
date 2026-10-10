/**
 * The two plot bodies every Command Center chart is drawn with — AreaPlot and
 * BarPlot — so the trend card and the drawer obey DESIGN.md §6 identically:
 *
 *  - lines 2px, round joins; area wash = vertical gradient 18% → 0%;
 *  - bars ≤ 24px, 4px rounded data end, square at the baseline, 2px gap;
 *  - ONE y-axis, zero-anchored, clean ticks; solid 1px horizontal grid in
 *    --fps-grid; axis ticks 12px ink-muted tabular figures;
 *  - crosshair (area) or band highlight (bar) + one tooltip listing every
 *    series at that x: value first (strong), label second, line-key;
 *  - the still-filling last bucket is dimmed (bars at 45%; the area's last
 *    segment at 45% with a hollow end-dot). The helper series that draws that
 *    segment also covers the last COMPLETE point, so it only ever draws a dot
 *    — static or active — on the last index; the complete point keeps the
 *    main series' filled dot alone;
 *  - colours come from the ChartConfig, which is keyed by SERIES KEY (never by
 *    position), and text never wears a series colour;
 *  - no animation: polls re-render every minute and a number must be right in
 *    every frame (DESIGN.md §7). That also makes reduced motion a non-issue.
 *
 * Keyboard: Recharts' accessibilityLayer (on by default in v3) makes the plot
 * focusable; arrow keys move the same tooltip the pointer shows. Keyboard focus
 * on the plot (<svg class="recharts-surface">) draws a 2px Electric Blue ring
 * (:focus-visible only — a pointer click shows none, and forced-colors keeps
 * the system outline). Recharts opens the tooltip by itself on the FIRST focus
 * only; when the plot is re-focused it keeps its last index and an arrow key
 * or Enter brings the tooltip back, so the ring is what tells the user where
 * focus is.
 *
 * Shadow DOM notes (checked against recharts 3.10.1):
 *  - Axis ticks get explicit font props (AXIS_TICK). Recharts thins ticks by
 *    measuring label widths with a hidden <span id="recharts_measurement_span">
 *    in document.body (util/DOMUtils.js), styled with the fontSize and
 *    letterSpacing it reads from the first rendered tick (CartesianAxis.js);
 *    the span's font-family is inherited from the desk's <body>, which uses
 *    the same InterVariable stack, so measurement and rendering agree.
 *  - Gradient ids come from React.useId() (identifierPrefix is unique per
 *    mount), so two charts never share a url(#…) target.
 *  - The in-chart tooltip is portalled into the chart's own wrapper and kept
 *    inside the plot's viewBox; no ancestor of a chart has overflow-hidden.
 *  - Area curves are type="monotone" = d3 curveMonotoneX in a horizontal
 *    layout: no overshoot, so a zero-anchored series never dips below 0.
 *  - XAxis interval="preserveEnd" (also the v3 default, pinned here): ticks are
 *    thinned from the end, so the last — still-filling — bucket keeps its
 *    label; it is shifted inwards rather than dropped when it would overflow.
 */
import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  XAxis,
  YAxis,
  useXAxisScale,
  useYAxisScale,
} from "recharts";
import { cn } from "@/lib/utils";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { formatValue } from "@/lib/format";
import type { Unit } from "@/types/dashboard";
import { PARTIAL_SUFFIX, approxTextWidth, niceScale, rawExtent, type ChartRow } from "./chart-utils";
import { svgSafeId } from "./shared";

export interface PlotSeries {
  key: string;
  label: string;
  /** CSS colour expression from SLOT_COLOR / ROLE_COLOR. Never a hex. */
  color: string;
}

export interface PlotProps {
  rows: readonly ChartRow[];
  /** 1–4 series. Callers fold anything beyond 4 into "Other" first. */
  series: readonly PlotSeries[];
  unit: Unit;
  currency?: string;
  /** Plot height in px, INCLUDING the x-axis band (no nested scroll). */
  height: number;
  /** Accessible name of the plot (SVG <title>). */
  title: string;
  /** Short spoken summary (SVG <desc>). */
  desc?: string;
  /** Tooltip heading for a row, e.g. "Week of 6 Oct · so far". */
  rowHeading: (row: ChartRow) => string;
  className?: string;
}

/** Dimming of the still-filling bucket. */
const PARTIAL_OPACITY = 0.45;

/** Tick text props for every axis (see the file comment: text measurement). */
const AXIS_TICK = { fontSize: 12, fontFamily: "InterVariable, Inter, sans-serif" } as const;

/** ChartConfig keyed by series key: the colour follows the entity, not its rank. */
function configFor(series: readonly PlotSeries[]): ChartConfig {
  const config: ChartConfig = {};
  for (const s of series) config[s.key] = { label: s.label, color: s.color };
  return config;
}

/** var(--color-<key>) as written by ChartStyle for this ChartContainer. */
function seriesVar(key: string): string {
  return `var(--color-${key})`;
}

interface Axis {
  domain: [number, number];
  ticks: number[];
  tickFormat: (n: number) => string;
  width: number;
}

function useAxis(rows: readonly ChartRow[], series: readonly PlotSeries[], unit: Unit, currency?: string): Axis {
  return React.useMemo(() => {
    const [min, max] = rawExtent(
      rows,
      series.map((s) => s.key),
    );
    const scale = niceScale(min, max, { ticks: 4, integer: unit === "count" });
    const tickFormat = (n: number) => formatValue(n, unit, currency, { compact: true });
    const width = Math.max(32, ...scale.ticks.map((t) => approxTextWidth(tickFormat(t)) + 8));
    return { domain: scale.domain, ticks: scale.ticks, tickFormat, width };
  }, [rows, series, unit, currency]);
}

/**
 * Tooltip body shared by both plots; reads `raw`, never the split dataKeys.
 *
 * Returns the ChartTooltipContent ELEMENT itself, not a wrapper component:
 * Recharts clones `content` with active / payload / label, and a wrapper
 * would swallow them (ChartTooltipContent renders nothing without them).
 *
 * The surface is the `glass-raised` utility (DESIGN.md §1 raised glass, §2
 * rule 4): only `.glass` / `.glass-raised` carry theme.css's mandatory
 * fallbacks — solid fill without backdrop-filter or under
 * prefers-reduced-transparency, no shadow under forced-colors. A hand-rolled
 * `bg-… backdrop-blur-[12px]` would not, and `backdrop-blur-*` after
 * `glass-raised` would also drop its saturate(140%). `bg-surface-raised` and
 * `border-hairline-strong` repeat the glass values so twMerge removes shadcn's
 * `bg-background` / `border-border/50` whatever the compiled order; the
 * unlayered fallbacks still beat both.
 */
export function tooltipContent({
  series,
  unit,
  currency,
  rowHeading,
}: Pick<PlotProps, "series" | "unit" | "currency" | "rowHeading">): React.ReactElement {
  const byKey = new Map(series.map((s) => [s.key, s]));
  return (
    <ChartTooltipContent
      className="glass-raised min-w-40 gap-2 rounded-lg border-hairline-strong bg-surface-raised px-2 py-2 text-ink"
      labelClassName="text-xs leading-4 font-medium text-ink-secondary"
      labelFormatter={(_label, payload) => {
        const row = payload[0]?.payload as ChartRow | undefined;
        return row ? rowHeading(row) : null;
      }}
      formatter={(_value, name, item) => {
        const key = String(name ?? "");
        const s = byKey.get(key);
        const row = item.payload as ChartRow | undefined;
        if (!s || !row) return null;
        return (
          <>
            <span aria-hidden="true" className="h-0.5 w-3 shrink-0 self-center rounded-full" style={{ background: s.color }} />
            <span className="font-semibold text-ink tabular-nums">{formatValue(row.raw[key] ?? 0, unit, currency)}</span>
            <span className="text-ink-secondary">{s.label}</span>
          </>
        );
      }}
    />
  );
}

/**
 * Shared container classes: fixed height incl. the x-axis band; ink-muted
 * tabular ticks; a visible keyboard focus ring on the plot (WCAG 2.4.7).
 *
 * shadcn's ChartContainer keeps `[&_.recharts-surface]:outline-hidden`, which
 * hides the ring for pointer focus and keeps the forced-colors outline. The
 * `:focus-visible` rules add the 2px Electric Blue ring for keyboard focus.
 * `outline-solid` is required: Tailwind v4's `outline-2` only sets
 * `outline-style: var(--tw-outline-style)`, and outline-hidden sets that
 * variable to `none` on the same element.
 */
function containerClass(className?: string): string {
  return cn(
    "aspect-auto w-full",
    "[&_.recharts-cartesian-axis-tick_text]:fill-ink-muted [&_.recharts-cartesian-axis-tick_text]:tabular-nums",
    "[&_.recharts-wrapper]:outline-none",
    "[&_.recharts-surface:focus-visible]:outline-solid [&_.recharts-surface:focus-visible]:outline-2 [&_.recharts-surface:focus-visible]:outline-offset-2 [&_.recharts-surface:focus-visible]:outline-electric",
    className,
  );
}

/* ------------------------------------------------------------------------ */
/* Direct end labels                                                          */
/* ------------------------------------------------------------------------ */

/** Below this gap two end labels would touch: show none and let the legend carry identity. */
const MIN_LABEL_GAP_PX = 16;

/**
 * The last value of each series, written just right of its line end (DESIGN.md
 * §6: ≤ 4 series → direct-label the last point). Ink text, never the series
 * colour. When any two labels would collide they are ALL dropped rather than
 * nudged apart — a nudged label detaches from its line and reads as noise; the
 * legend, tooltip and table view still carry every value.
 */
function EndLabels({
  rows,
  series,
  format,
}: {
  rows: readonly ChartRow[];
  series: readonly PlotSeries[];
  format: (n: number) => string;
}): React.ReactNode {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  const last = rows[rows.length - 1];
  if (!xScale || !yScale || !last) return null;
  const x = xScale(last.x, { position: "middle" });
  if (x === undefined) return null;
  const labels: { key: string; y: number; text: string }[] = [];
  for (const s of series) {
    const y = yScale(last.raw[s.key] ?? 0);
    if (y === undefined) return null;
    labels.push({ key: s.key, y, text: format(last.raw[s.key] ?? 0) });
  }
  const ys = labels.map((l) => l.y).sort((a, b) => a - b);
  for (let i = 1; i < ys.length; i += 1) if (ys[i] - ys[i - 1] < MIN_LABEL_GAP_PX) return null;
  return (
    <g aria-hidden="true" className="fps-end-labels">
      {labels.map((l) => (
        <text
          key={l.key}
          x={x + 10}
          y={l.y}
          dominantBaseline="middle"
          fill="var(--fps-text-secondary)"
          fontSize={12}
          fontWeight={500}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {l.text}
        </text>
      ))}
    </g>
  );
}

/* ------------------------------------------------------------------------ */
/* AreaPlot                                                                   */
/* ------------------------------------------------------------------------ */

export interface AreaPlotProps extends PlotProps {
  /** rows were built with the partial split (buildRows → split: true). */
  split: boolean;
  /** Write the last value beside each line end (callers decide whether it fits). */
  directLabels?: boolean;
}

export function AreaPlot({
  rows,
  series,
  unit,
  currency,
  height,
  title,
  desc,
  rowHeading,
  split,
  directLabels = false,
  className,
}: AreaPlotProps): React.JSX.Element {
  const gid = svgSafeId(`fps-area-${React.useId()}`);
  const config = React.useMemo(() => configFor(series), [series]);
  const axis = useAxis(rows, series, unit, currency);
  const labelFormat = React.useCallback((n: number) => formatValue(n, unit, currency, { compact: true }), [unit, currency]);
  const labelRoom = directLabels
    ? 16 + Math.max(...rows.slice(-1).flatMap((r) => series.map((s) => approxTextWidth(labelFormat(r.raw[s.key] ?? 0)))), 0)
    : 8;
  const lastIndex = rows.length - 1;
  const labelByX = React.useMemo(() => new Map(rows.map((r) => [r.x, r.label])), [rows]);

  /**
   * The hollow end-dot of the still-filling bucket, used for BOTH `dot` and
   * `activeDot` of the partial helper series. That series also holds the last
   * complete point (index n-2), where the main series already draws its filled
   * dot; drawing anything there would stack a hollow ring on top and make the
   * complete bucket read as partial. So: the last index only, or nothing. The
   * prop shape is the common subset of recharts' DotItemDotProps (dot) and
   * ActiveDotProps (activeDot).
   */
  const partialDot = (color: string) =>
    function PartialDot(props: { index: number; cx?: number | string; cy?: number | string }): React.ReactNode {
      const cx = Number(props.cx);
      const cy = Number(props.cy);
      if (props.index !== lastIndex || !Number.isFinite(cx) || !Number.isFinite(cy)) return null;
      return (
        <circle
          key={`partial-dot-${props.index}`}
          cx={cx}
          cy={cy}
          r={4}
          fill="var(--fps-surface-solid)"
          stroke={color}
          strokeWidth={2}
        />
      );
    };

  return (
    <ChartContainer config={config} className={containerClass(className)} style={{ height }}>
      <AreaChart
        data={rows as ChartRow[]}
        margin={{ top: 8, right: labelRoom, bottom: 0, left: 0 }}
        accessibilityLayer
        title={title}
        desc={desc}
      >
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`${gid}-${svgSafeId(s.key)}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={seriesVar(s.key)} stopOpacity={0.18} />
              <stop offset="100%" stopColor={seriesVar(s.key)} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} stroke="var(--fps-grid)" strokeWidth={1} />
        <XAxis
          dataKey="x"
          tickFormatter={(x: string) => labelByX.get(x) ?? x}
          tickLine={false}
          axisLine={{ stroke: "var(--fps-axis)" }}
          tickMargin={8}
          minTickGap={12}
          interval="preserveEnd"
          tick={AXIS_TICK}
        />
        <YAxis
          width={axis.width}
          domain={axis.domain}
          ticks={axis.ticks}
          tickFormatter={axis.tickFormat}
          tickLine={false}
          axisLine={false}
          tickMargin={4}
          tick={AXIS_TICK}
        />
        <ChartTooltip
          cursor={{ stroke: "var(--fps-border-strong)", strokeWidth: 1 }}
          filterNull={false}
          isAnimationActive={false}
          content={tooltipContent({ series, unit, currency, rowHeading })}
        />
        {series.map((s) => (
          <Area
            key={s.key}
            dataKey={s.key}
            name={s.key}
            type="monotone"
            stroke={seriesVar(s.key)}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            fill={`url(#${gid}-${svgSafeId(s.key)})`}
            fillOpacity={1}
            dot={false}
            activeDot={{ r: 4, fill: seriesVar(s.key), stroke: "var(--fps-surface-solid)", strokeWidth: 2 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        ))}
        {split
          ? series.map((s) => (
              <Area
                key={`${s.key}${PARTIAL_SUFFIX}`}
                dataKey={`${s.key}${PARTIAL_SUFFIX}`}
                name={`${s.key}${PARTIAL_SUFFIX}`}
                tooltipType="none"
                legendType="none"
                type="monotone"
                stroke={seriesVar(s.key)}
                strokeOpacity={PARTIAL_OPACITY}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                fill={`url(#${gid}-${svgSafeId(s.key)})`}
                fillOpacity={PARTIAL_OPACITY}
                dot={partialDot(seriesVar(s.key))}
                activeDot={partialDot(seriesVar(s.key))}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))
          : null}
        {directLabels ? <EndLabels rows={rows} series={series} format={labelFormat} /> : null}
      </AreaChart>
    </ChartContainer>
  );
}

/* ------------------------------------------------------------------------ */
/* BarPlot                                                                    */
/* ------------------------------------------------------------------------ */

/**
 * Grouped (never stacked) columns. Rows must be built WITHOUT the partial split;
 * the still-filling bucket is dimmed per cell instead.
 */
export function BarPlot({
  rows,
  series,
  unit,
  currency,
  height,
  title,
  desc,
  rowHeading,
  className,
}: PlotProps): React.JSX.Element {
  const config = React.useMemo(() => configFor(series), [series]);
  const axis = useAxis(rows, series, unit, currency);
  const labelByX = React.useMemo(() => new Map(rows.map((r) => [r.x, r.label])), [rows]);

  return (
    <ChartContainer config={config} className={containerClass(className)} style={{ height }}>
      <BarChart
        data={rows as ChartRow[]}
        margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
        barGap={2}
        barCategoryGap="20%"
        accessibilityLayer
        title={title}
        desc={desc}
      >
        <CartesianGrid vertical={false} stroke="var(--fps-grid)" strokeWidth={1} />
        <XAxis
          dataKey="x"
          tickFormatter={(x: string) => labelByX.get(x) ?? x}
          tickLine={false}
          axisLine={{ stroke: "var(--fps-axis)" }}
          tickMargin={8}
          minTickGap={12}
          interval="preserveEnd"
          tick={AXIS_TICK}
        />
        <YAxis
          width={axis.width}
          domain={axis.domain}
          ticks={axis.ticks}
          tickFormatter={axis.tickFormat}
          tickLine={false}
          axisLine={false}
          tickMargin={4}
          tick={AXIS_TICK}
        />
        <ChartTooltip
          cursor={{ fill: "var(--fps-surface-inset)" }}
          isAnimationActive={false}
          content={tooltipContent({ series, unit, currency, rowHeading })}
        />
        {series.map((s) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.key}
            fill={seriesVar(s.key)}
            radius={[4, 4, 0, 0]}
            maxBarSize={24}
            isAnimationActive={false}
          >
            {rows.map((r) => (
              <Cell key={r.x} fillOpacity={r.partial ? PARTIAL_OPACITY : 1} />
            ))}
          </Bar>
        ))}
      </BarChart>
    </ChartContainer>
  );
}
