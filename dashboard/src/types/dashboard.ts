/**
 * Payload contract between the React dashboard and the read-only Python API
 * in fps_erpnext/api/command_center.py (the FPS OPS Dashboard). The shapes
 * here are shared with the FPS ACC Dashboard (./acc.ts,
 * fps_erpnext/api/acc_dashboard.py), which reuses Kpi, Insight, TrendMode,
 * MetricDetail and friends.
 *
 * Every field here is produced by a whitelisted READ-ONLY method. Nothing in
 * the dashboard writes to ERPNext; the only side effects it may cause are
 * navigation (frappe.set_route) and opening a blank "new" form (frappe.new_doc)
 * that the user saves themselves.
 *
 * Change this file and command_center.py in the same commit.
 */

/** KPI window. 7d and 30d are daily points; 90d is 13 rolling 7-day buckets. */
export type Period = "7d" | "30d" | "90d";

export type Unit = "count" | "currency";

/** Whether an increase is good news for this metric (drives the delta colour). */
export type GoodDirection = "up" | "down" | "none";

/** Status scale — reserved colours, always rendered with an icon and a label. */
export type Severity = "positive" | "info" | "warning" | "critical";

export type Granularity = "day" | "week";

/** Stable metric ids. Colour, icon and copy are keyed by these — never by index. */
export type KpiKey =
  | "enquiries"
  | "quotations"
  | "jobs"
  | "customs_cleared"
  | "deliveries"
  | "job_activity"
  | "invoiced"
  | "collected"
  // FPS ACC Dashboard only (./acc.ts AccKpiKey).
  | "paid_out"
  | "purchases";

export interface SeriesPoint {
  /** ISO date (yyyy-mm-dd). For weekly buckets: the first day of the bucket. */
  date: string;
  value: number;
  /** true when the bucket is still filling up (today / the current week). */
  partial?: boolean;
}

export interface ContextLine {
  label: string;
  /** Pre-formatted by the server, e.g. "32" or "AED 756.6K". */
  value: string;
}

/**
 * A desk route the UI may navigate to. Plain URL as Frappe understands it,
 * e.g. "/app/job-order?fps_stage=In%20Progress". Navigation only.
 */
export type DeskRoute = string;

export interface Kpi {
  key: KpiKey;
  /** Sentence case, no trailing colon. */
  label: string;
  /** One-line definition shown in the info tooltip. */
  definition: string;
  unit: Unit;
  /** ISO currency code when unit === "currency" (always "AED" today). */
  currency?: string;
  /**
   * Total for the current period. A count is a non-negative integer; money can
   * be negative ("Invoiced (net)" includes credit notes).
   */
  value: number;
  /**
   * Total for the previous equal period; null when it is not comparable (the
   * source does not reach back over the whole previous window), never 0 for that.
   */
  previous: number | null;
  /**
   * Percentage change vs previous, rounded to 1 dp. null when previous is null,
   * 0 or negative. The UI then shows "—" when previous is null (no earlier
   * data), "new" when the base is 0 or negative and value > 0, and "—"
   * otherwise — never ±∞ and never a percentage of a negative base.
   */
  delta_pct: number | null;
  good_direction: GoodDirection;
  granularity: Granularity;
  /** 7 points (7d), 30 points (30d) or 13 points (90d), oldest first. */
  series: SeriesPoint[];
  /** Up to two extra facts, e.g. [{label: "Active pipeline", value: "32"}]. */
  context: ContextLine[];
  /** Honest data caveat, e.g. receipt booking lag. Rendered behind an amber icon. */
  caveat?: string;
  /** List view behind the number. */
  route: DeskRoute;
  /** DocType for the drawer's "New …" quick action; omitted when not sensible. */
  new_doctype?: string;
  /** Money KPI — only ever returned to Accounts User / Accounts Manager / System Manager. */
  finance: boolean;
}

/** One tile of the existing pipeline strip (fps_erpnext.api.pipeline.get_overview). */
export interface StageTile {
  key: string;
  label: string;
  note: string;
  count: number;
  route: DeskRoute;
}

export interface Stages {
  tiles: StageTile[];
  footnotes: string[];
}

export interface Insight {
  /** Stable id so the banner keeps its position across polls. */
  id: string;
  severity: Severity;
  /** ≤ 90 characters, plain text. */
  title: string;
  /** ≤ 200 characters, plain text. */
  detail: string;
  /** Opens this KPI's drawer when set. */
  metric_key?: KpiKey;
  /** Otherwise navigates here when set. */
  route?: DeskRoute;
}

