import type { ComponentMeta } from "./meta.types";

/**
 * Contract of MetricCard (MetricCard.tsx). Change this file and the component
 * in the same commit.
 */
export const meta = {
  component: "MetricCard",
  file: "dashboard/src/components/dashboard/MetricCard.tsx",
  purpose:
    "One KPI as a high-density glass card: icon, label, definition tooltip, Finance chip (money KPIs), deep-dive button, 32px value (compact; full figure on hover and for screen readers), DeltaBadge with compare label, Sparkline of the period series, up to two context facts, and the data caveat behind an amber icon. The whole card opens the ActionDrawer.",
  props: {
    kpi: {
      type: "Kpi",
      required: true,
      notes: "One element of payload.kpis. Icon is looked up by kpi.key (KPI_ICON), never by position.",
    },
    compareLabel: { type: "string", required: true, notes: "payload.compare_label, e.g. 'vs previous 7 days'." },
    onOpen: { type: "(key: KpiKey) => void", required: true, notes: "Opens the drawer; CommandCenter owns the drawer state." },
    className: { type: "string", required: false },
  },
  variants: {
    count: { description: "Electric Blue sparkline; value formatted as a count ('1,284', '12.9K').", when: "kpi.unit === 'count'." },
    money: { description: "Violet-series sparkline, 'AED 12.9K' value and a 'Finance' chip.", when: "kpi.unit === 'currency' (finance viewers only)." },
    caveat: { description: "Amber TriangleAlert 'Data caveat' button with tooltip.", when: "kpi.caveat is set." },
  },
  states: ["default", "hover (border strengthens)", "focus-visible (2px Electric Blue outline, 2px offset, around the whole card)", "no-activity (flat-zero sparkline caption)"],
  layout: {
    span: { sm: 12, md: 6, lg: 4, xl: 2 },
    minWidthPx: 224,
    minHeightPx: 224,
    overflow:
      "Label and value truncate with ellipsis (full text in title; the value also as sr-only text); context labels truncate (full text in title), values never; cards stretch to the row height. Padding 16px while the bento is under 480px wide, 24px from 480px. Spans per count: 8 KPIs → sm 12 / md 6 / lg 3; 6 KPIs → sm 12 / md 6 / lg 4 / xl 2; other counts auto-fit ≥ 240px.",
  },
  data: {
    source: "payload.kpis[n] from fps_erpnext.api.command_center.get_dashboard.",
    readOnly: true,
    permissions: "Money KPIs (finance: true) are only sent to, and only rendered for, finance viewers.",
  },
  a11y: [
    "The deep-dive button (PanelRightOpen, aria-label 'Open <label> details') is the card's single keyboard/AT activation point — a native button, so Enter and Space work.",
    "A pointer click anywhere on the card opens the drawer too, after moving focus to that button so focus returns to the card when the drawer closes.",
    "No interactive element is nested inside another (the info and caveat tooltips are their own buttons) — that is why the card itself is not a role=button.",
    "The open button is aria-describedby the full value and the delta sentence ('Up 12.4% compared with previous 7 days, favourable').",
    "Info and caveat buttons carry their full text in aria-label; hit targets ≥ 24px.",
    "Value uses proportional figures (no tabular-nums at 32px); context values use tabular-nums.",
  ],
  safety: [
    "Do not add a write call — the card only opens the read-only drawer.",
    "Value text never uses a series colour: ink tokens only; identity colour lives in the sparkline and icon tile.",
    "Money only when finance: never render a finance KPI for a non-finance viewer (CommandCenter filters, the API omits).",
    "No count-up animation on the value.",
    "At most 2 context lines (kpi.context.slice(0, 2)).",
    "Never compute a delta client-side; DeltaBadge renders the API's delta_pct and previous (previous null → '—' 'No earlier data'; null delta → 'new' only when value > 0 against a zero or negative base, otherwise '—').",
  ],
} satisfies ComponentMeta;
