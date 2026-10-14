import type { ComponentMeta } from "./meta.types";

/**
 * Contract of the dashboard root (CommandCenter.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "CommandCenter",
  file: "dashboard/src/components/dashboard/CommandCenter.tsx",
  purpose:
    "Root of the FPS OPS Dashboard, formerly 'Command Center' (default export, rendered by main.tsx for mount variant 'ops' in the <fps-command-center> element's own shadow root inside the FPS Overview Custom HTML Block on FPS Home). Open to every desk user; no money (invoices and collections moved to the FPS ACC Dashboard, AccDashboard.tsx). Owns the period filter and the open drawer, loads the payload, and lays out header, InsightBanner, filter row, KPI cards, TrendChart and StageStrip on the bento.",
  props: {},
  variants: {
    operations: {
      description: "6 KPIs, Sales pipeline + Operations trend tabs, stage strip without the Invoices tile.",
      when: "Always: since 14 Oct 2026 the OPS API sends viewer.finance = false and no money to every viewer, finance roles included.",
    },
    accLink: {
      description: "Header link 'Open the FPS ACC Dashboard' (/desk/fps-acc) under the subtitle.",
      when: "hasRole('Accounts Manager') (Administrator holds every role). The live Frappe 16.51 sidebar is the site-owned 'Sidebar' record, so the shipped sidebar file does not add an FPS ACC row; this link is how its holders reach the page. No money: the ACC API gate still refuses everyone else.",
    },
  },
  states: [
    "first-load (skeleton in the final layout's shapes: always 6 KPI placeholders — the OPS page has no money KPIs for anyone — so the cards do not reflow when the payload lands)",
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
      "The API returns only what the viewer may read: no money for anyone (viewer.finance is always false), stage tiles only for readable doctypes (and never the Invoices tile). The UI renders whatever subset arrives and additionally drops finance KPIs/modes because viewer.finance is false.",
  },
  a11y: [
    "One h2 ('FPS OPS Dashboard'); every card heading is an h3.",
    "Refresh is an icon button with aria-label 'Refresh dashboard'.",
    "The FPS ACC link is a real <a href> (DeskLink) with visible text; its arrow icon is aria-hidden.",
    "Live status is icon + text ('Live' / 'Stale' · 'Updated 09:30'), never colour alone, and is NOT a live region (it changes every minute).",
    "The period summary next to the filter is aria-live=polite so a period change is announced.",
    "Ambient glows are aria-hidden and removed under prefers-reduced-transparency and forced-colors.",
    "All motion (ping, spinner, transitions) stops under prefers-reduced-motion.",
  ],
  safety: [
    "Do not add a write call. Data comes only from the two whitelisted read methods via hooks/useDashboard.",
    "Interactions may only navigate (navigate/deskHref), open the read-only drawer, or open a BLANK new form (newDoc) the user saves themselves.",
    "No money on this page: never render a finance KPI or trend mode (viewer.finance is false for everyone; the ACC page has them).",
    "Keep the frame on refetch (60% opacity) — never swap back to the skeleton once data has been shown.",
    "No count-up or animated numbers: a number must be correct in every frame.",
    "Default period is 7d; the stored preference must be validated with isPeriod before use.",
    "Colours come from theme tokens (var(--fps-…) / token utilities) only — no hex in components.",
  ],
} satisfies ComponentMeta;
