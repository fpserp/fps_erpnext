/**
 * AgeingPanel — receivables or payables by days past DUE date, as of today
 * (FPS ACC Dashboard; acc.ts Ageing). Two of them sit side by side at lg.
 *
 *   header   title · "By days past due date · as of 14 Oct" · Table toggle · Full report ↗
 *   summary  Outstanding (link) · Overdue with its share of the total (link)
 *   buckets  the 7 buckets in contract order (Not due, 0–30 … Over 365), each a
 *            horizontal bar with its amount and document count printed beside it
 *            — or, with Table on, the same numbers as a real table, full figures
 *   top      the 5 largest parties: name, outstanding, overdue part, oldest
 *            overdue days and open documents; each row opens that party's list
 *   caveat   behind an amber icon
 *
 * Why bars, not a stacked bar: seven buckets would need seven colours and
 * DESIGN.md allows four series slots. The buckets are ordinal and every bar
 * carries its value as text, so ONE hue (the money role colour) is right; the
 * bucket label, not a colour, says how old the money is. Bars are 8px, square
 * at the baseline and 4px-rounded at the data end (DESIGN.md §6). A negative
 * bucket (credit notes, or payments not yet allocated, netted into the bucket
 * of their own date) draws no bar; its value prints with a minus sign. The
 * caveat line says how much was received / paid on account.
 *
 * Read-only: every number navigates (DeskLink) to the report or the list
 * behind it. Nothing here writes.
 */
