#!/usr/bin/env node
/**
 * Structural check of dev/fixtures/*.json against the payload contract
 * (src/types/dashboard.ts) and the rules the API promises on top of it.
 *
 *   node scripts/fixtures.check.mjs [fixtures-dir]   (npm run check:fixtures)
 *
 * Why this exists next to `make_fixtures.py --typecheck`: tsc proves each file
 * is ASSIGNABLE to its type, but not the semantics the UI relies on and the
 * type system cannot say — series of exactly 7/30/13 points ending on as_of,
 * `partial` only on the last point, KPIs in the fixed order, the delta rule
 * (null against a missing, zero or negative base), money only for finance viewers,
 * insights ≤ 90/200 characters and most severe first, records newest first
 * with unique names (React keys), and a drawer that agrees with the card it
 * was opened from. A fixture that breaks one of these would make the dev
 * harness lie about how the live dashboard behaves.
 *
 * Hand-written on purpose (no schema library): the dashboard has no runtime
 * dependency for validation, and the contract is small enough to mirror.
 * Keep the KEY lists below in step with src/types/dashboard.ts.
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
/* The contract, mirrored from src/types/dashboard.ts                         */
/* ------------------------------------------------------------------------ */

const PERIODS = {
  "7d": { points: 7, step: 1, granularity: "day", label: "Last 7 days", compare: "vs previous 7 days" },
  "30d": { points: 30, step: 1, granularity: "day", label: "Last 30 days", compare: "vs previous 30 days" },
  "90d": { points: 13, step: 7, granularity: "week", label: "Last 13 weeks", compare: "vs previous 13 weeks" },
};
/** Display order the API sends KPIs in (command_center_logic.KPI_ORDER). */
const KPI_ORDER = ["enquiries", "quotations", "jobs", "customs_cleared", "deliveries", "job_activity", "invoiced", "collected"];
const UNITS = ["count", "currency"];
const GOOD = ["up", "down", "none"];
/** Most severe first (command_center_logic.SEVERITY_ORDER): a good-news swing outranks a standing info note. */
const SEVERITY_ORDER = ["critical", "warning", "positive", "info"];
const TREND_KEYS = ["pipeline", "activity", "money"];
const TREND_WEEKS = 12;
/** Count metrics whose records carry a money amount (finance viewers only). */
const AMOUNT_COUNT_KEYS = ["quotations"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

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
/**
 * A count is a non-negative integer. Money may go below zero: "Invoiced (net)"
 * includes submitted credit notes (command_center_logic.points_invoiced), so a
 * day, a week or a customer can net out negative.
 */
const isAmount = (v, unit) => isNum(v) && (unit === "count" ? isInt(v) && v >= 0 : true);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

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
/* Pieces                                                                      */
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

/* ------------------------------------------------------------------------ */
/* Dashboard                                                                   */
/* ------------------------------------------------------------------------ */

function checkDashboard(d, file, expect) {
  const w = file;
  if (!shape(d, KEYS.dashboard, w)) return;
  ok(d.period === expect.period, w, `period "${d.period}" but the file name says ${expect.period}`);
  const spec = PERIODS[d.period];
  if (!ok(spec, w, `unknown period "${d.period}"`)) return;
  ok(d.period_label === spec.label, w, `period_label "${d.period_label}" != "${spec.label}"`);
  ok(d.compare_label === spec.compare, w, `compare_label "${d.compare_label}" != "${spec.compare}"`);
  ok(isStr(d.as_of) && ISO_DATE.test(d.as_of), w, "as_of is not yyyy-mm-dd");
  ok(isStr(d.generated_at) && ISO_DATETIME.test(d.generated_at), w, "generated_at is not yyyy-mm-dd HH:mm:ss");
  ok(isStr(d.generated_at) && d.generated_at.startsWith(d.as_of), w, "generated_at is not on as_of");

  shape(d.viewer, KEYS.viewer, `${w}.viewer`);
  ok(isBool(d.viewer?.finance), `${w}.viewer`, "finance is not boolean");
  if ("full_name" in (d.viewer ?? {})) ok(isStr(d.viewer.full_name), `${w}.viewer`, "full_name is not a string");
  ok(d.viewer?.finance === (expect.viewer === "finance"), `${w}.viewer`, `finance=${d.viewer?.finance} but the file is the ${expect.viewer} viewer`);
  const finance = d.viewer?.finance === true;
  // build_dashboard drops every money row for a non-finance viewer, so no
  // amount can leak through a context line, an insight or a caveat either.
  if (!finance) ok(!/\bAED\b/.test(JSON.stringify(d)), w, "money text (AED) in a non-finance payload");

  // KPIs ----------------------------------------------------------------
  if (ok(Array.isArray(d.kpis), w, "kpis is not an array")) {
    ok(d.kpis.length <= 8, w, `${d.kpis.length} KPIs (max 8)`);
    const keys = d.kpis.map((k) => k?.key);
    ok(new Set(keys).size === keys.length, w, `duplicate KPI keys ${keys.join(",")}`);
    const ranks = keys.map((k) => KPI_ORDER.indexOf(k));
    ok(ranks.every((r, i) => r >= 0 && (i === 0 || r > ranks[i - 1])), w, `KPIs out of order: ${keys.join(",")}`);
    // What the two viewers are promised: the six operational KPIs always,
    // the two money KPIs exactly when the viewer has an Accounts role.
    const expected = finance ? KPI_ORDER : KPI_ORDER.filter((k) => k !== "invoiced" && k !== "collected");
    ok(keys.join(",") === expected.join(","), w, `KPI set ${keys.join(",")} != ${expected.join(",")}`);
    d.kpis.forEach((k, i) => {
      const kw = `${w}.kpis[${i}:${k?.key}]`;
      if (!shape(k, KEYS.kpi, kw)) return;
      ok(KPI_ORDER.includes(k.key), kw, `unknown key "${k.key}"`);
      ok(isNonEmptyStr(k.label) && !k.label.endsWith(":"), kw, "label is empty or ends with a colon");
      ok(isNonEmptyStr(k.definition), kw, "definition is empty");
      checkUnitCurrency(k, kw);
      checkDeltaRule(k, kw);
      ok(k.granularity === spec.granularity, kw, `granularity "${k.granularity}" != "${spec.granularity}"`);
      checkSeries(k.series, { period: d.period, asOf: d.as_of, unit: k.unit, value: k.value, where: kw });
      if (ok(Array.isArray(k.context), kw, "context is not an array")) {
        ok(k.context.length <= 2, kw, `${k.context.length} context lines (max 2)`);
        k.context.forEach((c, j) => {
          const cw = `${kw}.context[${j}]`;
          if (shape(c, KEYS.context, cw)) ok(isNonEmptyStr(c.label) && isNonEmptyStr(c.value), cw, "label/value must be non-empty strings");
        });
      }
      if ("caveat" in k) ok(isNonEmptyStr(k.caveat), kw, "caveat is empty");
      ok(isRoute(k.route), kw, `route "${k.route}" is not a desk URL`);
      if ("new_doctype" in k) ok(isNonEmptyStr(k.new_doctype), kw, "new_doctype is empty");
      ok(isBool(k.finance), kw, "finance is not boolean");
      ok(k.finance === (k.unit === "currency"), kw, "finance must be true exactly for money KPIs");
      if (k.finance) ok(finance, kw, "money KPI sent to a non-finance viewer");
    });
  }

  // Stages --------------------------------------------------------------
  if (shape(d.stages, KEYS.stages, `${w}.stages`)) {
    const tiles = d.stages.tiles;
    if (ok(Array.isArray(tiles), `${w}.stages`, "tiles is not an array")) {
      ok(new Set(tiles.map((t) => t?.key)).size === tiles.length, `${w}.stages`, "duplicate tile keys");
      tiles.forEach((t, i) => {
        const tw = `${w}.stages.tiles[${i}:${t?.key}]`;
        if (!shape(t, KEYS.tile, tw)) return;
        ok(isNonEmptyStr(t.key) && isNonEmptyStr(t.label) && isStr(t.note), tw, "key/label/note must be strings");
        ok(isInt(t.count) && t.count >= 0, tw, `count ${t.count} is not a non-negative integer`);
        ok(isRoute(t.route), tw, `route "${t.route}" is not a desk URL`);
      });
    }
    if (ok(Array.isArray(d.stages.footnotes), `${w}.stages`, "footnotes is not an array")) {
      d.stages.footnotes.forEach((f, i) => ok(isNonEmptyStr(f), `${w}.stages.footnotes[${i}]`, "is not a non-empty string"));
    }
  }

  // Trend ---------------------------------------------------------------
  if (ok(Array.isArray(d.trend), w, "trend is not an array")) {
    ok(d.trend.length <= 3, w, `${d.trend.length} trend modes (max 3)`);
    const modeKeys = d.trend.map((m) => m?.key);
    ok(new Set(modeKeys).size === modeKeys.length, w, "duplicate trend modes");
    ok(modeKeys.includes("money") === finance, w, finance ? "finance viewer is missing the money trend" : "money trend sent to a non-finance viewer");
    d.trend.forEach((m, i) => {
      const mw = `${w}.trend[${i}:${m?.key}]`;
      if (!shape(m, KEYS.trendMode, mw)) return;
      ok(TREND_KEYS.includes(m.key), mw, `unknown mode "${m.key}"`);
      ok(isNonEmptyStr(m.label), mw, "label is empty");
      checkUnitCurrency(m, mw);
      ok(isBool(m.finance) && m.finance === (m.unit === "currency"), mw, "finance must be true exactly for the money mode");
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

  // Insights ------------------------------------------------------------
  if (ok(Array.isArray(d.insights), w, "insights is not an array")) {
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
        ok(KPI_ORDER.includes(x.metric_key), iw, `metric_key "${x.metric_key}" is not a KPI key`);
        ok(kpiKeys.has(x.metric_key), iw, `metric_key "${x.metric_key}" points at a KPI this viewer does not get`);
      }
      if ("route" in x) ok(isRoute(x.route), iw, `route "${x.route}" is not a desk URL`);
    });
  }
}

/* ------------------------------------------------------------------------ */
/* Metric detail                                                               */
/* ------------------------------------------------------------------------ */

function checkDetail(m, file, expect, asOf, dashboards) {
  const w = file;
  if (!shape(m, KEYS.detail, w)) return;
  ok(m.key === expect.key, w, `key "${m.key}" but the file name says ${expect.key}`);
  ok(m.period === expect.period, w, `period "${m.period}" but the file name says ${expect.period}`);
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
      // money metric; on a count metric only where the record has an amount
      // (the Quotation total, sent to finance viewers).
      if (m.unit === "currency") ok(isNum(r.value), rw, "a money record needs a value");
      else if ("value" in r) ok(AMOUNT_COUNT_KEYS.includes(m.key) && isNum(r.value) && r.value >= 0, rw, `a ${m.key} record carries no amount`);
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
    });
  }

  // The drawer must agree with the card it opens from (same period, "All").
  if (!expect.dimension) {
    const dash = dashboards.get(`finance.${m.period}`);
    const kpi = dash?.kpis?.find((k) => k.key === m.key);
    if (ok(kpi, w, `no ${m.key} KPI in dashboard.finance.${m.period}.json to compare with`)) {
      for (const field of ["label", "unit", "currency", "value", "previous", "delta_pct", "good_direction", "granularity", "caveat"]) {
        ok(JSON.stringify(kpi[field]) === JSON.stringify(m[field]), w, `${field} ${JSON.stringify(m[field])} != card ${JSON.stringify(kpi[field])}`);
      }
      ok(JSON.stringify(kpi.series) === JSON.stringify(m.series), w, "series differs from the card's sparkline");
    }
  } else {
    // A dimension narrows a count; it can never exceed "All". (Not for money:
    // "All" may include a credit note that the filter leaves out.)
    const all = dashboards.get(`finance.${m.period}`)?.kpis?.find((k) => k.key === m.key);
    if (all && isNum(m.value) && m.unit === "count") ok(m.value <= all.value, w, `filtered value ${m.value} exceeds the unfiltered ${all.value}`);
  }
}

