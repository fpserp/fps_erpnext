/**
 * ActionDrawer — the contextual drill-down for one KPI (shadcn Sheet, right
 * side, min(480px, 100vw) wide, raised glass). It renders through the portal
 * container of the body-level <fps-cc-portal> host that mount() creates (the
 * patched sheet.tsx does this): never inside a glass card, where a
 * backdrop-filter ancestor would trap the fixed-position drawer, and never
 * inside the block, where EditorJS's stacking context would keep it under the
 * desk navbar and sidebar. It closes when the desk route leaves the workspace.
 *
 * Contents, top to bottom:
 *   header   icon · label · [Finance] · full value · DeltaBadge · period text
 *   filters  ONE row: Period toggle (defaults to the dashboard's period) and,
 *            when the API names a dimension, chips "All" + its options
 *   chart    area chart of the detail series (single series → no legend; the
 *            heading names it) with a Table toggle (its accessible twin)
 *   breakdown horizontal single-hue bars, value label at the bar tip
 *   records  latest ≤ 8 records; a row opens the record and closes the drawer
 *   footer   quick actions from the API (open a list, open a BLANK new form
 *            the user saves themselves) + Close
 *
 * Loading keeps the previous content dimmed (no skeleton flash) once anything
 * has been shown; errors render inline with Retry. Escape, the overlay and
 * Close all dismiss it, and focus returns to the card that opened it (handled
 * by the shadow-safe Sheet).
 *
 * PRESENTATION ONLY: the drawer reads get_metric_detail and navigates. Its
 * "New …" action calls newDoc(), which opens an unsaved blank form — nothing
 * is created unless the user saves that form. Never add a write call here.
 */
