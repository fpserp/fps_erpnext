/**
 * FPS ACC Dashboard — the accounting dashboard on Workspace "FPS ACC", block
 * "FPS ACC Overview" (mount variant "acc", see main.tsx). Accounts Manager
 * only: the Workspace is limited to that role and every API method checks it
 * (frappe.only_for) before reading anything; anyone else gets the calm
 * "You do not have access" panel, never a number.
 *
 * Built from the same components and tokens as the FPS OPS Dashboard
 * (CommandCenter.tsx), both palettes. Layout (DESIGN.md §8 bento, container
 * widths sm < 768 ≤ md < 1024 ≤ lg):
 *
 *   header      "FPS ACC Dashboard" · company · as-of · live status · refresh · appearance
 *               · "Open the FPS OPS Dashboard" link
 *   insights    InsightBanner (rule-based)                       12
 *   filter row  Period 7D/30D/90D · "Last 7 days · vs previous 7 days"
 *   KPI cards   Invoiced (net) · Collected · Paid to suppliers · Purchases booked
 *               (MetricCard; the drawer opens on click)          sm 12 / md 6 / lg 3
 *   positions   Receivables · Payables · Cash & bank · VAT for the quarter
 *               (BalanceCard; as of today, NOT the period)       sm 12 / md 6 / lg 3
 *   trend       TrendChart, Billing / Cash flow tabs             lg 8
 *   banks       BankStatusCard                                   lg 4
 *   ageing      AgeingPanel receivables · AgeingPanel payables    lg 6 + 6
 *
 * Every number is a link or opens the drawer. State owned here: the period
 * (per-viewer convenience in localStorage, its own key, separate from OPS) and
 * the open drawer. Data: useAccDashboard(period) → fps_erpnext.api.
 * acc_dashboard.get_dashboard; the drawer's useMetricDetail reads the variant
 * from context and calls acc_dashboard.get_metric_detail.
 *
 * Loading behaviour mirrors CommandCenter: a skeleton in the final layout on
 * first load; the previous frame dimmed to 60% on a period change or manual
 * refresh; silent background polls.
 *
 * PRESENTATION ONLY. Nothing here writes to ERPNext: interactions navigate,
 * open the read-only drawer, or open a blank form the user saves themselves.
 */
import * as React from "react";
import { LockKeyhole } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatLongDate } from "@/lib/format";
import { VARIANTS } from "@/lib/variant";
import { useAccDashboard } from "@/hooks/useDashboard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { BalanceCard as BalanceCardData } from "@/types/acc";
import type { Kpi, KpiKey, Period } from "@/types/dashboard";
import { ActionDrawer, type DrawerState } from "./ActionDrawer";
import { AgeingPanel } from "./AgeingPanel";
import { BalanceCard } from "./BalanceCard";
import { BankStatusCard } from "./BankStatusCard";
import { BentoGrid, BentoItem, type BentoColumns, type ResponsiveSpan } from "./BentoGrid";
import { DashboardFrame, DashboardHeader, ErrorState } from "./DashboardChrome";
import { DeskLink } from "./DeskLink";
import { InsightBanner } from "./InsightBanner";
import { MetricCard } from "./MetricCard";
import { PeriodFilter } from "./PeriodFilter";
import { TrendChart } from "./TrendChart";
import { PERIOD_OPTIONS, isPeriod, readLocal, writeLocal } from "./shared";

/** Per-viewer convenience: the last period chosen on this page (not shared with OPS). */
const PERIOD_STORAGE_KEY = "fps-acc:period:v1";
const DEFAULT_PERIOD: Period = "7d";
/** The FPS OPS Dashboard (Workspace "FPS"), offered from the no-access panel. */
const OPS_ROUTE = "/app/fps";
/** Header link back to the FPS OPS Dashboard (open to every desk user). */
const OPS_LINK = { label: "Open the FPS OPS Dashboard", route: OPS_ROUTE } as const;

/* ------------------------------------------------------------------------ */
/* Layout rules                                                               */
/* ------------------------------------------------------------------------ */

export interface CardRowLayout {
  columns: BentoColumns;
  span?: ResponsiveSpan;
}

/** Four cards: one row at lg, two at md, stacked on phones (KPIs and balances alike). */
export const ACC_CARD_SPAN: ResponsiveSpan = { sm: 12, md: 6, lg: 3 };
export const ACC_TREND_SPAN: ResponsiveSpan = { sm: 12, lg: 8 };
export const ACC_BANKS_SPAN: ResponsiveSpan = { sm: 12, lg: 4 };
export const ACC_AGEING_SPAN: ResponsiveSpan = { sm: 12, lg: 6 };

