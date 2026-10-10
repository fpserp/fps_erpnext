/**
 * StageStrip — "Pipeline now", the bento's stage card (DESIGN.md §8: lg 4
 * columns). It replaces the old FPS Overview strip and keeps everything that
 * strip showed: every tile from fps_erpnext.api.pipeline.get_overview in
 * SERVER order with its label, note, count and exact route, the footnotes
 * ("2 past ETA", "20 with no ETA", "45 PODs on file"), the "<n> stages" meta,
 * and the "No stages are visible to you." empty state. Tiles the viewer cannot
 * read are omitted by the server (never sent as zero); this card renders
 * whatever subset arrives.
 *
 * Each row is a link (DeskLink): left click navigates inside the desk with the
 * list filters, middle/Ctrl-click opens the list in a new tab.
 *
 * The bars are a single hue (Electric Blue) proportional to the largest count:
 * they compare stage sizes, they do not encode identity, so one colour is
 * right (a value-ramp on nominal stages would be an anti-pattern).
 */
import * as React from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCount } from "@/lib/format";
import type { Stages } from "@/types/dashboard";
import { DeskLink } from "./DeskLink";

export interface StageStripProps {
  /** payload.stages — the existing Overview tiles and footnotes, unchanged. */
  stages: Stages;
  className?: string;
}

export function StageStrip({ stages, className }: StageStripProps): React.JSX.Element {
  const headingId = React.useId();
  const { tiles, footnotes } = stages;
  const max = tiles.reduce((m, t) => Math.max(m, t.count), 0);

  return (
    <section
      aria-labelledby={headingId}
      data-slot="stage-strip"
      className={cn("glass flex h-full min-w-0 flex-col gap-4 rounded-2xl p-4 @min-[480px]/bento:p-6", className)}
    >
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id={headingId} className="text-base leading-6 font-semibold text-ink">
            Pipeline now
          </h3>
          <p className="text-[13px] leading-5 text-ink-muted">Live count by stage — open the list behind any row</p>
        </div>
        {tiles.length > 0 ? (
          <span className="shrink-0 pt-1 text-xs leading-4 text-ink-muted tabular-nums">
            {tiles.length} {tiles.length === 1 ? "stage" : "stages"}
          </span>
        ) : null}
      </header>

      {tiles.length === 0 ? (
        <p className="py-8 text-sm leading-5 text-ink-muted">No stages are visible to you.</p>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {tiles.map((tile) => {
            const pct = max > 0 ? (tile.count / max) * 100 : 0;
            return (
              <li key={tile.key}>
                <DeskLink
                  route={tile.route}
                  aria-label={`${tile.label}, ${tile.note}: ${formatCount(tile.count)}. Open list`}
                  className="group/row grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-2 gap-y-1 rounded-lg px-2 py-2 outline-none transition-colors duration-150 ease-fps hover:bg-surface-inset focus-visible:ring-2 focus-visible:ring-electric"
                >
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate text-sm leading-5 font-medium text-ink" title={tile.label}>
                      {tile.label}
                    </span>
                    <span className="truncate text-xs leading-4 text-ink-muted" title={tile.note}>
                      {tile.note}
                    </span>
                  </span>
                  <span className="text-base leading-6 font-semibold text-ink tabular-nums">{formatCount(tile.count)}</span>
                  <ChevronRight
                    aria-hidden="true"
                    className="size-4 text-ink-muted transition-transform duration-150 ease-fps group-hover/row:translate-x-0.5 group-hover/row:text-electric-ui motion-reduce:transition-none motion-reduce:group-hover/row:translate-x-0"
                  />
                  {/* Proportional bar: track + fill, 6px tall, single hue. DESIGN.md §6: square at
                      the baseline (left), 4px rounded data end — like the drawer's breakdown bars.
                      The track loses its left radius too, or its overflow-hidden would clip the
                      bar start into a semicircle. */}
                  <span aria-hidden="true" className="col-span-2 h-1.5 overflow-hidden rounded-r-[4px] bg-surface-inset">
                    <span
                      className="block h-full rounded-r-[4px] bg-electric"
                      style={{ width: `${pct}%`, minWidth: tile.count > 0 ? 6 : 0 }}
                    />
                  </span>
                </DeskLink>
              </li>
            );
          })}
        </ul>
      )}

      {footnotes.length > 0 ? (
        <ul aria-label="Notes" className="mt-auto flex flex-wrap gap-x-4 gap-y-1 border-t border-hairline pt-4 text-xs leading-4 text-ink-muted">
          {footnotes.map((note) => (
            <li key={note} className="tabular-nums">
              {note}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
