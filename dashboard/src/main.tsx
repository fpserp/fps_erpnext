/// <reference types="vite/client" />
/**
 * FPS Command Center — bundle entry.
 *
 * The FPS Overview Custom HTML Block's script (a short loader) imports this
 * module from /assets/fps_erpnext/dashboard/fps-command-center.js?v=<hash> and
 * calls mount(root_element, { mountPoint }). Frappe renders every Custom HTML
 * Block inside an OPEN shadow root (frappe.create_shadow_element), and that
 * root also holds a <link> to desk.bundle.css: Bootstrap 4 and the desk
 * utilities, UNLAYERED (they beat every Tailwind @layer rule) and partly
 * !important (.hidden, .border, .shadow*, .rounded, the 7px spacing scale).
 * So the dashboard never renders in Frappe's shadow root:
 *
 *  1. ITS OWN SHADOW ROOT. mount() inserts one <fps-command-center> element
 *     into the block's mount point. The element attaches its own open shadow
 *     root, adopts the shared stylesheet (one module-level CSSStyleSheet, or a
 *     <style> where constructable sheets are missing), creates the React root
 *     in connectedCallback and unmounts it in disconnectedCallback. Frappe
 *     discards the block's DOM with no teardown hook (workspace switch, Edit
 *     toggle, Save, Discard); disconnectedCallback IS the teardown. Frappe's
 *     own shadow root is left exactly as Frappe built it.
 *  2. A BODY-LEVEL PORTAL HOST. Radix portals (the drawer, tooltips) render
 *     into ONE <fps-cc-portal> appended to document.body: position:fixed, 0×0,
 *     z-index 1030 — above the desk sidebar (1020) and navbar (1019), below
 *     Bootstrap modals (1040/1050). Inside the block they could never rise
 *     above the navbar: EditorJS makes .codex-editor a stacking context at
 *     z-index 1. The host has its own shadow root with the same stylesheet,
 *     is reference-counted across mounted dashboards and is removed when the
 *     last one disconnects. Because it lives outside the page container the
 *     desk hides on navigation, overlays close when the route leaves the
 *     workspace (LayerDismissProvider in lib/shadow.tsx) and on unmount.
 *  3. KEYDOWN GUARD on both shadow roots: Frappe's workspace shortcuts (a-z
 *     opens the awesomebar, shift+t the System Console …) check
 *     document.activeElement, which is the shadow HOST while the user types in
 *     a dashboard input. Keydown from an input/select/textarea/contenteditable
 *     stops at the shadow root; React (listening on its own containers) and
 *     Radix's Escape handling (document capture phase) are unaffected.
 *  4. CSS. theme.css is compiled at build time with the @property rewrite in
 *     vite.config.ts (tailwindShadowDom): nothing is registered on the
 *     document, so there is no desk-wide side effect.
 *  5. Idempotent. mount() on a shadow root that already holds a dashboard
 *     returns the existing handle. A registry on globalThis (shared by every
 *     copy of the bundle) backs unmountAll().
 *
 * Exports (the loader relies on these): mount(shadowRoot, { mountPoint }),
 * unmountAll(), version. The same three are put on window.FPSCommandCenter
 * when the module runs, so a loader that looks for a global gets the real API;
 * this file is an ES module, so a classic <script> / frappe.require load fails
 * loudly (SyntaxError on `export`) rather than silently.
 *
 * Presentation only: nothing reachable from here writes to ERPNext.
 */
import { Component, Fragment, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import CommandCenter from "@/components/dashboard/CommandCenter";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LayerDismissProvider, ShadowProvider } from "@/lib/shadow";
import themeCss from "./styles/theme.css?inline";

declare const __FPS_CC_VERSION__: string;

/** Bundle version (package.json "version"; "-dev" under the Vite dev server). */
export const version: string = __FPS_CC_VERSION__;

export interface MountOptions {
  /**
   * The block's placeholder (<div data-fps="cc-root">). The <fps-command-center>
   * element replaces its children while mounted (they come back on unmount()).
   * Defaults to the shadow root's [data-fps="cc-root"]; without one, the element
   * is appended to the shadow root.
   */
  mountPoint?: HTMLElement | null;
}

export interface MountHandle {
  unmount(): void;
}

export interface FpsCommandCenterApi {
  mount: typeof mount;
  unmountAll: typeof unmountAll;
  version: string;
}

declare global {
  interface Window {
    FPSCommandCenter?: FpsCommandCenterApi;
  }
}

