/**
 * FPS OPS Dashboard (formerly "Command Center") — the root of the operations
 * dashboard mounted in the FPS Overview Custom HTML Block on FPS Home
 * (mount variant "ops"; see main.tsx for the shadow-root plumbing). Open to
 * every desk user and carries NO MONEY since 14 Oct 2026: the API sends the
 * six operations KPIs, the Pipeline / Operations trend and no money insight
 * to everyone, and viewer.finance is always false. Invoices and collections
 * moved to the FPS ACC Dashboard (AccDashboard.tsx, Accounts Manager only).
 *
 * Layout (DESIGN.md §8, 12-column bento measured on the dashboard's own width):
 *   header        "FPS OPS Dashboard" · company · as-of date · live status · refresh
 *   insights      InsightBanner                                   12 / 12 / 12
 *   filter row    Period 7D/30D/90D · "Last 7 days · vs previous 7 days"
 *   KPI cards     6 → 3 per row at lg (6 in a row at xl); 8 → 4 per row at lg
 *                 (an older payload); any other count auto-fits ≥ 240px columns
 *   trend         TrendChart                                       lg 8 / 12
 *   stages        StageStrip (the old Overview tiles)              lg 4 / 12
 *
 * State owned here: the period (remembered per viewer in localStorage — a
 * convenience only; losing it is harmless) and the open drawer
 * {key, period, dimension}. Data comes from useDashboard(period), which only
 * ever GETs the whitelisted read-only method.
 *
 * Loading behaviour:
 *  - first load: a skeleton with the final layout's shapes (no layout jump) —
 *    always 6 KPI placeholders (the OPS page has no money KPIs for anyone);
 *  - error with nothing to show: an inline error with Retry;
 *  - refetch after a period change or a manual refresh: the previous frame
 *    stays, dimmed to 60% (no skeleton flash, DESIGN.md §6);
 *  - silent background polls (every 60 s): the frame stays at full strength
 *    and only the header's refresh icon spins. Dimming the whole dashboard for
 *    a second every minute would read as flicker on a wall screen.
 *
 * The drawer renders in the body-level portal host (see main.tsx); the Sheet
 * closes itself when the desk route leaves the workspace (lib/shadow.tsx
 * useDismissSignal), and it unmounts with the dashboard.
 *
 * PRESENTATION ONLY. Nothing here writes to ERPNext: no write method, no
 * frappe.client call, no POST. Interactions navigate, open the read-only
 * drawer, or open a blank form the user saves themselves.
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import { hasRole } from "@/lib/frappe";
import { VARIANTS } from "@/lib/variant";
import { useDashboard } from "@/hooks/useDashboard";
import { Skeleton } from "@/components/ui/skeleton";
import type { Kpi, KpiKey, Period } from "@/types/dashboard";
import { ActionDrawer, type DrawerState } from "./ActionDrawer";
import { BentoGrid, BentoItem, type BentoColumns, type ResponsiveSpan } from "./BentoGrid";
import { DashboardFrame, DashboardHeader, ErrorState } from "./DashboardChrome";
import { InsightBanner } from "./InsightBanner";
import { MetricCard } from "./MetricCard";
import { PeriodFilter } from "./PeriodFilter";
import { StageStrip } from "./StageStrip";
import { TrendChart } from "./TrendChart";
import { PERIOD_OPTIONS, isPeriod, readLocal, writeLocal } from "./shared";

/** Per-viewer convenience: the last period chosen on this browser. */
const PERIOD_STORAGE_KEY = "fps-cc:period:v1";
const DEFAULT_PERIOD: Period = "7d";
/** The six operations KPIs the API sends to every viewer (first-load skeleton size). */
const OPS_KPI_COUNT = 6;

/* ------------------------------------------------------------------------ */
/* Layout rules                                                               */
/* ------------------------------------------------------------------------ */

export interface KpiLayout {
  columns: BentoColumns;
  span?: ResponsiveSpan;
}

/**
 * KPI grid by count. Hand-tuned for the count the API sends (6, to everyone)
 * and for 8 (an older payload with the money KPIs); anything else auto-fits so
 * a future count never leaves a ragged hole.
 */
export function kpiLayout(count: number): KpiLayout {
  if (count === 8) return { columns: "12", span: { sm: 12, md: 6, lg: 3 } };
  if (count === 6) return { columns: "12", span: { sm: 12, md: 6, lg: 4, xl: 2 } };
  return { columns: "auto-fit" };
}

