/**
 * PeriodFilter — the 7D / 30D / 90D segmented control used by the dashboard's
 * filter row and by the ActionDrawer.
 *
 * Single-select and never empty: Radix ToggleGroup reports "" when the active
 * item is pressed again, and that value is ignored, so a period is always set.
 * Arrow keys move between items (Radix roving focus).
 *
 * Accessible names keep the visible text first ("7D, last 7 days") so speech
 * users can say what they see (WCAG 2.5.3 Label in Name).
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Period } from "@/types/dashboard";
import { PERIOD_OPTIONS, isPeriod } from "./shared";

export interface PeriodFilterProps {
  value: Period;
  onChange: (period: Period) => void;
  /** Group name for assistive tech. */
  label?: string;
  disabled?: boolean;
  className?: string;
}

/** Shared look for compact segmented controls (period, chart kind, dimension chips). */
export const SEGMENT_GROUP_CLASS = "rounded-lg bg-surface-inset p-1 ring-1 ring-hairline";
export const SEGMENT_ITEM_CLASS =
  "h-8 min-w-10 rounded-md px-2 text-[13px] leading-5 font-medium text-ink-secondary hover:bg-surface-inset hover:text-ink focus-visible:ring-2 focus-visible:ring-electric data-[state=on]:bg-electric/15 data-[state=on]:text-ink";

export function PeriodFilter({
  value,
  onChange,
  label = "Period",
  disabled = false,
  className,
}: PeriodFilterProps): React.JSX.Element {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(next) => {
        if (isPeriod(next)) onChange(next);
      }}
      aria-label={label}
      disabled={disabled}
      spacing={1}
      size="sm"
      className={cn(SEGMENT_GROUP_CLASS, className)}
    >
      {PERIOD_OPTIONS.map((option) => (
        <ToggleGroupItem key={option.value} value={option.value} className={SEGMENT_ITEM_CLASS}>
          {option.short}
          <span className="sr-only">{`, ${option.long.toLowerCase()}`}</span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
