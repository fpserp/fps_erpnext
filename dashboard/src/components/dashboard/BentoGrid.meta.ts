import type { ComponentMeta } from "./meta.types";

/**
 * Contract of BentoGrid / BentoItem (BentoGrid.tsx). Change this file and the
 * component in the same commit.
 */
export const meta = {
  component: "BentoGrid",
  file: "dashboard/src/components/dashboard/BentoGrid.tsx",
  purpose:
    "The 12-column bento layout primitive of DESIGN.md §8. BentoGrid is a size container (`@container/bento`) wrapping a CSS grid; BentoItem spans columns per breakpoint. Breakpoints are container widths: sm < 768 (base), md ≥ 768, lg ≥ 1024, xl ≥ 1440.",
  props: {
    columns: {
      type: '"12" | "auto-fit"',
      required: false,
      allowed: ["12", "auto-fit"],
      default: "12",
      notes: 'auto-fit = repeat(auto-fit, minmax(min(<minItemWidth>px, 100%), 1fr)); BentoItem spans are ignored inside it (context-aware).',
    },
    minItemWidth: {
      type: "200 | 240 | 280",
      required: false,
      allowed: [200, 240, 280],
      default: 240,
      notes: "Only for columns=\"auto-fit\". Multiples of 8.",
    },
    gridClassName: { type: "string", required: false, notes: "Classes for the inner grid element." },
    className: { type: "string", required: false, notes: "Classes for the outer container element." },
    "BentoItem.span": {
      type: "Partial<Record<'sm'|'md'|'lg'|'xl', 1..12>>",
      required: false,
      allowed: { min: 1, max: 12 },
      default: "{ sm: 12 }",
      notes: "Mobile-first: a missing breakpoint inherits the next smaller one. Classes are literal strings in SPAN_* maps; never concatenate class names.",
    },
    "BentoItem.as": {
      type: '"div" | "section" | "aside"',
      required: false,
      allowed: ["div", "section", "aside"],
      default: "div",
      notes: "Use section + aria-label when the cell is a named region (e.g. Key metrics).",
    },
  },
  variants: {
    "12": { description: "12-column grid with explicit spans.", when: "Every dashboard area and KPI counts with a hand-tuned layout (6, 8)." },
    "auto-fit": { description: "As many ≥ minItemWidth tracks as fit.", when: "KPI counts with no hand-tuned layout (1–5, 7)." },
  },
  states: ["default"],
  layout: {
    span: { sm: 12, md: 12, lg: 12, xl: 12 },
    minWidthPx: 288,
    overflow:
      "Cells are min-w-0 so wide content shrinks or scrolls inside its own card; the grid itself never scrolls horizontally. Gutters: 16px under 768px, 24px from 768px (8px grid).",
  },
  data: {
    source: "None — pure layout.",
    readOnly: true,
    permissions: "None.",
  },
  a11y: [
    "Layout only: DOM order is reading order; spans never reorder content visually.",
    "Group a region with BentoItem as=\"section\" and an aria-label rather than an unlabeled div.",
  ],
  safety: [
    "Breakpoints are CONTAINER queries on the dashboard's own width, not viewport media queries (the desk sidebar takes ~300px).",
    "Span classes must stay literal strings in the SPAN_* maps — Tailwind cannot see concatenated class names.",
    "Never put a span class on an item of an auto-fit grid (col-span-12 would create implicit columns); BentoItem enforces this via context.",
    "Spacing stays on the 8px grid: gap-4 / gap-6 only.",
  ],
} satisfies ComponentMeta;
