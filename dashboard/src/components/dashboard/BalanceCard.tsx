/**
 * BalanceCard — one "as of today" position on the FPS ACC Dashboard
 * (Receivables, Payables, Cash & bank, VAT for the quarter). A position is a
 * stock, not a flow: it ignores the period filter and has no sparkline and no
 * delta (acc.ts BalanceCard).
 *
 *   icon · label · (i) definition
 *   value (32/40 semibold, compact) ↗   — a real link to the report/list behind it
 *   "Payable" / "Refundable" (VAT only, sign of the net VAT) · [severity chip]
 *   up to four pre-formatted context lines (server strings, shown as sent)
 *   the data caveat behind an amber icon
 *
 * Severity (warning / critical / positive) tints the card with a 2px top edge
 * in the state colour AND a chip with icon + label — never colour alone
 * (DESIGN.md §2 rule 2: an accent is a top edge, never the border). Info adds
 * no emphasis. The value itself stays in ink: text never wears a colour.
 *
 * Read-only: the value only navigates (DeskLink — left click inside the desk,
 * middle/Ctrl-click in a new tab).
 */
import * as React from "react";
import { ArrowUpRight, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatMoney, formatMoneyCompact } from "@/lib/format";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { BalanceCard as BalanceCardData } from "@/types/acc";
import type { Severity } from "@/types/dashboard";
import { DeskLink } from "./DeskLink";
import { BALANCE_ICON, SEVERITY_META } from "./shared";

export interface BalanceCardProps {
  /** One element of payload.balances. */
  balance: BalanceCardData;
  className?: string;
}

/** The contract allows up to 4 context lines; never render more. */
export const MAX_BALANCE_CONTEXT = 4;

/** Severities that tint the card. "info" is no emphasis on a position. */
const EMPHASIS: ReadonlySet<Severity> = new Set<Severity>(["critical", "warning", "positive"]);

/** 2px top edge per severity (state tokens only). */
const EDGE: Readonly<Record<Severity, string>> = {
  critical: "bg-rose",
  warning: "bg-amber",
  positive: "bg-mint",
  info: "",
};

/** "Payable" / "Refundable" / "Nil" for the VAT card (acc.ts: positive = payable). */
function vatDirection(value: number): string {
  if (value > 0) return "Payable";
  if (value < 0) return "Refundable";
  return "Nil";
}

export function BalanceCard({ balance, className }: BalanceCardProps): React.JSX.Element {
  const baseId = React.useId();
  const labelId = `${baseId}-label`;
  const Icon = BALANCE_ICON[balance.key] ?? Info;
  const compact = formatMoneyCompact(balance.value, balance.currency);
  const full = formatMoney(balance.value, balance.currency);
  const context = balance.context.slice(0, MAX_BALANCE_CONTEXT);
  const severity = balance.severity && EMPHASIS.has(balance.severity) ? balance.severity : null;
  const sev = severity ? SEVERITY_META[severity] : null;
  const SevIcon = sev?.icon;

  return (
    <article
      data-slot="balance-card"
      data-balance={balance.key}
      data-severity={severity ?? undefined}
      aria-labelledby={labelId}
      className={cn(
        "glass relative flex h-full min-w-0 flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6",
        "transition-[border-color] duration-150 ease-fps hover:border-hairline-strong",
        className,
      )}
    >
      {severity ? (
        <span aria-hidden="true" className={cn("absolute inset-x-4 top-0 h-0.5 rounded-b-full @min-[480px]/bento:inset-x-6", EDGE[severity])} />
      ) : null}

      {/* Top row */}
      <div className="flex min-w-0 items-center gap-2">
        <span
          aria-hidden="true"
          className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-inset text-electric-ui ring-1 ring-hairline"
        >
          <Icon className="size-4" />
        </span>
        <h3 id={labelId} title={balance.label} className="min-w-0 truncate text-sm leading-5 font-medium text-ink-secondary">
          {balance.label}
        </h3>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`About ${balance.label}: ${balance.definition}`}
              className="-m-1 flex size-6 shrink-0 cursor-help items-center justify-center rounded-md text-ink-muted outline-none transition-colors duration-150 hover:text-ink-secondary focus-visible:text-ink focus-visible:ring-2 focus-visible:ring-electric"
            >
              <Info aria-hidden="true" className="size-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-64 text-left">
            {balance.definition}
          </TooltipContent>
        </Tooltip>
      </div>

      {/* Value: the link to the report or list behind the number. The visible
          compact figure starts the accessible name (WCAG 2.5.3); the full
          figure follows for screen readers and in the hover title. The
          severity chip gets its own row under the value (with "Payable" /
          "Refundable" on the VAT card), so neither the label above
          ("VAT Jul–Sep 2026") nor the value has to truncate for it. */}
      <div className="flex min-w-0 flex-col gap-1">
        <DeskLink
          route={balance.route}
          title={`${full} · open the list behind this number`}
          className="group/value -mx-1 flex w-fit max-w-full min-w-0 items-center gap-1 rounded-md px-1 outline-none focus-visible:ring-2 focus-visible:ring-electric"
        >
          <span className="min-w-0 truncate text-[32px] leading-10 font-semibold tracking-tight text-ink decoration-hairline-strong decoration-1 underline-offset-4 group-hover/value:underline">
            {compact}
          </span>
          <span className="sr-only">{` (${full}), open the ${balance.label} list`}</span>
          <ArrowUpRight
            aria-hidden="true"
            className="size-4 shrink-0 text-ink-muted transition-colors duration-150 group-hover/value:text-electric-ui group-focus-visible/value:text-electric-ui"
          />
        </DeskLink>
        {balance.key === "vat" || (sev && SevIcon) ? (
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            {balance.key === "vat" ? <p className="text-xs leading-4 text-ink-muted">{vatDirection(balance.value)}</p> : null}
            {sev && SevIcon ? (
              <span
                className={cn(
                  "inline-flex shrink-0 items-center gap-1 rounded-md border px-1 text-xs leading-5 font-medium",
                  sev.text,
                  sev.chip,
                )}
              >
                <SevIcon aria-hidden="true" className="size-3.5" />
                {sev.label}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {context.length > 0 || balance.caveat ? (
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
          {balance.caveat ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  aria-label={`Data caveat: ${balance.caveat}`}
                  className="-mx-1 flex w-fit items-center gap-1 rounded-md px-1 text-xs leading-5 text-amber outline-none focus-visible:ring-2 focus-visible:ring-electric"
                >
                  <TriangleAlert aria-hidden="true" className="size-3.5" />
                  Data caveat
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-72 text-left">
                {balance.caveat}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
