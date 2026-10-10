import type { ComponentMeta } from "./meta.types";

/**
 * Contract of TrendChart (TrendChart.tsx, drawn with charts.tsx AreaPlot /
 * BarPlot and ChartTableView.tsx). Change this file and the components in the
 * same commit.
 */
export const meta = {
  component: "TrendChart",
  file: "dashboard/src/components/dashboard/TrendChart.tsx",
  purpose:
    "'Trends · last 12 weeks' glass card: one tab per trend mode (Pipeline / Activity / Money), Area | Bar toggle, Table toggle (accessible twin), legend, direct end-labels, partial-week note and the mode's data caveat. Weekly totals, independent of the period filter.",
  props: {
    modes: {
      type: "readonly TrendMode[]",
      required: true,
      allowed: { min: 0, max: 3 },
      notes: "payload.trend. Each mode has ONE unit and 1–4 series with fixed slots; 12 ISO weeks, the last usually partial.",
    },
    viewerFinance: { type: "boolean", required: true, notes: "payload.viewer.finance; finance modes are dropped when false." },
    defaultKind: { type: '"area" | "bar"', required: false, allowed: ["area", "bar"], default: "area" },
    className: { type: "string", required: false },
  },
  variants: {
    area: { description: "2px monotone lines, 18%→0% wash, crosshair, activeDot r=4 with 2px surface ring; last segment at 45% with a hollow end dot when the week is partial (static and on hover/keyboard — the hollow dot appears on the still-filling week only; the last complete week keeps a single filled dot).", when: "Chart type 'Area' (default)." },
    bar: { description: "Grouped (never stacked) columns ≤ 24px, 4px rounded top, 2px gap; partial week cells at 45%.", when: "Chart type 'Bar'." },
    table: { description: "ChartTableView: week rows × series columns, full figures, partial row marked 'so far'.", when: "Table toggle pressed." },
    "single-mode": { description: "No tab list; the mode label is shown as text.", when: "Exactly one visible mode." },
  },
  states: ["empty ('No trend data is available to you.')", "all-zero (note under the chart)", "partial-week", "with-caveat", "table-view"],
  layout: {
    span: { sm: 12, md: 12, lg: 8, xl: 8 },
    minWidthPx: 288,
    minHeightPx: 440,
    overflow:
      "Plot is a fixed 280px including the x-axis band (no nested scroll). X ticks thin automatically on narrow widths (interval preserveEnd: the last, still-filling week's label is always kept); the table view scrolls inside a focusable 280px region. Direct end-labels only when the plot is ≥ 480px wide. The tab list is 40px (32px tabs + 4px padding), like the other segmented controls. Under a 480px card width (@container/trend): 16px padding and tab labels that shrink and truncate (full label in title) instead of overflowing.",
  },
  data: {
    source: "payload.trend from fps_erpnext.api.command_center.get_dashboard.",
    readOnly: true,
    permissions: "The Money mode (finance: true) is only sent to finance viewers and is also filtered client-side.",
  },
  a11y: [
    "Tabs, chart-type toggle group and Table toggle are keyboard operable (Radix: arrow keys within groups, aria-pressed / aria-selected).",
    "The plot is focusable (Recharts accessibilityLayer) and shows a 2px Electric Blue focus ring on keyboard focus (focus-visible; none for pointer focus, system outline under forced-colors): arrow keys move the same tooltip the pointer shows, and after re-focusing the plot an arrow key or Enter brings it back; the SVG has <title> and <desc>.",
    "Tooltip: value first (strong, tabular), series label second, colour line-key — and every value is also in the table view (tooltips never gate). The tooltip is raised glass with the theme's solid fallbacks.",
    "Legend for ≥ 2 series (line keys for area, swatches for bars); a single surviving series is named in plain ink text in the legend's place and in the plot title and table caption ('Operations · Cleared'); text in ink tokens.",
    "Axis ticks 12px --fps-text-muted (4.7:1) with tabular figures; gridlines decorative.",
  ],
  safety: [
    "Do not add a write call.",
    "Series colour is keyed by series key → server slot (slot 1 --fps-electric, 2 --fps-violet-series, 3 --fps-cyan, 4 --fps-amber-series); never by index in a filtered list.",
    "Max 4 series; a 5th+ folds into 'Other' (--fps-series-other). Never generate a hue.",
    "No dual axis: one y-axis per plot; different units live in different tabs.",
    "Value text never uses the series colour — labels, values and legends use ink tokens.",
    "Money only when finance: never show the Money mode to a non-finance viewer.",
    "Gridlines solid 1px --fps-grid, horizontal only; never dashed.",
    "No pie/donut, no stacked bars, no chart animation (polls re-render every minute).",
  ],
} satisfies ComponentMeta;
