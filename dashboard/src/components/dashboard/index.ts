/**
 * Public surface of the dashboard components (FPS OPS — CommandCenter, FPS
 * ACC — AccDashboard) and their layout contracts.
 *
 * main.tsx imports the two roots' default exports directly; this barrel is for
 * tooling, reviews and future views that want a component or the full list of
 * `*.meta.ts` contracts (e.g. a check that every layout component has one).
 */
import type { ComponentMeta } from "./meta.types";
import { meta as accDashboardMeta } from "./AccDashboard.meta";
import { meta as actionDrawerMeta } from "./ActionDrawer.meta";
import { meta as ageingPanelMeta } from "./AgeingPanel.meta";
import { meta as balanceCardMeta } from "./BalanceCard.meta";
import { meta as bankStatusCardMeta } from "./BankStatusCard.meta";
import { meta as bentoGridMeta } from "./BentoGrid.meta";
import { meta as commandCenterMeta } from "./CommandCenter.meta";
import { meta as deltaBadgeMeta } from "./DeltaBadge.meta";
import { meta as insightBannerMeta } from "./InsightBanner.meta";
import { meta as metricCardMeta } from "./MetricCard.meta";
import { meta as sparklineMeta } from "./Sparkline.meta";
import { meta as stageStripMeta } from "./StageStrip.meta";
import { meta as trendChartMeta } from "./TrendChart.meta";

export { default as CommandCenter, kpiLayout, STAGES_SPAN, TREND_SPAN, type KpiLayout } from "./CommandCenter";
export {
  default as AccDashboard,
  ACC_AGEING_SPAN,
  ACC_BANKS_SPAN,
  ACC_CARD_SPAN,
  ACC_TREND_SPAN,
  accCardLayout,
  NoAccessPanel,
  type CardRowLayout,
} from "./AccDashboard";
export { ActionDrawer, MAX_RECORDS, type ActionDrawerProps, type DrawerState } from "./ActionDrawer";
export { AgeingPanel, ageingTitle, MAX_AGEING_PARTIES, type AgeingPanelProps } from "./AgeingPanel";
export { BalanceCard, MAX_BALANCE_CONTEXT, type BalanceCardProps } from "./BalanceCard";
export { BankStatusCard, type BankStatusCardProps } from "./BankStatusCard";
export {
  BentoGrid,
  BentoItem,
  spanClasses,
  type BentoColumns,
  type BentoGridProps,
  type BentoItemProps,
  type ColumnSpan,
  type ResponsiveSpan,
} from "./BentoGrid";
export { ChartTableView, type ChartTableColumn, type ChartTableRow, type ChartTableViewProps } from "./ChartTableView";
export {
  AmbientGlow,
  AppearanceButton,
  DashboardFrame,
  DashboardHeader,
  ErrorState,
  STALE_AFTER_MS,
  useNow,
  type DashboardHeaderProps,
} from "./DashboardChrome";
export { DeltaBadge, deltaState, type DeltaBadgeProps, type DeltaKind, type DeltaState, type DeltaTone } from "./DeltaBadge";
export { DeskLink, type DeskLinkProps } from "./DeskLink";
export { InsightBanner, type InsightBannerProps } from "./InsightBanner";
export { MetricCard, type MetricCardProps } from "./MetricCard";
export { PeriodFilter, type PeriodFilterProps } from "./PeriodFilter";
export { Sparkline, type SparklineProps } from "./Sparkline";
export { StageStrip, type StageStripProps } from "./StageStrip";
export { MAX_SERIES, TrendChart, type TrendChartKind, type TrendChartProps } from "./TrendChart";
export type { Breakpoint, ComponentMeta, PropSpec } from "./meta.types";

export {
  accDashboardMeta,
  actionDrawerMeta,
  ageingPanelMeta,
  balanceCardMeta,
  bankStatusCardMeta,
  bentoGridMeta,
  commandCenterMeta,
  deltaBadgeMeta,
  insightBannerMeta,
  metricCardMeta,
  sparklineMeta,
  stageStripMeta,
  trendChartMeta,
};

/** Every layout contract, roots first. Keep in step with the *.meta.ts files. */
export const allMetas: readonly ComponentMeta[] = [
  commandCenterMeta,
  accDashboardMeta,
  bentoGridMeta,
  insightBannerMeta,
  metricCardMeta,
  deltaBadgeMeta,
  sparklineMeta,
  trendChartMeta,
  stageStripMeta,
  balanceCardMeta,
  bankStatusCardMeta,
  ageingPanelMeta,
  actionDrawerMeta,
];
