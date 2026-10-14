import type { ComponentMeta } from "./meta.types";

/**
 * Contract of BankStatusCard (BankStatusCard.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "BankStatusCard",
  file: "dashboard/src/components/dashboard/BankStatusCard.tsx",
  purpose:
    "'Bank statements' glass card on the FPS ACC Dashboard: one link row per bank / card account (ADCB, WIO, Qashio – General, Qashio – Government) with the latest statement month, its reconciliation status (icon + text chip), the closing balance and how many months the statements are behind; the header counts the accounts that are up to date.",
  props: {
    banks: {
      type: "BankStatus[] (types/acc.ts)",
      required: true,
      notes: "AccPayload.banks in server order. Render every row as sent; never invent an account.",
    },
    currency: { type: "string", required: false, notes: "Company currency for the closing balances (AED)." },
    className: { type: "string", required: false },
  },
  variants: {
    reconciled: { description: "Mint CircleCheck 'Reconciled' chip.", when: "status === 'Reconciled'." },
    inProgress: { description: "Amber Clock 'In progress' chip.", when: "status === 'In Progress'." },
    missing: { description: "Rose CircleDashed 'Missing' chip; 'No statement on file'.", when: "status === 'Missing' (latest_month and closing_balance null)." },
    behind: {
      description: "Amber Clock + 'N months behind' instead of muted 'Up to date', and a third line 'Not reconciled: <open_months>' (server text, e.g. 'Jul missing, Aug in progress').",
      when: "months_behind ≥ 1 (open_months is sent with it).",
    },
    empty: { description: "'No bank or card accounts are tracked.'", when: "banks is empty." },
  },
  states: ["default", "row-hover", "row-focus-visible", "empty"],
  layout: {
    span: { sm: 12, md: 12, lg: 4, xl: 4 },
    minWidthPx: 288,
    minHeightPx: 320,
    overflow: "Label and detail line truncate (full text in title); the status chip and 'behind' text never wrap. Rows never scroll horizontally.",
  },
  data: {
    source: "AccPayload.banks (FPS Bank Statement, latest per bank code) from fps_erpnext.api.acc_dashboard.get_dashboard.",
    readOnly: true,
    permissions: "Accounts Manager only (server gate before any read).",
  },
  a11y: [
    "Each row is a real link whose name starts with the visible account label, then status, latest month, closing balance and how far behind.",
    "Status is a chip with icon + text; 'behind' is icon + text: never colour alone.",
    "Chevron is aria-hidden; focus ring 2px Electric Blue.",
  ],
  safety: [
    "Do not add a write call — rows only navigate.",
    "Mint / amber / rose are state colours only, always with their icon and label.",
    "Never compute months_behind or open_months client-side; show the server's number and text.",
  ],
} satisfies ComponentMeta;
