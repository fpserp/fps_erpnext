/**
 * BentoGrid — the 12-column layout primitive of DESIGN.md §8.
 *
 * Breakpoints are CONTAINER queries on the grid's own width, not viewport
 * media queries. The dashboard lives inside the ERPNext desk, whose sidebar
 * and page padding take 300+ px; on a 1440 px screen the dashboard itself is
 * ~1100 px wide. Measuring the viewport would put six KPI cards in a row on a
 * width that only fits four. The thresholds are DESIGN.md's:
 *   sm  < 768   (base)      md  ≥ 768      lg  ≥ 1024      xl  ≥ 1440
 *
 * Every class below is written out literally because Tailwind only generates
 * utilities it can find as complete strings in the source; never build these
 * class names with string concatenation.
 *
 * Gutters stay on the 8px grid: 16px under md, 24px from md up.
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import type { Breakpoint } from "./meta.types";

export type ColumnSpan = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;

/** Column span per breakpoint. Missing breakpoints inherit the next smaller one (mobile-first). */
export type ResponsiveSpan = Partial<Record<Breakpoint, ColumnSpan>>;

const SPAN_SM: Readonly<Record<ColumnSpan, string>> = {
  1: "col-span-1",
  2: "col-span-2",
  3: "col-span-3",
  4: "col-span-4",
  5: "col-span-5",
  6: "col-span-6",
  7: "col-span-7",
  8: "col-span-8",
  9: "col-span-9",
  10: "col-span-10",
  11: "col-span-11",
  12: "col-span-12",
};

const SPAN_MD: Readonly<Record<ColumnSpan, string>> = {
  1: "@min-[768px]/bento:col-span-1",
  2: "@min-[768px]/bento:col-span-2",
  3: "@min-[768px]/bento:col-span-3",
  4: "@min-[768px]/bento:col-span-4",
  5: "@min-[768px]/bento:col-span-5",
  6: "@min-[768px]/bento:col-span-6",
  7: "@min-[768px]/bento:col-span-7",
  8: "@min-[768px]/bento:col-span-8",
  9: "@min-[768px]/bento:col-span-9",
  10: "@min-[768px]/bento:col-span-10",
  11: "@min-[768px]/bento:col-span-11",
  12: "@min-[768px]/bento:col-span-12",
};

const SPAN_LG: Readonly<Record<ColumnSpan, string>> = {
  1: "@min-[1024px]/bento:col-span-1",
  2: "@min-[1024px]/bento:col-span-2",
  3: "@min-[1024px]/bento:col-span-3",
  4: "@min-[1024px]/bento:col-span-4",
  5: "@min-[1024px]/bento:col-span-5",
  6: "@min-[1024px]/bento:col-span-6",
  7: "@min-[1024px]/bento:col-span-7",
  8: "@min-[1024px]/bento:col-span-8",
  9: "@min-[1024px]/bento:col-span-9",
  10: "@min-[1024px]/bento:col-span-10",
  11: "@min-[1024px]/bento:col-span-11",
  12: "@min-[1024px]/bento:col-span-12",
};

const SPAN_XL: Readonly<Record<ColumnSpan, string>> = {
  1: "@min-[1440px]/bento:col-span-1",
  2: "@min-[1440px]/bento:col-span-2",
  3: "@min-[1440px]/bento:col-span-3",
  4: "@min-[1440px]/bento:col-span-4",
  5: "@min-[1440px]/bento:col-span-5",
  6: "@min-[1440px]/bento:col-span-6",
  7: "@min-[1440px]/bento:col-span-7",
  8: "@min-[1440px]/bento:col-span-8",
  9: "@min-[1440px]/bento:col-span-9",
  10: "@min-[1440px]/bento:col-span-10",
  11: "@min-[1440px]/bento:col-span-11",
  12: "@min-[1440px]/bento:col-span-12",
};

/** The class list for a responsive span (exported for skeletons that mirror the layout). */
export function spanClasses(span: ResponsiveSpan | undefined): string {
  const s = span ?? {};
  return cn(
    SPAN_SM[s.sm ?? 12],
    s.md !== undefined && SPAN_MD[s.md],
    s.lg !== undefined && SPAN_LG[s.lg],
    s.xl !== undefined && SPAN_XL[s.xl],
  );
}

export type BentoColumns = "12" | "auto-fit";

export interface BentoGridProps extends React.ComponentProps<"div"> {
  /**
   * "12" (default): the 12-column grid; children are BentoItems with spans.
   * "auto-fit": as many ≥ 240px columns as fit (used when the KPI count has no
   * hand-tuned layout); BentoItem spans are ignored by this grid.
   */
  columns?: BentoColumns;
  /** Minimum track width for columns="auto-fit". Multiple of 8. */
  minItemWidth?: 200 | 240 | 280;
  /** Extra classes for the inner grid element (the outer element is the size container). */
  gridClassName?: string;
}

const AUTO_FIT: Readonly<Record<NonNullable<BentoGridProps["minItemWidth"]>, string>> = {
  200: "grid-cols-[repeat(auto-fit,minmax(min(200px,100%),1fr))]",
  240: "grid-cols-[repeat(auto-fit,minmax(min(240px,100%),1fr))]",
  280: "grid-cols-[repeat(auto-fit,minmax(min(280px,100%),1fr))]",
};

/**
 * Items need to know their grid's mode: a span class inside an auto-fit grid
 * (col-span-12 by default) would create eleven implicit columns.
 */
const BentoColumnsContext = React.createContext<BentoColumns>("12");

/**
 * Two elements on purpose: the outer one is the query container (`bento`) and
 * the inner one is the grid. An element cannot container-query itself, and
 * the gutter has to respond to the width too.
 */
export function BentoGrid({
  columns = "12",
  minItemWidth = 240,
  className,
  gridClassName,
  children,
  ...rest
}: BentoGridProps): React.JSX.Element {
  return (
    <div data-slot="bento" className={cn("@container/bento min-w-0", className)} {...rest}>
      <div
        className={cn(
          "grid gap-4 @min-[768px]/bento:gap-6",
          columns === "12" ? "grid-cols-12" : AUTO_FIT[minItemWidth],
          gridClassName,
        )}
      >
        <BentoColumnsContext value={columns}>{children}</BentoColumnsContext>
      </div>
    </div>
  );
}

export interface BentoItemProps extends Omit<React.ComponentProps<"div">, "ref"> {
  /** Columns spanned per breakpoint; default { sm: 12 } (full width everywhere). */
  span?: ResponsiveSpan;
  /** Render as a landmark-friendly element when it groups a region. */
  as?: "div" | "section" | "aside";
}

/**
 * One cell of the bento. `min-w-0` lets long content (tables, chips) shrink
 * instead of forcing the grid wider than the page — the dashboard must never
 * scroll horizontally. Cells stretch to the row height so cards in a row align.
 */
export function BentoItem({ span, as = "div", className, children, ...rest }: BentoItemProps): React.JSX.Element {
  const columns = React.useContext(BentoColumnsContext);
  const Comp = as;
  return (
    <Comp
      data-slot="bento-item"
      className={cn("min-w-0", columns === "12" && spanClasses(span), className)}
      {...rest}
    >
      {children}
    </Comp>
  );
}