/**
 * A row of cards by count: the four the API sends get the hand-tuned spans; a
 * row the server could only partly compute (a KPI or account left out, never
 * sent as zero) auto-fits so it never leaves a ragged hole.
 */
export function accCardLayout(count: number): CardRowLayout {
  if (count === 4) return { columns: "12", span: ACC_CARD_SPAN };
  return { columns: "auto-fit" };
}

/* ------------------------------------------------------------------------ */
/* Pieces                                                                     */
/* ------------------------------------------------------------------------ */

function KpiRow({ kpis, compareLabel, onOpen }: { kpis: readonly Kpi[]; compareLabel: string; onOpen: (key: KpiKey) => void }) {
  if (kpis.length === 0) {
    return <p className="glass rounded-2xl p-6 text-sm leading-5 text-ink-muted">No figures could be computed for this period.</p>;
  }
  const layout = accCardLayout(kpis.length);
  return (
    <BentoGrid columns={layout.columns}>
      {kpis.map((kpi) => (
        <BentoItem key={kpi.key} span={layout.span}>
          <MetricCard kpi={kpi} compareLabel={compareLabel} onOpen={onOpen} financeChip={false} />
        </BentoItem>
      ))}
    </BentoGrid>
  );
}

function BalanceRow({ balances }: { balances: readonly BalanceCardData[] }) {
  if (balances.length === 0) {
    return <p className="glass rounded-2xl p-6 text-sm leading-5 text-ink-muted">No balances could be computed.</p>;
  }
  const layout = accCardLayout(balances.length);
  return (
    <BentoGrid columns={layout.columns}>
      {balances.map((balance) => (
        <BentoItem key={balance.key} span={layout.span}>
          <BalanceCard balance={balance} />
        </BentoItem>
      ))}
    </BentoGrid>
  );
}

/**
 * The server said PermissionError: this viewer is not an Accounts Manager. A
 * calm statement, not an error — and no number of any kind.
 */
export function NoAccessPanel(): React.JSX.Element {
  return (
    <div role="status" data-slot="acc-no-access" className="glass flex flex-col items-start gap-4 rounded-2xl p-6">
      <p className="flex items-center gap-2 text-base leading-6 font-semibold text-ink">
        <LockKeyhole aria-hidden="true" className="size-5 shrink-0 text-ink-secondary" />
        You do not have access to the FPS ACC Dashboard.
      </p>
      <p className="max-w-[72ch] text-sm leading-5 text-ink-secondary">
        It shows the company accounts and is open to Accounts Managers only. Ask an administrator if you need it.
      </p>
      <Button asChild variant="outline" size="sm" className="px-4">
        <DeskLink route={OPS_ROUTE}>Open the FPS OPS Dashboard</DeskLink>
      </Button>
    </div>
  );
}

/** First-load skeleton in the final layout's shapes: 4 KPIs, 4 balances, trend + banks, 2 ageing panels. */
function LoadingFrame() {
  const block = "bg-hairline motion-reduce:animate-none";
  const card = (key: number, height: string) => (
    <BentoItem key={key} span={ACC_CARD_SPAN}>
      <div className={cn("glass flex flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6", height)}>
        <Skeleton className={cn("h-8 w-32", block)} />
        <Skeleton className={cn("h-10 w-28", block)} />
        <Skeleton className={cn("h-5 w-36", block)} />
        <Skeleton className={cn("h-10 w-full", block)} />
      </div>
    </BentoItem>
  );
  return (
    <>
      <p role="status" className="sr-only">
        Loading the FPS ACC Dashboard…
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
          <BentoGrid>{[0, 1, 2, 3].map((i) => card(i, "h-56"))}</BentoGrid>
        </BentoItem>
        <BentoItem>
          <div className="flex flex-col gap-4">
            <Skeleton className={cn("h-5 w-64 max-w-full", block)} />
            <BentoGrid>{[0, 1, 2, 3].map((i) => card(i, "h-48"))}</BentoGrid>
          </div>
        </BentoItem>
        <BentoItem span={ACC_TREND_SPAN}>
          <div className="glass flex h-[440px] flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
            <Skeleton className={cn("h-6 w-48", block)} />
            <Skeleton className={cn("h-8 w-64 max-w-full", block)} />
            <Skeleton className={cn("w-full flex-1 rounded-lg", block)} />
          </div>
        </BentoItem>
        <BentoItem span={ACC_BANKS_SPAN}>
          <div className="glass flex h-[440px] flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
            <Skeleton className={cn("h-6 w-40", block)} />
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className={cn("h-12 w-full", block)} />
            ))}
          </div>
        </BentoItem>
        {[0, 1].map((i) => (
          <BentoItem key={i} span={ACC_AGEING_SPAN}>
            <div className="glass flex h-[520px] flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6">
              <Skeleton className={cn("h-6 w-48", block)} />
              <Skeleton className={cn("h-10 w-full", block)} />
              {[0, 1, 2, 3, 4, 5, 6].map((j) => (
                <Skeleton key={j} className={cn("h-3 w-full", block)} />
              ))}
              <Skeleton className={cn("w-full flex-1 rounded-lg", block)} />
            </div>
          </BentoItem>
        ))}
      </BentoGrid>
    </>
  );
}

