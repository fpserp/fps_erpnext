/**
 * Shadow-root plumbing. The dashboard renders inside its OWN shadow root (the
 * <fps-command-center> element that mount() puts in the FPS Overview block),
 * and its Radix portals (Sheet, Tooltip) render into a SECOND shadow root: the
 * body-level <fps-cc-portal> host (z-index 1030). The portal cannot live inside
 * the block: EditorJS makes `.codex-editor` a stacking context at z-index 1, so
 * anything fixed-positioned inside the block paints under the desk's sticky
 * page head (6), navbar (1019) and sidebar (1020), whatever its own z-index.
 *
 * Contract (implemented by main.tsx):
 *  - <ShadowProvider host shadowRoot portalContainer> wraps the app.
 *  - usePortalContainer(): HTMLElement | null — pass as `container` to every
 *    Radix Portal (SheetPortal, TooltipPortal).
 *  - useHostVisible(): boolean — false while the workspace page is hidden or
 *    the host is detached (pause polling, skip work).
 *  - <LayerDismissProvider> + useDismissSignal(): a counter that goes up when
 *    the desk route LEAVES the workspace the dashboard lives on. The body-level
 *    portal host is outside the page container Frappe hides on navigation, so
 *    every overlay (drawer, tooltip) must close itself on that signal or it
 *    would stay on screen over the next list or form.
 *
 * Why visibility needs its own store: Frappe never unmounts the block when you
 * leave the workspace. Going to a list and back only hides and shows the shared
 * page container (workspace.js returns early for the same page), and switching
 * workspaces discards the block's DOM with no teardown hook (the custom
 * element's disconnectedCallback is the teardown). So "visible" is derived from
 * the DOM — connected, rendered, tab in front — and re-checked on the events
 * that can change it, plus a cheap 5 s guard for anything we miss.
 */
import * as React from "react";
import { getRoute, onRouteChange } from "@/lib/frappe";

export interface ShadowContextValue {
  host: HTMLElement | null;
  shadowRoot: ShadowRoot | null;
  portalContainer: HTMLElement | null;
}

const EMPTY: ShadowContextValue = { host: null, shadowRoot: null, portalContainer: null };

const ShadowContext = React.createContext<ShadowContextValue>(EMPTY);
ShadowContext.displayName = "FpsShadowContext";

export function ShadowProvider(props: ShadowContextValue & { children: React.ReactNode }): React.JSX.Element {
  const { host, shadowRoot, portalContainer, children } = props;
  const value = React.useMemo<ShadowContextValue>(
    () => ({ host, shadowRoot, portalContainer }),
    [host, shadowRoot, portalContainer],
  );
  return <ShadowContext value={value}>{children}</ShadowContext>;
}

export function usePortalContainer(): HTMLElement | null {
  return React.useContext(ShadowContext).portalContainer;
}

export function useShadowContext(): ShadowContextValue {
  return React.useContext(ShadowContext);
}

/**
 * The element that really has focus, looking through open shadow roots (any
 * depth: the desk's block root → <fps-command-center>'s root, or the portal
 * host's root). document.activeElement stops at the outermost shadow HOST,
 * which is why Radix's own focus management cannot see focus inside the
 * dashboard (see sheet.tsx).
 */
export function getDeepActiveElement(root: Document | ShadowRoot = document): Element | null {
  let active: Element | null = root.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  return active;
}

/* ------------------------------------------------------------------------ */
/* Overlay dismissal on route leave                                           */
/* ------------------------------------------------------------------------ */

const DismissContext = React.createContext(0);
DismissContext.displayName = "FpsDismissSignal";

/**
 * The workspace route the dashboard was mounted on; `fallback` (the variant's
 * own workspace: "FPS" or "FPS ACC") when the route is not a workspace yet.
 */
function homeWorkspace(route: readonly string[], fallback: string): string {
  return route[0] === "Workspaces" && route[1] ? route[1] : fallback;
}

/** True when the desk route is the dashboard's workspace (Workspaces/<name>). */
export function isOnWorkspace(route: readonly string[], workspace: string): boolean {
  return route[0] === "Workspaces" && route[1] === workspace;
}

