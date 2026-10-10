/**
 * Which palette the dashboard shows: "pearl" (light) or "black" (Matte Black).
 *
 * The desk decides, the dashboard follows. fps_theme.js stamps
 * html[data-fps-theme="pearl" | "black"] from the user's own Frappe theme
 * (html[data-theme], resolved light/dark), so reading that attribute keeps the
 * dashboard and the desk around it one material. Where the desk theme is off
 * (dev harness, a page outside the FPS tile) the Frappe theme is used directly.
 *
 * The tokens hang off the .fps-cc app and portal roots (styles/theme.css), so
 * the palette is applied by stamping data-palette on those roots -- they live
 * in our own shadow roots, outside React, which is why this is a small
 * observer module rather than component state. One observer per page, however
 * many dashboards are mounted.
 */
import { useSyncExternalStore } from "react";

export type Palette = "pearl" | "black";

export function currentPalette(): Palette {
  const html = document.documentElement;
  const stamped = html.getAttribute("data-fps-theme");
  if (stamped === "black" || stamped === "pearl") return stamped;
  return html.getAttribute("data-theme") === "dark" ? "black" : "pearl";
}

const roots = new Set<HTMLElement>();
const listeners = new Set<() => void>();
let observer: MutationObserver | null = null;
let last: Palette | null = null;

function sync(): void {
  const palette = currentPalette();
  roots.forEach((el) => {
    if (el.getAttribute("data-palette") !== palette) el.setAttribute("data-palette", palette);
  });
  if (palette !== last) {
    last = palette;
    listeners.forEach((fn) => fn());
  }
}

function ensureObserver(): void {
  if (observer || typeof MutationObserver !== "function") return;
  observer = new MutationObserver(sync);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-fps-theme", "data-theme"] });
}

function maybeStop(): void {
  if (roots.size === 0 && listeners.size === 0 && observer) {
    observer.disconnect();
    observer = null;
    last = null;
  }
}

/** Keep `el`'s data-palette in step with the desk; returns the untrack function. */
export function trackPalette(el: HTMLElement): () => void {
  roots.add(el);
  el.setAttribute("data-palette", currentPalette());
  ensureObserver();
  return () => {
    roots.delete(el);
    maybeStop();
  };
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  ensureObserver();
  return () => {
    listeners.delete(fn);
    maybeStop();
  };
}

/** The current palette, re-rendering when the user switches theme. */
export function usePalette(): Palette {
  return useSyncExternalStore(subscribe, currentPalette, () => "pearl");
}