const ELEMENT_TAG = "fps-command-center";
const PORTAL_TAG = "fps-cc-portal";

/**
 * Root classes of the app and the portal containers, written out in full so
 * Tailwind finds them. The desk's <body> sets letter-spacing .02em,
 * text-align left and font-variation-settings "opsz" 24, which all inherit
 * through shadow boundaries: tracking and alignment are reset to the design's,
 * and the optical size is pinned to the desk's so Inter renders identically
 * inside and outside the dashboard (Tailwind's preflight would reset it to
 * "normal" on :host). No `dark` class: Pearl is a light scheme (theme.css sets
 * color-scheme: light), so shadcn's dark: variants must stay off.
 */
const APP_ROOT_CLASS = "fps-cc tracking-normal text-start [font-variation-settings:'opsz'_24]";
const PORTAL_ROOT_CLASS = "fps-cc fps-cc-portal tracking-normal text-start [font-variation-settings:'opsz'_24]";

/** Inline, so no desk stylesheet can move it: fixed, no box, above the chrome, below modals. */
const PORTAL_HOST_STYLE = "position:fixed;top:0;left:0;width:0;height:0;overflow:visible;z-index:1030";

/* ------------------------------------------------------------------------ */
/* Styles: one compiled sheet, adopted by every shadow root we own            */
/* ------------------------------------------------------------------------ */

/** The compiled theme; replaced in place by dev HMR. */
let currentCss: string = themeCss;
/** undefined = not attempted yet; null = constructable sheets unavailable. */
let sharedSheet: CSSStyleSheet | null | undefined;
const fallbackStyles = new Set<HTMLStyleElement>();

function getSharedSheet(): CSSStyleSheet | null {
  if (sharedSheet !== undefined) return sharedSheet;
  sharedSheet = null;
  const supported =
    typeof ShadowRoot !== "undefined" &&
    "adoptedStyleSheets" in ShadowRoot.prototype &&
    typeof CSSStyleSheet !== "undefined" &&
    "replaceSync" in CSSStyleSheet.prototype;
  if (!supported) return null;
  try {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(currentCss);
    sharedSheet = sheet;
  } catch (err) {
    console.warn("fps-command-center: constructable stylesheet failed, using <style>", err);
  }
  return sharedSheet;
}

/** Give one of OUR shadow roots the dashboard CSS; returns the undo for a fallback <style>. */
function adoptStyles(root: ShadowRoot): () => void {
  const sheet = getSharedSheet();
  if (sheet) {
    if (!root.adoptedStyleSheets.includes(sheet)) root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
    return () => {};
  }
  let style = Array.from(root.children).find(
    (child): child is HTMLStyleElement => child instanceof HTMLStyleElement && child.dataset.fpsCc === "styles",
  );
  if (!style) {
    style = document.createElement("style");
    style.setAttribute("data-fps-cc", "styles");
    style.textContent = currentCss;
    root.prepend(style);
  }
  const el = style;
  fallbackStyles.add(el);
  return () => {
    fallbackStyles.delete(el);
  };
}

if (import.meta.hot) {
  // Dev only (stripped from the build): restyle live roots without a reload.
  import.meta.hot.accept("./styles/theme.css?inline", (mod) => {
    const next = (mod as { default?: unknown } | undefined)?.default;
    if (typeof next !== "string") return;
    currentCss = next;
    if (sharedSheet) sharedSheet.replaceSync(next);
    fallbackStyles.forEach((style) => {
      style.textContent = next;
    });
  });
}

/* ------------------------------------------------------------------------ */
/* Keydown guard                                                              */
/* ------------------------------------------------------------------------ */

const EDITABLE = 'input, select, textarea, [contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]';

/**
 * Stop keydown from editable targets at the shadow root, so the desk's
 * window-level shortcut handler never sees keys typed into a dashboard field.
 * composedPath()[0] is the real target (event.target is retargeted to the host
 * outside the root).
 */
function guardKeydown(event: Event): void {
  const target = event.composedPath()[0];
  if (!(target instanceof Element)) return;
  if (target.matches(EDITABLE) || (target instanceof HTMLElement && target.isContentEditable === true)) {
    event.stopPropagation();
  }
}

/* ------------------------------------------------------------------------ */
/* Body-level portal host (one per bundle copy, reference-counted)            */
/* ------------------------------------------------------------------------ */