import * as React from "react";
import { ArrowUpRight, Table2, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCount, formatMoney, formatMoneyCompact, formatShortDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import type { Ageing, AgeingBucket, AgeingParty } from "@/types/acc";
import { DeskLink } from "./DeskLink";
import { SEGMENT_ITEM_CLASS } from "./PeriodFilter";
import { ROLE_COLOR } from "./shared";

export interface AgeingPanelProps {
  /** One element of payload.ageing: receivables or payables. */
  ageing: Ageing;
  /** payload.as_of (yyyy-mm-dd), for the subtitle. */
  asOf?: string;
  className?: string;
}

/** The contract sends the top 5 parties; never render more. */
export const MAX_AGEING_PARTIES = 5;

/** What one open document is called on each side. */
const NOUNS: Readonly<Record<Ageing["key"], { party: string; doc: string; docs: string }>> = {
  receivables: { party: "customers", doc: "invoice", docs: "invoices" },
  payables: { party: "suppliers", doc: "bill", docs: "bills" },
};

/**
 * The panel title. The API sends the side ("Receivables"); the panel sits
 * under the balance card of the same name, so it reads "Receivables ageing".
 * A label that already says ageing is kept as sent.
 */
export function ageingTitle(label: string): string {
  return /ageing|aging/i.test(label) ? label : `${label} ageing`;
}

function plural(n: number, one: string, many: string): string {
  return `${formatCount(n)} ${Math.round(n) === 1 ? one : many}`;
}

/** "Not due" stays as is; "31–60" reads "31–60 days past due". */
function spokenBucket(bucket: AgeingBucket): string {
  return bucket.key === "not_due" ? bucket.label : `${bucket.label} days past due`;
}

function BucketBars({
  buckets,
  currency,
  docs,
  label,
}: {
  buckets: readonly AgeingBucket[];
  currency: string;
  docs: { one: string; many: string };
  label: string;
}) {
  const max = buckets.reduce((m, b) => Math.max(m, b.value), 0);
  return (
    <ul aria-label={label} className="flex flex-col gap-2">
      {buckets.map((bucket) => {
        const frac = max > 0 ? Math.max(0, bucket.value) / max : 0;
        const full = formatMoney(bucket.value, currency);
        return (
          <li
            key={bucket.key}
            className="grid grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-x-2 text-xs leading-4"
          >
            <span className="sr-only">{`${spokenBucket(bucket)}: ${full}, ${plural(bucket.count, docs.one, docs.many)}.`}</span>
            <span aria-hidden="true" className="truncate text-ink-secondary" title={bucket.label}>
              {bucket.label}
            </span>
            {/* Track + fill: square at the baseline (left), 4px rounded data end. */}
            <span aria-hidden="true" className="h-2 min-w-0 overflow-hidden rounded-r-[4px] bg-surface-inset">
              <span
                className="block h-full rounded-r-[4px]"
                style={{ width: `${(frac * 100).toFixed(2)}%`, minWidth: bucket.value > 0 ? 2 : 0, background: ROLE_COLOR.currency }}
              />
            </span>
            <span aria-hidden="true" className="flex items-baseline justify-end gap-1 whitespace-nowrap tabular-nums" title={full}>
              <span className="font-medium text-ink">{formatMoneyCompact(bucket.value, currency)}</span>
              <span className="w-8 text-right text-ink-muted">{formatCount(bucket.count)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function BucketTable({
  buckets,
  currency,
  caption,
  docsHeader,
}: {
  buckets: readonly AgeingBucket[];
  currency: string;
  caption: string;
  docsHeader: string;
}) {
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className="overflow-auto rounded-lg ring-1 ring-hairline outline-none focus-visible:ring-2 focus-visible:ring-electric"
    >
      <table className="w-full border-collapse text-[13px] leading-5">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-solid">
          <tr className="border-b border-hairline-strong">
            <th scope="col" className="px-4 py-2 text-left text-xs font-medium text-ink-muted">
              Days past due
            </th>
            <th scope="col" className="px-4 py-2 text-right text-xs font-medium text-ink-muted">
              Amount ({currency})
            </th>
            <th scope="col" className="px-4 py-2 text-right text-xs font-medium text-ink-muted">
              {docsHeader}
            </th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((bucket) => (
            <tr key={bucket.key} className="border-b border-hairline last:border-b-0">
              <th scope="row" className="px-4 py-2 text-left font-normal text-ink-secondary">
                {bucket.label}
              </th>
              <td className="px-4 py-2 text-right whitespace-nowrap text-ink tabular-nums">{formatMoney(bucket.value, currency)}</td>
              <td className="px-4 py-2 text-right text-ink-secondary tabular-nums">{formatCount(bucket.count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PartyRow({ party, currency, docs }: { party: AgeingParty; currency: string; docs: { one: string; many: string } }) {
  const full = formatMoney(party.value, currency);
  const facts = [
    party.overdue !== 0
      ? `${formatMoneyCompact(party.overdue, currency)} overdue${party.oldest_days > 0 ? ` · oldest ${plural(party.oldest_days, "day", "days")}` : ""}`
      : "Nothing overdue",
    plural(party.count, `open ${docs.one}`, `open ${docs.many}`),
  ].join(" · ");
  return (
    <li>
      <DeskLink
        route={party.route}
        title={`${party.label} · ${full}`}
        className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 rounded-lg px-2 py-2 outline-none transition-colors duration-150 ease-fps hover:bg-surface-inset focus-visible:ring-2 focus-visible:ring-electric"
      >
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-sm leading-5 font-medium text-ink">{party.label}</span>
          <span className="truncate text-xs leading-4 text-ink-muted">{facts}</span>
        </span>
        <span className="text-sm leading-5 font-semibold whitespace-nowrap text-ink tabular-nums">
          {formatMoneyCompact(party.value, currency)}
          <span className="sr-only">{` (${full}). Open the open ${docs.many} of ${party.label}`}</span>
        </span>
      </DeskLink>
    </li>
  );
}

export function AgeingPanel({ ageing, asOf, className }: AgeingPanelProps): React.JSX.Element {
  const headingId = React.useId();
  const [showTable, setShowTable] = React.useState(false);
  const title = ageingTitle(ageing.label);
  const nouns = NOUNS[ageing.key] ?? NOUNS.receivables;
  const docs = { one: nouns.doc, many: nouns.docs };
  const top = ageing.top.slice(0, MAX_AGEING_PARTIES);
  // A share over 100 % (parties in credit net the total below the overdue) reads
  // as an error, so it is only shown while overdue is part of the total.
  const share =
    ageing.total > 0 && ageing.overdue > 0 && ageing.overdue <= ageing.total
      ? Math.round((ageing.overdue / ageing.total) * 100)
      : null;
  const totalDocs = ageing.buckets.reduce((n, b) => n + b.count, 0);
  const empty = ageing.total === 0 && totalDocs === 0;

  return (
    <section
      aria-labelledby={headingId}
      data-slot="ageing-panel"
      data-ageing={ageing.key}
      className={cn("glass flex h-full min-w-0 flex-col gap-6 rounded-2xl p-4 @min-[480px]/bento:p-6", className)}
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id={headingId} className="text-base leading-6 font-semibold text-ink">
            {title}
          </h3>
          <p className="text-[13px] leading-5 text-ink-muted">
            By days past due date{asOf ? ` · as of ${formatShortDate(asOf)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Toggle
            pressed={showTable}
            onPressedChange={setShowTable}
            size="sm"
            aria-label={`Show ${title} as a table`}
            className={cn(SEGMENT_ITEM_CLASS, "ring-1 ring-hairline")}
          >
            <Table2 aria-hidden="true" className="size-4" />
            Table
          </Toggle>
          <Button asChild variant="outline" size="sm" className="gap-2 px-4 has-[>svg]:px-4">
            <DeskLink route={ageing.route}>
              <ArrowUpRight aria-hidden="true" />
              Full report
            </DeskLink>
          </Button>
        </div>
      </header>

      {/* Summary: both numbers open the full report. */}
      <dl className="grid grid-cols-2 gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <dt className="text-xs leading-4 text-ink-muted">Outstanding</dt>
          <dd className="min-w-0">
            <DeskLink
              route={ageing.route}
              title={formatMoney(ageing.total, ageing.currency)}
              className="-mx-1 block w-fit max-w-full truncate rounded-md px-1 text-xl leading-7 font-semibold tracking-tight text-ink decoration-hairline-strong underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-electric"
            >
              {formatMoneyCompact(ageing.total, ageing.currency)}
              <span className="sr-only">{` (${formatMoney(ageing.total, ageing.currency)}), ${plural(totalDocs, `open ${docs.one}`, `open ${docs.many}`)}. Open the full report`}</span>
            </DeskLink>
          </dd>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <dt className="text-xs leading-4 text-ink-muted">Overdue</dt>
          <dd className="flex min-w-0 items-baseline gap-2">
            <DeskLink
              route={ageing.route}
              title={formatMoney(ageing.overdue, ageing.currency)}
              className="-mx-1 block w-fit max-w-full truncate rounded-md px-1 text-xl leading-7 font-semibold tracking-tight text-ink decoration-hairline-strong underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-electric"
            >
              {formatMoneyCompact(ageing.overdue, ageing.currency)}
              <span className="sr-only">{` (${formatMoney(ageing.overdue, ageing.currency)}${share !== null ? `, ${share}% of the total` : ""}). Open the full report`}</span>
            </DeskLink>
            {share !== null ? (
              <span aria-hidden="true" className="shrink-0 text-xs leading-4 text-ink-muted tabular-nums">
                {share}% of total
              </span>
            ) : null}
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-2">
        {!showTable ? (
          <div aria-hidden="true" className="grid grid-cols-[4.5rem_minmax(0,1fr)_auto] gap-x-2 text-xs leading-4 text-ink-muted">
            <span>Days</span>
            <span />
            <span className="flex justify-end gap-1">
              <span>Amount</span>
              <span className="w-8 text-right">Docs</span>
            </span>
          </div>
        ) : null}
        {showTable ? (
          <BucketTable
            buckets={ageing.buckets}
            currency={ageing.currency}
            caption={`${title} by days past due date`}
            docsHeader={sentenceCase(docs.many)}
          />
        ) : (
          <BucketBars
            buckets={ageing.buckets}
            currency={ageing.currency}
            docs={docs}
            label={`${title} by days past due date`}
          />
        )}
        {empty ? <p className="text-xs leading-4 text-ink-muted">Nothing outstanding.</p> : null}
      </div>

      <div className="flex flex-col gap-2">
        <h4 className="text-sm leading-5 font-medium text-ink">Top {nouns.party}</h4>
        {top.length === 0 ? (
          <p className="text-[13px] leading-5 text-ink-muted">No open {docs.many}.</p>
        ) : (
          <ul className="-mx-2 flex flex-col">
            {top.map((party) => (
              <PartyRow key={party.party} party={party} currency={ageing.currency} docs={docs} />
            ))}
          </ul>
        )}
      </div>

      {ageing.caveat ? (
        <p className="mt-auto flex items-start gap-1 text-xs leading-4 text-ink-secondary">
          <TriangleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0 text-amber" />
          <span>
            <span className="font-medium text-amber">Caveat: </span>
            {ageing.caveat}
          </span>
        </p>
      ) : null}
    </section>
  );
}

function sentenceCase(text: string): string {
  return text.slice(0, 1).toUpperCase() + text.slice(1);
}