import * as React from "react";
import { CircleAlert, ExternalLink, Plus, RefreshCw, Table2, TriangleAlert, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { newDoc } from "@/lib/frappe";
import { formatLongDate, formatMoney, formatShortDate, formatValue } from "@/lib/format";
import { useMetricDetail } from "@/hooks/useDashboard";
import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { BreakdownRow, DrillAction, DrillRecord, Kpi, KpiKey, MetricDetail, Period, Unit } from "@/types/dashboard";
import { AreaPlot } from "./charts";
import { approxTextWidth, buildRows, type ChartRow } from "./chart-utils";
import { ChartTableView } from "./ChartTableView";
import { DeltaBadge } from "./DeltaBadge";
import { DeskLink } from "./DeskLink";
import { PeriodFilter, SEGMENT_GROUP_CLASS, SEGMENT_ITEM_CLASS } from "./PeriodFilter";
import { KPI_ICON, ROLE_COLOR } from "./shared";

/** What the drawer shows. Owned by CommandCenter; the drawer only proposes changes. */
export interface DrawerState {
  key: KpiKey;
  period: Period;
  /** Active dimension value, or null for "All". */
  dimension: string | null;
}

export interface ActionDrawerProps {
  /** null = closed. */
  state: DrawerState | null;
  /** The KPI's summary from the dashboard payload: an instant header while the detail loads. */
  kpi: Kpi | null;
  /** The period that `kpi` was computed for (payload.period). */
  dashboardPeriod: Period;
  onChange: (next: DrawerState) => void;
  onClose: () => void;
}

/** Records shown at most (the API sends ≤ 8; never render more). */
export const MAX_RECORDS = 8;
/** Drawer chart height incl. the x-axis band. Multiple of 8. */
const DRAWER_PLOT_HEIGHT = 176;
/** Chip value for "All" — the API's "no dimension" is null, which a toggle cannot hold. */
const ALL = "__all__";

export function ActionDrawer({ state, kpi, dashboardPeriod, onChange, onClose }: ActionDrawerProps): React.JSX.Element {
  // Keep the last content while the Sheet animates out: `state` is already
  // null then, and an empty drawer sliding away looks broken.
  const [shown, setShown] = React.useState<DrawerState | null>(state);
  const [shownKpi, setShownKpi] = React.useState<Kpi | null>(kpi);
  if (state !== null && state !== shown) setShown(state);
  if (state !== null && kpi !== shownKpi) setShownKpi(kpi);
  const [retry, setRetry] = React.useState(0);

  return (
    <Sheet
      open={state !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        side="right"
        // Our own 32px close button sits in the header; the stock one is a 16px target.
        showCloseButton={false}
        className={cn(
          "glass-raised w-[min(480px,100vw)] max-w-none gap-0 border-l border-hairline-strong bg-surface-raised p-0 text-ink sm:max-w-none",
          "ease-fps data-[state=closed]:duration-200 data-[state=open]:duration-200",
          "motion-reduce:data-[state=closed]:animate-none motion-reduce:data-[state=open]:animate-none",
        )}
      >
        {shown ? (
          <DrawerBody
            key={`${shown.key}-${retry}`}
            state={shown}
            kpi={shownKpi && shownKpi.key === shown.key ? shownKpi : null}
            dashboardPeriod={dashboardPeriod}
            onChange={onChange}
            onClose={onClose}
            onRetry={() => setRetry((n) => n + 1)}
          />
        ) : (
          // Radix requires a title and description even before the first open.
          <>
            <SheetTitle className="sr-only">Metric details</SheetTitle>
            <SheetDescription className="sr-only">Details of a dashboard metric.</SheetDescription>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

/* ------------------------------------------------------------------------ */
/* Body                                                                       */
/* ------------------------------------------------------------------------ */

interface HeaderFacts {
  label: string;
  unit: Unit;
  currency?: string;
  value: number;
  previous: number | null;
  delta_pct: number | null;
  good_direction: Kpi["good_direction"];
  period_label?: string;
  compare_label?: string;
  finance: boolean;
}

function headerFacts(detail: MetricDetail | null, kpi: Kpi | null, useKpi: boolean): HeaderFacts | null {
  if (detail) {
    return {
      label: detail.label,
      unit: detail.unit,
      currency: detail.currency,
      value: detail.value,
      previous: detail.previous,
      delta_pct: detail.delta_pct,
      good_direction: detail.good_direction,
      period_label: detail.period_label,
      compare_label: detail.compare_label,
      finance: detail.unit === "currency" || Boolean(kpi?.finance),
    };
  }
  if (kpi && useKpi) {
    return {
      label: kpi.label,
      unit: kpi.unit,
      currency: kpi.currency,
      value: kpi.value,
      previous: kpi.previous,
      delta_pct: kpi.delta_pct,
      good_direction: kpi.good_direction,
      finance: kpi.finance,
    };
  }
  return null;
}

function DrawerBody({
  state,
  kpi,
  dashboardPeriod,
  onChange,
  onClose,
  onRetry,
}: {
  state: DrawerState;
  kpi: Kpi | null;
  dashboardPeriod: Period;
  onChange: (next: DrawerState) => void;
  onClose: () => void;
  onRetry: () => void;
}) {
  const detail = useMetricDetail(state.key, state.period, state.dimension);
  const data = detail.data && detail.data.key === state.key ? detail.data : null;
  // The dashboard's KPI numbers match the drawer only for the same period and "All".
  const facts = headerFacts(data, kpi, state.period === dashboardPeriod && state.dimension === null);
  const Icon = KPI_ICON[state.key];
  const label = facts?.label ?? kpi?.label ?? "Metric";
  const dims = data && data.dimension_label && data.dimension_options.length > 0 ? data : null;
  const firstLoad = !data && !detail.error;

  return (
    <>
      <SheetHeader className="gap-4 border-b border-hairline p-6">
        <div className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-inset text-electric-ui ring-1 ring-hairline"
          >
            <Icon className="size-4" />
          </span>
          <SheetTitle className="min-w-0 truncate text-base leading-6 font-semibold text-ink" title={label}>
            {label}
          </SheetTitle>
          {facts?.finance ? (
            <span className="shrink-0 rounded-md border border-hairline px-1.5 text-xs leading-5 text-ink-secondary">Finance</span>
          ) : null}
          {/* First tabbable element: the shadow-safe Sheet focuses it on open. */}
          <SheetClose asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Close details"
              className="-mr-2 ml-auto shrink-0 text-ink-secondary hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
            >
              <X aria-hidden="true" />
            </Button>
          </SheetClose>
        </div>
        <SheetDescription className="text-[13px] leading-5 text-ink-muted">
          {kpi?.definition ?? "Details behind this dashboard number."}
        </SheetDescription>
        {facts ? (
          <div className={cn("flex flex-col gap-2 transition-opacity duration-150", detail.refreshing && "opacity-60")}>
            <p className="text-[32px] leading-10 font-semibold tracking-tight break-words text-ink">
              {formatValue(facts.value, facts.unit, facts.currency)}
            </p>
            <DeltaBadge
              size="md"
              deltaPct={facts.delta_pct}
              value={facts.value}
              previous={facts.previous}
              goodDirection={facts.good_direction}
              compareLabel={facts.compare_label}
            />
            {facts.period_label ? (
              <p className="text-xs leading-4 text-ink-muted">
                {facts.period_label}
                {facts.compare_label ? ` · ${facts.compare_label}` : ""}
                {facts.previous !== null ? `: ${formatValue(facts.previous, facts.unit, facts.currency)}` : ""}
              </p>
            ) : null}
          </div>
        ) : !detail.error ? (
          <div className="flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-10 w-48 bg-hairline motion-reduce:animate-none" />
            <Skeleton className="h-5 w-40 bg-hairline motion-reduce:animate-none" />
          </div>
        ) : null}
      </SheetHeader>

      {/* One-row filter bar: period first (it scopes everything below), then dimension chips. */}
      <div className="flex min-w-0 items-center gap-2 border-b border-hairline px-6 py-4">
        <PeriodFilter
          value={state.period}
          onChange={(period) => onChange({ ...state, period })}
          label="Detail period"
          className="shrink-0"
        />
        {dims ? (
          <div className="min-w-0 flex-1 overflow-x-auto [scrollbar-width:thin]">
            <ToggleGroup
              type="single"
              value={state.dimension ?? ALL}
              onValueChange={(next) => {
                if (!next) return; // never empty: pressing the active chip keeps it
                onChange({ ...state, dimension: next === ALL ? null : next });
              }}
              aria-label={dims.dimension_label ?? "Filter"}
              spacing={1}
              size="sm"
              className={cn(SEGMENT_GROUP_CLASS, "w-max")}
            >
              <ToggleGroupItem value={ALL} className={SEGMENT_ITEM_CLASS}>
                All
              </ToggleGroupItem>
              {dims.dimension_options.map((option) => (
                <ToggleGroupItem key={option.key} value={option.key} className={SEGMENT_ITEM_CLASS}>
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        ) : null}
      </div>

      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-6"
        aria-busy={detail.loading || detail.refreshing}
      >
        {detail.error && !data ? (
          <div role="alert" className="flex flex-col items-start gap-2 rounded-xl border border-rose/25 bg-rose/10 p-4">
            <p className="flex items-center gap-2 text-sm leading-5 font-medium text-ink">
              <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-rose" />
              Could not load the details
            </p>
            <p className="text-[13px] leading-5 text-ink-secondary">{detail.error}</p>
            <Button variant="outline" size="sm" onClick={onRetry} className="mt-2 gap-2 px-4 has-[>svg]:px-4">
              <RefreshCw aria-hidden="true" />
              Retry
            </Button>
          </div>
        ) : firstLoad ? (
          <DrawerSkeleton />
        ) : data ? (
          <div className={cn("flex flex-col gap-8 transition-opacity duration-150", detail.refreshing && "opacity-60")}>
            <DetailChart detail={data} />
            {data.breakdown && data.breakdown.rows.length > 0 ? (
              <Breakdown title={data.breakdown.title} rows={data.breakdown.rows} unit={data.unit} currency={data.currency} />
            ) : null}
            <Records records={data.records} currency={data.currency} onNavigate={onClose} />
            {data.caveat ? (
              <p className="flex items-start gap-2 text-xs leading-4 text-ink-secondary">
                <TriangleAlert aria-hidden="true" className="size-3.5 shrink-0 text-amber" />
                <span>
                  <span className="font-medium text-amber">Caveat: </span>
                  {data.caveat}
                </span>
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <SheetFooter className="flex-row flex-wrap items-center gap-2 border-t border-hairline p-6">
        {(data?.actions ?? []).map((action) => (
          <QuickAction key={action.key} action={action} onDone={onClose} />
        ))}
        <SheetClose asChild>
          <Button variant="ghost" size="sm" className="ml-auto px-4 text-ink-secondary hover:text-ink">
            Close
          </Button>
        </SheetClose>
      </SheetFooter>
    </>
  );
}

/* ------------------------------------------------------------------------ */
/* Sections                                                                   */
/* ------------------------------------------------------------------------ */

function DrawerSkeleton() {
  const bar = "bg-hairline motion-reduce:animate-none";
  return (
    <div className="flex flex-col gap-8" aria-hidden="true">
      <div className="flex flex-col gap-2">
        <Skeleton className={cn("h-5 w-32", bar)} />
        <Skeleton className={cn("h-44 w-full rounded-lg", bar)} />
      </div>
      <div className="flex flex-col gap-2">
        <Skeleton className={cn("h-5 w-24", bar)} />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className={cn("h-8 w-full", bar)} />
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <Skeleton className={cn("h-5 w-28", bar)} />
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className={cn("h-12 w-full", bar)} />
        ))}
      </div>
    </div>
  );
}

function DetailChart({ detail }: { detail: MetricDetail }) {
  const [showTable, setShowTable] = React.useState(false);
  const headingId = React.useId();
  const color = ROLE_COLOR[detail.unit];
  const weekly = detail.granularity === "week";
  const { rows, split } = React.useMemo(
    () =>
      buildRows(
        detail.series.map((p) => ({
          x: p.date,
          label: formatShortDate(p.date),
          partial: Boolean(p.partial),
          values: { value: p.value },
        })),
        ["value"],
      ),
    [detail.series],
  );
  const series = React.useMemo(() => [{ key: "value", label: detail.label, color }], [detail.label, color]);
  const fullFormat = (n: number) => formatValue(n, detail.unit, detail.currency);
  const heading = `${detail.label} per ${weekly ? "week" : "day"}`;
  const rowHeading = (row: ChartRow) =>
    `${weekly ? `Week of ${row.label}` : formatLongDate(row.x)}${row.partial ? " · so far" : ""}`;
  const last = rows[rows.length - 1];

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h4 id={headingId} className="text-sm leading-5 font-medium text-ink">
          {heading}
          {detail.unit === "currency" && detail.currency ? <span className="text-ink-muted">{` (${detail.currency})`}</span> : null}
        </h4>
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
      {rows.length === 0 ? (
        <p className="py-4 text-[13px] leading-5 text-ink-muted">No data for this period.</p>
      ) : showTable ? (
        <ChartTableView
          caption={heading}
          rowHeader={weekly ? "Week of" : "Date"}
          columns={[{ key: "value", label: detail.label, color }]}
          rows={rows.map((r) => ({ key: r.x, label: r.label, partial: r.partial, values: r.raw }))}
          format={fullFormat}
          maxHeight={DRAWER_PLOT_HEIGHT + 64}
        />
      ) : (
        <AreaPlot
          rows={rows}
          split={split}
          series={series}
          unit={detail.unit}
          currency={detail.currency}
          height={DRAWER_PLOT_HEIGHT}
          title={heading}
          desc={last ? `Latest ${weekly ? "week" : "day"} (${last.label}${last.partial ? ", so far" : ""}): ${fullFormat(last.raw.value ?? 0)}.` : undefined}
          rowHeading={rowHeading}
        />
      )}
    </section>
  );
}

/**
 * Horizontal single-hue bars. The value label sits at the bar tip and is never
 * clipped: every bar's track is the row width minus room reserved for the
 * widest label, and the bar itself may shrink before the label does.
 */
function Breakdown({
  title,
  rows,
  unit,
  currency,
}: {
  title: string;
  rows: readonly BreakdownRow[];
  unit: Unit;
  currency?: string;
}) {
  const headingId = React.useId();
  const color = ROLE_COLOR[unit];
  const texts = rows.map((r) => formatValue(r.value, unit, currency));
  const max = rows.reduce((m, r) => Math.max(m, r.value), 0);
  const reserve = Math.max(...texts.map((t) => approxTextWidth(t)), 0) + 16;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h4 id={headingId} className="text-sm leading-5 font-medium text-ink">
        {title}
      </h4>
      <ul className="flex flex-col gap-4">
        {rows.map((row, i) => {
          const frac = max > 0 ? Math.max(0, row.value) / max : 0;
          return (
            <li key={row.key} className="flex min-w-0 flex-col gap-1">
              <span className="text-[13px] leading-5 text-ink-secondary">{row.label}</span>
              <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className="h-2 rounded-r-[4px]"
                  style={{
                    width: `calc((100% - ${reserve}px) * ${frac.toFixed(4)})`,
                    minWidth: row.value > 0 ? 2 : 0,
                    background: color,
                  }}
                />
                <span className="shrink-0 text-xs leading-4 font-medium whitespace-nowrap text-ink tabular-nums">{texts[i]}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * A record's `value` is always an AMOUNT OF MONEY in the company currency,
 * whatever the metric's unit: the invoice or receipt behind a money metric,
 * or — for finance viewers only — the grand total of a quotation behind the
 * Quotations count. Formatting it with the metric's unit would print a
 * quotation's AED 12,874.50 as the count "12,875", so it is always formatted
 * as money (`currency` is absent for count metrics; formatMoney then uses the
 * desk's company currency, the same AED the server reports in).
 */
function Records({
  records,
  currency,
  onNavigate,
}: {
  records: readonly DrillRecord[];
  currency?: string;
  onNavigate: () => void;
}) {
  const headingId = React.useId();
  const shown = records.slice(0, MAX_RECORDS);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h4 id={headingId} className="text-sm leading-5 font-medium text-ink">
        Latest records
      </h4>
      {shown.length === 0 ? (
        <p className="text-[13px] leading-5 text-ink-muted">No records in this period.</p>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {shown.map((record) => {
            const meta = [record.name, record.subtitle].filter(Boolean).join(" · ");
            const hasValue = typeof record.value === "number";
            return (
              <li key={record.name}>
                <DeskLink
                  route={record.route}
                  onNavigate={onNavigate}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-1 rounded-lg px-2 py-2 outline-none transition-colors duration-150 ease-fps hover:bg-surface-inset focus-visible:ring-2 focus-visible:ring-electric"
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-sm leading-5 font-medium text-ink" title={record.title}>
                      {record.title}
                    </span>
                    <span className="truncate text-xs leading-4 text-ink-muted" title={meta}>
                      {meta}
                    </span>
                  </span>
                  <span className="flex flex-col items-end gap-1">
                    <span className="text-sm leading-5 font-medium whitespace-nowrap text-ink tabular-nums">
                      {hasValue ? formatMoney(record.value as number, currency) : formatShortDate(record.date)}
                    </span>
                    {record.status || hasValue ? (
                      <span className="flex items-center gap-2 text-xs leading-4 text-ink-muted">
                        {record.status ? (
                          <span className="rounded-md border border-hairline px-1 whitespace-nowrap text-ink-secondary">{record.status}</span>
                        ) : null}
                        {hasValue ? <span className="whitespace-nowrap tabular-nums">{formatShortDate(record.date)}</span> : null}
                      </span>
                    ) : null}
                  </span>
                </DeskLink>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** A footer quick action: open a list/report, or open a BLANK new form (never saves). */
function QuickAction({ action, onDone }: { action: DrillAction; onDone: () => void }) {
  const cls = "gap-2 px-4 has-[>svg]:px-4";
  if (action.kind === "route" && action.route) {
    return (
      <Button asChild variant="outline" size="sm" className={cls}>
        <DeskLink route={action.route} onNavigate={onDone}>
          <ExternalLink aria-hidden="true" />
          {action.label}
        </DeskLink>
      </Button>
    );
  }
  if (action.kind === "new_doc" && action.doctype) {
    const doctype = action.doctype;
    return (
      <Button
        variant="outline"
        size="sm"
        className={cls}
        onClick={() => {
          // Close first (lib/frappe contract, as DeskLink does before navigate):
          // the drawer hands focus back to its card before Frappe's Quick Entry
          // dialog focuses its first field (Bootstrap's "shown", after the
          // fade), so the dialog keeps focus.
          onDone();
          newDoc(doctype); // opens an unsaved blank form; the user decides whether to save
        }}
      >
        <Plus aria-hidden="true" />
        {action.label}
      </Button>
    );
  }
  return null;
}
