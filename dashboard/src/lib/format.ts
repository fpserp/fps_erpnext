/**
 * Number and date formatting (DESIGN.md §5). Signatures are fixed; the core
 * module implements them.
 *
 *  formatCount(1284)                 -> "1,284"
 *  formatCompact(12874.5)            -> "12.9K"   (1 dp, K/M/B)
 *  formatMoneyCompact(12874.5,"AED") -> "AED 12.9K"
 *  formatMoney(12874.5,"AED")        -> "AED 12,874.50"
 *  formatValue(v, unit, currency, {compact})  -> dispatches on unit
 *  formatDelta(12.43)                -> "+12.4%" ; formatDelta(-3) -> "−3.0%" (U+2212)
 *  formatShortDate("2026-10-06")     -> "6 Oct"
 *  formatLongDate("2026-10-06")      -> "Tue 6 Oct 2026"
 *  formatTime(date)                  -> "14:32"
 *
 * House rules:
 *  - en-US digit grouping everywhere ("12,874.50"), whatever the browser
 *    locale, so a screenshot reads the same on every executive's laptop.
 *  - Negatives use the real minus sign U+2212, not a hyphen: it is the width
 *    of a digit, so signed columns stay aligned, and screen readers say "minus".
 *  - The sign always comes first ("−AED 1.2K", "−3.0%").
 *  - Non-finite input (NaN, ±Infinity) renders an em dash instead of "NaN".
 *  - Dates are parsed from the ISO text by hand, never with `new Date(iso)`:
 *    that parses a bare date as UTC midnight and shows the previous day for
 *    anyone west of Greenwich.
 *
 * This file has no runtime imports on purpose: scripts/format.check.ts runs it
 * directly under Node's type stripping, which cannot resolve "@/…" aliases or
 * extension-less relative imports. The type import below is erased.
 */
import type { Unit } from "@/types/dashboard";

/** U+2212 MINUS SIGN. */
export const MINUS = "−";
/** What a missing or non-finite number renders as. */
export const EMPTY_VALUE = "—";

const DEFAULT_CURRENCY = "AED";

const INTEGER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const ONE_DP_MAX = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const ONE_DP_FIXED = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const TWO_DP_FIXED = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
/** Same rounding as ONE_DP_MAX, without grouping, so the result parses back. */
const ONE_DP_PLAIN = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  useGrouping: false,
});

