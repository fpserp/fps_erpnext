/**
 * ChartTableView — the accessible twin of a chart (DESIGN.md §6: "every chart
 * has a table view toggle"). Same numbers as the chart, full figures, one row
 * per bucket, the still-filling bucket marked "so far".
 *
 * Text never wears the series colour: the column header carries a small
 * line-key swatch beside ink text (DESIGN.md §5).
 *
 * The scroll region is focusable (tabIndex 0) and labelled, so keyboard users
 * can scroll it; the header row is sticky.
 */
import * as React from "react";
import { cn } from "@/lib/utils";

export interface ChartTableColumn {
  key: string;
  label: string;
  /** Series colour for the header line-key (CSS colour expression). */
  color?: string;
}

export interface ChartTableRow {
  key: string;
  /** Row header text, e.g. "6 Oct". */
  label: string;
  /** The current bucket, still filling. */
  partial?: boolean;
  values: Record<string, number>;
}

export interface ChartTableViewProps {
  caption: string;
  /** Header of the first column, e.g. "Week of" or "Date". */
  rowHeader: string;
  columns: readonly ChartTableColumn[];
  rows: readonly ChartTableRow[];
  /** Full-figure formatter (no compacting in tables). */
  format: (n: number) => string;
  /** Text appended to the partial row's header. */
  partialNote?: string;
  /** Height of the scroll region in px; matches the chart it replaces. */
  maxHeight?: number;
  className?: string;
}

export function ChartTableView({
  caption,
  rowHeader,
  columns,
  rows,
  format,
  partialNote = "so far",
  maxHeight = 280,
  className,
}: ChartTableViewProps): React.JSX.Element {
  return (
    <div
      role="region"
      aria-label={caption}
      tabIndex={0}
      className={cn(
        "overflow-auto rounded-lg ring-1 ring-hairline outline-none focus-visible:ring-2 focus-visible:ring-electric",
        className,
      )}
      style={{ maxHeight }}
    >
      <table className="w-full border-collapse text-[13px] leading-5">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-surface-solid">
          <tr className="border-b border-hairline-strong">
            <th scope="col" className="px-4 py-2 text-left text-xs font-medium text-ink-muted">
              {rowHeader}
            </th>
            {columns.map((col) => (
              <th key={col.key} scope="col" className="px-4 py-2 text-right text-xs font-medium text-ink-muted">
                <span className="inline-flex items-center justify-end gap-1">
                  {col.color ? (
                    <span aria-hidden="true" className="h-0.5 w-3 rounded-full" style={{ background: col.color }} />
                  ) : null}
                  {col.label}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-hairline last:border-b-0">
              <th scope="row" className="px-4 py-2 text-left font-normal whitespace-nowrap text-ink-secondary">
                {row.label}
                {row.partial ? <span className="text-ink-muted">{` (${partialNote})`}</span> : null}
              </th>
              {columns.map((col) => (
                <td key={col.key} className="px-4 py-2 text-right whitespace-nowrap text-ink tabular-nums">
                  {format(row.values[col.key] ?? 0)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