/* ------------------------------------------------------------------------ */
/* Root                                                                       */
/* ------------------------------------------------------------------------ */

export default function AccDashboard(): React.JSX.Element {
  const [period, setPeriodState] = React.useState<Period>(() => {
    const saved = readLocal(PERIOD_STORAGE_KEY);
    return isPeriod(saved) ? saved : DEFAULT_PERIOD;
  });
  const setPeriod = React.useCallback((next: Period) => {
    setPeriodState(next);
    writeLocal(PERIOD_STORAGE_KEY, next);
  }, []);

  const dash = useAccDashboard(period);
  const { data, refresh } = dash;
  const [drawer, setDrawer] = React.useState<DrawerState | null>(null);
  const balancesHeadingId = React.useId();

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

  const kpis = React.useMemo(() => data?.kpis ?? [], [data]);
  const kpiByKey = React.useMemo(() => new Map(kpis.map((k) => [k.key, k])), [kpis]);
  const canOpenMetric = React.useCallback((key: KpiKey) => kpiByKey.has(key), [kpiByKey]);
  const openMetric = React.useCallback(
    (key: KpiKey) => {
      if (!kpiByKey.has(key)) return;
      setDrawer({ key, period, dimension: null });
    },
    [kpiByKey, period],
  );

  // A refusal closes any open drawer: no detail may load for a refused viewer.
  if (dash.denied && drawer) setDrawer(null);

  const periodText =
    data && data.period === period
      ? `${data.period_label} · ${data.compare_label}`
      : `${PERIOD_OPTIONS.find((o) => o.value === period)?.long ?? ""} · loading…`;
  const frameClass = cn("transition-opacity duration-150 ease-fps motion-reduce:transition-none", dim && "opacity-60");
  const currency = data?.balances[0]?.currency ?? data?.kpis[0]?.currency;

  return (
    <DashboardFrame slot="acc-dashboard">
      <div className="relative flex flex-col gap-6 p-4 @min-[768px]/cc:p-6">
        <DashboardHeader
          title={VARIANTS.acc.title}
          link={OPS_LINK}
          asOf={data?.as_of ?? null}
          generatedAt={data?.generated_at}
          lastUpdated={dash.lastUpdated}
          busy={busy}
          onRefresh={onRefresh}
        />

        {!data ? (
          dash.denied ? (
            <NoAccessPanel />
          ) : dash.error ? (
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

            <BentoItem as="section" aria-label="Money in and out for the period" className={frameClass}>
              <KpiRow kpis={kpis} compareLabel={data.compare_label} onOpen={openMetric} />
            </BentoItem>

            <BentoItem as="section" aria-labelledby={balancesHeadingId} className={cn("flex flex-col gap-4", frameClass)}>
              {/* Sits on the bare plane (outside any card), so it uses secondary ink (DESIGN.md §5). */}
              <p id={balancesHeadingId} className="text-[13px] leading-5 text-ink-secondary">
                <span className="font-medium">Position as of {formatLongDate(data.as_of)}</span>
                {" · not affected by the period filter"}
              </p>
              <BalanceRow balances={data.balances} />
            </BentoItem>

            <BentoItem span={ACC_TREND_SPAN} className={frameClass}>
              {/* The ACC API only answers Accounts Managers, so its money modes are for this viewer. */}
              <TrendChart modes={data.trend} viewerFinance />
            </BentoItem>

            <BentoItem span={ACC_BANKS_SPAN} className={frameClass}>
              <BankStatusCard banks={data.banks} currency={currency} />
            </BentoItem>

            {data.ageing.map((ageing) => (
              <BentoItem key={ageing.key} span={ACC_AGEING_SPAN} className={frameClass}>
                <AgeingPanel ageing={ageing} asOf={data.as_of} />
              </BentoItem>
            ))}
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
