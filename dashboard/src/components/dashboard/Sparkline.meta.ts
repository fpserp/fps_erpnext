import type { ComponentMeta } from "./meta.types";

/**
 * Contract of Sparkline (Sparkline.tsx). Change this file and the component in
 * the same commit.
 */
export const meta = {
  component: "Sparkline",
  file: "dashboard/src/components/dashboard/Sparkline.tsx",
  purpose:
    "A KPI's period series as a tiny hand-rolled SVG line: 2px line in the metric's role colour, 18%→0% wash, 8px end dot ringed in the surface colour (hollow when the last bucket is partial), no axes. Flat-zero series render a muted baseline + 'No activity in this period'.",
  props: {
    points: {
      type: "readonly SeriesPoint[]",
      required: true,
      allowed: { min: 0, max: 30 },
      notes: "Oldest first: 7 (7d), 30 (30d) or 13 weekly points (90d).",
    },
    unit: {
      type: "Unit",
      required: true,
      allowed: ["count", "currency"],
      notes: "Picks the role colour: count → --fps-electric, currency → --fps-violet-series.",
    },
    currency: { type: "string", required: false, notes: "For the spoken summary of money values." },
    granularity: { type: "Granularity", required: true, allowed: ["day", "week"], notes: "Spoken summary noun ('7-day trend', '13-week trend')." },
    height: { type: "32 | 40 | 48", required: false, allowed: [32, 40, 48], default: 40 },
    className: { type: "string", required: false },
  },
  variants: {
    line: { description: "Line + wash + end dot.", when: "Any non-zero value." },
    "flat-zero": { description: "Muted 1px baseline and the caption 'No activity in this period'.", when: "Every value is 0." },
    empty: { description: "'No data for this period'.", when: "No points." },
  },
  states: ["complete (filled end dot)", "partial (hollow end dot)", "flat-zero", "empty"],
  layout: {
    minWidthPx: 96,
    minHeightPx: 32,
    overflow:
      "SVG stretches to the box (preserveAspectRatio=none, non-scaling 2px stroke); the end dot is an HTML overlay so it stays round, and may overhang the box edge by its radius (inside card padding).",
  },
  data: {
    source: "Kpi.series from get_dashboard.",
    readOnly: true,
    permissions: "None of its own.",
  },
  a11y: [
    "The drawing is aria-hidden; an sr-only sentence lists every value ('7-day trend: 0, 0, 2, 6, 14, 0, 0 (last day so far).').",
    "No interaction and no animation.",
  ],
  safety: [
    "Role colour only (electric for counts, violet-series for money) — never a status colour, never Soft Violet (--fps-violet).",
    "Zero-anchored: the y-range always includes 0 so a small value never looks like a spike.",
    "No axes, no gridlines, no tooltip — the card's number is the precise value.",
    "Never a hex colour; CSS variables only.",
  ],
} satisfies ComponentMeta;
