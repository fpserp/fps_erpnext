/**
 * Public surface of the Command Center components and their layout contracts.
 *
 * main.tsx imports CommandCenter's default export directly; this barrel is for
 * tooling, reviews and future views that want a component or the full list of
 * `*.meta.ts` contracts (e.g. a check that every layout component has one).
 */
import type { ComponentMeta } from "./meta.types";
import { meta as actionDrawerMeta } from "./ActionDrawer.meta";
import { meta as bentoGridMeta } from "./BentoGrid.meta";
import { meta as commandCenterMeta } from "./CommandCenter.meta";
import { meta as deltaBadgeMeta } from "./DeltaBadge.meta";
import { meta as insightBannerMeta } from "./InsightBanner.meta";
import { meta as metricCardMeta } from "./MetricCard.meta";
import { meta as sparklineMeta } from "./Sparkline.meta";
import { meta as stageStripMeta } from "./StageStrip.meta";
import { meta as trendChartMeta } from "./TrendChart.meta";

export { default as CommandCenter, kpiLayout, STAGES_SPAN, TREND_SPAN, type KpiLayout } from "./CommandCenter";
export { ActionDrawer, MAX_RECORDS, type ActionDrawerProps, type DrawerState } from "./ActionDrawer";
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
  actionDrawerMeta,
  bentoGridMeta,
  commandCenterMeta,
  deltaBadgeMeta,
  insightBannerMeta,
  metricCardMeta,
  sparklineMeta,
  stageStripMeta,
  trendChartMeta,
};

/** Every layout contract, root first. Keep in step with the *.meta.ts files. */
export const allMetas: readonly ComponentMeta[] = [
  commandCenterMeta,
  bentoGridMeta,
  insightBannerMeta,
  metricCardMeta,
  deltaBadgeMeta,
  sparklineMeta,
  trendChartMeta,
  stageStripMeta,
  actionDrawerMeta,
];
