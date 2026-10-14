import type { ComponentMeta } from "./meta.types";

/**
 * Contract of ActionDrawer (ActionDrawer.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "ActionDrawer",
  file: "dashboard/src/components/dashboard/ActionDrawer.tsx",
  purpose:
    "The contextual drill-down for one KPI: a right-side Sheet (min(480px, 100vw), raised glass) with header (icon, label, full value, DeltaBadge, period text), a one-row filter bar (Period + dimension chips), an area chart of the detail series with a Table toggle, a breakdown as horizontal bars, the latest ≤ 8 records and quick actions.",
  props: {
    state: {
      type: "DrawerState | null",
      required: true,
      notes: "{ key: KpiKey, period: Period, dimension: string | null }; null = closed. Owned by CommandCenter.",
    },
    kpi: { type: "Kpi | null", required: true, notes: "The KPI summary from the dashboard: instant header while the detail loads (same period, 'All' only)." },
    dashboardPeriod: { type: "Period", required: true, allowed: ["7d", "30d", "90d"], notes: "payload.period — the period `kpi` was computed for." },
    onChange: { type: "(next: DrawerState) => void", required: true, notes: "Period or dimension chip changed." },
    onClose: { type: "() => void", required: true, notes: "Escape, overlay click, Close, or after a navigation/quick action." },
  },
  variants: {
    "with-dimension": { description: "Chips 'All' + dimension_options in the filter row.", when: "detail.dimension_label is set and dimension_options is non-empty." },
    "with-breakdown": { description: "Horizontal single-hue bars with value labels at the bar tip.", when: "detail.breakdown has rows." },
    money: { description: "Violet-series chart and bars, full AED figures, Finance chip.", when: "detail.unit === 'currency' (the FPS ACC KPIs; Accounts Managers only)." },
  },
  states: [
    "closed",
    "first-load (skeleton)",
    "ready",
    "refetching (previous content at 60% opacity, aria-busy)",
    "error (inline alert + Retry)",
    "closing (last content kept during the 200ms exit)",
  ],
  layout: {
    minWidthPx: 320,
    maxWidthPx: 480,
    overflow:
      "Header, filter bar and footer are fixed; the body scrolls (overscroll-contain). Dimension chips scroll horizontally inside their own strip so the filter bar stays one row. Record titles truncate; values and dates never do; breakdown value labels are never clipped (the bar shrinks first).",
  },
  data: {
    source: "useMetricDetail(key, period, dimension) → get_metric_detail of the dashboard variant in context (lib/variant.tsx): fps_erpnext.api.command_center.get_metric_detail on FPS OPS, fps_erpnext.api.acc_dashboard.get_metric_detail on FPS ACC (GET, whitelisted, read-only). Caches never mix between the two.",
    readOnly: true,
    permissions:
      "The API checks read permission per metric. The OPS API rejects the money metrics for everyone; the ACC API answers Accounts Managers only (a refusal shows 'You do not have access to these details.'). CommandCenter / AccDashboard only open the drawer for KPIs present in the viewer's payload.",
  },
  a11y: [
    "Shadow-safe Sheet: aria-modal, focus trapped (Tab/Shift+Tab wrap), first focus on the 32px 'Close details' button, Escape and overlay click close, focus returns to the card that opened it.",
    "SheetTitle = metric label; SheetDescription = the KPI definition.",
    "Period and dimension chips are single-select toggle groups (arrow keys), never empty; names keep the visible text first.",
    "Chart is focusable (2px Electric Blue ring on keyboard focus) with keyboard tooltips — arrow keys move it, and after re-focusing the plot an arrow key or Enter brings it back — and has a Table twin; breakdown values are text, bars aria-hidden.",
    "Record rows and the 'Open list' action are links (new-tab capable); body is aria-busy while loading.",
    "Slide is 200ms cubic-bezier(.2,.8,.2,1) and is removed under prefers-reduced-motion.",
  ],
  safety: [
    "Do not add a write call. The drawer only reads get_metric_detail and navigates.",
    "Quick actions: kind 'route' → navigate; kind 'new_doc' → newDoc(doctype), which opens a BLANK unsaved form the user saves themselves. Never pre-fill or save anything. Close the drawer BEFORE navigate()/newDoc() (the desk only hides the page).",
    "A record's value is always MONEY (DrillRecord.value): format it with formatMoney, never with the metric's unit (a Quotations record carries the quotation total for finance viewers).",
    "Single series → no legend; the section heading names it ('New jobs per day').",
    "Series colour by role (--fps-electric counts, --fps-violet-series money); value text never uses the series colour.",
    "Max 8 records (MAX_RECORDS), newest first as sent.",
    "Money only when finance — never open a finance metric for a non-finance viewer.",
    "Render through the body-level portal host (usePortalContainer, patched sheet.tsx), never inside a glass card (backdrop-filter traps position:fixed) or the block (EditorJS's z-index 1 stacking context keeps it under the desk navbar/sidebar).",
    "Close on route leave (the Sheet listens to useDismissSignal): the portal host lives outside the page the desk hides.",
  ],
} satisfies ComponentMeta;
