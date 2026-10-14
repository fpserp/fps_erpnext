import type { ComponentMeta } from "./meta.types";

/**
 * Contract of AgeingPanel (AgeingPanel.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "AgeingPanel",
  file: "dashboard/src/components/dashboard/AgeingPanel.tsx",
  purpose:
    "Receivables or payables by days past due date, as of today (FPS ACC Dashboard): header with Table toggle and 'Full report' link, Outstanding and Overdue (with its share of the total) as links, the seven buckets as single-hue horizontal bars with amount and document count printed beside each (or a real table with full figures), the top 5 parties with outstanding, overdue part, oldest overdue days and open documents — each row opens that party's open documents — and the caveat.",
  props: {
    ageing: {
      type: "Ageing (types/acc.ts)",
      required: true,
      notes: "AccPayload.ageing[n]: key 'receivables' | 'payables'; buckets always all 7 in AgeingBucketKey order, zeros included; top ≤ 5, largest first. The title is ageingTitle(label): 'Receivables' → 'Receivables ageing' (a label that already says ageing is kept).",
    },
    asOf: { type: "string (yyyy-mm-dd)", required: false, notes: "AccPayload.as_of, shown in the subtitle." },
    className: { type: "string", required: false },
  },
  variants: {
    bars: { description: "Seven 8px bars in the money role colour (--fps-violet-series), value + count at the end.", when: "Table toggle off (default)." },
    table: { description: "Days past due | Amount (full figure) | Invoices/Bills.", when: "Table toggle on." },
    empty: { description: "Zero bars and 'Nothing outstanding.'; 'No open invoices/bills.' under Top.", when: "total is 0 and no bucket holds a document." },
  },
  states: ["default", "table", "empty", "party-row hover / focus-visible", "negative bucket (no bar, value with a minus sign)"],
  layout: {
    span: { sm: 12, md: 12, lg: 6, xl: 6 },
    minWidthPx: 288,
    minHeightPx: 480,
    overflow:
      "Bucket labels sit in a fixed 72px column; bars shrink before the value text does; party names and their facts truncate (full text in title). Never scrolls horizontally; the table view scrolls inside its own focusable region if ever too narrow.",
  },
  data: {
    source: "AccPayload.ageing from fps_erpnext.api.acc_dashboard.get_dashboard (as of today, not affected by the period filter).",
    readOnly: true,
    permissions: "Accounts Manager only (server gate before any read).",
  },
  a11y: [
    "The bars are a labelled list; each item has one screen-reader sentence ('31–60 days past due: AED 12,345.00, 4 invoices.') and its visual parts are aria-hidden.",
    "Table toggle (aria-pressed) swaps in a real <table> with caption, column and row headers — the chart's accessible twin (DESIGN.md §6).",
    "Outstanding, Overdue and every party row are real links; the visible compact figure starts each accessible name.",
    "Focus ring 2px Electric Blue on every link and control.",
  ],
  safety: [
    "Do not add a write call — every number only navigates.",
    "One hue for all bars (the money role colour): the buckets are ordinal and labelled; never a per-bucket colour, a stacked 7-colour bar or a status colour without its icon and label (DESIGN.md §4).",
    "Bars: ≤ 8px thick, square at the baseline, 4px rounded data end (DESIGN.md §6).",
    "Render all 7 buckets in contract order, zeros included; at most 5 parties (MAX_AGEING_PARTIES).",
    "Never compute an ageing client-side; the only derived figure is the overdue share of the total, for display.",
  ],
} satisfies ComponentMeta;
