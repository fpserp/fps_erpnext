/**
 * DeltaBadge — period-over-period change, DESIGN.md §4 "Delta semantics".
 *
 * Colour = direction × whether up is good FOR THIS METRIC:
 *   good_direction "up"   → up mint ▲, down rose ▼
 *   good_direction "down" → up rose ▲, down mint ▼
 *   good_direction "none" → muted either way
 * and the special cases (DESIGN.md §4; API contract in types/dashboard.ts):
 *   previous null                        → "—"   no earlier data: the source does
 *                                                not reach back over the previous
 *                                                window, so nothing is comparable
 *   delta null, previous ≤ 0, value > 0  → "new" never "+∞%": no percentage
 *                                                against a zero (or negative) base
 *   delta null otherwise                 → "—"   no activity in either period, or
 *                                                not comparable (negative figures)
 *   delta rounding to 0.0%               → "0.0%" muted, Minus icon (no change)
 * "new" is reserved for a base of nothing; it is never shown merely because the
 * API has no previous figure — that is "—" with "No earlier data to compare with."
 *
 * The badge is a STATUS (icon + label), which is the one place the status
 * tokens may colour text; the mint and rose tokens clear 4.5:1 on the
 * darkest glass. Direction is carried by the arrow icon as well as the sign,
 * so it never depends on colour; the good/bad reading is repeated in the
 * screen-reader sentence.
 */
import * as React from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDelta } from "@/lib/format";
import type { GoodDirection } from "@/types/dashboard";
import { spokenCompare } from "./shared";

export type DeltaTone = "good" | "bad" | "neutral";
export type DeltaKind = "up" | "down" | "flat" | "new" | "none";

export interface DeltaBadgeProps {
  /** Percentage change, 1 dp, from the API; null when there is no comparable base. */
  deltaPct: number | null;
  /** Current-period total; with previous ≤ 0 it decides between "new" (> 0) and "—". */
  value: number;
  /**
   * API previous; null = the source does not reach back (not comparable), which
   * renders "—", never "new". 0 or negative with value > 0 renders "new".
   */
  previous: number | null;
  goodDirection: GoodDirection;
  /** Server text such as "vs previous 7 days"; shown muted after the badge when set. */
  compareLabel?: string;
  /** sm: cards and lists (12px); md: drawer header (13px). */
  size?: "sm" | "md";
  /** Hide the visible compare text (it stays in the screen-reader sentence). */
  hideCompare?: boolean;
  className?: string;
}

export interface DeltaState {
  kind: DeltaKind;
  tone: DeltaTone;
  text: string;
  /** Screen-reader sentence for the "new" and "none" cases, which carry no compare text. */
  spoken?: string;
}

/** Pure mapping, exported so tests and other views read deltas exactly the same way. */
export function deltaState(
  deltaPct: number | null,
  value: number,
  previous: number | null,
  goodDirection: GoodDirection,
): DeltaState {
  // DESIGN.md §4: "no prior data" is a muted "—"; "new" only replaces +∞% against a base of nothing.
  if (previous === null) {
    return { kind: "none", tone: "neutral", text: "—", spoken: "No earlier data to compare with." };
  }
  if (deltaPct === null || !Number.isFinite(deltaPct)) {
    if (previous <= 0 && value > 0) {
      return {
        kind: "new",
        tone: "neutral",
        text: "new",
        spoken:
          previous === 0
            ? "New this period; none in the previous period."
            : "New this period; the previous period was net negative, so there is no percentage.",
      };
    }
    return {
      kind: "none",
      tone: "neutral",
      text: "—",
      spoken: value === 0 && previous === 0 ? "No activity in either period." : "Not comparable with the previous period.",
    };
  }
  const text = formatDelta(deltaPct);
  // formatDelta rounds to 1 dp; anything that rounds to 0.0% is "flat".
  if (!/[1-9]/.test(text)) return { kind: "flat", tone: "neutral", text };
  const kind: DeltaKind = deltaPct > 0 ? "up" : "down";
  if (goodDirection === "none") return { kind, tone: "neutral", text };
  const good = (kind === "up") === (goodDirection === "up");
  return { kind, tone: good ? "good" : "bad", text };
}

const TONE_CLASS: Readonly<Record<DeltaTone, string>> = {
  good: "text-mint bg-mint/10 border-mint/20",
  bad: "text-rose bg-rose/10 border-rose/20",
  neutral: "text-ink-secondary bg-surface-inset border-hairline",
};

function spokenSentence(state: DeltaState, compareLabel: string | undefined): string {
  const against = compareLabel ? ` ${spokenCompare(compareLabel)}` : "";
  switch (state.kind) {
    case "new":
    case "none":
      return state.spoken ?? "Nothing to compare with.";
    case "flat":
      return `No change${against}.`;
    default: {
      const magnitude = state.text.replace(/^[+−-]/, "");
      const judgement = state.tone === "good" ? ", favourable" : state.tone === "bad" ? ", unfavourable" : "";
      return `${state.kind === "up" ? "Up" : "Down"} ${magnitude}${against}${judgement}.`;
    }
  }
}

export function DeltaBadge({
  deltaPct,
  value,
  previous,
  goodDirection,
  compareLabel,
  size = "sm",
  hideCompare = false,
  className,
}: DeltaBadgeProps): React.JSX.Element {
  const state = deltaState(deltaPct, value, previous, goodDirection);
  const Icon = state.kind === "up" ? ArrowUpRight : state.kind === "down" ? ArrowDownRight : state.kind === "flat" ? Minus : null;
  const showCompare = Boolean(compareLabel) && !hideCompare && state.kind !== "new" && state.kind !== "none";

  return (
    <span
      data-slot="delta-badge"
      data-tone={state.tone}
      data-kind={state.kind}
      className={cn("inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1", className)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex shrink-0 items-center gap-1 rounded-md border px-1 font-medium whitespace-nowrap tabular-nums",
          size === "md" ? "py-0.5 text-[13px] leading-5" : "text-xs leading-5",
          TONE_CLASS[state.tone],
        )}
      >
        {Icon ? <Icon className={size === "md" ? "size-4" : "size-3.5"} strokeWidth={2.25} /> : null}
        {state.text}
      </span>
      {showCompare ? (
        <span aria-hidden="true" className={cn("text-ink-muted", size === "md" ? "text-[13px] leading-5" : "text-xs leading-4")}>
          {compareLabel}
        </span>
      ) : null}
      <span className="sr-only">{spokenSentence(state, compareLabel)}</span>
    </span>
  );
}