/* ------------------------------------------------------------------------ */
/* Main                                                                        */
/* ------------------------------------------------------------------------ */

const files = readdirSync(FIXTURES).filter((f) => f.endsWith(".json")).sort();
const docs = new Map(files.map((f) => [f, JSON.parse(readFileSync(path.join(FIXTURES, f), "utf8"))]));

const dashboards = new Map();
const plan = [];
for (const f of files) {
  let m;
  if ((m = /^dashboard\.(finance|ops)\.(7d|30d|90d)\.json$/.exec(f))) {
    dashboards.set(`${m[1]}.${m[2]}`, docs.get(f));
    plan.push(() => checkDashboard(docs.get(f), f, { viewer: m[1], period: m[2] }));
  } else if ((m = /^metric_detail\.([a-z_]+)\.(7d|30d|90d)(\.dimension)?\.json$/.exec(f))) {
    const [, key, period, dim] = m;
    plan.push(() => {
      const asOf = dashboards.get(`finance.${period}`)?.as_of;
      checkDetail(docs.get(f), f, { key, period, dimension: Boolean(dim) }, asOf, dashboards);
    });
  } else {
    fail(f, "unexpected fixture name (the dev mock would never serve it)");
  }
}

// Coverage: everything the dev mock can be asked for exists.
for (const viewer of ["finance", "ops"]) {
  for (const period of Object.keys(PERIODS)) {
    ok(dashboards.has(`${viewer}.${period}`), "coverage", `dashboard.${viewer}.${period}.json is missing`);
  }
}
for (const key of KPI_ORDER) {
  for (const period of Object.keys(PERIODS)) {
    ok(docs.has(`metric_detail.${key}.${period}.json`), "coverage", `metric_detail.${key}.${period}.json is missing`);
  }
}

// The two viewers see the same site: shared numbers must match.
for (const period of Object.keys(PERIODS)) {
  const fin = dashboards.get(`finance.${period}`);
  const ops = dashboards.get(`ops.${period}`);
  if (!fin || !ops) continue;
  ok(fin.as_of === ops.as_of, "coverage", `as_of differs between viewers for ${period}`);
  for (const k of ops.kpis ?? []) {
    const twin = (fin.kpis ?? []).find((x) => x.key === k.key);
    ok(twin && twin.value === k.value && JSON.stringify(twin.series) === JSON.stringify(k.series), `dashboard.ops.${period}.json`, `${k.key} differs from the finance viewer's numbers`);
  }
}

for (const run of plan) run();

if (failures.length > 0) {
  console.error(`fixtures.check: ${failures.length} failure(s) in ${files.length} fixtures (${checks} checks)`);
  for (const f of failures.slice(0, 200)) console.error(`  - ${f}`);
  if (failures.length > 200) console.error(`  … and ${failures.length - 200} more`);
  process.exit(1);
}
console.log(`fixtures.check: ${files.length} fixtures OK (${checks} checks)`);
