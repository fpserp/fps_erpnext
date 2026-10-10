/**
 * FPS Command Center — the root of the executive dashboard mounted in the
 * FPS Overview Custom HTML Block (see main.tsx for the shadow-root plumbing).
 *
 * Layout (DESIGN.md §8, 12-column bento measured on the dashboard's own width):
 *   header        "Command Center" · company · as-of date · live status · refresh
 *   insights      InsightBanner                                   12 / 12 / 12
 *   filter row    Period 7D/30D/90D · "Last 7 days · vs previous 7 days"
 *   KPI cards     8 → 4 per row at lg; 6 → 3 per row at lg (6 in a row at xl);
 *                 any other count auto-fits ≥ 240px columns
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
 *    8 KPI placeholders for finance roles, 6 otherwise, read from the desk's
 *    roles before any request;
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
import { CircleAlert, Moon, RefreshCw, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatLongDate, formatTime } from "@/lib/format";
import { hasRole, openThemeSwitcher } from "@/lib/frappe";
import { usePalette } from "@/lib/palette";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useHostVisible } from "@/lib/shadow";
import { POLL_INTERVAL_MS, useDashboard } from "@/hooks/useDashboard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Kpi, KpiKey, Period } from "@/types/dashboard";
import { ActionDrawer, type DrawerState } from "./ActionDrawer";
import { BentoGrid, BentoItem, type BentoColumns, type ResponsiveSpan } from "./BentoGrid";
import { InsightBanner } from "./InsightBanner";
import { MetricCard } from "./MetricCard";
import { PeriodFilter } from "./PeriodFilter";
import { StageStrip } from "./StageStrip";
import { TrendChart } from "./TrendChart";
import { PERIOD_OPTIONS, isPeriod, readLocal, writeLocal } from "./shared";

/** Per-viewer convenience: the last period chosen on this browser. */
const PERIOD_STORAGE_KEY = "fps-cc:period:v1";
const DEFAULT_PERIOD: Period = "7d";
/** Three missed polls and the live dot turns amber "Stale". */
const STALE_AFTER_MS = 3 * POLL_INTERVAL_MS;

/* ------------------------------------------------------------------------ */
/* Layout rules                                                               */
/* ------------------------------------------------------------------------ */

export interface KpiLayout {
  columns: BentoColumns;
  span?: ResponsiveSpan;
}

/**
 * KPI grid by count. Hand-tuned for the two counts the API actually sends
 * (8 for finance viewers, 6 for everyone else); anything else auto-fits so a
 * future count never leaves a ragged hole.
 */
export function kpiLayout(count: number): KpiLayout {
  if (count === 8) return { columns: "12", span: { sm: 12, md: 6, lg: 3 } };
  if (count === 6) return { columns: "12", span: { sm: 12, md: 6, lg: 4, xl: 2 } };
  return { columns: "auto-fit" };
}

export const TREND_SPAN: ResponsiveSpan = { sm: 12, lg: 8 };
export const STAGES_SPAN: ResponsiveSpan = { sm: 12, lg: 4 };

/**
 * Mirrors fps_erpnext.api.command_center.FINANCE_ROLES: the API sends 8 KPIs
 * to these roles and 6 to everyone else. Used only to size the first-load
 * skeleton; what is RENDERED always follows the payload (and viewer.finance).
 */
const FINANCE_ROLES = ["Accounts User", "Accounts Manager", "System Manager"] as const;

/* ------------------------------------------------------------------------ */
/* Small pieces                                                               */
/* ------------------------------------------------------------------------ */

/**
 * Two fixed, very low-alpha radial glows (Electric Blue top-left, Soft Violet
 * top-right) so the glass has something to blur. Decoration only — no data —
 * and removed under reduced transparency and forced colours (DESIGN.md §1).
 */
function AmbientGlow() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-[inherit] forced-colors:hidden [@media(prefers-reduced-transparency:reduce)]:hidden"
    >
      {/* Strength is a palette token: 10% / 8% on Pearl, 4% / 3% on Matte Black. */}
      <div
        className="absolute -top-48 -left-40 size-[640px] rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--fps-electric) var(--fps-glow-electric, 10%), transparent), transparent)",
        }}
      />
      <div
        className="absolute -top-48 -right-40 size-[560px] rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--fps-violet) var(--fps-glow-violet, 8%), transparent), transparent)",
        }}
      />
    </div>
  );
}

/**
 * Sun / moon: opens Frappe's own Toggle Theme dialog. Light = Pearl, Dark =
 * Matte Black, Automatic = follows the computer. The choice is Frappe's to
 * save (on the user's own profile, as from the avatar menu); this button only
 * opens the dialog. Hidden where the desk has no theme dialog (dev harness
 * without a mock).
 */
