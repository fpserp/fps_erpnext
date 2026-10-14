import type { ComponentMeta } from "./meta.types";

/**
 * Contract of the FPS ACC Dashboard root (AccDashboard.tsx). Change this file
 * and the component in the same commit.
 */
export const meta = {
  component: "AccDashboard",
  file: "dashboard/src/components/dashboard/AccDashboard.tsx",
  purpose:
    "Root of the FPS ACC Dashboard (default export, rendered by main.tsx for mount variant 'acc' in the FPS ACC Overview block on Workspace 'FPS ACC'). Owns the period filter and the open drawer, loads AccPayload, and lays out header, InsightBanner, filter row, 4 KPI cards, 4 balance cards, TrendChart (Billing / Cash flow) beside BankStatusCard, and the receivables and payables AgeingPanels on the bento. The header links back to the FPS OPS Dashboard ('Open the FPS OPS Dashboard'). Shows the no-access panel when the API refuses the viewer.",
  props: {},
  variants: {
    ready: { description: "The full bento.", when: "A payload arrived." },
    noAccess: {
      description: "Calm panel: 'You do not have access to the FPS ACC Dashboard.' with a link to the FPS OPS Dashboard. No number of any kind.",
      when: "get_dashboard answered PermissionError (viewer is not an Accounts Manager).",
    },
  },
  states: [
    "first-load (skeleton in the final layout: 4 KPI placeholders, 4 balance placeholders, trend + banks, 2 ageing panels)",
    "no-access (PermissionError: payload and cached ACC numbers dropped, automatic polls stopped, drawer closed)",
    "error-without-data (inline error + Retry)",
    "ready",
    "refetching after period change or manual refresh (frame at 60% opacity, aria-busy)",
    "background poll (full strength, header refresh icon spins)",
    "stale (no successful fetch for 3 poll intervals: amber 'Stale' dot)",
    "drawer-open",
  ],
  layout: {
    span: { sm: 12, md: 12, lg: 12, xl: 12 },
    minWidthPx: 320,
    overflow:
      "Same frame as CommandCenter (DashboardFrame): rounded-2xl bg-plane, NO overflow-hidden (chart tooltips), 16px padding under a 768px container, 24px above. KPI and balance rows: 4 → sm 12 / md 6 / lg 3, other counts auto-fit. Trend lg 8 + banks lg 4; ageing lg 6 + 6; everything sm 12. Never scrolls horizontally.",
  },
  data: {
    source:
      "useAccDashboard(period) → fps_erpnext.api.acc_dashboard.get_dashboard (GET, whitelisted, read-only, Accounts Manager only). Drawer: useMetricDetail (variant 'acc' from context) → acc_dashboard.get_metric_detail. Period preference: localStorage key 'fps-acc:period:v1' (try/catch; per-viewer convenience only, separate from the OPS key).",
    readOnly: true,
    permissions:
      "Workspace 'FPS ACC' is limited to Accounts Manager and every API method checks the role before reading anything. A PermissionError renders the no-access panel; the UI never shows a cached ACC number after a refusal.",
  },
  a11y: [
    "One h2 ('FPS ACC Dashboard'); every card heading is an h3.",
    "The KPI row is a section labelled 'Money in and out for the period'; the balance row is a section labelled by its visible 'Position as of …' line.",
    "Refresh is an icon button with aria-label 'Refresh dashboard'; live status is icon + text and not a live region.",
    "The period summary is aria-live=polite; the no-access panel is role=status (calm, not an alert).",
    "All motion stops under prefers-reduced-motion; glows are removed under reduced transparency and forced colours.",
  ],
  safety: [
    "Do not add a write call. Data comes only from the two whitelisted acc_dashboard read methods via hooks/useDashboard.",
    "Interactions may only navigate, open the read-only drawer, or open a BLANK new form (newDoc) the user saves themselves.",
    "On PermissionError show the no-access panel and nothing else — never a number, never a cached payload.",
    "Keep the frame on refetch (60% opacity) — never swap back to the skeleton once data has been shown.",
    "No count-up or animated numbers.",
    "Colours come from theme tokens only — no hex in components; both palettes (Pearl, Matte Black) come from the same tokens.",
  ],
} satisfies ComponentMeta;
