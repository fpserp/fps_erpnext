import type { ComponentMeta } from "./meta.types";

/**
 * Contract of DeltaBadge (DeltaBadge.tsx). Change this file and the component
 * in the same commit.
 */
export const meta = {
  component: "DeltaBadge",
  file: "dashboard/src/components/dashboard/DeltaBadge.tsx",
  purpose:
    "Period-over-period change as a status chip (arrow icon + signed percentage) followed by the muted compare label, coloured by DESIGN.md §4 delta semantics: direction × whether up is good for this metric.",
  props: {
    deltaPct: { type: "number | null", required: true, notes: "API delta_pct (1 dp). null when there is no comparable base (previous null, 0 or negative)." },
    value: { type: "number", required: true, notes: "Current total; with previous 0 or negative and value > 0 → 'new'; otherwise a null delta → '—'." },
    previous: {
      type: "number | null",
      required: true,
      notes: "API previous. null = the source does not reach back (not comparable) → muted '—' spoken 'No earlier data to compare with.' — never 'new'.",
    },
    goodDirection: { type: "GoodDirection", required: true, allowed: ["up", "down", "none"] },
    compareLabel: { type: "string", required: false, notes: "e.g. 'vs previous 7 days'; omitted for 'new' and '—'." },
    size: { type: '"sm" | "md"', required: false, allowed: ["sm", "md"], default: "sm", notes: "sm on cards (12px), md in the drawer header (13px)." },
    hideCompare: { type: "boolean", required: false, default: false, notes: "Hides the visible compare text; the spoken sentence keeps it." },
    className: { type: "string", required: false },
  },
  variants: {
    good: { description: "Mint chip, ArrowUpRight or ArrowDownRight.", when: "up with goodDirection 'up', or down with 'down'." },
    bad: { description: "Rose chip.", when: "down with goodDirection 'up', or up with 'down'." },
    neutral: { description: "Muted chip.", when: "goodDirection 'none', a change that rounds to 0.0% (Minus icon), 'new', or '—'." },
  },
  states: [
    "up",
    "down",
    "flat ('0.0%' with Minus icon; spoken 'No change…')",
    "new (previous 0 or negative, value > 0)",
    "none ('—': previous null = no earlier data; or no activity in either period; or not comparable)",
  ],
  layout: {
    minWidthPx: 48,
    overflow: "The chip never wraps (nowrap); the compare label wraps onto the next line under the chip when space runs out.",
  },
  data: {
    source: "Kpi / MetricDetail fields delta_pct, value, good_direction, compare_label.",
    readOnly: true,
    permissions: "None of its own; renders what the caller passes.",
  },
  a11y: [
    "Direction is carried by the arrow icon and the sign, never by colour alone.",
    "The visible chip is aria-hidden; an sr-only sentence says 'Up 12.4% compared with previous 7 days, favourable' (or 'No change…', 'New this period; none in the previous period.', 'No earlier data to compare with.', 'No activity in either period.', 'Not comparable with the previous period.').",
    "Status-token text (--fps-mint / --fps-rose) clears 4.5:1 on the darkest glass; neutral uses ink-secondary.",
    "Percentages use tabular figures and the real minus sign U+2212 (formatDelta).",
  ],
  safety: [
    "Never compute a percentage against a zero or negative base (the API sends null for both): a null delta renders 'new' (value > 0) or '—', never ±∞%.",
    "'new' is only for a base of nothing (previous 0 or negative). previous null means the source has no earlier data — render '—' and say so; never call that 'new' (DESIGN.md §4).",
    "Colour = direction × good_direction of THIS metric; never colour by sign alone.",
    "Status colours (mint/rose) are reserved for state; never reuse them as chart series colours.",
    "Do not format the delta yourself — use formatDelta (1 dp, U+2212).",
  ],
} satisfies ComponentMeta;
