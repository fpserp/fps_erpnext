import type { ComponentMeta } from "./meta.types";

/**
 * Contract of BalanceCard (BalanceCard.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "BalanceCard",
  file: "dashboard/src/components/dashboard/BalanceCard.tsx",
  purpose:
    "One 'as of today' position on the FPS ACC Dashboard (Receivables, Payables, Cash & bank, VAT for the quarter) as a glass card: icon, label, definition tooltip, optional severity chip, a 32px value that links to the report or list behind it, 'Payable'/'Refundable' under the VAT value, up to four server-formatted context lines and the data caveat behind an amber icon. No sparkline and no delta: a position is not compared period on period and ignores the period filter.",
  props: {
    balance: {
      type: "BalanceCard (types/acc.ts)",
      required: true,
      notes: "One element of AccPayload.balances. Icon is looked up by balance.key (BALANCE_ICON), never by position.",
    },
    className: { type: "string", required: false },
  },
  variants: {
    plain: { description: "No tint.", when: "severity is absent or 'info'." },
    emphasised: {
      description: "2px top edge in the state colour (amber / rose / mint) plus a chip with icon and label ('Warning', 'Critical', 'Positive').",
      when: "severity is 'warning', 'critical' or 'positive' (e.g. overdue share ≥ 50 %, VAT due within 14 days or past due).",
    },
    vat: { description: "'Payable' / 'Refundable' / 'Nil' under the value, from its sign (positive = payable).", when: "balance.key === 'vat'." },
    caveat: { description: "Amber TriangleAlert 'Data caveat' button with tooltip.", when: "balance.caveat is set." },
  },
  states: ["default", "hover (border strengthens)", "value-link hover (underline) / focus-visible (2px Electric Blue ring)", "emphasised"],
  layout: {
    span: { sm: 12, md: 6, lg: 3, xl: 3 },
    minWidthPx: 224,
    minHeightPx: 192,
    overflow:
      "Label and value truncate (full figure in the link title and for screen readers); context labels truncate, their values never; cards stretch to the row height. Padding 16px while the bento is under 480px wide, 24px from 480px. 4 cards → sm 12 / md 6 / lg 3; any other count auto-fits ≥ 240px.",
  },
  data: {
    source: "AccPayload.balances[n] from fps_erpnext.api.acc_dashboard.get_dashboard.",
    readOnly: true,
    permissions: "Only ever rendered for Accounts Managers: the API refuses everyone else before reading anything, and the page then shows the no-access panel instead.",
  },
  a11y: [
    "The value is a real link (DeskLink): the visible compact figure starts its accessible name (WCAG 2.5.3), followed by the full figure and 'open the <label> list'.",
    "Severity is icon + text in a chip, never the tint alone; the top edge is aria-hidden decoration.",
    "Info and caveat buttons carry their full text in aria-label; hit targets ≥ 24px; focus ring 2px Electric Blue.",
    "Context values use tabular-nums; the 32px value uses proportional figures.",
  ],
  safety: [
    "Do not add a write call — the card only navigates.",
    "Render the server's context strings as sent (they are pre-formatted); at most 4 (MAX_BALANCE_CONTEXT).",
    "The value stays in ink tokens; state colours only on the chip and the 2px top edge, always with the chip's icon and label.",
    "Never compute a delta or a sparkline for a position.",
    "No count-up animation on the value.",
  ],
} satisfies ComponentMeta;
