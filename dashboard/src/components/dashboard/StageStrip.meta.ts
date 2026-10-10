import type { ComponentMeta } from "./meta.types";

/**
 * Contract of StageStrip (StageStrip.tsx). Change this file and the component
 * in the same commit.
 */
export const meta = {
  component: "StageStrip",
  file: "dashboard/src/components/dashboard/StageStrip.tsx",
  purpose:
    "'Pipeline now' glass card: the existing FPS Overview tiles (fps_erpnext.api.pipeline.get_overview) as rows — label, note, count, a thin proportional bar and a chevron — each linking to the list behind it, with the footnotes underneath and the '<n> stages' meta. Replaces the old Overview strip without dropping anything it showed.",
  props: {
    stages: {
      type: "Stages",
      required: true,
      notes: "payload.stages: { tiles: StageTile[] (0–7, server order), footnotes: string[] }. Render every tile and footnote exactly as sent.",
    },
    className: { type: "string", required: false },
  },
  variants: {
    rows: { description: "One link row per tile.", when: "tiles.length > 0." },
    empty: { description: "'No stages are visible to you.'", when: "tiles is empty (viewer cannot read any stage doctype)." },
  },
  states: ["default", "row-hover", "row-focus-visible", "empty", "no-footnotes"],
  layout: {
    span: { sm: 12, md: 12, lg: 4, xl: 4 },
    minWidthPx: 288,
    minHeightPx: 440,
    overflow:
      "Label and note truncate (full text in title); the count never does. Footnotes wrap. Rows never scroll horizontally. Padding 16px while the bento is under 480px wide, 24px from 480px.",
  },
  data: {
    source: "payload.stages (built by get_dashboard from fps_erpnext.api.pipeline.get_overview).",
    readOnly: true,
    permissions: "Tiles whose doctype the viewer cannot read are omitted by the server (never sent as 0); footnotes are gated by read permission on their doctype.",
  },
  a11y: [
    "Each row is a real link (href = deskHref(route)): Enter activates, middle/Ctrl-click opens a new tab.",
    "Link name reads 'Enquiry, open: 37. Open list' (visible text first, WCAG 2.5.3).",
    "Bars and chevrons are aria-hidden; focus ring 2px Electric Blue.",
    "Footnotes are a labelled list ('Notes').",
  ],
  safety: [
    "Do not add a write call — rows only navigate.",
    "Keep every tile's label, note, count and EXACT route, and every footnote; do not re-order (server order is the pipeline order).",
    "Never invent a tile or show a zero for an omitted one (that would leak the existence of unreadable records).",
    "Bars are a single hue (--fps-electric) proportional to the largest count — never a value ramp or per-stage colours.",
    "Bars are 6px tall, square at the baseline and 4px-rounded at the data end only (DESIGN.md §6), matching the drawer's breakdown bars; the track carries the same radius so it never clips the bar start.",
  ],
} satisfies ComponentMeta;