/** Fixed categorical slot (DESIGN.md §4). Slot follows the series key, never its rank. */
export type SeriesSlot = 1 | 2 | 3 | 4;

export interface TrendSeries {
  key: string;
  label: string;
  slot: SeriesSlot;
}

export interface TrendPoint {
  /** Monday of the ISO week (yyyy-mm-dd). */
  week_start: string;
  /** Axis label, e.g. "6 Oct". */
  label: string;
  /** The current, still-running week. */
  partial: boolean;
  values: Record<string, number>;
}

/**
 * "pipeline" / "activity": FPS OPS. "money": the old finance tab, no longer
 * sent by the OPS API (kept so an older payload still type-checks).
 * "billing" / "cashflow": FPS ACC (./acc.ts AccPayload.trend).
 */
export type TrendModeKey = "pipeline" | "activity" | "money" | "billing" | "cashflow";

export interface TrendMode {
  key: TrendModeKey;
  label: string;
  unit: Unit;
  currency?: string;
  /** 1–4 series. */
  series: TrendSeries[];
  /** 12 ISO weeks, oldest first; the last one is usually partial. */
  points: TrendPoint[];
  caveat?: string;
  finance: boolean;
}

export interface Viewer {
  /**
   * Always false on the FPS OPS Dashboard since 14 Oct 2026 (money moved to
   * the FPS ACC Dashboard, ./acc.ts). Kept so the UI's money gate stays shut.
   */
  finance: boolean;
  full_name?: string;
}

export interface DashboardPayload {
  /** Site-local date the numbers are computed for (yyyy-mm-dd). */
  as_of: string;
  /** Site-local timestamp of computation (yyyy-mm-dd HH:mm:ss). */
  generated_at: string;
  period: Period;
  /** "Last 7 days" / "Last 30 days" / "Last 13 weeks". */
  period_label: string;
  /** "vs previous 7 days" etc. */
  compare_label: string;
  viewer: Viewer;
  /**
   * 0–6 operations KPIs, in display order (the API no longer sends the money
   * KPIs on this page). The UI renders whatever subset arrives.
   */
  kpis: Kpi[];
  stages: Stages;
  /** 0–2 modes: "pipeline" and "activity" (no money on this page). */
  trend: TrendMode[];
  /** 0–6 insights, most severe first: critical, warning, positive, info. */
  insights: Insight[];
}

export interface BreakdownRow {
  key: string;
  label: string;
  value: number;
}

export interface DrillRecord {
  name: string;
  /** Main line, e.g. customer or party name. */
  title: string;
  /** Secondary line, e.g. "Customs clearance · BOE 1012345". */
  subtitle?: string;
  /** yyyy-mm-dd */
  date: string;
  /**
   * An amount of money in the company currency (AED), whatever the metric's
   * unit: always present for money metrics; for a count metric only when the
   * record has an amount AND the viewer has an Accounts role (today: the
   * Quotation grand total behind the Quotations count). The UI formats it as
   * money, never with the metric's unit.
   */
  value?: number;
  status?: string;
  route: DeskRoute;
}

export interface DrillAction {
  key: string;
  label: string;
  kind: "route" | "new_doc";
  route?: DeskRoute;
  doctype?: string;
}

export interface DimensionOption {
  key: string;
  label: string;
}

/**
 * fps_erpnext.api.command_center.get_metric_detail(key, period, dimension) for
 * the OPS KPIs, fps_erpnext.api.acc_dashboard.get_metric_detail for the ACC ones.
 */
export interface MetricDetail {
  key: KpiKey;
  label: string;
  unit: Unit;
  currency?: string;
  period: Period;
  period_label: string;
  compare_label: string;
  granularity: Granularity;
  value: number;
  previous: number | null;
  delta_pct: number | null;
  good_direction: GoodDirection;
  series: SeriesPoint[];
  /** What the dimension chips filter by, e.g. "Service line". null = no dimension. */
  dimension_label: string | null;
  dimension_options: DimensionOption[];
  /** The active dimension value, or null for "All". */
  dimension: string | null;
  breakdown: { title: string; rows: BreakdownRow[] } | null;
  /** Latest ≤ 8 records behind the number, newest first. */
  records: DrillRecord[];
  actions: DrillAction[];
  caveat?: string;
}
