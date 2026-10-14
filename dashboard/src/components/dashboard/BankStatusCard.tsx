/**
 * BankStatusCard — "Bank statements": the reconciliation state of each bank /
 * card account's monthly statement (custom doctype FPS Bank Statement), FPS
 * ACC Dashboard, lg 4 columns beside the trend chart (acc.ts BankStatus).
 *
 * One row per account, in server order (ADCB, WIO, Qashio – General, Qashio –
 * Government):
 *
 *   label                                           [status: icon + text]
 *   "Sep 2026 · closing AED 1.2M"                   "Up to date" | ⏱ "2 months behind"
 *   "Not reconciled: Jul missing, Aug in progress"  (only when behind; server text)
 *
 * "Behind" counts every month since go-live up to last month without a
 * reconciled statement (acc.ts BankStatus.months_behind) — a missing month
 * behind the latest one counts — and open_months names them.
 * Status is a state colour (mint Reconciled / amber In progress / rose Missing)
 * and ALWAYS ships with its icon and label. "Behind" is amber text with a
 * clock icon, so it never relies on colour either. Each row is a real link to
 * the statement (or the account's statement list when none exists).
 *
 * Read-only: rows only navigate.
 */
import * as React from "react";
import { ChevronRight, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatMoney, formatMoneyCompact } from "@/lib/format";
import type { BankStatus } from "@/types/acc";
import { DeskLink } from "./DeskLink";
import { BANK_STATUS_META } from "./shared";

export interface BankStatusCardProps {
  /** payload.banks — ADCB, WIO, QGEN, QGOV in that order. */
  banks: readonly BankStatus[];
  /** Company currency for the closing balances. */
  currency?: string;
  className?: string;
}

function behindText(months: number): string {
  if (months <= 0) return "Up to date";
  return `${months} ${months === 1 ? "month" : "months"} behind`;
}

function BankRow({ bank, currency }: { bank: BankStatus; currency?: string }) {
  const meta = BANK_STATUS_META[bank.status] ?? BANK_STATUS_META.Missing;
  const Icon = meta.icon;
  const behind = bank.months_behind > 0;
  const closing =
    bank.closing_balance === null ? null : { compact: formatMoneyCompact(bank.closing_balance, currency), full: formatMoney(bank.closing_balance, currency) };
  const detail = bank.latest_month
    ? `${bank.latest_month}${closing ? ` · closing ${closing.compact}` : ""}`
    : "No statement on file";
  const open = behind && bank.open_months ? `Not reconciled: ${bank.open_months}` : null;
  const spoken = [
    bank.label,
    meta.label,
    bank.latest_month ? `latest statement ${bank.latest_month}` : "no statement on file",
    closing ? `closing balance ${closing.full}` : "",
    behindText(bank.months_behind),
    open ?? "",
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <li>
      <DeskLink
        route={bank.route}
        aria-label={`${spoken}. Open ${bank.latest_month ? "the statement" : "the statement list"}`}
        title={closing ? `${bank.label} · closing ${closing.full}` : bank.label}
        className="group/row grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-2 gap-y-1 rounded-lg px-2 py-2 outline-none transition-colors duration-150 ease-fps hover:bg-surface-inset focus-visible:ring-2 focus-visible:ring-electric"
      >
        <span className="truncate text-sm leading-5 font-medium text-ink" title={bank.label}>
          {bank.label}
        </span>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-1 text-xs leading-5 font-medium",
            meta.text,
            meta.chip,
          )}
        >
          <Icon aria-hidden="true" className="size-3.5" />
          {meta.label}
        </span>
        <ChevronRight
          aria-hidden="true"
          className="row-span-2 size-4 text-ink-muted transition-transform duration-150 ease-fps group-hover/row:translate-x-0.5 group-hover/row:text-electric-ui motion-reduce:transition-none motion-reduce:group-hover/row:translate-x-0"
        />
        <span className="truncate text-xs leading-4 text-ink-muted tabular-nums" title={detail}>
          {detail}
        </span>
        <span
          className={cn(
            "flex items-center justify-end gap-1 text-xs leading-4 whitespace-nowrap",
            behind ? "font-medium text-amber" : "text-ink-muted",
          )}
        >
          {behind ? <Clock aria-hidden="true" className="size-3.5 shrink-0" /> : null}
          {behindText(bank.months_behind)}
        </span>
        {open ? (
          <span className="col-span-2 truncate text-xs leading-4 text-ink-secondary" title={open}>
            {open}
          </span>
        ) : null}
      </DeskLink>
    </li>
  );
}

export function BankStatusCard({ banks, currency, className }: BankStatusCardProps): React.JSX.Element {
  const headingId = React.useId();
  // Up to date = last month's statement exists AND is reconciled.
  const upToDate = banks.filter((b) => b.months_behind <= 0 && b.status === "Reconciled").length;

  return (
    <section
      aria-labelledby={headingId}
      data-slot="bank-status"
      className={cn("glass flex h-full min-w-0 flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6", className)}
    >
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id={headingId} className="text-base leading-6 font-semibold text-ink">
            Bank statements
          </h3>
          <p className="text-[13px] leading-5 text-ink-muted">Latest statement per account — open any row</p>
        </div>
        {banks.length > 0 ? (
          <span className="shrink-0 pt-1 text-xs leading-4 text-ink-muted tabular-nums">
            {upToDate} of {banks.length} up to date
          </span>
        ) : null}
      </header>

      {banks.length === 0 ? (
        <p className="py-8 text-sm leading-5 text-ink-muted">No bank or card accounts are tracked.</p>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {banks.map((bank) => (
            <BankRow key={bank.bank} bank={bank} currency={currency} />
          ))}
        </ul>
      )}

      <p className="mt-auto border-t border-hairline pt-4 text-xs leading-4 text-ink-muted">
        Behind = months since go-live, up to last month, without a reconciled statement.
      </p>
    </section>
  );
}