/**
 * Bumps a counter every time the desk route changes to something that is not
 * the dashboard's own workspace. Overlays (Sheet, Tooltip) close on a bump.
 * One router subscription per mounted dashboard, released on unmount.
 */
export function LayerDismissProvider({
  workspace = "FPS",
  children,
}: {
  /** The dashboard's own workspace, used when the route at mount is not a workspace. */
  workspace?: string;
  children: React.ReactNode;
}): React.JSX.Element {
  const [epoch, setEpoch] = React.useState(0);
  React.useEffect(() => {
    const home = homeWorkspace(getRoute(), workspace);
    return onRouteChange((route) => {
      if (!isOnWorkspace(route, home)) setEpoch((n) => n + 1);
    });
  }, [workspace]);
  return <DismissContext value={epoch}>{children}</DismissContext>;
}

/** Changes whenever open overlays must close (the route left the workspace). */
export function useDismissSignal(): number {
  return React.useContext(DismissContext);
}

/* ------------------------------------------------------------------------ */
/* Host visibility store — one per host, shared by every hook that asks.     */
/* ------------------------------------------------------------------------ */

const GUARD_INTERVAL_MS = 5000;
/** The desk renders a different workspace asynchronously after the route event. */
const ROUTE_SETTLE_MS = 300;

function computeVisible(host: HTMLElement | null): boolean {
  if (typeof document === "undefined") return false;
  if (document.visibilityState !== "visible") return false;
  if (!host) return true; // outside a block (tests, storybook-like use): only the tab matters
  // getClientRects() is empty when the host or an ancestor is display:none,
  // which is how Frappe hides an inactive page. (offsetParent is null for
  // position:fixed too, so it would misreport.)
  return host.isConnected && host.getClientRects().length > 0;
}

interface VisibilityStore {
  subscribe: (notify: () => void) => () => void;
  getSnapshot: () => boolean;
}

const stores = new WeakMap<HTMLElement, VisibilityStore>();
let detachedStore: VisibilityStore | null = null;

function createVisibilityStore(host: HTMLElement | null): VisibilityStore {
  const listeners = new Set<() => void>();
  // Cached so getSnapshot never forces a layout during React's render phase.
  let value = computeVisible(host);
  let teardown: (() => void) | null = null;

  const recompute = () => {
    const next = computeVisible(host);
    if (next === value) return;
    value = next;
    for (const notify of Array.from(listeners)) notify();
  };

  const start = () => {
    const timers = new Set<number>();
    const onVisibility = () => recompute();
    document.addEventListener("visibilitychange", onVisibility);
    const offRoute = onRouteChange(() => {
      recompute();
      const t = window.setTimeout(() => {
        timers.delete(t);
        recompute();
      }, ROUTE_SETTLE_MS);
      timers.add(t);
    });
    const guard = window.setInterval(recompute, GUARD_INTERVAL_MS);
    teardown = () => {
      document.removeEventListener("visibilitychange", onVisibility);
      offRoute();
      window.clearInterval(guard);
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
    };
  };

  return {
    subscribe(notify) {
      listeners.add(notify);
      if (listeners.size === 1) {
        value = computeVisible(host); // may have changed while nobody listened
        start();
      }
      return () => {
        listeners.delete(notify);
        if (listeners.size === 0 && teardown) {
          teardown();
          teardown = null;
        }
      };
    },
    getSnapshot: () => value,
  };
}

function storeFor(host: HTMLElement | null): VisibilityStore {
  if (!host) {
    detachedStore ??= createVisibilityStore(null);
    return detachedStore;
  }
  let store = stores.get(host);
  if (!store) {
    store = createVisibilityStore(host);
    stores.set(host, store);
  }
  return store;
}

/**
 * host.isConnected && tab visible && host rendered (not inside a display:none
 * page). Re-evaluated on visibilitychange, on desk route change (now and once
 * the page settles) and every 5 s while anything is subscribed.
 */
export function useHostVisible(): boolean {
  const { host } = useShadowContext();
  const store = storeFor(host);
  return React.useSyncExternalStore(store.subscribe, store.getSnapshot, () => false);
}
