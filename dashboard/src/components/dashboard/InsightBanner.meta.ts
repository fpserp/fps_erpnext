import type { ComponentMeta } from "./meta.types";

/**
 * Contract of InsightBanner (InsightBanner.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "InsightBanner",
  file: "dashboard/src/components/dashboard/InsightBanner.tsx",
  purpose:
    "The 'Auto-insights' glass widget: rule-based anomaly checks from the API, the most severe shown large with severity icon + label, paging (prev/next, 'n of N', dots) and a 'Show all' list. Violet AI accent and a 1px animated gradient border shimmer.",
  props: {
    insights: {
      type: "readonly Insight[]",
      required: true,
      allowed: { min: 0, max: 6 },
      notes: "payload.insights, most severe first. Stable `id` per insight; position is kept by id across polls.",
    },
    updatedAt: { type: "Date | null", required: true, notes: "Shown as 'rule-based · updated 14:32'." },
    onOpenMetric: { type: "(key: KpiKey) => void", required: true, notes: "Opens the ActionDrawer for insights with metric_key." },
    canOpenMetric: {
      type: "(key: KpiKey) => boolean",
      required: true,
      notes: "False when the viewer does not have that KPI; the insight then falls back to its route (or stays static).",
    },
    className: { type: "string", required: false },
  },
  variants: {
    empty: { description: "'All clear — no anomalies in the data right now.' with a mint check icon.", when: "insights is empty." },
    single: { description: "One insight, no paging controls.", when: "insights.length === 1." },
    paged: { description: "Prev/next, 'n of N', dot indicators and 'Show all'.", when: "insights.length > 1." },
    expanded: { description: "Featured insight plus an ordered list of all insights.", when: "'Show all' toggled on (aria-expanded)." },
  },
  states: ["empty", "featured", "expanded", "shimmer-running", "shimmer-paused (prefers-reduced-motion)"],
  layout: {
    span: { sm: 12, md: 12, lg: 12, xl: 12 },
    minWidthPx: 288,
    minHeightPx: 136,
    overflow:
      "Insight titles and details wrap (detail capped at 72ch, long tokens break); never truncated. Below a 480px banner width (container query @container/insight): 16px padding, the 'rule-based · updated' line stacks under the title and truncates with its full text in title, and the pager controls (prev, n of N, next, Show all) take their own full-width row. 24px padding and one header row from 480px.",
  },
  data: {
    source: "payload.insights from fps_erpnext.api.command_center.get_dashboard (rule-based, computed server-side).",
    readOnly: true,
    permissions: "The server only emits insights over data the viewer may read; a metric_key the viewer lacks is degraded to its route.",
  },
  a11y: [
    "Severity is always icon + label (Critical CircleAlert rose, Warning TriangleAlert amber, Positive TrendingUp mint, Info Info electric-ui) — never colour alone.",
    "Prev/next and dot buttons have aria-labels; the active dot has aria-current; dots have 24px hit targets.",
    "'Show all' is a disclosure: aria-expanded + aria-controls.",
    "The featured insight is aria-live=polite/aria-atomic and starts with 'Insight n of N'.",
    "Insights with metric_key are buttons; with route are links (new-tab capable); otherwise plain text.",
    "Shimmer is aria-hidden, paused under prefers-reduced-motion, hidden under forced-colors, and skipped where mask-composite is unsupported.",
  ],
  safety: [
    "Do not add a write call — actions only open the read-only drawer or navigate.",
    "Label it 'rule-based': these are deterministic checks, never present them as model output.",
    "Soft Violet (--fps-violet) is a UI accent only here; never reuse it as a chart series colour.",
    "Keep insight position by id, not index, so polls never jump the reader to another insight.",
    "Plain text only: title and detail are rendered as text, never as HTML.",
    "Colours via tokens only; the mask uses named black (alpha only), no hex.",
  ],
} satisfies ComponentMeta;