export const TREND_SPAN: ResponsiveSpan = { sm: 12, lg: 8 };
export const STAGES_SPAN: ResponsiveSpan = { sm: 12, lg: 4 };

/* ------------------------------------------------------------------------ */
/* Small pieces (the shared header, glow and error state: DashboardChrome)    */
/* ------------------------------------------------------------------------ */

function KpiGrid({
  kpis,
  compareLabel,
  onOpen,
}: {
  kpis: readonly Kpi[];
  compareLabel: string;
  onOpen: (key: KpiKey) => void;
}) {
  if (kpis.length === 0) {
    return <p className="glass rounded-2xl p-6 text-sm leading-5 text-ink-muted">No metrics are visible to you.</p>;
  }
  const layout = kpiLayout(kpis.length);
  return (
    <BentoGrid columns={layout.columns}>
      {kpis.map((kpi) => (
        <BentoItem key={kpi.key} span={layout.span}>
          <MetricCard kpi={kpi} compareLabel={compareLabel} onOpen={onOpen} />
        </BentoItem>
      ))}
    </BentoGrid>
  );
}

/**
 * First-load skeleton in the layout the payload will use: always 6 KPI cards
 * (lg 3, xl 6 per row) — the OPS page sends the six operations KPIs to every
 * viewer — so the real cards land where the placeholders were and nothing
 * below jumps. (A viewer who cannot read one source doctype gets 5 and
 * auto-fit; that reflow is accepted.)
 */
function LoadingFrame() {
  const block = "bg-hairline motion-reduce:animate-none";
  const count = OPS_KPI_COUNT;
  const kpi = kpiLayout(count);
  return (
    <>
      <p role="status" className="sr-only">
        Loading the dashboard…
      </p>
      <BentoGrid aria-hidden="true">
        <BentoItem>
          <div className="glass flex h-36 flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
            <Skeleton className={cn("h-5 w-40", block)} />
            <Skeleton className={cn("h-6 w-3/4", block)} />
            <Skeleton className={cn("h-4 w-1/2", block)} />
          </div>
        </BentoItem>
        <BentoItem>
          <Skeleton className={cn("h-10 w-72 max-w-full rounded-lg", block)} />
        </BentoItem>
        <BentoItem>
          <BentoGrid columns={kpi.columns}>
            {Array.from({ length: count }, (_, i) => (
              <BentoItem key={i} span={kpi.span}>
                <div className="glass flex h-56 flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
                  <Skeleton className={cn("h-8 w-32", block)} />
                  <Skeleton className={cn("h-10 w-24", block)} />
                  <Skeleton className={cn("h-5 w-36", block)} />
                  <Skeleton className={cn("h-10 w-full", block)} />
                </div>
              </BentoItem>
            ))}
          </BentoGrid>
        </BentoItem>
        <BentoItem span={TREND_SPAN}>
          <div className="glass flex h-[440px] flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
            <Skeleton className={cn("h-6 w-48", block)} />
            <Skeleton className={cn("h-8 w-64", block)} />
            <Skeleton className={cn("w-full flex-1 rounded-lg", block)} />
          </div>
        </BentoItem>
        <BentoItem span={STAGES_SPAN}>
          <div className="glass flex h-[440px] flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
            <Skeleton className={cn("h-6 w-32", block)} />
            {Array.from({ length: 7 }, (_, i) => (
              <Skeleton key={i} className={cn("h-8 w-full", block)} />
            ))}
          </div>
        </BentoItem>
      </BentoGrid>
    </>
  );
}

/* ------------------------------------------------------------------------ */
/* Root                                                                       */
/* ------------------------------------------------------------------------ */

/** Role that opens the FPS ACC Dashboard (acc_dashboard.GATE_ROLE). */
export const ACC_ROLE = "Accounts Manager";
/** Workspace "FPS ACC" (slug fps-acc). */
export const ACC_ROUTE = "/desk/fps-acc";

