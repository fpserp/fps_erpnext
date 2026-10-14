/**
 * Payload contract for the FPS ACC Dashboard (accounting) and the read-only
 * Python API in fps_erpnext/api/acc_dashboard.py.
 *
 *   fps_erpnext.api.acc_dashboard.get_dashboard(period)                 -> AccPayload
 *   fps_erpnext.api.acc_dashboard.get_metric_detail(key, period, dim)   -> MetricDetail
 *
 * ACCESS: Accounts Manager only (today exactly Administrator, agam@ and
 * abhishek@). The server checks the role before reading anything; anyone else
 * gets frappe.PermissionError and the page shows "You do not have access".
 *
 * Everything is read-only. Money is in the company currency (AED) and rounded
 * to fils (2 dp) by the server; the UI only formats.
 *
 * Shapes reused from ./dashboard: Kpi, Insight, TrendMode, ContextLine,
 * DeskRoute, Period, MetricDetail, Severity. For this contract:
 *   - KpiKey (in ./dashboard) gains "paid_out" | "purchases".
 *   - TrendModeKey (in ./dashboard) gains "billing" | "cashflow".
 *
 * Change this file, ./dashboard and acc_dashboard.py in the same commit.
 */
import type { ContextLine, DeskRoute, Insight, Kpi, Period, Severity, TrendMode } from "./dashboard";

/** The four period KPIs, in display order. */
export type AccKpiKey = "invoiced" | "collected" | "paid_out" | "purchases";

/** The four "as of today" position cards, in display order. */
export type BalanceKey = "receivables" | "payables" | "cash" | "vat";

/**
 * A position (stock) figure as of `as_of` — not affected by the period filter.
 * No sparkline and no delta: positions are not compared period on period.
 */
export interface BalanceCard {
  key: BalanceKey;
  /** Sentence case: "Receivables", "Payables", "Cash & bank", "VAT Jul–Sep 2026". */
  label: string;
  /** One-line definition for the info tooltip. */
  definition: string;
  currency: string;
  /**
   * receivables: outstanding on submitted Sales Invoices (credit notes net) LESS
   *              customer receipts not yet allocated to an invoice — the total of
   *              the FPS Customer Receivables / Accounts Receivable reports;
   * payables:    outstanding on submitted Purchase Invoices (debit notes net) LESS
   *              supplier payments not yet allocated to a bill;
   * cash:        sum of General Ledger balances of every Bank and Cash account
   *              (the book figure; the context compares it with the statements);
   * vat:         net VAT for the quarter = output VAT (sales invoices) − input VAT
   *              (purchase invoices) on the VAT accounts (positive = payable).
   */
  value: number;
  /**
   * Up to 4 pre-formatted lines, e.g. {label: "Overdue", value: "AED 710.4K"}.
   * Receivables / payables "Overdue" is net per party: a party's credits (notes,
   * payments on account) clear its past-due documents first.
   */
  context: ContextLine[];
  /**
   * Optional emphasis for the value: receivables warning when overdue share ≥ 50 %;
   * VAT warning ≤ 14 days to the due date; cash critical when the books differ
   * from a bank statement by more than 1 % at the statement date.
   */
  severity?: Severity;
  /** Honest data caveat, rendered behind an amber icon. */
  caveat?: string;
  /** Report or list behind the number. */
  route: DeskRoute;
}

export type AgeingBucketKey =
  | "not_due"
  | "0_30"
  | "31_60"
  | "61_90"
  | "91_180"
  | "181_365"
  | "over_365";

/**
 * Days past DUE date (the bucket ranges of the "FPS Customer Receivables"
 * report). not_due = due_date on or after as_of, so a document due TODAY is
 * "Not due" here while that report counts it in 0–30.
 */
export interface AgeingBucket {
  key: AgeingBucketKey;
  /** "Not due", "0–30", "31–60", "61–90", "91–180", "181–365", "Over 365". */
  label: string;
  value: number;
  /** Number of open documents in the bucket. */
  count: number;
}

