/**
 * InsightBanner — the "Auto-insights" glass widget at the top of the bento.
 *
 * What it is (and is not): the insights are RULE-BASED checks computed by the
 * read-only API (command_center_logic.py), not model output, and the banner
 * says so ("rule-based"). The violet accent marks it as the assistant's voice;
 * Soft Violet is a UI accent here, never a chart mark (DESIGN.md §4).
 *
 *  - The most severe insight shows large (title + detail) with its severity as
 *    icon + label — never colour alone.
 *  - Prev/next, "n of N" and dot indicators page through the rest; "Show all"
 *    expands a list of every insight.
 *  - Position is kept BY ID across polls, so a refresh that re-orders or adds
 *    insights does not yank the one being read out from under the reader.
 *  - An insight with metric_key opens that KPI's drawer (if the viewer has the
 *    KPI); otherwise one with a route links to the list behind it.
 *  - The 1px border shimmer is a 6 s gradient sweep, paused under
 *    prefers-reduced-motion and hidden under forced-colors.
 *  - Narrow banners (container < 480px, e.g. a phone or a split desk): the
 *    title and its "rule-based · updated" line stack, and the pager controls
 *    (prev, n of N, next, Show all) drop to their own full-width row, so the
 *    title is never squeezed. Truncated text keeps its full value in `title`.
 *
 * Read-only: every action here is navigation or opening the read-only drawer.
 */
import * as React from "react";
import { ArrowRight, ChevronDown, ChevronLeft, ChevronRight, CircleCheck, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/format";
import type { Insight, KpiKey } from "@/types/dashboard";
import { DeskLink } from "./DeskLink";
import { SEVERITY_META } from "./shared";

export interface InsightBannerProps {
  /** payload.insights — 0–6, most severe first. */
  insights: readonly Insight[];
  /** When the payload was last fetched (shown as "updated 14:32"). */
  updatedAt: Date | null;
  /** Opens the drawer for a KPI. */
  onOpenMetric: (key: KpiKey) => void;
  /** Whether the viewer has this KPI on the dashboard (else fall back to the route). */
  canOpenMetric: (key: KpiKey) => boolean;
  className?: string;
}

/**
 * Keyframes cannot live in a utility class, and theme.css belongs to the core
 * module, so the one animation this component owns ships with it. Rendered as
 * an in-place <style> (no href/precedence, so React 19 does not hoist it to
 * document.head, where it could not reach the shadow root).
 */
const SHIMMER_CSS = `@keyframes fps-cc-insight-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}`;

/**
 * The ring: a wide gradient (highlight in its middle 30–70%) swept along the
 * edge, with the content box masked out by the `exclude` compositing operator
 * written INSIDE the mask shorthand (a separate mask-composite would be reset
 * by the shorthand, depending on rule order). Mask colours only carry alpha.
 */
const SHIMMER_STYLE: React.CSSProperties = {
  background:
    "linear-gradient(90deg, transparent 0%, transparent 30%, var(--fps-violet) 45%, var(--fps-electric) 55%, transparent 70%, transparent 100%) 0 0 / 200% 100%",
  mask: "linear-gradient(black, black) content-box exclude, linear-gradient(black, black)",
};

/**
 * Without mask compositing the "ring" would be a gradient sweeping across the
 * whole banner, so engines that cannot exclude simply get no shimmer.
 */
const shimmerSupported =
  typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("mask-composite", "exclude");

function SeverityChip({ insight, size = "sm" }: { insight: Insight; size?: "sm" | "md" }) {
  const meta = SEVERITY_META[insight.severity] ?? SEVERITY_META.info;
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md border px-1 font-medium",
        size === "md" ? "py-0.5 text-[13px] leading-5" : "text-xs leading-5",
        meta.text,
        meta.chip,
      )}
    >
      <Icon aria-hidden="true" className={size === "md" ? "size-4" : "size-3.5"} />
      {meta.label}
    </span>
  );
}

type InsightAction =
  | { kind: "metric"; key: KpiKey; label: string }
  | { kind: "route"; route: string; label: string }
  | { kind: "none" };

function actionFor(insight: Insight, canOpenMetric: (key: KpiKey) => boolean): InsightAction {
  if (insight.metric_key && canOpenMetric(insight.metric_key)) {
    return { kind: "metric", key: insight.metric_key, label: "View details" };
  }
  if (insight.route) return { kind: "route", route: insight.route, label: "Open list" };
  return { kind: "none" };
}

