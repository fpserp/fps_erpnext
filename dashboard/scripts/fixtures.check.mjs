#!/usr/bin/env node
/**
 * Structural check of dev/fixtures/*.json against the payload contracts
 * (src/types/dashboard.ts for the FPS OPS Dashboard, src/types/acc.ts for the
 * FPS ACC Dashboard) and the rules the APIs promise on top of them.
 *
 *   node scripts/fixtures.check.mjs [fixtures-dir]   (npm run check:fixtures)
 *
 * Why this exists next to `make_fixtures.py --typecheck`: tsc proves each file
 * is ASSIGNABLE to its type, but not the semantics the UI relies on and the
 * type system cannot say — series of exactly 7/30/13 points ending on as_of,
 * `partial` only on the last point, KPIs in the fixed order, the delta rule
 * (null against a missing, zero or negative base), NO MONEY anywhere on the
 * OPS page (since 14 Oct 2026, for every viewer), insights ≤ 90/200 characters
 * and most severe first, records newest first with unique names (React keys),
 * a drawer that agrees with the card it was opened from, and for ACC: balances
 * and ageing in contract order, ageing totals equal to the matching balance,
 * all 7 buckets, top ≤ 5 largest first, banks ADCB/WIO/QGEN/QGOV with a
 * consistent "Missing". A fixture that breaks one of these would make the dev
 * harness lie about how the live dashboards behave.
 *
 * Hand-written on purpose (no schema library): the dashboard has no runtime
 * dependency for validation, and the contracts are small enough to mirror.
 * Keep the KEY lists below in step with src/types/dashboard.ts and acc.ts.
 *
 * Read-only: it only reads files. Exit code 1 on any failure.
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// Optional first argument: another fixtures folder (used to prove the checker
// catches broken files without touching the real ones).
const FIXTURES = path.resolve(process.argv[2] ?? path.join(here, "..", "dev", "fixtures"));

/* ------------------------------------------------------------------------ */
/* The contracts, mirrored from src/types/dashboard.ts and acc.ts             */
/* ------------------------------------------------------------------------ */

const PERIODS = {
  "7d": { points: 7, step: 1, granularity: "day", label: "Last 7 days", compare: "vs previous 7 days" },
  "30d": { points: 30, step: 1, granularity: "day", label: "Last 30 days", compare: "vs previous 30 days" },
  "90d": { points: 13, step: 7, granularity: "week", label: "Last 13 weeks", compare: "vs previous 13 weeks" },
};
/** FPS OPS: the six operations KPIs, display order (command_center_logic.KPI_ORDER minus money). */
const OPS_KPI_ORDER = ["enquiries", "quotations", "jobs", "customs_cleared", "deliveries", "job_activity"];
/** FPS ACC: acc.ts AccKpiKey, display order. */
const ACC_KPI_ORDER = ["invoiced", "collected", "paid_out", "purchases"];
const ALL_KPI_KEYS = [...OPS_KPI_ORDER, ...ACC_KPI_ORDER];
const UNITS = ["count", "currency"];
const GOOD = ["up", "down", "none"];
/** Most severe first (command_center_logic.SEVERITY_ORDER): a good-news swing outranks a standing info note. */
const SEVERITY_ORDER = ["critical", "warning", "positive", "info"];
const OPS_TREND_KEYS = ["pipeline", "activity"];
const ACC_TREND_KEYS = ["billing", "cashflow"];
const TREND_WEEKS = 12;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** OPS stage tiles that belong to ACC and must never reach the OPS strip. */
const OPS_HIDDEN_TILES = ["invoices"];
const BALANCE_ORDER = ["receivables", "payables", "cash", "vat"];
const BUCKET_ORDER = ["not_due", "0_30", "31_60", "61_90", "91_180", "181_365", "over_365"];
const BUCKET_LABELS = ["Not due", "0–30", "31–60", "61–90", "91–180", "181–365", "Over 365"];
const BANK_ORDER = ["ADCB", "WIO", "QGEN", "QGOV"];
const BANK_STATUSES = ["Reconciled", "In Progress", "Missing"];

const KEYS = {
  dashboard: {
    required: ["as_of", "generated_at", "period", "period_label", "compare_label", "viewer", "kpis", "stages", "trend", "insights"],
    optional: [],
  },
  viewer: { required: ["finance"], optional: ["full_name"] },
  kpi: {
    required: ["key", "label", "definition", "unit", "value", "previous", "delta_pct", "good_direction", "granularity", "series", "context", "route", "finance"],
    optional: ["currency", "caveat", "new_doctype"],
  },
  seriesPoint: { required: ["date", "value"], optional: ["partial"] },
  context: { required: ["label", "value"], optional: [] },
  stages: { required: ["tiles", "footnotes"], optional: [] },
  tile: { required: ["key", "label", "note", "count", "route"], optional: [] },
  insight: { required: ["id", "severity", "title", "detail"], optional: ["metric_key", "route"] },
  trendMode: { required: ["key", "label", "unit", "series", "points", "finance"], optional: ["currency", "caveat"] },
  trendSeries: { required: ["key", "label", "slot"], optional: [] },
  trendPoint: { required: ["week_start", "label", "partial", "values"], optional: [] },
  detail: {
    required: [
      "key", "label", "unit", "period", "period_label", "compare_label", "granularity", "value", "previous",
      "delta_pct", "good_direction", "series", "dimension_label", "dimension_options", "dimension", "breakdown",
      "records", "actions",
    ],
    optional: ["currency", "caveat"],
  },
  dimensionOption: { required: ["key", "label"], optional: [] },
  breakdown: { required: ["title", "rows"], optional: [] },
  breakdownRow: { required: ["key", "label", "value"], optional: [] },
  record: { required: ["name", "title", "date", "route"], optional: ["subtitle", "value", "status"] },
  action: { required: ["key", "label", "kind"], optional: ["route", "doctype"] },
  // acc.ts
  accPayload: {
    required: ["as_of", "generated_at", "period", "period_label", "compare_label", "viewer", "kpis", "balances", "ageing", "banks", "trend", "insights"],
    optional: [],
  },
  accViewer: { required: [], optional: ["full_name"] },
  balance: { required: ["key", "label", "definition", "currency", "value", "context", "route"], optional: ["severity", "caveat"] },
  ageing: { required: ["key", "label", "currency", "total", "overdue", "buckets", "top", "route"], optional: ["caveat"] },
  bucket: { required: ["key", "label", "value", "count"], optional: [] },
  party: { required: ["party", "label", "value", "overdue", "oldest_days", "count", "route"], optional: [] },
  bank: { required: ["bank", "label", "latest_month", "status", "closing_balance", "months_behind", "route"], optional: ["open_months"] },
};

