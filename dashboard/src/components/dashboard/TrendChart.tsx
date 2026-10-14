/**
 * TrendChart — "Trends · last 12 weeks", the bento's analytics card
 * (DESIGN.md §8: lg 8 columns, md/sm 12).
 *
 *  - Tabs: one per trend mode the API returned (Pipeline / Activity / Money).
 *    Money exists only for finance viewers; the API omits it for everyone else
 *    and this component drops any finance mode for a non-finance viewer too.
 *  - Area | Bar toggle (single-select, never empty) and a Table toggle that
 *    swaps the plot for its accessible twin (ChartTableView) of the same numbers.
 *  - Series colour comes from the series' fixed SLOT, which the server assigns
 *    by series key — so hiding a series never repaints the survivors.
 *  - At most 4 series; anything beyond folds into "Other" (--fps-series-other).
 *  - One y-axis per plot. Units never mix inside a mode (a mode has ONE unit),
 *    which is why money has its own tab rather than a second axis.
 *  - Legend for ≥ 2 series (line keys for area, swatches for bars); a single
 *    surviving series (the viewer cannot read the others) is named in plain
 *    text instead, and in the plot title and table caption; direct end-labels
 *    for ≤ 4 series where they fit; "This week so far" note when the last week
 *    is still running; the mode's data caveat in amber.
 *
 * The weekly trend is independent of the dashboard's period filter — it always
 * covers the last 12 ISO weeks — and the subtitle says so.
 */
import * as React from "react";
import { ChartArea, ChartColumn, Table2, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatValue } from "@/lib/format";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { TrendMode, TrendModeKey } from "@/types/dashboard";
import { AreaPlot, BarPlot, type PlotSeries } from "./charts";
import { buildRows, type ChartRow } from "./chart-utils";
import { ChartTableView } from "./ChartTableView";
import { SEGMENT_GROUP_CLASS, SEGMENT_ITEM_CLASS } from "./PeriodFilter";
import { SLOT_COLOR, useElementWidth } from "./shared";

export type TrendChartKind = "area" | "bar";

export interface TrendChartProps {
  /** payload.trend — 0–3 modes, in display order. */
  modes: readonly TrendMode[];
  /** payload.viewer.finance — defensive gate for money modes. */
  viewerFinance: boolean;
  /** Initial plot kind. */
  defaultKind?: TrendChartKind;
  className?: string;
}

/** DESIGN.md §4: four categorical slots, then everything else is "Other". */
export const MAX_SERIES = 4;
const OTHER_KEY = "__other";
/** Plot height incl. the x-axis band. Multiple of 8. */
const PLOT_HEIGHT = 280;
/** Below this card-content width the end labels would squeeze the plot. */
const MIN_WIDTH_FOR_END_LABELS = 480;

interface PreparedMode {
  mode: TrendMode;
  series: PlotSeries[];
  rows: ChartRow[];
  splitRows: ChartRow[];
  split: boolean;
  hasPartial: boolean;
  allZero: boolean;
}

function prepare(mode: TrendMode): PreparedMode {
  const raw = mode.series;
  const keep = raw.length > MAX_SERIES ? raw.slice(0, MAX_SERIES - 1) : raw;
  const folded = raw.length > MAX_SERIES ? raw.slice(MAX_SERIES - 1) : [];
  const series: PlotSeries[] = keep.map((s) => ({ key: s.key, label: s.label, color: SLOT_COLOR[s.slot] ?? "var(--fps-series-other)" }));
  if (folded.length > 0) series.push({ key: OTHER_KEY, label: "Other", color: "var(--fps-series-other)" });

  const points = mode.points.map((p) => {
    const values: Record<string, number> = {};
    for (const s of keep) values[s.key] = p.values[s.key] ?? 0;
    if (folded.length > 0) values[OTHER_KEY] = folded.reduce((sum, s) => sum + (p.values[s.key] ?? 0), 0);
    return { x: p.week_start, label: p.label, partial: p.partial, values };
  });
  const keys = series.map((s) => s.key);
  const plain = buildRows(
    points.map((p) => ({ ...p, partial: false })),
    keys,
  );
  // Bars dim per cell, so they take plain rows with the real partial flag back.
  const rows = plain.rows.map((r, i) => ({ ...r, partial: points[i].partial }));
  const splitBuild = buildRows(points, keys);
  return {
    mode,
    series,
    rows,
    splitRows: splitBuild.rows,
    split: splitBuild.split,
    hasPartial: points.some((p) => p.partial),
    allZero: points.every((p) => keys.every((k) => (p.values[k] ?? 0) === 0)),
  };
}

