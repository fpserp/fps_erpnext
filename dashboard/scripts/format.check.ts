/**
 * Assertions for src/lib/format.ts, run straight from TypeScript with Node's
 * built-in type stripping (Node >= 22.18 / 23.6; no test framework needed):
 *
 *   npm run check:format      (node scripts/format.check.ts)
 *
 * format.ts is written to be importable here: no runtime imports, and the
 * `window` access is guarded. Exits 1 on the first failed group.
 */
import assert from "node:assert/strict";
import {
  formatCompact,
  formatCount,
  formatDelta,
  formatLongDate,
  formatMoney,
  formatMoneyCompact,
  formatShortDate,
  formatTime,
  formatValue,
} from "../src/lib/format.ts";

const M = "−"; // the minus sign the formatter must use
let failures = 0;

function group(name: string, body: () => void): void {
  try {
    body();
    console.log(`ok   ${name}`);
  } catch (err) {
    failures += 1;
    console.error(`FAIL ${name}\n     ${err instanceof Error ? err.message : String(err)}`);
  }
}

group("formatCount: en-US grouping, rounding, U+2212", () => {
  assert.equal(formatCount(1284), "1,284");
  assert.equal(formatCount(0), "0");
  assert.equal(formatCount(1234567), "1,234,567");
  assert.equal(formatCount(-1284), `${M}1,284`);
  assert.equal(formatCount(12.6), "13");
  assert.equal(formatCount(-0.4), "0", "no negative zero");
  assert.equal(formatCount(Number.NaN), "—");
});

group("formatCompact: 1 dp, K/M/B/T, unit promotion", () => {
  assert.equal(formatCompact(12874.5), "12.9K");
  assert.equal(formatCompact(950), "950");
  assert.equal(formatCompact(999.4), "999");
  assert.equal(formatCompact(999.5), "1K");
  assert.equal(formatCompact(1000), "1K");
  assert.equal(formatCompact(1050), "1.1K");
  assert.equal(formatCompact(756600), "756.6K");
  assert.equal(formatCompact(999950), "1M", "999.95K rounds up into the next unit");
  assert.equal(formatCompact(1234567), "1.2M");
  assert.equal(formatCompact(2.5e9), "2.5B");
  assert.equal(formatCompact(3e12), "3T");
  assert.equal(formatCompact(-12874.5), `${M}12.9K`);
  assert.equal(formatCompact(-0.2), "0");
  assert.equal(formatCompact(Number.POSITIVE_INFINITY), "—");
});

group("formatMoneyCompact / formatMoney", () => {
  assert.equal(formatMoneyCompact(12874.5, "AED"), "AED 12.9K");
  assert.equal(formatMoneyCompact(1.2e6, "aed"), "AED 1.2M", "code is upper-cased");
  assert.equal(formatMoneyCompact(950.4, "AED"), "AED 950");
  assert.equal(formatMoneyCompact(-12874.5, "AED"), `${M}AED 12.9K`);
  assert.equal(formatMoneyCompact(5000), "AED 5K", "defaults to AED outside the desk");
  assert.equal(formatMoney(12874.5, "AED"), "AED 12,874.50");
  assert.equal(formatMoney(0, "AED"), "AED 0.00");
  assert.equal(formatMoney(-12874.5, "USD"), `${M}USD 12,874.50`);
  assert.equal(formatMoney(-0.001, "AED"), "AED 0.00", "no negative zero");
  assert.equal(formatMoney(1234567.891, "AED"), "AED 1,234,567.89");
});

group("formatValue dispatch", () => {
  assert.equal(formatValue(1284, "count", undefined), "1,284");
  assert.equal(formatValue(1284, "count", undefined, { compact: true }), "1.3K");
  assert.equal(formatValue(12874.5, "currency", "AED"), "AED 12,874.50");
  assert.equal(formatValue(12874.5, "currency", "AED", { compact: true }), "AED 12.9K");
});

group("formatDelta: always 1 dp, sign first, U+2212, no signed zero", () => {
  assert.equal(formatDelta(12.43), "+12.4%");
  assert.equal(formatDelta(-3), `${M}3.0%`);
  assert.equal(formatDelta(0), "0.0%");
  assert.equal(formatDelta(-0.04), "0.0%");
  assert.equal(formatDelta(0.05), "+0.1%");
  assert.equal(formatDelta(1234.56), "+1,234.6%");
  assert.equal(formatDelta(Number.NaN), "—");
});

group("dates: parsed by hand, no timezone drift", () => {
  assert.equal(formatShortDate("2026-10-06"), "6 Oct");
  assert.equal(formatShortDate("2026-01-31"), "31 Jan");
  assert.equal(formatShortDate("2026-10-06 14:32:00"), "6 Oct");
  assert.equal(formatLongDate("2026-10-06"), "Tue 6 Oct 2026");
  assert.equal(formatLongDate("2026-03-01"), "Sun 1 Mar 2026");
  assert.equal(formatLongDate("2024-02-29"), "Thu 29 Feb 2024");
  assert.equal(formatShortDate("2026-02-31"), "2026-02-31", "invalid dates are returned unchanged");
  assert.equal(formatShortDate("not a date"), "not a date");
});

group("formatTime: 24 h, zero-padded, local", () => {
  assert.equal(formatTime(new Date(2026, 9, 6, 14, 32)), "14:32");
  assert.equal(formatTime(new Date(2026, 9, 6, 9, 5)), "09:05");
  assert.equal(formatTime(new Date(2026, 9, 6, 0, 0)), "00:00");
  assert.equal(formatTime(new Date(Number.NaN)), "—");
});

if (failures > 0) {
  console.error(`\n${failures} group(s) failed.`);
  process.exit(1);
}
console.log("\nformat.ts: all checks passed.");
