/**
 * Shape of every `*.meta.ts` companion file. A meta file is the machine- and
 * human-readable contract of a layout component: which props it accepts,
 * which variants exist, and the layout limits it must not break. Future
 * changes (by people or by prompts) must keep component and meta in step.
 */
export type Breakpoint = "sm" | "md" | "lg" | "xl";

export interface PropSpec {
  type: string;
  required: boolean;
  /** Allowed literal values or a range, when constrained. */
  allowed?: readonly (string | number)[] | { min?: number; max?: number };
  default?: string | number | boolean | null;
  notes?: string;
}

export interface ComponentMeta {
  component: string;
  file: string;
  purpose: string;
  props: Record<string, PropSpec>;
  variants?: Record<string, { description: string; when: string }>;
  states: readonly string[];
  layout: {
    /** Grid columns spanned in the 12-column bento, per breakpoint. */
    span?: Partial<Record<Breakpoint, number>>;
    minWidthPx?: number;
    maxWidthPx?: number;
    minHeightPx?: number;
    /** What happens to overflowing content. */
    overflow: string;
  };
  data: {
    source: string;
    /** Always true — nothing in the dashboard writes. */
    readOnly: true;
    permissions: string;
  };
  a11y: readonly string[];
  /** Hard rules: break one and the UI breaks. */
  safety: readonly string[];
}