function Legend({ series, kind }: { series: readonly PlotSeries[]; kind: TrendChartKind }) {
  return (
    <ul aria-label="Legend" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs leading-4 text-ink-secondary">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className={kind === "area" ? "h-0.5 w-3 rounded-full" : "size-2 rounded-[2px]"}
            style={{ background: s.color }}
          />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function ModeBody({
  prepared,
  kind,
  showTable,
}: {
  prepared: PreparedMode;
  kind: TrendChartKind;
  showTable: boolean;
}) {
  const { mode, series } = prepared;
  const [measureRef, width] = useElementWidth<HTMLDivElement>();
  const fullFormat = (n: number) => formatValue(n, mode.unit, mode.currency);
  const last = prepared.rows[prepared.rows.length - 1];
  const weeks = prepared.rows.length;
  // DESIGN.md §6: 1 series → no legend box; the title names it. A mode arrives
  // with one series when the viewer cannot read the other doctypes, so the
  // heading, the plot's accessible title and the table caption all carry it.
  const only = series.length === 1 ? series[0] : null;
  const subject = only ? `${mode.label} · ${only.label}` : mode.label;
  const title = `${subject}, weekly totals, last ${weeks} weeks`;
  const desc = last
    ? `Latest week (${last.label}${last.partial ? ", so far" : ""}): ${series
        .map((s) => `${s.label} ${fullFormat(last.raw[s.key] ?? 0)}`)
        .join(", ")}.`
    : "No data.";
  const rowHeading = (row: ChartRow) => `Week of ${row.label}${row.partial ? " · so far" : ""}`;
  const directLabels = kind === "area" && series.length <= MAX_SERIES && width >= MIN_WIDTH_FOR_END_LABELS;

  return (
    <div className="flex flex-col gap-4">
      {series.length >= 2 ? (
        <Legend series={series} kind={kind} />
      ) : only ? (
        // The single series' name in the legend's place: plain ink text, no swatch or box.
        <p className="text-xs leading-4 text-ink-secondary">{only.label}</p>
      ) : null}
      <div ref={measureRef} className="min-w-0">
        {showTable ? (
          <ChartTableView
            caption={`${subject} by week`}
            rowHeader="Week of"
            columns={series.map((s) => ({ key: s.key, label: s.label, color: s.color }))}
            rows={prepared.rows.map((r) => ({ key: r.x, label: r.label, partial: r.partial, values: r.raw }))}
            format={fullFormat}
            maxHeight={PLOT_HEIGHT}
          />
        ) : kind === "area" ? (
          <AreaPlot
            rows={prepared.splitRows}
            split={prepared.split}
            series={series}
            unit={mode.unit}
            currency={mode.currency}
            height={PLOT_HEIGHT}
            title={title}
            desc={desc}
            rowHeading={rowHeading}
            directLabels={directLabels}
          />
        ) : (
          <BarPlot
            rows={prepared.rows}
            series={series}
            unit={mode.unit}
            currency={mode.currency}
            height={PLOT_HEIGHT}
            title={title}
            desc={desc}
            rowHeading={rowHeading}
          />
        )}
      </div>
      {prepared.allZero || (prepared.hasPartial && !showTable) || mode.caveat ? (
        <div className="flex flex-col gap-1 text-xs leading-4">
          {prepared.allZero ? <p className="text-ink-muted">No activity in the last {weeks} weeks.</p> : null}
          {prepared.hasPartial && !showTable ? (
            <p className="flex items-center gap-2 text-ink-muted">
              <span
                aria-hidden="true"
                className={cn(
                  "shrink-0",
                  kind === "area" ? "size-2 rounded-full border-2 border-ink-muted" : "size-2 rounded-[2px] bg-ink-muted/45",
                )}
              />
              This week so far — the last {kind === "area" ? "segment" : "column"} is still filling and is drawn lighter.
            </p>
          ) : null}
          {mode.caveat ? (
            <p className="flex items-start gap-1 text-ink-secondary">
              <TriangleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0 text-amber" />
              <span>
                <span className="font-medium text-amber">Caveat: </span>
                {mode.caveat}
              </span>
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function TrendChart({ modes, viewerFinance, defaultKind = "area", className }: TrendChartProps): React.JSX.Element {
  const visible = React.useMemo(() => modes.filter((m) => !m.finance || viewerFinance), [modes, viewerFinance]);
  const prepared = React.useMemo(() => visible.map(prepare), [visible]);
  const [activeKey, setActiveKey] = React.useState<TrendModeKey | null>(null);
  const [kind, setKind] = React.useState<TrendChartKind>(defaultKind);
  const [showTable, setShowTable] = React.useState(false);
  const headingId = React.useId();

  // The selected tab survives polls; if its mode disappears, fall back to the first.
  const active = prepared.find((p) => p.mode.key === activeKey) ?? prepared[0];
  const weeks = active?.rows.length || 12;

  return (
    <section
      aria-labelledby={headingId}
      data-slot="trend-chart"
      className={cn("glass @container/trend flex h-full min-w-0 flex-col gap-4 rounded-2xl p-4 @min-[480px]/trend:p-6", className)}
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id={headingId} className="text-base leading-6 font-semibold text-ink">
            Trends · last {weeks} weeks
          </h3>
          <p className="text-[13px] leading-5 text-ink-muted">Weekly totals · not affected by the period filter</p>
        </div>
        {active ? (
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              value={kind}
              onValueChange={(next) => {
                if (next === "area" || next === "bar") setKind(next);
              }}
              aria-label="Chart type"
              spacing={1}
              size="sm"
              disabled={showTable}
              className={SEGMENT_GROUP_CLASS}
            >
              <ToggleGroupItem value="area" className={SEGMENT_ITEM_CLASS}>
                <ChartArea aria-hidden="true" className="size-4" />
                Area
              </ToggleGroupItem>
              <ToggleGroupItem value="bar" className={SEGMENT_ITEM_CLASS}>
                <ChartColumn aria-hidden="true" className="size-4" />
                Bar
              </ToggleGroupItem>
            </ToggleGroup>
            <Toggle
              pressed={showTable}
              onPressedChange={setShowTable}
              size="sm"
              className={cn(SEGMENT_ITEM_CLASS, "ring-1 ring-hairline")}
            >
              <Table2 aria-hidden="true" className="size-4" />
              Table
            </Toggle>
          </div>
        ) : null}
      </header>

      {!active ? (
        <p className="py-8 text-sm leading-5 text-ink-muted">No trend data is available to you.</p>
      ) : prepared.length === 1 ? (
        // One mode: a tab list of one would be a tabpanel without a purpose.
        <div className="flex min-w-0 flex-col gap-4">
          <p className="text-sm leading-5 font-medium text-ink-secondary">{active.mode.label}</p>
          <ModeBody prepared={active} kind={kind} showTable={showTable} />
        </div>
      ) : (
        <Tabs value={active.mode.key} onValueChange={(v) => setActiveKey(v as TrendModeKey)} className="min-w-0 gap-4">
          {/* 40px = 32px tabs + 2×4px padding (DESIGN.md §3 default control height), the same box
              as the other segmented controls. The variant must match shadcn's base
              `group-data-[orientation=horizontal]/tabs:h-9`, or twMerge keeps that 36px rule. */}
          <TabsList
            aria-label="Trend"
            className="group-data-[orientation=horizontal]/tabs:h-10 max-w-full rounded-lg bg-surface-inset p-1 ring-1 ring-hairline"
          >
            {prepared.map((p) => (
              <TabsTrigger
                key={p.mode.key}
                value={p.mode.key}
                title={p.mode.label}
                // flex-auto, not shadcn's flex-1: equal-width tabs truncated the longer
                // label ("Cash flow") although the list had room; sized by content they
                // only truncate when the card is really too narrow.
                className="h-8 min-w-0 flex-auto px-2 text-[13px] leading-5 text-ink-secondary focus-visible:ring-2 focus-visible:ring-electric data-[state=active]:border-transparent data-[state=active]:bg-electric/15 data-[state=active]:text-ink @min-[480px]/trend:px-4 dark:data-[state=active]:border-transparent dark:data-[state=active]:bg-electric/15"
              >
                <span className="truncate">{p.mode.label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
          {prepared.map((p) => (
            <TabsContent key={p.mode.key} value={p.mode.key} className="min-w-0 focus-visible:outline-2 focus-visible:outline-electric">
              <ModeBody prepared={p} kind={kind} showTable={showTable} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </section>
  );
}