interface PortalHost {
  host: HTMLElement;
  container: HTMLElement;
  refs: number;
  releaseStyles: () => void;
}

let portalHost: PortalHost | null = null;

function acquirePortal(): { container: HTMLElement; release: () => void } {
  if (!portalHost || !portalHost.host.isConnected) {
    if (portalHost) {
      portalHost.host.remove();
      portalHost.releaseStyles();
    }
    const host = document.createElement(PORTAL_TAG);
    host.setAttribute("data-fps-cc", "portal-host");
    host.setAttribute("style", PORTAL_HOST_STYLE);
    const root = host.attachShadow({ mode: "open" });
    const releaseStyles = adoptStyles(root);
    root.addEventListener("keydown", guardKeydown);
    const container = document.createElement("div");
    container.className = PORTAL_ROOT_CLASS;
    container.setAttribute("data-fps-cc", "portal");
    root.append(container);
    document.body.append(host);
    portalHost = { host, container, refs: 0, releaseStyles };
  }
  const acquired = portalHost;
  acquired.refs += 1;
  let released = false;
  return {
    container: acquired.container,
    release() {
      if (released) return;
      released = true;
      acquired.refs -= 1;
      if (acquired.refs > 0 || portalHost !== acquired) return;
      acquired.host.remove();
      acquired.releaseStyles();
      portalHost = null;
    },
  };
}

/* ------------------------------------------------------------------------ */
/* Registry (shared by every copy of the bundle on the page)                  */
/* ------------------------------------------------------------------------ */

interface MountRecord {
  readonly element: HTMLElement;
  readonly handle: MountHandle;
}

interface Registry {
  /** Dashboards whose React root is live (connected element). */
  records: Set<MountRecord>;
  /** Mount counter: distinct useId() prefixes per mount. */
  seq: number;
}

const REGISTRY_KEY = Symbol.for("fps.command-center.registry");
const CONTROLLER = Symbol.for("fps.command-center.controller");
const HANDLE = Symbol.for("fps.command-center.handle");

function registry(): Registry {
  const g = globalThis as typeof globalThis & { [REGISTRY_KEY]?: Registry };
  return (g[REGISTRY_KEY] ??= { records: new Set(), seq: 0 });
}

/** Unmount every live dashboard on the page (debugging, tests). */
export function unmountAll(): void {
  for (const record of Array.from(registry().records)) record.handle.unmount();
}

/* ------------------------------------------------------------------------ */
/* The custom element                                                         */
/* ------------------------------------------------------------------------ */

/**
 * What an <fps-command-center> element does when the DOM connects or
 * disconnects it. Set on the instance by the bundle copy that mounted it, so
 * the element class (defined once per page, by whichever copy came first)
 * stays a thin shell.
 */
interface Controller {
  connected(element: HTMLElement): void;
  disconnected(element: HTMLElement): void;
  /** Synchronous teardown (handle.unmount, unmountAll). */
  teardown(): void;
}

type DashboardElement = HTMLElement & { [CONTROLLER]?: Controller; [HANDLE]?: MountHandle };

function defineElement(): void {
  if (customElements.get(ELEMENT_TAG)) return;
  customElements.define(
    ELEMENT_TAG,
    class FpsCommandCenterElement extends HTMLElement {
      connectedCallback(): void {
        (this as DashboardElement)[CONTROLLER]?.connected(this);
      }
      disconnectedCallback(): void {
        (this as DashboardElement)[CONTROLLER]?.disconnected(this);
      }
    },
  );
}

/**
 * Last line of defence: without it, an exception while rendering would unmount
 * the whole tree and leave a silent empty gap on the FPS home page. Shows one
 * calm line instead; the details go to the console.
 */
class CrashBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("fps-command-center: the dashboard crashed", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="glass rounded-xl p-6 text-sm text-ink-secondary">
        The dashboard could not be shown. Reload the page to try again; the rest of the workspace works as usual.
      </div>
    );
  }
}

/** StrictMode double-invokes effects in development only; production renders once. */
const DevStrict = import.meta.env.DEV ? StrictMode : Fragment;