export interface AgeingParty {
  /** Customer / Supplier name (the record id). */
  party: string;
  /** Display name. */
  label: string;
  /** Net outstanding for the party (payments on account netted). */
  value: number;
  /**
   * Part of value that is past due, after the party's credits (notes and
   * payments on account) clear its oldest past-due documents. Never more than
   * value when value > 0.
   */
  overdue: number;
  /** Days past due of the oldest document still overdue after that (0 when none). */
  oldest_days: number;
  /** Open invoices / bills (payments on account not counted). */
  count: number;
  /** The party's open documents (list view filtered to the party). */
  route: DeskRoute;
}

export interface Ageing {
  key: "receivables" | "payables";
  label: string;
  currency: string;
  /** Same as the matching BalanceCard value. */
  total: number;
  /**
   * Past-due amount netted per party: each party's credits (notes and payments
   * on account) clear its oldest past-due documents first. The SAME figure as
   * the BalanceCard's "Overdue" line. Because a party in credit is netted
   * against its own documents only, it can exceed `total` (total nets every
   * party); the past-due buckets need not add up to it.
   */
  overdue: number;
  /**
   * Always all 7 buckets, in the order of AgeingBucketKey, zeros included.
   * A payment not yet allocated is a negative document in the bucket of its
   * posting date (as in the native reports), counted in `count`.
   */
  buckets: AgeingBucket[];
  /** Top 5 parties by net outstanding (> 0), largest first. */
  top: AgeingParty[];
  /** Full report: FPS Customer Receivables / Accounts Payable. */
  route: DeskRoute;
  /** Present when payments on account were netted: how much, how many. */
  caveat?: string;
}

/** One bank / card account's statement reconciliation (custom doctype FPS Bank Statement). */
export interface BankStatus {
  /** Bank code as used in statement names: "ADCB" | "WIO" | "QGEN" | "QGOV". */
  bank: string;
  /** Display name, e.g. "ADCB", "WIO", "Qashio – General", "Qashio – Government". */
  label: string;
  /** Latest statement's month, e.g. "Sep 2026"; null when none exists. */
  latest_month: string | null;
  /** Status of the latest statement, or "Missing" when there is none. */
  status: "Reconciled" | "In Progress" | "Missing";
  /** Closing balance on the latest statement (null when none). */
  closing_balance: number | null;
  /**
   * Months from go-live (Jun 2026) up to LAST month with no reconciled
   * statement: missing, or not Reconciled — except last month itself still In
   * Progress, which is reconciled during the running month. 0 = up to date. A
   * gap behind the latest month counts (ADCB with no July statement).
   */
  months_behind: number;
  /** Those months, e.g. "Jul missing, Aug in progress"; only when months_behind > 0. */
  open_months?: string;
  route: DeskRoute;
}

export interface AccViewer {
  full_name?: string;
}

export interface AccPayload {
  /** Site-local date the numbers are computed for (yyyy-mm-dd). */
  as_of: string;
  /** Site-local timestamp of computation (yyyy-mm-dd HH:mm:ss). */
  generated_at: string;
  period: Period;
  period_label: string;
  compare_label: string;
  viewer: AccViewer;
  /** The AccKpiKey KPIs that could be computed, in AccKpiKey order. Kpi.finance is true. */
  kpis: Kpi[];
  /** The BalanceKey cards, in BalanceKey order. */
  balances: BalanceCard[];
  /** [receivables, payables]. */
  ageing: Ageing[];
  /** ADCB, WIO, QGEN, QGOV in that order. */
  banks: BankStatus[];
  /**
   * "billing": Invoiced (net) slot 1 vs Collected slot 2;
   * "cashflow": Collected slot 1 vs Paid out slot 2. 12 ISO weeks, currency.
   */
  trend: TrendMode[];
  /** 0–6, most severe first (same ranking as the OPS dashboard). */
  insights: Insight[];
}
