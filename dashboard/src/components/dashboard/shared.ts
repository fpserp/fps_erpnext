/**
 * Shared presentation vocabulary for the Command Center components: which icon
 * and colour belong to which metric, severity or series slot, plus the small
 * hooks every component needs. Keeping these maps in ONE place is what makes
 * "colour follows the entity, never its rank" (DESIGN.md §4) enforceable: a
 * component never picks a colour itself, it looks the entity up here.
 *
 * Colours are CSS variable references only (theme.css owns the values), so a
 * palette change never needs a component change. Never add a hex here.
 *
 * Presentation only: nothing in this file reads or writes ERPNext data.
 */
import { useCallback, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BriefcaseBusiness,
  CircleAlert,
  FileText,
  Inbox,
  Info,
  ReceiptText,
  ShieldCheck,
  TrendingUp,
  TriangleAlert,
  Truck,
  Wallet,
} from "lucide-react";
import { formatValue } from "@/lib/format";
import type { Granularity, KpiKey, Period, SeriesSlot, Severity, Unit } from "@/types/dashboard";

/* ------------------------------------------------------------------------ */
/* Entity → icon / colour maps                                                */
/* ------------------------------------------------------------------------ */

/** One icon per KPI key. Keyed by the stable id, never by display order. */
export const KPI_ICON: Readonly<Record<KpiKey, LucideIcon>> = {
  enquiries: Inbox,
  quotations: FileText,
  jobs: BriefcaseBusiness,
  customs_cleared: ShieldCheck,
  deliveries: Truck,
  job_activity: Activity,
  invoiced: ReceiptText,
  collected: Wallet,
};

/**
 * Categorical chart colours by FIXED slot (DESIGN.md §4). The server assigns
 * each trend series a slot by its key, so a hidden series never repaints the
 * survivors. There is deliberately no slot 5: a fifth series folds into Other.
 */
export const SLOT_COLOR: Readonly<Record<SeriesSlot, string>> = {
  1: "var(--fps-electric)",
  2: "var(--fps-violet-series)",
  3: "var(--fps-cyan)",
  4: "var(--fps-amber-series)",
};

/**
 * The single-series role colour of a metric: Electric Blue for counts, the
 * deep violet SERIES step for money. (The light Soft Violet is UI-only; next to
 * blue at the same lightness it collapses for protanopes, see DESIGN.md §4.)
 */
export const ROLE_COLOR: Readonly<Record<Unit, string>> = {
  count: "var(--fps-electric)",
  currency: "var(--fps-violet-series)",
};

export interface SeverityMeta {
  icon: LucideIcon;
  /** Always rendered next to the icon: status is never colour alone. */
  label: string;
  /** Text/icon colour utility (status token). */
  text: string;
  /** Tinted chip background + hairline for the severity label. */
  chip: string;
}

export const SEVERITY_META: Readonly<Record<Severity, SeverityMeta>> = {
  critical: { icon: CircleAlert, label: "Critical", text: "text-rose", chip: "bg-rose/10 border-rose/25" },
  warning: { icon: TriangleAlert, label: "Warning", text: "text-amber", chip: "bg-amber/10 border-amber/25" },
  positive: { icon: TrendingUp, label: "Positive", text: "text-mint", chip: "bg-mint/10 border-mint/25" },
  info: { icon: Info, label: "Info", text: "text-electric-ui", chip: "bg-electric-ui/10 border-electric-ui/25" },
};

/* ------------------------------------------------------------------------ */
/* Periods                                                                    */
/* ------------------------------------------------------------------------ */

export interface PeriodOption {
  value: Period;
  /** Toggle text. */
  short: string;
  /** Accessible name; matches the server's period_label. */
  long: string;
}

export const PERIOD_OPTIONS: readonly PeriodOption[] = [
  { value: "7d", short: "7D", long: "Last 7 days" },
  { value: "30d", short: "30D", long: "Last 30 days" },
  { value: "90d", short: "90D", long: "Last 13 weeks" },
];

export function isPeriod(value: unknown): value is Period {
  return value === "7d" || value === "30d" || value === "90d";
}

/** "7-day trend" / "30-day trend" / "13-week trend" for screen-reader summaries. */
export function trendNoun(points: number, granularity: Granularity): string {
  return `${points}-${granularity === "week" ? "week" : "day"} trend`;
}

/** "vs previous 7 days" → "compared with previous 7 days" (spoken form). */
export function spokenCompare(compareLabel: string): string {
  const trimmed = compareLabel.trim();
  return /^vs\.?\s+/i.test(trimmed) ? trimmed.replace(/^vs\.?\s+/i, "compared with ") : trimmed;
}

/* ------------------------------------------------------------------------ */
/* Number formatting shortcuts                                                */
/* ------------------------------------------------------------------------ */

export type NumberFormatter = (n: number) => string;

/** A formatter bound to one unit/currency, compact for cards and axes. */
export function formatterFor(unit: Unit, currency: string | undefined, compact: boolean): NumberFormatter {
  return (n: number) => formatValue(n, unit, currency, { compact });
}

/* ------------------------------------------------------------------------ */
/* Browser helpers                                                            */
/* ------------------------------------------------------------------------ */

/**
 * SVG ids referenced as url(#id) must be plain: React's useId output contains
 * characters (":" or "«»") that break the url() reference in some engines.
 */
export function svgSafeId(raw: string): string {
  return raw.replace(/[^A-Za-z0-9_-]/g, "");
}

/** localStorage read that never throws (private windows, blocked storage). */
export function readLocal(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** localStorage write that never throws; a lost preference is harmless. */
export function writeLocal(key: string, value: string): void {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the preference simply is not remembered */
  }
}

/**
 * Content-box width of an element, kept current with a ResizeObserver. Used to
 * decide whether chart direct labels fit; 0 until the first measurement.
 */
export function useElementWidth<T extends HTMLElement>(): [(node: T | null) => (() => void) | undefined, number] {
  const [width, setWidth] = useState(0);
  const ref = useCallback((node: T | null) => {
    if (!node) return undefined;
    setWidth(node.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}