/** The clickable title: a button for the drawer, a link for a route, plain text otherwise. */
function InsightTitle({
  insight,
  action,
  onOpenMetric,
  className,
}: {
  insight: Insight;
  action: InsightAction;
  onOpenMetric: (key: KpiKey) => void;
  className?: string;
}) {
  const interactive = cn(
    className,
    "rounded-md text-left outline-none decoration-hairline-strong underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-electric",
  );
  if (action.kind === "metric") {
    return (
      <button type="button" className={interactive} onClick={() => onOpenMetric(action.key)}>
        {insight.title}
      </button>
    );
  }
  if (action.kind === "route") {
    return (
      <DeskLink route={action.route} className={interactive}>
        {insight.title}
      </DeskLink>
    );
  }
  return <span className={className}>{insight.title}</span>;
}

export function InsightBanner({
  insights,
  updatedAt,
  onOpenMetric,
  canOpenMetric,
  className,
}: InsightBannerProps): React.JSX.Element {
  const headingId = React.useId();
  const listId = React.useId();
  const [activeId, setActiveId] = React.useState<string | null>(insights[0]?.id ?? null);
  const [lastIndex, setLastIndex] = React.useState(0);
  const [expanded, setExpanded] = React.useState(false);

  const count = insights.length;
  const found = activeId === null ? -1 : insights.findIndex((i) => i.id === activeId);
  // Keep position by id; if that insight resolved itself, stay at the same slot.
  const index = found >= 0 ? found : Math.min(lastIndex, Math.max(0, count - 1));
  const current = count > 0 ? insights[index] : undefined;

  const go = (next: number) => {
    if (count === 0) return;
    const wrapped = (next + count) % count;
    setActiveId(insights[wrapped].id);
    setLastIndex(wrapped);
  };

  const updatedText = updatedAt ? `updated ${formatTime(updatedAt)}` : "updating";

  return (
    <section
      aria-labelledby={headingId}
      data-slot="insight-banner"
      // No overflow-hidden: it clips at the padding box, and the shimmer ring sits ON the border.
      className={cn("glass @container/insight relative isolate rounded-2xl", className)}
    >
      <style>{SHIMMER_CSS}</style>
      {/* 1px animated gradient border: a ring (content box masked out) over the glass hairline. */}
      {shimmerSupported ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -inset-px rounded-2xl p-px [animation:fps-cc-insight-shimmer_6s_linear_infinite] motion-reduce:[animation:none] forced-colors:hidden"
          style={SHIMMER_STYLE}
        />
      ) : null}
      {/* Violet AI accent: a 2px top edge glow, decoration only. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-8 top-0 h-0.5 rounded-full forced-colors:hidden"
        style={{ background: "linear-gradient(90deg, transparent, var(--fps-violet), transparent)", opacity: 0.6 }}
      />

      <div className="flex flex-col gap-4 p-4 @min-[480px]/insight:p-6">
        <header className="flex flex-col gap-2 @min-[480px]/insight:flex-row @min-[480px]/insight:flex-wrap @min-[480px]/insight:items-center @min-[480px]/insight:justify-between @min-[480px]/insight:gap-x-4">
          <div className="flex min-w-0 items-center gap-2">
            <span
              aria-hidden="true"
              className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-violet/10 text-violet ring-1 ring-violet/25"
            >
              <Sparkles className="size-4" />
            </span>
            <div className="flex min-w-0 flex-col @min-[480px]/insight:flex-row @min-[480px]/insight:items-baseline @min-[480px]/insight:gap-2">
              <h3 id={headingId} className="shrink-0 text-sm leading-5 font-semibold whitespace-nowrap text-ink">
                Auto-insights
              </h3>
              <span className="truncate text-xs leading-4 text-ink-muted" title={`rule-based · ${updatedText}`}>
                rule-based · {updatedText}
              </span>
            </div>
          </div>
          {count > 1 ? (
            <div className="flex w-full items-center gap-1 @min-[480px]/insight:w-auto">
              <button
                type="button"
                onClick={() => go(index - 1)}
                aria-label="Previous insight"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-secondary outline-none hover:bg-surface-inset hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
              >
                <ChevronLeft aria-hidden="true" className="size-4" />
              </button>
              <span className="min-w-12 shrink-0 text-center text-xs leading-4 whitespace-nowrap text-ink-muted tabular-nums" aria-hidden="true">
                {index + 1} of {count}
              </span>
              <button
                type="button"
                onClick={() => go(index + 1)}
                aria-label="Next insight"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-secondary outline-none hover:bg-surface-inset hover:text-ink focus-visible:ring-2 focus-visible:ring-electric"
              >
                <ChevronRight aria-hidden="true" className="size-4" />
              </button>
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                aria-controls={listId}
                className="ml-auto flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-[13px] leading-5 font-medium whitespace-nowrap text-ink-secondary outline-none hover:bg-surface-inset hover:text-ink focus-visible:ring-2 focus-visible:ring-electric @min-[480px]/insight:ml-2"
              >
                {expanded ? "Hide list" : "Show all"}
                <ChevronDown
                  aria-hidden="true"
                  className={cn("size-4 transition-transform duration-150 motion-reduce:transition-none", expanded && "rotate-180")}
                />
              </button>
            </div>
          ) : null}
        </header>

        {current ? (
          <div aria-live="polite" aria-atomic="true" className="flex min-w-0 flex-col gap-2">
            <span className="sr-only">{`Insight ${index + 1} of ${count}.`}</span>
            <div className="flex min-w-0 flex-wrap items-start gap-x-4 gap-y-2">
              <SeverityChip insight={current} size="md" />
              <InsightTitle
                insight={current}
                action={actionFor(current, canOpenMetric)}
                onOpenMetric={onOpenMetric}
                className="min-w-0 flex-1 text-base leading-6 font-semibold break-words text-ink"
              />
            </div>
            <p className="max-w-[72ch] text-sm leading-5 break-words text-ink-secondary">{current.detail}</p>
            <CurrentAction insight={current} action={actionFor(current, canOpenMetric)} onOpenMetric={onOpenMetric} />
          </div>
        ) : (
          <p className="flex items-center gap-2 text-sm leading-5 text-ink-secondary">
            <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-mint" />
            All clear — no anomalies in the data right now.
          </p>
        )}

        {count > 1 ? (
          <div className="-my-2 flex flex-wrap items-center" role="group" aria-label="Choose insight">
            {insights.map((insight, i) => (
              <button
                key={insight.id}
                type="button"
                onClick={() => go(i)}
                aria-label={`Insight ${i + 1}: ${SEVERITY_META[insight.severity]?.label ?? "Info"}, ${insight.title}`}
                aria-current={i === index ? "true" : undefined}
                className="group/dot flex size-6 items-center justify-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-electric"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "block rounded-full transition-[width,background-color] duration-150 ease-fps motion-reduce:transition-none",
                    i === index ? "h-1.5 w-4 bg-violet" : "size-1.5 bg-hairline-strong group-hover/dot:bg-ink-muted",
                  )}
                />
              </button>
            ))}
          </div>
        ) : null}

        {count > 1 && expanded ? (
          <ol id={listId} aria-label="All insights" className="flex flex-col divide-y divide-hairline border-t border-hairline">
            {insights.map((insight) => {
              const action = actionFor(insight, canOpenMetric);
              return (
                <li key={insight.id} className="flex min-w-0 flex-col gap-1 py-4 last:pb-0">
                  <div className="flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1">
                    <SeverityChip insight={insight} />
                    <InsightTitle
                      insight={insight}
                      action={action}
                      onOpenMetric={onOpenMetric}
                      className="min-w-0 flex-1 text-sm leading-5 font-medium break-words text-ink"
                    />
                  </div>
                  <p className="max-w-[72ch] text-[13px] leading-5 break-words text-ink-muted">{insight.detail}</p>
                </li>
              );
            })}
          </ol>
        ) : (
          // Keeps aria-controls pointing at a real element while collapsed.
          <div id={listId} hidden />
        )}
      </div>
    </section>
  );
}

/** "View details →" / "Open list →" under the featured insight. */
function CurrentAction({
  insight,
  action,
  onOpenMetric,
}: {
  insight: Insight;
  action: InsightAction;
  onOpenMetric: (key: KpiKey) => void;
}) {
  const cls =
    "inline-flex w-fit items-center gap-1 rounded-md text-[13px] leading-5 font-medium text-electric-ui outline-none hover:underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-electric";
  if (action.kind === "metric") {
    return (
      <button type="button" className={cls} onClick={() => onOpenMetric(action.key)} aria-label={`${action.label}: ${insight.title}`}>
        {action.label}
        <ArrowRight aria-hidden="true" className="size-3.5" />
      </button>
    );
  }
  if (action.kind === "route") {
    return (
      <DeskLink route={action.route} className={cls} aria-label={`${action.label}: ${insight.title}`}>
        {action.label}
        <ArrowRight aria-hidden="true" className="size-3.5" />
      </DeskLink>
    );
  }
  return null;
}
