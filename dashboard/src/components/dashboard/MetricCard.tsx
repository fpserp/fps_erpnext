/**
 * MetricCard — one KPI of the bento (DESIGN.md §8), high density:
 *   icon · label · (i) definition · [Finance] · deep-dive button
 *   value (32/40 semibold, proportional figures, compact; full figure on hover)
 *   DeltaBadge "+12.4% vs previous 7 days"
 *   Sparkline of the period series
 *   up to two context facts, and the data caveat behind an amber icon.
 *
 * Interaction model — why not one big <button>: the card also holds two
 * interactive tooltips (definition, caveat), and interactive content nested
 * inside a button (or role="button") is invalid and unreachable for screen
 * readers. So:
 *  - the deep-dive icon button ("Open <label> details") is the card's single
 *    keyboard/AT activation point (native button: Enter and Space);
 *  - a pointer click ANYWHERE on the card does the same thing, and first moves
 *    focus to that button so the drawer returns focus to this card on close;
 *  - the focus ring (2px Electric Blue, 2px offset) is drawn around the WHOLE
 *    card whenever that button has keyboard focus.
 *
 * Read-only: opening the drawer only loads more read-only data.
 */
import * as React from "react";
import { Info, PanelRightOpen, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatValue } from "@/lib/format";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Kpi, KpiKey } from "@/types/dashboard";
import { DeltaBadge } from "./DeltaBadge";
import { Sparkline } from "./Sparkline";
import { KPI_ICON } from "./shared";

export interface MetricCardProps {
  kpi: Kpi;
  /** Payload compare_label, e.g. "vs previous 7 days". */
  compareLabel: string;
  /** Opens the ActionDrawer for this metric. */
  onOpen: (key: KpiKey) => void;
  className?: string;
}

/** Clicks on these never double as "open the card". */
const INTERACTIVE = "button, a, [role='button'], [data-card-ignore]";

export function MetricCard({ kpi, compareLabel, onOpen, className }: MetricCardProps): React.JSX.Element {
  const openRef = React.useRef<HTMLButtonElement>(null);
  const baseId = React.useId();
  const valueId = `${baseId}-value`;
  const deltaId = `${baseId}-delta`;
  const Icon = KPI_ICON[kpi.key];
  const isMoney = kpi.unit === "currency";
  const compact = formatValue(kpi.value, kpi.unit, kpi.currency, { compact: true });
  const full = formatValue(kpi.value, kpi.unit, kpi.currency);
  const context = kpi.context.slice(0, 2);

  const open = () => {
    // Focus first, so the Sheet records this card as the element to return to.
    openRef.current?.focus({ preventScroll: true });
    onOpen(kpi.key);
  };

  const handleCardClick = (event: React.MouseEvent<HTMLElement>) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest(INTERACTIVE)) return;
    // Selecting the number to copy it must not open the drawer.
    const selection = typeof window !== "undefined" ? window.getSelection()?.toString() : "";
    if (selection) return;
    open();
  };

  return (
    <article
      data-slot="metric-card"
      data-kpi={kpi.key}
      aria-labelledby={`${baseId}-label`}
      onClick={handleCardClick}
      className={cn(
        // 16px padding on a narrow dashboard (< 480px), 24px otherwise (DESIGN.md §3).
        "glass group/card relative flex h-full min-w-0 cursor-pointer flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6",
        "transition-[border-color,background-color] duration-150 ease-fps",
        "hover:border-hairline-strong",
        // The whole card shows the keyboard focus of its activation button.
        "has-[[data-slot=metric-open]:focus-visible]:outline-2 has-[[data-slot=metric-open]:focus-visible]:outline-offset-2 has-[[data-slot=metric-open]:focus-visible]:outline-electric",
        className,
      )}
    >
      {/* Top row */}
      <div className="flex min-w-0 items-center gap-2">
        <span
          aria-hidden="true"
          className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-inset text-electric-ui ring-1 ring-hairline"
        >
          <Icon className="size-4" />
        </span>
        <h3 id={`${baseId}-label`} title={kpi.label} className="min-w-0 truncate text-sm leading-5 font-medium text-ink-secondary">
          {kpi.label}
        </h3>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`About ${kpi.label}: ${kpi.definition}`}
              className="-m-1 flex size-6 shrink-0 cursor-help items-center justify-center rounded-md text-ink-muted outline-none transition-colors duration-150 hover:text-ink-secondary focus-visible:text-ink focus-visible:ring-2 focus-visible:ring-electric"
            >
              <Info aria-hidden="true" className="size-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-64 text-left">
            {kpi.definition}
          </TooltipContent>
        </Tooltip>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {isMoney ? (
            <span className="rounded-md border border-hairline px-1.5 text-xs leading-5 text-ink-secondary">Finance</span>
          ) : null}
          <button
            ref={openRef}
            type="button"
            data-slot="metric-open"
            aria-label={`Open ${kpi.label} details`}
            aria-describedby={`${valueId} ${deltaId}`}
            onClick={() => onOpen(kpi.key)}
            className="flex size-8 items-center justify-center rounded-lg text-ink-muted outline-none transition-colors duration-150 group-hover/card:text-electric-ui hover:bg-surface-inset focus-visible:text-electric-ui"
          >
            <PanelRightOpen aria-hidden="true" className="size-4" />
          </button>
        </span>
      </div>

      {/* Value + delta */}
      <div className="flex min-w-0 flex-col gap-2">
        <p id={valueId} className="min-w-0 truncate text-[32px] leading-10 font-semibold tracking-tight text-ink" title={full}>
          <span aria-hidden="true">{compact}</span>
          <span className="sr-only">{full}</span>
        </p>
        {/* The wrapper carries the id so the open button's description reads the
            badge's spoken sentence (its visible chip is aria-hidden). */}
        <div id={deltaId} className="min-w-0">
          <DeltaBadge
            deltaPct={kpi.delta_pct}
            value={kpi.value}
            previous={kpi.previous}
            goodDirection={kpi.good_direction}
            compareLabel={compareLabel}
          />
          {kpi.previous !== null ? (
            <span className="sr-only">
              {` Previous period: ${formatValue(kpi.previous, kpi.unit, kpi.currency)}.`}
            </span>
          ) : null}
        </div>
      </div>

      <Sparkline points={kpi.series} unit={kpi.unit} currency={kpi.currency} granularity={kpi.granularity} />

      {context.length > 0 || kpi.caveat ? (
        <div className="mt-auto flex flex-col gap-2">
          {context.length > 0 ? (
            <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 text-xs leading-4">
              {context.map((line) => (
                <React.Fragment key={line.label}>
                  <dt className="truncate text-ink-muted" title={line.label}>
                    {line.label}
                  </dt>
                  <dd className="text-right font-medium text-ink-secondary tabular-nums">{line.value}</dd>
                </React.Fragment>
              ))}
            </dl>
          ) : null}
          {kpi.caveat ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  aria-label={`Data caveat: ${kpi.caveat}`}
                  className="-mx-1 flex w-fit items-center gap-1 rounded-md px-1 text-xs leading-5 text-amber outline-none focus-visible:ring-2 focus-visible:ring-electric"
                >
                  <TriangleAlert aria-hidden="true" className="size-3.5" />
                  Data caveat
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-72 text-left">
                {kpi.caveat}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
