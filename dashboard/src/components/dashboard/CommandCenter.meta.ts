import type { ComponentMeta } from "./meta.types";

/**
 * Contract of the dashboard root (CommandCenter.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "CommandCenter",
  file: "dashboard/src/components/dashboard/CommandCenter.tsx",
  purpose:
    "Root of the FPS Command Center (default export, rendered by main.tsx in the <fps-command-center> element's own shadow root inside the FPS Overview Custom HTML Block). Owns the period filter and the open drawer, loads the payload, and lays out header, InsightBanner, filter row, KPI cards, TrendChart and StageStrip on the bento.",
  props: {},
  variants: {
    finance: { description: "8 KPIs (adds Invoiced, Collected) and a Money trend tab.", when: "payload.viewer.finance is true (Accounts User / Accounts Manager / System Manager)." },
    operations: { description: "6 KPIs, Pipeline + Activity trend tabs only.", when: "payload.viewer.finance is false." },
  },
  states: [
    "first-load (skeleton in the final layout's shapes: 8 KPI placeholders for finance roles, 6 otherwise — decided from the desk roles (hasRole, mirrors the API's FINANCE_ROLES) before the fetch, so the cards do not reflow when the payload lands)",
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
      "Root is rounded-2xl bg-plane (it must look right even where the desk around it is not themed) and has NO overflow-hidden, so nothing clips the charts' in-chart tooltips; the ambient glow clips itself. 16px padding under a 768px container width, 24px above. Never scrolls horizontally; the drawer and tooltips portal to the body-level <fps-cc-portal> host and close when the route leaves the workspace.",
  },
  data: {
    source:
      "useDashboard(period) → fps_erpnext.api.command_center.get_dashboard (GET, whitelisted, read-only). Drawer: useMetricDetail → get_metric_detail. Period preference: localStorage key 'fps-cc:period:v1' (try/catch; per-viewer convenience only).",
    readOnly: true,
    permissions:
      "The API returns only what the viewer may read: money KPIs and the Money trend only for finance roles, stage tiles only for readable doctypes. The UI renders whatever subset arrives and additionally drops finance KPIs/modes when viewer.finance is false.",
  },
  a11y: [
    "One h2 ('Command Center'); every card heading is an h3.",
    "Refresh is an icon button with aria-label 'Refresh dashboard'.",
    "Live status is icon + text ('Live' / 'Stale' · 'Updated 09:30'), never colour alone, and is NOT a live region (it changes every minute).",
    "The period summary next to the filter is aria-live=polite so a period change is announced.",
    "Ambient glows are aria-hidden and removed under prefers-reduced-transparency and forced-colors.",
    "All motion (ping, spinner, transitions) stops under prefers-reduced-motion.",
  ],
  safety: [
    "Do not add a write call. Data comes only from the two whitelisted read methods via hooks/useDashboard.",
    "Interactions may only navigate (navigate/deskHref), open the read-only drawer, or open a BLANK new form (newDoc) the user saves themselves.",
    "Money only when finance: never render a finance KPI or trend mode for a non-finance viewer.",
    "Keep the frame on refetch (60% opacity) — never swap back to the skeleton once data has been shown.",
    "No count-up or animated numbers: a number must be correct in every frame.",
    "Default period is 7d; the stored preference must be validated with isPeriod before use.",
    "Colours come from theme tokens (var(--fps-…) / token utilities) only — no hex in components.",
  ],
} satisfies ComponentMeta;