function createController(handle: () => MountHandle): Controller {
  let stop: (() => void) | null = null;
  // Bumped by every connect/disconnect: a pending teardown only runs if it is
  // still the latest thing that happened to the element.
  let generation = 0;

  const start = (element: HTMLElement): (() => void) => {
    const reg = registry();
    const shadowRoot = element.shadowRoot ?? element.attachShadow({ mode: "open" });
    const releaseStyles = adoptStyles(shadowRoot);
    shadowRoot.addEventListener("keydown", guardKeydown);

    const appRoot = document.createElement("div");
    appRoot.className = APP_ROOT_CLASS;
    appRoot.setAttribute("data-fps-cc", "app");
    shadowRoot.append(appRoot);

    const portal = acquirePortal();
    reg.seq += 1;
    const reactRoot = createRoot(appRoot, {
      // Distinct useId() prefixes per mount keep aria and SVG ids unique if a
      // page ever shows two dashboards.
      identifierPrefix: `fpscc${reg.seq}-`,
      onUncaughtError: (error) => console.error("fps-command-center: render failed", error),
    });
    reactRoot.render(
      <DevStrict>
        <ShadowProvider host={element} shadowRoot={shadowRoot} portalContainer={portal.container}>
          <LayerDismissProvider>
            <TooltipProvider delayDuration={200}>
              <CrashBoundary>
                <CommandCenter />
              </CrashBoundary>
            </TooltipProvider>
          </LayerDismissProvider>
        </ShadowProvider>
      </DevStrict>,
    );

    const record: MountRecord = { element, handle: handle() };
    reg.records.add(record);

    return () => {
      reg.records.delete(record);
      try {
        reactRoot.unmount(); // also unmounts the portalled drawer and tooltips
      } catch (err) {
        console.error("fps-command-center: unmount failed", err);
      }
      appRoot.remove();
      shadowRoot.removeEventListener("keydown", guardKeydown);
      releaseStyles();
      portal.release();
    };
  };

  const runStop = () => {
    const current = stop;
    stop = null;
    current?.();
  };

  return {
    connected(element) {
      generation += 1; // cancels a teardown queued by a disconnect in the same task (a DOM move)
      if (!stop) stop = start(element);
    },
    disconnected(element) {
      const mine = (generation += 1);
      // Deferred one microtask: a move (remove + insert) reconnects before it
      // runs and keeps the live root; a real removal unmounts.
      queueMicrotask(() => {
        if (mine === generation && !element.isConnected) runStop();
      });
    },
    teardown() {
      generation += 1;
      runStop();
    },
  };
}

/* ------------------------------------------------------------------------ */
/* mount()                                                                    */
/* ------------------------------------------------------------------------ */

export function mount(shadowRoot: ShadowRoot, options?: MountOptions): MountHandle {
  if (typeof ShadowRoot === "undefined" || !(shadowRoot instanceof ShadowRoot)) {
    throw new TypeError("fps-command-center: mount() needs the block's shadow root (root_element).");
  }
  defineElement();

  // Idempotent: one dashboard per block shadow root.
  const existing = shadowRoot.querySelector<DashboardElement>(ELEMENT_TAG);
  if (existing) {
    const known = existing[HANDLE];
    if (known) return known;
    const adopted: MountHandle = {
      unmount() {
        existing[CONTROLLER]?.teardown();
        existing.remove();
      },
    };
    existing[HANDLE] = adopted;
    return adopted;
  }

  const requested = options?.mountPoint ?? shadowRoot.querySelector<HTMLElement>('[data-fps="cc-root"]');
  const mountPoint = requested && requested.getRootNode() === shadowRoot ? requested : null;
  if (requested && !mountPoint) {
    console.warn("fps-command-center: mountPoint is not inside this shadow root; appending to the root instead.");
  }

  const element = document.createElement(ELEMENT_TAG) as DashboardElement;
  let unmounted = false;
  let placeholder: ChildNode[] = [];
  const handle: MountHandle = {
    unmount() {
      if (unmounted) return;
      unmounted = true;
      element[CONTROLLER]?.teardown();
      element.remove();
      // Give the block its placeholder back (only if nothing else took the spot).
      if (mountPoint && mountPoint.childNodes.length === 0) mountPoint.append(...placeholder);
      placeholder = [];
    },
  };
  element[HANDLE] = handle;
  // Set before insertion: inserting into a connected tree runs connectedCallback.
  element[CONTROLLER] = createController(() => handle);

  if (mountPoint) {
    placeholder = Array.from(mountPoint.childNodes);
    mountPoint.replaceChildren(element);
  } else {
    shadowRoot.append(element);
  }
  return handle;
}

if (typeof window !== "undefined") {
  window.FPSCommandCenter = { mount, unmountAll, version };
}