function AppearanceButton() {
  const palette = usePalette();
  const [available] = React.useState(() => typeof window.frappe?.ui?.ThemeSwitcher === "function");
  if (!available) return null;
  const name = palette === "black" ? "Matte Black" : "Pearl";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Appearance: ${name}. Change theme`}
          onClick={() => openThemeSwitcher()}
          className="text-ink-secondary hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
        >
          {palette === "black" ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        {name} · Light = Pearl, Dark = Matte Black
      </TooltipContent>
    </Tooltip>
  );
}

/** Wall-clock ms, ticking while the dashboard is on screen (drives "Stale"). */
function useNow(intervalMs: number): number {
  const visible = useHostVisible();
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!visible) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [visible, intervalMs]);
  return now;
}

/** "09:30" from the server's "yyyy-mm-dd HH:mm:ss" when no client fetch time exists yet. */
function serverTime(generatedAt: string | undefined): string | null {
  const match = generatedAt ? /\d{4}-\d{2}-\d{2}[ T](\d{2}):(\d{2})/.exec(generatedAt) : null;
  return match ? `${match[1]}:${match[2]}` : null;
}

function DashboardHeader({
  asOf,
  generatedAt,
  lastUpdated,
  busy,
  onRefresh,
}: {
  asOf: string | null;
  generatedAt?: string;
  lastUpdated: Date | null;
  busy: boolean;
  onRefresh: () => void;
}) {
  const now = useNow(30_000);
  const stale = lastUpdated !== null && now - lastUpdated.getTime() > STALE_AFTER_MS;
  const time = lastUpdated ? formatTime(lastUpdated) : serverTime(generatedAt);

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-xl leading-7 font-semibold tracking-tight text-ink">Command Center</h2>
        <p className="text-[13px] leading-5 text-ink-muted">
          Fast Planet Shipping{asOf ? ` · ${formatLongDate(asOf)}` : ""}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {time ? (
          <span className="flex items-center gap-2 text-xs leading-4 text-ink-muted">
            <span aria-hidden="true" className="relative flex size-2">
              {!stale ? (
                <span className="absolute inset-0 animate-ping rounded-full bg-mint/50 [animation-duration:2.4s] motion-reduce:hidden" />
              ) : null}
              <span className={cn("relative size-2 rounded-full", stale ? "bg-amber" : "bg-mint")} />
            </span>
            <span>
              <span className={cn("font-medium", stale ? "text-amber" : "text-ink-secondary")}>{stale ? "Stale" : "Live"}</span>
              {` · Updated ${time}`}
            </span>
          </span>
        ) : null}
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Refresh dashboard"
          aria-busy={busy}
          onClick={onRefresh}
          className="text-ink-secondary hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
        >
          <RefreshCw aria-hidden="true" className={cn(busy && "animate-spin motion-reduce:animate-none")} />
        </Button>
        <AppearanceButton />
      </div>
    </header>
  );
}

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
 * First-load skeleton in the layout the payload will use: 8 KPI cards for
 * finance roles (lg 4 per row), 6 for everyone else (lg 3, xl 6 per row), so
 * the real cards land where the placeholders were and nothing below jumps.
 * (A finance viewer who cannot read one source doctype gets 7 and auto-fit;
 * that reflow is accepted.)
 */
function LoadingFrame() {
  const block = "bg-hairline motion-reduce:animate-none";
  const count = hasRole(...FINANCE_ROLES) ? 8 : 6;
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

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="glass flex flex-col items-start gap-4 rounded-2xl p-6">
      <p className="flex items-center gap-2 text-base leading-6 font-semibold text-ink">
        <CircleAlert aria-hidden="true" className="size-5 shrink-0 text-rose" />
        Could not load the dashboard
      </p>
      <p className="max-w-[72ch] text-sm leading-5 text-ink-secondary">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry} className="gap-2 px-4 has-[>svg]:px-4">
        <RefreshCw aria-hidden="true" />
        Retry
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Root                                                                       */
/* ------------------------------------------------------------------------ */

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
  // payload ever carried one by mistake (the API already omits them).
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
    <div
      data-slot="command-center"
      // No overflow-hidden here: it would clip the charts' in-chart tooltips.
      // The ambient glow clips itself (its own overflow-hidden + inherited radius).
      className="@container/cc relative isolate min-w-0 rounded-2xl bg-plane font-sans text-ink antialiased"
    >
      <AmbientGlow />
      <div className="relative flex flex-col gap-6 p-4 @min-[768px]/cc:p-6">
        <DashboardHeader
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
    </div>
  );
}