/* ------------------------------------------------------------------------ */
/* Tiny assertion kit                                                          */
/* ------------------------------------------------------------------------ */

const failures = [];
let checks = 0;

function fail(where, message) {
  failures.push(`${where}: ${message}`);
}

function ok(cond, where, message) {
  checks += 1;
  if (!cond) fail(where, message);
  return Boolean(cond);
}

const isObj = (v) => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v) => typeof v === "string";
const isNonEmptyStr = (v) => typeof v === "string" && v.trim().length > 0;
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const isInt = (v) => Number.isInteger(v);
const isBool = (v) => typeof v === "boolean";
const isNumOrNull = (v) => v === null || isNum(v);
/** Money rounded to fils by the server (2 dp), within float noise. */
const isFils = (v) => isNum(v) && Math.abs(v * 100 - Math.round(v * 100)) < 1e-6;
const near = (a, b) => isNum(a) && isNum(b) && Math.abs(a - b) <= 0.011;
/**
 * A count is a non-negative integer. Money may go below zero: "Invoiced (net)"
 * includes submitted credit notes, purchases include debit notes, so a day, a
 * week or a customer can net out negative.
 */
const isAmount = (v, unit) => isNum(v) && (unit === "count" ? isInt(v) && v >= 0 : true);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;
const MONTH_LABEL = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$/;

/** Exact key set: every required key present, nothing outside required+optional. */
function shape(obj, spec, where) {
  if (!ok(isObj(obj), where, "is not an object")) return false;
  for (const key of spec.required) ok(key in obj, where, `missing required "${key}"`);
  const allowed = new Set([...spec.required, ...spec.optional]);
  for (const key of Object.keys(obj)) ok(allowed.has(key), where, `unexpected key "${key}"`);
  for (const key of spec.optional) {
    // Optional in TypeScript means absent or the type, never null.
    if (key in obj) ok(obj[key] !== null && obj[key] !== undefined, where, `optional "${key}" is null (omit it instead)`);
  }
  return true;
}

function parseDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