/** Ascending, so a value that rounds up to 1000 of one unit moves to the next. */
const COMPACT_UNITS: ReadonlyArray<readonly [number, string]> = [
  [1e3, "K"],
  [1e6, "M"],
  [1e9, "B"],
  [1e12, "T"],
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Prefix for a value whose rounded magnitude is not zero (avoids "−0"). */
function signOf(n: number, roundedMagnitude: string): string {
  return n < 0 && /[1-9]/.test(roundedMagnitude) ? MINUS : "";
}

/**
 * The desk's company currency, read without importing ./frappe (see the file
 * comment). Falls back to AED, the only currency FPS reports in today.
 */
function deskCurrency(): string {
  if (typeof window === "undefined") return DEFAULT_CURRENCY;
  const code = window.frappe?.boot?.sysdefaults?.currency;
  return typeof code === "string" && code.trim() ? code.trim() : DEFAULT_CURRENCY;
}

function currencyCode(currency: string | undefined): string {
  return currency && currency.trim() ? currency.trim().toUpperCase() : deskCurrency();
}

/** Magnitude only, 1 dp max, K/M/B/T. `abs` must be finite and >= 0. */
function compactMagnitude(abs: number): string {
  // Below 999.5 the integer form is shorter and exact enough for a card.
  if (abs < 999.5) return INTEGER.format(abs);
  for (let i = 0; i < COMPACT_UNITS.length; i += 1) {
    const [base, suffix] = COMPACT_UNITS[i];
    const scaled = abs / base;
    const isLast = i === COMPACT_UNITS.length - 1;
    // 999,950 is "999.95K", which rounds to "1000K": promote it to "1M".
    if (isLast || Number.parseFloat(ONE_DP_PLAIN.format(scaled)) < 1000) {
      return `${ONE_DP_MAX.format(scaled)}${suffix}`;
    }
  }
  return INTEGER.format(abs); // unreachable: the last unit always returns
}

/** "1,284". Rounds to a whole number; counts are never fractional. */
export function formatCount(n: number): string {
  if (!Number.isFinite(n)) return EMPTY_VALUE;
  const magnitude = INTEGER.format(Math.abs(n));
  return `${signOf(n, magnitude)}${magnitude}`;
}

/** "12.9K", "1.2M", "950". One decimal at most; trailing ".0" is dropped. */
export function formatCompact(n: number): string {
  if (!Number.isFinite(n)) return EMPTY_VALUE;
  const magnitude = compactMagnitude(Math.abs(n));
  return `${signOf(n, magnitude)}${magnitude}`;
}

/** "AED 12.9K". Currency defaults to the desk's company currency. */
export function formatMoneyCompact(n: number, currency?: string): string {
  if (!Number.isFinite(n)) return EMPTY_VALUE;
  const magnitude = compactMagnitude(Math.abs(n));
  return `${signOf(n, magnitude)}${currencyCode(currency)} ${magnitude}`;
}

/** "AED 12,874.50" — the full figure for the drawer and table views. */
export function formatMoney(n: number, currency?: string): string {
  if (!Number.isFinite(n)) return EMPTY_VALUE;
  const magnitude = TWO_DP_FIXED.format(Math.abs(n));
  return `${signOf(n, magnitude)}${currencyCode(currency)} ${magnitude}`;
}

/** Dispatch on the KPI unit. Full figures unless `compact` is set. */
export function formatValue(
  n: number,
  unit: Unit,
  currency?: string,
  opts?: { compact?: boolean },
): string {
  const compact = opts?.compact ?? false;
  if (unit === "currency") return compact ? formatMoneyCompact(n, currency) : formatMoney(n, currency);
  return compact ? formatCompact(n) : formatCount(n);
}

/** "+12.4%", "−3.0%", "0.0%". Always one decimal; zero carries no sign. */
export function formatDelta(pct: number): string {
  if (!Number.isFinite(pct)) return EMPTY_VALUE;
  const magnitude = ONE_DP_FIXED.format(Math.abs(pct));
  if (!/[1-9]/.test(magnitude)) return `${magnitude}%`;
  return `${pct < 0 ? MINUS : "+"}${magnitude}%`;
}

interface IsoDate {
  year: number;
  month: number; // 1-12
  day: number;
}

/** Accepts "yyyy-mm-dd" and "yyyy-mm-dd HH:mm:ss" / "yyyy-mm-ddTHH:mm…". */
function parseIsoDate(iso: string): IsoDate | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])/.exec(iso.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  // Round-trip through UTC to reject "2026-02-31" and friends.
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) {
    return null;
  }
  return { year, month, day };
}

/** "6 Oct". Unparseable input is returned unchanged rather than hidden. */
export function formatShortDate(iso: string): string {
  const d = parseIsoDate(iso);
  if (!d) return iso;
  return `${d.day} ${MONTHS[d.month - 1]}`;
}

/** "Tue 6 Oct 2026". */
export function formatLongDate(iso: string): string {
  const d = parseIsoDate(iso);
  if (!d) return iso;
  const weekday = WEEKDAYS[new Date(Date.UTC(d.year, d.month - 1, d.day)).getUTCDay()];
  return `${weekday} ${d.day} ${MONTHS[d.month - 1]} ${d.year}`;
}

/** "14:32" — 24-hour, zero-padded, in the viewer's local time. */
export function formatTime(d: Date): string {
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return EMPTY_VALUE;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}