export default function CommandCenter(): React.JSX.Element {
  const [period, setPeriodState] = React.useState<Period>(() => {
    const saved = readLocal(PERIOD_STORAGE_KEY);
    return isPeriod(saved) ? saved : DEFAULT_PERIOD;
  });
  const setPeriod = React.useCallback((next: Period) => {
    setPeriodState(next);
    writeLocal(PERIOD_STORAGE_KEY, next);
  }, []);

  const dash = useDashboard(period);
  const { data, refresh } = dash;
  const [drawer, setDrawer] = React.useState<DrawerState | null>(null);
  // The FPS ACC Dashboard has no sidebar row on Frappe 16.51 (the site's
  // "Sidebar" record is site-owned; see build_workspaces.py), so its holders
  // reach it from here. Shown only to Accounts Manager (Administrator holds
  // every role); the ACC API refuses everyone else before it reads anything.
  const [accLink] = React.useState(() =>
    hasRole(ACC_ROLE) ? { label: "Open the FPS ACC Dashboard", route: ACC_ROUTE } : null,
  );

  // Dim only for a refetch the viewer asked for (manual refresh) or whose
  // numbers are visibly out of date (another period's payload on screen).
  const [manualRefresh, setManualRefresh] = React.useState(false);
  const busy = dash.loading || dash.refreshing;
  if (manualRefresh && !busy) setManualRefresh(false);
  const dim = Boolean(data) && dash.refreshing && (manualRefresh || data?.period !== period);

  const onRefresh = React.useCallback(() => {
    setManualRefresh(true);
    refresh();
  }, [refresh]);

  // Defensive: money KPIs only ever render for finance viewers, even if a
  // payload ever carried one by mistake. The OPS API sends viewer.finance =
  // false to everyone and no money KPI at all, so on this page none renders.
  const viewerFinance = data?.viewer.finance ?? false;
  const kpis = React.useMemo(
    () => (data?.kpis ?? []).filter((k) => !k.finance || viewerFinance),
    [data, viewerFinance],
  );
  const kpiByKey = React.useMemo(() => new Map(kpis.map((k) => [k.key, k])), [kpis]);
  const canOpenMetric = React.useCallback((key: KpiKey) => kpiByKey.has(key), [kpiByKey]);

  const openMetric = React.useCallback(
    (key: KpiKey) => {
      if (!kpiByKey.has(key)) return;
      setDrawer({ key, period, dimension: null });
    },
    [kpiByKey, period],
  );

  const periodText =
    data && data.period === period
      ? `${data.period_label} · ${data.compare_label}`
      : `${PERIOD_OPTIONS.find((o) => o.value === period)?.long ?? ""} · loading…`;
  const frameClass = cn("transition-opacity duration-150 ease-fps motion-reduce:transition-none", dim && "opacity-60");

  return (
    <DashboardFrame slot="command-center">
      <div className="relative flex flex-col gap-6 p-4 @min-[768px]/cc:p-6">
        <DashboardHeader
          title={VARIANTS.ops.title}
          link={accLink}
          asOf={data?.as_of ?? null}
          generatedAt={data?.generated_at}
          lastUpdated={dash.lastUpdated}
          busy={busy}
          onRefresh={onRefresh}
        />

        {!data ? (
          dash.error ? (
            <ErrorState message={dash.error} onRetry={onRefresh} />
          ) : (
            <LoadingFrame />
          )
        ) : (
          <BentoGrid aria-busy={dim}>
            <BentoItem className={frameClass}>
              <InsightBanner
                insights={data.insights}
                updatedAt={dash.lastUpdated}
                onOpenMetric={openMetric}
                canOpenMetric={canOpenMetric}
              />
            </BentoItem>

            <BentoItem>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <span aria-hidden="true" className="text-[13px] leading-5 font-medium text-ink-secondary">
                  Period
                </span>
                <PeriodFilter value={period} onChange={setPeriod} label="Period" />
                <span className="text-[13px] leading-5 text-ink-muted" aria-live="polite">
                  {periodText}
                </span>
              </div>
            </BentoItem>

            <BentoItem as="section" aria-label="Key metrics" className={frameClass}>
              <KpiGrid kpis={kpis} compareLabel={data.compare_label} onOpen={openMetric} />
            </BentoItem>

            <BentoItem span={TREND_SPAN} className={frameClass}>
              <TrendChart modes={data.trend} viewerFinance={viewerFinance} />
            </BentoItem>

            <BentoItem span={STAGES_SPAN} className={frameClass}>
              <StageStrip stages={data.stages} />
            </BentoItem>
          </BentoGrid>
        )}
      </div>

      <ActionDrawer
        state={drawer}
        kpi={drawer ? (kpiByKey.get(drawer.key) ?? null) : null}
        dashboardPeriod={data?.period ?? period}
        onChange={setDrawer}
        onClose={() => setDrawer(null)}
      />
    </DashboardFrame>
  );
}