const DAY_MS = 86_400_000;
const daysBetween = (a, b) => Math.round((parseDate(b) - parseDate(a)) / DAY_MS);
const shortDate = (iso) => {
  const [, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
};
const isMonday = (iso) => new Date(parseDate(iso)).getUTCDay() === 1;

function isRoute(v) {
  return isStr(v) && /^\/(app|desk)(\/|\?|$)/.test(v) && !/\s/.test(v);
}

/**
 * Python's round-half-up to 1 dp, within float noise. Only against a positive
 * base (command_center_logic.delta_pct): null for no previous, a zero base and a
 * negative one (net credit notes), where a percentage is no signal.
 */
function expectedDelta(value, previous) {
  if (previous === null || previous <= 0) return null;
  return ((value - previous) / previous) * 100;
}

/* ------------------------------------------------------------------------ */
/* Pieces shared by both pages                                                 */
/* ------------------------------------------------------------------------ */

function checkSeries(series, { period, asOf, unit, value, where }) {
  const spec = PERIODS[period];
  if (!ok(Array.isArray(series), where, "series is not an array")) return;
  ok(series.length === spec.points, where, `series has ${series.length} points, expected ${spec.points} for ${period}`);
  let sum = 0;
  series.forEach((p, i) => {
    const pw = `${where}.series[${i}]`;
    if (!shape(p, KEYS.seriesPoint, pw)) return;
    ok(isStr(p.date) && ISO_DATE.test(p.date), pw, `date "${p.date}" is not yyyy-mm-dd`);
    ok(isAmount(p.value, unit), pw, `value ${p.value} is not a valid ${unit}`);
    if ("partial" in p) ok(p.partial === true, pw, "partial is present but not true (omit it instead)");
    const last = i === series.length - 1;
    ok(last ? p.partial === true : !("partial" in p), pw, last ? "the last point must be partial" : "only the last point may be partial");
    if (i > 0 && isStr(series[i - 1].date) && isStr(p.date)) {
      ok(daysBetween(series[i - 1].date, p.date) === spec.step, pw, `not ${spec.step} day(s) after the previous point`);
    }
    if (isNum(p.value)) sum += p.value;
  });
  const lastPoint = series[series.length - 1];
  if (lastPoint && isStr(lastPoint.date) && asOf) {
    // Daily: the last point IS as_of. Weekly (rolling 7-day buckets): the last bucket ends on as_of.
    ok(daysBetween(lastPoint.date, asOf) === spec.step - 1, where, `last point ${lastPoint.date} does not end on as_of ${asOf}`);
  }
  if (isNum(value)) {
    const tol = unit === "currency" ? 0.01 * series.length + 1e-6 : 0;
    ok(Math.abs(sum - value) <= tol, where, `series sums to ${sum}, value is ${value}`);
  }
}

function checkDeltaRule(obj, where) {
  ok(isNum(obj.value), where, "value is not a number");
  if (obj.unit === "count") ok(isInt(obj.value), where, `count value ${obj.value} is not an integer`);
  ok(isNumOrNull(obj.previous), where, "previous is not number|null");
  if (obj.unit === "count" && isNum(obj.previous)) ok(isInt(obj.previous), where, "count previous is not an integer");
  ok(isNumOrNull(obj.delta_pct), where, "delta_pct is not number|null");
  const exp = expectedDelta(obj.value, obj.previous);
  if (exp === null) {
    ok(obj.delta_pct === null, where, `delta_pct must be null when previous is ${obj.previous}`);
  } else if (isNum(obj.delta_pct)) {
    ok(Math.abs(obj.delta_pct - exp) <= 0.05 + 1e-9, where, `delta_pct ${obj.delta_pct} != ${exp.toFixed(3)} rounded to 1 dp`);
    ok(Math.abs(obj.delta_pct * 10 - Math.round(obj.delta_pct * 10)) < 1e-6, where, `delta_pct ${obj.delta_pct} has more than 1 dp`);
  } else {
    fail(where, `delta_pct is null although previous is ${obj.previous}`);
  }
  ok(GOOD.includes(obj.good_direction), where, `good_direction "${obj.good_direction}" not in ${GOOD.join("|")}`);
}

function checkUnitCurrency(obj, where) {
  ok(UNITS.includes(obj.unit), where, `unit "${obj.unit}" not in ${UNITS.join("|")}`);
  if (obj.unit === "currency") ok(isStr(obj.currency) && /^[A-Z]{3}$/.test(obj.currency), where, "a currency unit needs a 3-letter currency code");
  else ok(!("currency" in obj), where, "a count carries no currency");
}

function checkContext(lines, where, max) {
  if (!ok(Array.isArray(lines), where, "context is not an array")) return;
  ok(lines.length <= max, where, `${lines.length} context lines (max ${max})`);
  lines.forEach((c, j) => {
    const cw = `${where}.context[${j}]`;
    if (shape(c, KEYS.context, cw)) ok(isNonEmptyStr(c.label) && isNonEmptyStr(c.value), cw, "label/value must be non-empty strings");
  });
}

function checkPayloadHead(d, w, period) {
  ok(d.period === period, w, `period "${d.period}" but the file name says ${period}`);
  const spec = PERIODS[d.period];
  if (!ok(spec, w, `unknown period "${d.period}"`)) return null;
  ok(d.period_label === spec.label, w, `period_label "${d.period_label}" != "${spec.label}"`);
  ok(d.compare_label === spec.compare, w, `compare_label "${d.compare_label}" != "${spec.compare}"`);
  ok(isStr(d.as_of) && ISO_DATE.test(d.as_of), w, "as_of is not yyyy-mm-dd");
  ok(isStr(d.generated_at) && ISO_DATETIME.test(d.generated_at), w, "generated_at is not yyyy-mm-dd HH:mm:ss");
  ok(isStr(d.generated_at) && d.generated_at.startsWith(d.as_of), w, "generated_at is not on as_of");
  return spec;
}

/** KPIs in `order` (a subset in order is allowed by the type; these pages promise the full set). */
function checkKpis(d, w, { order, money }) {
  const spec = PERIODS[d.period];
  if (!ok(Array.isArray(d.kpis), w, "kpis is not an array")) return;
  const keys = d.kpis.map((k) => k?.key);
  ok(new Set(keys).size === keys.length, w, `duplicate KPI keys ${keys.join(",")}`);
  ok(keys.join(",") === order.join(","), w, `KPI set ${keys.join(",")} != ${order.join(",")}`);
  d.kpis.forEach((k, i) => {
    const kw = `${w}.kpis[${i}:${k?.key}]`;
    if (!shape(k, KEYS.kpi, kw)) return;
    ok(order.includes(k.key), kw, `unknown key "${k.key}"`);
    ok(isNonEmptyStr(k.label) && !k.label.endsWith(":"), kw, "label is empty or ends with a colon");
    ok(isNonEmptyStr(k.definition), kw, "definition is empty");
    checkUnitCurrency(k, kw);
    checkDeltaRule(k, kw);
    ok(k.granularity === spec.granularity, kw, `granularity "${k.granularity}" != "${spec.granularity}"`);
    checkSeries(k.series, { period: d.period, asOf: d.as_of, unit: k.unit, value: k.value, where: kw });
    checkContext(k.context, kw, 2);
    if ("caveat" in k) ok(isNonEmptyStr(k.caveat), kw, "caveat is empty");
    ok(isRoute(k.route), kw, `route "${k.route}" is not a desk URL`);
    if ("new_doctype" in k) ok(isNonEmptyStr(k.new_doctype), kw, "new_doctype is empty");
    ok(isBool(k.finance), kw, "finance is not boolean");
    ok(k.finance === (k.unit === "currency"), kw, "finance must be true exactly for money KPIs");
    ok(k.finance === money, kw, money ? "every ACC KPI is money (finance true)" : "the OPS page carries no money KPI");
  });
}

function checkTrend(d, w, { keys, money }) {
  if (!ok(Array.isArray(d.trend), w, "trend is not an array")) return;
  ok(d.trend.length <= keys.length, w, `${d.trend.length} trend modes (max ${keys.length})`);
  const modeKeys = d.trend.map((m) => m?.key);
  ok(new Set(modeKeys).size === modeKeys.length, w, "duplicate trend modes");
  ok(modeKeys.every((k) => keys.includes(k)), w, `trend modes ${modeKeys.join(",")} not within ${keys.join(",")}`);
  d.trend.forEach((m, i) => {
    const mw = `${w}.trend[${i}:${m?.key}]`;
    if (!shape(m, KEYS.trendMode, mw)) return;
    ok(isNonEmptyStr(m.label), mw, "label is empty");
    checkUnitCurrency(m, mw);
    ok(isBool(m.finance) && m.finance === (m.unit === "currency"), mw, "finance must be true exactly for a money mode");
    ok(m.finance === money, mw, money ? "ACC trend modes are money" : "the OPS page carries no money mode");
    if ("caveat" in m) ok(isNonEmptyStr(m.caveat), mw, "caveat is empty");
    if (ok(Array.isArray(m.series), mw, "series is not an array")) {
      ok(m.series.length >= 1 && m.series.length <= 4, mw, `${m.series.length} series (1–4)`);
      m.series.forEach((s, j) => {
        const sw = `${mw}.series[${j}]`;
        if (shape(s, KEYS.trendSeries, sw)) {
          ok(isNonEmptyStr(s.key) && isNonEmptyStr(s.label), sw, "key/label must be non-empty strings");
          ok([1, 2, 3, 4].includes(s.slot), sw, `slot ${s.slot} not in 1..4`);
        }
      });
      ok(new Set(m.series.map((s) => s?.key)).size === m.series.length, mw, "duplicate series keys");
      ok(new Set(m.series.map((s) => s?.slot)).size === m.series.length, mw, "two series share a colour slot");
    }
    if (ok(Array.isArray(m.points), mw, "points is not an array")) {
      ok(m.points.length === TREND_WEEKS, mw, `${m.points.length} weeks, expected ${TREND_WEEKS}`);
      const seriesKeys = (m.series ?? []).map((s) => s?.key).sort().join(",");
      m.points.forEach((p, j) => {
        const pw = `${mw}.points[${j}]`;
        if (!shape(p, KEYS.trendPoint, pw)) return;
        ok(isStr(p.week_start) && ISO_DATE.test(p.week_start) && isMonday(p.week_start), pw, `week_start "${p.week_start}" is not a Monday yyyy-mm-dd`);
        ok(isStr(p.week_start) && p.label === shortDate(p.week_start), pw, `label "${p.label}" != "${isStr(p.week_start) ? shortDate(p.week_start) : "?"}"`);
        const last = j === m.points.length - 1;
        ok(p.partial === last, pw, last ? "the current week must be partial" : "only the current week may be partial");
        if (j > 0) ok(daysBetween(m.points[j - 1].week_start, p.week_start) === 7, pw, "not 7 days after the previous week");
        if (ok(isObj(p.values), pw, "values is not an object")) {
          ok(Object.keys(p.values).sort().join(",") === seriesKeys, pw, `values keys ${Object.keys(p.values).join(",")} != series ${seriesKeys}`);
          for (const [key, v] of Object.entries(p.values)) {
            ok(isAmount(v, m.unit), pw, `values.${key}=${v} is not a valid ${m.unit}`);
          }
        }
      });
      const lastWeek = m.points[m.points.length - 1]?.week_start;
      if (isStr(lastWeek) && isStr(d.as_of)) {
        const offset = daysBetween(lastWeek, d.as_of);
        ok(offset >= 0 && offset <= 6, mw, `last week ${lastWeek} does not contain as_of ${d.as_of}`);
      }
    }
  });
}

function checkInsights(d, w) {
  if (!ok(Array.isArray(d.insights), w, "insights is not an array")) return;
  ok(d.insights.length <= 6, w, `${d.insights.length} insights (max 6)`);
  ok(new Set(d.insights.map((x) => x?.id)).size === d.insights.length, w, "duplicate insight ids");
  const kpiKeys = new Set((d.kpis ?? []).map((k) => k.key));
  let lastRank = -1;
  d.insights.forEach((x, i) => {
    const iw = `${w}.insights[${i}:${x?.id}]`;
    if (!shape(x, KEYS.insight, iw)) return;
    ok(isNonEmptyStr(x.id), iw, "id is empty");
    const rank = SEVERITY_ORDER.indexOf(x.severity);
    ok(rank >= 0, iw, `severity "${x.severity}" not in ${SEVERITY_ORDER.join("|")}`);
    ok(rank >= lastRank, iw, "insights are not ordered most severe first");
    lastRank = Math.max(lastRank, rank);
    ok(isNonEmptyStr(x.title) && x.title.length <= 90, iw, `title is empty or ${x.title?.length} > 90 chars`);
    ok(isNonEmptyStr(x.detail) && x.detail.length <= 200, iw, `detail is empty or ${x.detail?.length} > 200 chars`);
    ok(!/[<>]/.test(`${x.title}${x.detail}`), iw, "title/detail must be plain text");
    if ("metric_key" in x) {
      ok(ALL_KPI_KEYS.includes(x.metric_key), iw, `metric_key "${x.metric_key}" is not a KPI key`);
      ok(kpiKeys.has(x.metric_key), iw, `metric_key "${x.metric_key}" points at a KPI this page does not have`);
    }
    if ("route" in x) ok(isRoute(x.route), iw, `route "${x.route}" is not a desk URL`);
  });
}

/* ------------------------------------------------------------------------ */
/* FPS OPS dashboard                                                           */
/* ------------------------------------------------------------------------ */

function checkOpsDashboard(d, file, period) {
  const w = file;
  if (!shape(d, KEYS.dashboard, w)) return;
  if (!checkPayloadHead(d, w, period)) return;

  shape(d.viewer, KEYS.viewer, `${w}.viewer`);
  if ("full_name" in (d.viewer ?? {})) ok(isStr(d.viewer.full_name), `${w}.viewer`, "full_name is not a string");
  // Since 14 Oct 2026 the OPS page has no money for anyone, finance roles included.
  ok(d.viewer?.finance === false, `${w}.viewer`, "viewer.finance must always be false on the OPS page");
  ok(!/\bAED\b/.test(JSON.stringify(d)), w, "money text (AED) in an OPS payload");

  checkKpis(d, w, { order: OPS_KPI_ORDER, money: false });

  if (shape(d.stages, KEYS.stages, `${w}.stages`)) {
    const tiles = d.stages.tiles;
    if (ok(Array.isArray(tiles), `${w}.stages`, "tiles is not an array")) {
      ok(new Set(tiles.map((t) => t?.key)).size === tiles.length, `${w}.stages`, "duplicate tile keys");
      tiles.forEach((t, i) => {
        const tw = `${w}.stages.tiles[${i}:${t?.key}]`;
        if (!shape(t, KEYS.tile, tw)) return;
        ok(isNonEmptyStr(t.key) && isNonEmptyStr(t.label) && isStr(t.note), tw, "key/label/note must be strings");
        ok(!OPS_HIDDEN_TILES.includes(t.key), tw, "the Invoices tile belongs to the FPS ACC Dashboard");
        ok(isInt(t.count) && t.count >= 0, tw, `count ${t.count} is not a non-negative integer`);
        ok(isRoute(t.route), tw, `route "${t.route}" is not a desk URL`);
      });
    }
    if (ok(Array.isArray(d.stages.footnotes), `${w}.stages`, "footnotes is not an array")) {
      d.stages.footnotes.forEach((f, i) => ok(isNonEmptyStr(f), `${w}.stages.footnotes[${i}]`, "is not a non-empty string"));
    }
  }

  checkTrend(d, w, { keys: OPS_TREND_KEYS, money: false });
  checkInsights(d, w);
}

/* ------------------------------------------------------------------------ */
/* FPS ACC dashboard                                                           */
/* ------------------------------------------------------------------------ */

function checkBalance(b, i, w) {
  const bw = `${w}.balances[${i}:${b?.key}]`;
  if (!shape(b, KEYS.balance, bw)) return;
  ok(isNonEmptyStr(b.label) && !b.label.endsWith(":"), bw, "label is empty or ends with a colon");
  ok(isNonEmptyStr(b.definition), bw, "definition is empty");
  ok(isStr(b.currency) && /^[A-Z]{3}$/.test(b.currency), bw, "currency is not a 3-letter code");
  ok(isFils(b.value), bw, `value ${b.value} is not money rounded to fils`);
  checkContext(b.context, bw, 4);
  if ("severity" in b) ok(SEVERITY_ORDER.includes(b.severity), bw, `severity "${b.severity}" not in ${SEVERITY_ORDER.join("|")}`);
  if ("caveat" in b) ok(isNonEmptyStr(b.caveat), bw, "caveat is empty");
  ok(isRoute(b.route), bw, `route "${b.route}" is not a desk URL`);
  if (b.key === "vat") ok(/^VAT [A-Z][a-z]{2}–[A-Z][a-z]{2} \d{4}$/.test(b.label), bw, `VAT label "${b.label}" is not "VAT Jul–Sep 2026"-shaped`);
}

function checkAgeing(a, i, w, balanceByKey) {
  const aw = `${w}.ageing[${i}:${a?.key}]`;
  if (!shape(a, KEYS.ageing, aw)) return;
  ok(isNonEmptyStr(a.label), aw, "label is empty");
  ok(isStr(a.currency) && /^[A-Z]{3}$/.test(a.currency), aw, "currency is not a 3-letter code");
  ok(isFils(a.total) && isFils(a.overdue), aw, "total/overdue are not money rounded to fils");
  ok(isRoute(a.route), aw, `route "${a.route}" is not a desk URL`);
  if ("caveat" in a) ok(isNonEmptyStr(a.caveat), aw, "caveat is empty");
  const balance = balanceByKey.get(a.key);
  if (balance) ok(near(balance.value, a.total), aw, `total ${a.total} != the ${a.key} balance ${balance.value}`);
  if (ok(Array.isArray(a.buckets), aw, "buckets is not an array")) {
    ok(a.buckets.map((b) => b?.key).join(",") === BUCKET_ORDER.join(","), aw, "buckets must be all 7, in AgeingBucketKey order");
    a.buckets.forEach((b, j) => {
      const bw = `${aw}.buckets[${j}:${b?.key}]`;
      if (!shape(b, KEYS.bucket, bw)) return;
      ok(b.label === BUCKET_LABELS[j], bw, `label "${b.label}" != "${BUCKET_LABELS[j]}"`);
      ok(isFils(b.value), bw, `value ${b.value} is not money rounded to fils`);
      ok(isInt(b.count) && b.count >= 0, bw, `count ${b.count} is not a non-negative integer`);
      ok(b.count > 0 || b.value === 0, bw, "a bucket with no documents must be 0");
    });
    const sum = a.buckets.reduce((s, b) => s + (isNum(b?.value) ? b.value : 0), 0);
    ok(near(sum, a.total), aw, `buckets sum to ${sum.toFixed(2)}, total is ${a.total}`);
    // overdue is the per-party net figure (same as the card's "Overdue" line),
    // not the sum of the past-due buckets: it is never negative.
    ok(isNum(a.overdue) && a.overdue >= 0, aw, `overdue ${a.overdue} is negative`);
  }
  if (ok(Array.isArray(a.top), aw, "top is not an array")) {
    ok(a.top.length <= 5, aw, `${a.top.length} top parties (max 5)`);
    ok(new Set(a.top.map((p) => p?.party)).size === a.top.length, aw, "duplicate parties (React keys)");
    a.top.forEach((p, j) => {
      const pw = `${aw}.top[${j}:${p?.party}]`;
      if (!shape(p, KEYS.party, pw)) return;
      ok(isNonEmptyStr(p.party) && isNonEmptyStr(p.label), pw, "party/label must be non-empty strings");
      ok(isFils(p.value) && isFils(p.overdue), pw, "value/overdue are not money rounded to fils");
      ok(isInt(p.oldest_days) && p.oldest_days >= 0, pw, `oldest_days ${p.oldest_days} is not a non-negative integer`);
      ok(isInt(p.count) && p.count >= 1, pw, `count ${p.count} is not a positive integer`);
      ok(isRoute(p.route), pw, `route "${p.route}" is not a desk URL`);
      if (j > 0 && isNum(a.top[j - 1]?.value)) ok(a.top[j - 1].value >= p.value, pw, "top parties are not largest first");
    });
  }
}

function checkBank(b, i, w) {
  const bw = `${w}.banks[${i}:${b?.bank}]`;
  if (!shape(b, KEYS.bank, bw)) return;
  ok(b.bank === BANK_ORDER[i], bw, `bank "${b.bank}" != "${BANK_ORDER[i]}" (order ADCB, WIO, QGEN, QGOV)`);
  ok(isNonEmptyStr(b.label), bw, "label is empty");
  ok(BANK_STATUSES.includes(b.status), bw, `status "${b.status}" not in ${BANK_STATUSES.join("|")}`);
  if (b.status === "Missing") {
    ok(b.latest_month === null && b.closing_balance === null, bw, "a Missing bank has no latest_month and no closing_balance");
  } else {
    ok(isStr(b.latest_month) && MONTH_LABEL.test(b.latest_month), bw, `latest_month "${b.latest_month}" is not "Sep 2026"-shaped`);
    ok(b.closing_balance === null || isFils(b.closing_balance), bw, "closing_balance is not money|null");
  }
  ok(isInt(b.months_behind) && b.months_behind >= 0, bw, `months_behind ${b.months_behind} is not a non-negative integer`);
  // open_months names the months behind (acc.ts): present exactly when behind.
  if (b.months_behind > 0) ok(isNonEmptyStr(b.open_months), bw, "behind but no open_months text");
  else ok(!("open_months" in b), bw, "open_months sent for a bank that is not behind");
  ok(isRoute(b.route), bw, `route "${b.route}" is not a desk URL`);
}

function checkAccDashboard(d, file, period) {
  const w = file;
  if (!shape(d, KEYS.accPayload, w)) return;
  if (!checkPayloadHead(d, w, period)) return;
  shape(d.viewer, KEYS.accViewer, `${w}.viewer`);
  if ("full_name" in (d.viewer ?? {})) ok(isStr(d.viewer.full_name), `${w}.viewer`, "full_name is not a string");

  checkKpis(d, w, { order: ACC_KPI_ORDER, money: true });

  const balanceByKey = new Map();
  if (ok(Array.isArray(d.balances), w, "balances is not an array")) {
    ok(d.balances.map((b) => b?.key).join(",") === BALANCE_ORDER.join(","), w, `balances ${d.balances.map((b) => b?.key).join(",")} != ${BALANCE_ORDER.join(",")}`);
    d.balances.forEach((b, i) => {
      checkBalance(b, i, w);
      if (isObj(b)) balanceByKey.set(b.key, b);
    });
  }
  if (ok(Array.isArray(d.ageing), w, "ageing is not an array")) {
    ok(d.ageing.map((a) => a?.key).join(",") === "receivables,payables", w, "ageing must be [receivables, payables]");
    d.ageing.forEach((a, i) => checkAgeing(a, i, w, balanceByKey));
  }
  if (ok(Array.isArray(d.banks), w, "banks is not an array")) {
    ok(d.banks.length === BANK_ORDER.length, w, `${d.banks.length} banks, expected ${BANK_ORDER.length}`);
    d.banks.forEach((b, i) => checkBank(b, i, w));
  }
  checkTrend(d, w, { keys: ACC_TREND_KEYS, money: true });
  checkInsights(d, w);
}

/* ------------------------------------------------------------------------ */
/* Metric detail (both pages)                                                  */
/* ------------------------------------------------------------------------ */

function checkDetail(m, file, expect, dash) {
  const w = file;
  if (!shape(m, KEYS.detail, w)) return;
  const asOf = dash?.as_of;
  ok(m.key === expect.key, w, `key "${m.key}" but the file name says ${expect.key}`);
  ok(m.period === expect.period, w, `period "${m.period}" but the file name says ${expect.period}`);
  ok(expect.order.includes(m.key), w, `"${m.key}" is not a KPI of the ${expect.page} page`);
  const spec = PERIODS[m.period];
  if (!ok(spec, w, `unknown period "${m.period}"`)) return;
  ok(m.period_label === spec.label, w, `period_label "${m.period_label}" != "${spec.label}"`);
  ok(m.compare_label === spec.compare, w, `compare_label "${m.compare_label}" != "${spec.compare}"`);
  ok(m.granularity === spec.granularity, w, `granularity "${m.granularity}" != "${spec.granularity}"`);
  ok(isNonEmptyStr(m.label), w, "label is empty");
  checkUnitCurrency(m, w);
  checkDeltaRule(m, w);
  if ("caveat" in m) ok(isNonEmptyStr(m.caveat), w, "caveat is empty");
  checkSeries(m.series, { period: m.period, asOf, unit: m.unit, value: m.value, where: w });
  if (expect.page === "ops") ok(!/\bAED\b/.test(JSON.stringify(m)), w, "money text (AED) in an OPS drawer");
  if (expect.page === "acc") ok(m.unit === "currency", w, "an ACC drawer is money");

  // Dimension
  ok(m.dimension_label === null || isNonEmptyStr(m.dimension_label), w, "dimension_label is not string|null");
  if (ok(Array.isArray(m.dimension_options), w, "dimension_options is not an array")) {
    m.dimension_options.forEach((o, i) => {
      const ow = `${w}.dimension_options[${i}]`;
      if (shape(o, KEYS.dimensionOption, ow)) ok(isNonEmptyStr(o.key) && isNonEmptyStr(o.label), ow, "key/label must be non-empty strings");
    });
    ok(new Set(m.dimension_options.map((o) => o?.key)).size === m.dimension_options.length, w, "duplicate dimension options");
    if (m.dimension_label === null) ok(m.dimension_options.length === 0, w, "options without a dimension_label");
  }
  ok(m.dimension === null || isNonEmptyStr(m.dimension), w, "dimension is not string|null");
  ok(m.dimension === (expect.dimension ? m.dimension : null), w, "an unfiltered fixture must have dimension null");
  if (expect.dimension) {
    ok(isNonEmptyStr(m.dimension), w, "a dimension fixture needs a dimension");
    ok((m.dimension_options ?? []).some((o) => o.key === m.dimension), w, `dimension "${m.dimension}" is not one of the options`);
  }

  // Breakdown
  if (m.breakdown !== null && shape(m.breakdown, KEYS.breakdown, `${w}.breakdown`)) {
    ok(isNonEmptyStr(m.breakdown.title), `${w}.breakdown`, "title is empty");
    if (ok(Array.isArray(m.breakdown.rows), `${w}.breakdown`, "rows is not an array")) {
      m.breakdown.rows.forEach((r, i) => {
        const rw = `${w}.breakdown.rows[${i}]`;
        if (!shape(r, KEYS.breakdownRow, rw)) return;
        ok(isNonEmptyStr(r.key) && isNonEmptyStr(r.label), rw, "key/label must be non-empty strings");
        ok(isAmount(r.value, m.unit), rw, `value ${r.value} is not a valid ${m.unit}`);
      });
      ok(new Set(m.breakdown.rows.map((r) => r?.key)).size === m.breakdown.rows.length, `${w}.breakdown`, "duplicate row keys");
    }
  }

  // Records
  if (ok(Array.isArray(m.records), w, "records is not an array")) {
    ok(m.records.length <= 8, w, `${m.records.length} records (max 8)`);
    ok(new Set(m.records.map((r) => r?.name)).size === m.records.length, w, "duplicate record names (React keys)");
    m.records.forEach((r, i) => {
      const rw = `${w}.records[${i}:${r?.name}]`;
      if (!shape(r, KEYS.record, rw)) return;
      ok(isNonEmptyStr(r.name) && isNonEmptyStr(r.title), rw, "name/title must be non-empty strings");
      ok(isStr(r.date) && ISO_DATE.test(r.date), rw, `date "${r.date}" is not yyyy-mm-dd`);
      if (i > 0 && isStr(m.records[i - 1].date)) ok(m.records[i - 1].date >= r.date, rw, "records are not newest first");
      ok(isRoute(r.route), rw, `route "${r.route}" is not a desk URL`);
      // value is always money (dashboard.ts DrillRecord.value): required for a
      // money metric; never on the OPS page (no amounts for anyone there).
      if (m.unit === "currency") ok(isNum(r.value), rw, "a money record needs a value");
      else ok(!("value" in r), rw, "an OPS record carries no amount (Quotation totals stay off this page)");
      for (const key of ["subtitle", "status"]) if (key in r) ok(isNonEmptyStr(r[key]), rw, `${key} is empty`);
    });
  }

  // Actions
  if (ok(Array.isArray(m.actions), w, "actions is not an array")) {
    ok(new Set(m.actions.map((a) => a?.key)).size === m.actions.length, w, "duplicate action keys");
    m.actions.forEach((a, i) => {
      const aw = `${w}.actions[${i}:${a?.key}]`;
      if (!shape(a, KEYS.action, aw)) return;
      ok(isNonEmptyStr(a.key) && isNonEmptyStr(a.label), aw, "key/label must be non-empty strings");
      if (a.kind === "route") ok(isRoute(a.route) && !("doctype" in a), aw, "a route action needs a desk route and no doctype");
      else if (a.kind === "new_doc") ok(isNonEmptyStr(a.doctype) && !("route" in a), aw, "a new_doc action needs a doctype and no route");
      else fail(aw, `kind "${a.kind}" not in route|new_doc`);
      // SPEC §2.3: no "New" action for money that left (paid_out) or bills (purchases).
      if (["paid_out", "purchases"].includes(m.key)) ok(a.kind !== "new_doc", aw, `no "New" action on ${m.key}`);
    });
  }

  // The drawer must agree with the card it opens from (same period, "All").
  if (!expect.dimension) {
    const kpi = dash?.kpis?.find((k) => k.key === m.key);
    if (ok(kpi, w, `no ${m.key} KPI in the ${expect.page} dashboard for ${m.period} to compare with`)) {
      for (const field of ["label", "unit", "currency", "value", "previous", "delta_pct", "good_direction", "granularity", "caveat"]) {
        ok(JSON.stringify(kpi[field]) === JSON.stringify(m[field]), w, `${field} ${JSON.stringify(m[field])} != card ${JSON.stringify(kpi[field])}`);
      }
      ok(JSON.stringify(kpi.series) === JSON.stringify(m.series), w, "series differs from the card's sparkline");
    }
  } else {
    // A dimension narrows a count; it can never exceed "All". (Not for money:
    // "All" may include a credit note that the filter leaves out.)
    const all = dash?.kpis?.find((k) => k.key === m.key);
    if (all && isNum(m.value) && m.unit === "count") ok(m.value <= all.value, w, `filtered value ${m.value} exceeds the unfiltered ${all.value}`);
  }
}

/* ------------------------------------------------------------------------ */
/* Main                                                                        */
/* ------------------------------------------------------------------------ */

const files = readdirSync(FIXTURES).filter((f) => f.endsWith(".json")).sort();
const docs = new Map(files.map((f) => [f, JSON.parse(readFileSync(path.join(FIXTURES, f), "utf8"))]));

/** "ops.7d", "acc.7d", "acc.7d.edge" → payload */
const dashboards = new Map();
const plan = [];
for (const f of files) {
  let m;
  if ((m = /^dashboard\.(7d|30d|90d)\.json$/.exec(f))) {
    const [, period] = m;
    dashboards.set(`ops.${period}`, docs.get(f));
    plan.push(() => checkOpsDashboard(docs.get(f), f, period));
  } else if ((m = /^acc\.dashboard\.(7d|30d|90d)(?:\.([a-z]+))?\.json$/.exec(f))) {
    const [, period, scenario] = m;
    dashboards.set(`acc.${period}${scenario ? `.${scenario}` : ""}`, docs.get(f));
    plan.push(() => checkAccDashboard(docs.get(f), f, period));
  } else if ((m = /^(acc\.)?metric_detail\.([a-z_]+)\.(7d|30d|90d)(\.dimension)?\.json$/.exec(f))) {
    const [, acc, key, period, dim] = m;
    const page = acc ? "acc" : "ops";
    plan.push(() =>
      checkDetail(docs.get(f), f, { key, period, dimension: Boolean(dim), page, order: acc ? ACC_KPI_ORDER : OPS_KPI_ORDER }, dashboards.get(`${page}.${period}`)),
    );
  } else {
    fail(f, "unexpected fixture name (the dev mock would never serve it)");
  }
}

// Coverage: everything the dev mock can be asked for exists.
for (const period of Object.keys(PERIODS)) {
  ok(dashboards.has(`ops.${period}`), "coverage", `dashboard.${period}.json is missing`);
  ok(dashboards.has(`acc.${period}`), "coverage", `acc.dashboard.${period}.json is missing`);
  for (const key of OPS_KPI_ORDER) ok(docs.has(`metric_detail.${key}.${period}.json`), "coverage", `metric_detail.${key}.${period}.json is missing`);
  for (const key of ACC_KPI_ORDER) ok(docs.has(`acc.metric_detail.${key}.${period}.json`), "coverage", `acc.metric_detail.${key}.${period}.json is missing`);
}
// The OPS page no longer has money drawers.
for (const key of ACC_KPI_ORDER.filter((k) => !OPS_KPI_ORDER.includes(k))) {
  for (const period of Object.keys(PERIODS)) {
    ok(!docs.has(`metric_detail.${key}.${period}.json`), "coverage", `metric_detail.${key}.${period}.json is an OPS money drawer (it moved to acc.*)`);
  }
}
// A scenario page shares the default page's KPIs and trend (the drawers are shared).
for (const [name, payload] of dashboards) {
  const m = /^acc\.(7d|30d|90d)\.([a-z]+)$/.exec(name);
  if (!m) continue;
  const base = dashboards.get(`acc.${m[1]}`);
  if (!base) continue;
  ok(payload.as_of === base.as_of, name, "a scenario page must share as_of with the default page");
  ok(JSON.stringify(payload.kpis) === JSON.stringify(base.kpis), name, "a scenario page must share the KPIs (the drawers are shared)");
}

for (const run of plan) run();

if (failures.length > 0) {
  console.error(`fixtures.check: ${failures.length} failure(s) in ${files.length} fixtures (${checks} checks)`);
  for (const f of failures.slice(0, 200)) console.error(`  - ${f}`);
  if (failures.length > 200) console.error(`  … and ${failures.length - 200} more`);
  process.exit(1);
}
console.log(`fixtures.check: ${files.length} fixtures OK (${checks} checks)`);
