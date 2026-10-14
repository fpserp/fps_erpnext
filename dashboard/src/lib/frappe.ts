/**
 * Typed, READ-ONLY bridge to the Frappe desk globals (window.frappe).
 *
 * Contract (implemented by the core module — signatures are fixed):
 *  - call<T>(method, args): GET request to a whitelisted READ-ONLY method,
 *    resolves r.message. Only methods in READ_METHODS may be called.
 *  - navigate(route): in-app navigation to a desk URL such as
 *    "/app/job-order?fps_stage=In%20Progress" (route_options + set_route),
 *    falling back to location.assign when the router is unavailable.
 *  - newDoc(doctype): opens a blank form (frappe.new_doc). Nothing is saved
 *    until the user saves it themselves.
 *  - openThemeSwitcher(): opens Frappe's OWN Toggle Theme dialog (the one in
 *    the avatar menu). Nothing is saved by this module; if the user picks a
 *    theme there, Frappe saves it on their own profile exactly as it does
 *    from the avatar menu, and the palette follows (lib/palette.ts).
 *  - hasRole / currentUser / currency / onRouteChange: desk context.
 *
 * NEVER add a write helper here (set_value, insert, delete, submit, xcall to a
 * write method, POST). The presentation-only rule in DESIGN.md forbids it.
 *
 * Behaviour notes (Frappe v16.24.1, verified against its source):
 *  - frappe.call() pops desk dialogs for some failures (403/404/500/504) no
 *    matter what; `silent: true` at least suppresses the server-message
 *    msgprint, because the dashboard renders its own inline error state.
 *  - frappe.set_route() pushes only the PATH into history (router.js
 *    push_state); the list view then reads its filters from
 *    frappe.route_options because location.search is empty
 *    (list_view.js parse_filters_from_route_options). So filters must travel
 *    in route_options, as STRINGS: the list view JSON-parses a string value
 *    that looks like "[...]" into an operator filter, and uses "=" otherwise.
 *  - frappe.router.off() can never remove a handler: EventEmitterMixin.off
 *    unbinds a freshly created wrapper closure (event_emitter.js), so jQuery
 *    finds nothing to remove. We therefore attach ONE router listener per page
 *    and fan out to our own subscriber set, which we can unsubscribe from.
 */
export const READ_METHODS = [
  // FPS OPS Dashboard (Workspace "FPS"): every desk user, no money.
  "fps_erpnext.api.command_center.get_dashboard",
  "fps_erpnext.api.command_center.get_metric_detail",
  // FPS ACC Dashboard (Workspace "FPS ACC"): Accounts Manager only — the
  // server raises PermissionError for anyone else before reading anything.
  "fps_erpnext.api.acc_dashboard.get_dashboard",
  "fps_erpnext.api.acc_dashboard.get_metric_detail",
] as const;

export type ReadMethod = (typeof READ_METHODS)[number];

/* ------------------------------------------------------------------------ */
/* Minimal typing of the desk globals we touch. Deliberately partial: every   */
/* member is optional so a missing desk API degrades instead of throwing.     */
/* ------------------------------------------------------------------------ */

/** Body of a Frappe /api/method response (and of most error payloads). */
export interface FrappeResponse {
  message?: unknown;
  exc?: string;
  exc_type?: string;
  exception?: string;
  _server_messages?: string;
  _error_message?: string;
}

export interface FrappeCallOptions {
  method: string;
  args?: Record<string, unknown>;
  type?: "GET" | "POST";
  /** Suppress Frappe's msgprint of _server_messages. */
  silent?: boolean;
  callback?: (r: FrappeResponse) => void;
  /** Frappe passes a parsed body, a jqXHR or nothing, depending on the status. */
  error?: (r?: unknown) => void;
}

export interface FrappeRouter {
  current_route?: string[] | null;
  on?: (event: "change", handler: (data?: unknown) => void) => void;
  off?: (event: "change", handler: (data?: unknown) => void) => void;
}

export interface FrappeUser {
  name?: string;
  /** Frappe returns true or undefined, never false. */
  has_role?: (role: string | string[]) => boolean | undefined;
}

export interface FrappeGlobal {
  call?: (opts: FrappeCallOptions) => PromiseLike<unknown> | undefined | void;
  set_route?: (...route: unknown[]) => PromiseLike<unknown> | undefined | void;
  get_route?: () => unknown[] | null | undefined;
  new_doc?: (doctype: string, opts?: Record<string, unknown>) => PromiseLike<unknown> | undefined | void;
  route_options?: Record<string, unknown> | null;
  route_hash?: string | null;
  router?: FrappeRouter;
  user?: FrappeUser;
  /** frappe.ui.ThemeSwitcher: the desk's Light / Dark / Automatic dialog. */
  ui?: { ThemeSwitcher?: new () => { show?: () => void } };
  session?: { user?: string; user_email?: string; user_fullname?: string };
  boot?: {
    sysdefaults?: { currency?: string };
    user?: { roles?: string[]; full_name?: string; email?: string; name?: string };
  };
}

declare global {
  interface Window {
    frappe?: FrappeGlobal;
  }
}

/** Read lazily: the module may be evaluated before or after the desk boots. */
function desk(): FrappeGlobal | undefined {
  return typeof window === "undefined" ? undefined : window.frappe;
}

/* ------------------------------------------------------------------------ */
/* call()                                                                     */
/* ------------------------------------------------------------------------ */

/** An error from a read call, with a message fit to show in the UI. */
export class FrappeCallError extends Error {
  readonly method: string;
  readonly status?: number;
  readonly excType?: string;

  constructor(message: string, method: string, status?: number, excType?: string) {
    super(message);
    this.name = "FrappeCallError";
    this.method = method;
    this.status = status;
    this.excType = excType;
  }
}

const READ_METHOD_SET: ReadonlySet<string> = new Set(READ_METHODS);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function stripHtml(s: string): string {
  if (typeof DOMParser === "undefined") return s.replace(/<[^>]*>/g, "").trim();
  // DOMParser never executes scripts, so this is safe for server-sent HTML.
  return (new DOMParser().parseFromString(s, "text/html").body.textContent ?? "").trim();
}

/** _server_messages is a JSON list of JSON strings ({"message": "..."}) or plain strings. */
function serverMessages(raw: unknown): string[] {
  if (typeof raw !== "string" || !raw) return [];
  try {
    const list: unknown = JSON.parse(raw);
    if (!Array.isArray(list)) return [];
    return list
      .map((item) => {
        if (typeof item !== "string") return "";
        try {
          const parsed: unknown = JSON.parse(item);
          if (isRecord(parsed) && typeof parsed.message === "string") return stripHtml(parsed.message);
          return typeof parsed === "string" ? stripHtml(parsed) : "";
        } catch {
          return stripHtml(item);
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

/** "frappe.exceptions.PermissionError: Not permitted" -> "Not permitted". */
function exceptionText(exception: unknown): string {
  if (typeof exception !== "string" || !exception) return "";
  const idx = exception.indexOf(": ");
  return (idx >= 0 ? exception.slice(idx + 2) : exception).trim();
}

/**
 * Turn whatever Frappe handed the error callback (a parsed body, a jqXHR, an
 * Error or nothing) into one readable sentence.
 */
function toCallError(raw: unknown, method: string): FrappeCallError {
  if (raw instanceof FrappeCallError) return raw;
  const short = method.split(".").pop() ?? method;

  let body: Record<string, unknown> | null = null;
  let status: number | undefined;
  let statusText = "";
  if (isRecord(raw) && typeof raw.status === "number" && "readyState" in raw) {
    // A jqXHR: pull the JSON body out of it when there is one.
    status = raw.status;
    statusText = typeof raw.statusText === "string" ? raw.statusText : "";
    if (isRecord(raw.responseJSON)) body = raw.responseJSON;
    else if (typeof raw.responseText === "string") {
      try {
        const parsed: unknown = JSON.parse(raw.responseText);
        if (isRecord(parsed)) body = parsed;
      } catch {
        /* not JSON (proxy error page, timeout) */
      }
    }
  } else if (isRecord(raw)) {
    body = raw;
  }

  const excType = body && typeof body.exc_type === "string" ? body.exc_type : undefined;
  const text =
    (body && serverMessages(body._server_messages).join(" ")) ||
    (body && typeof body._error_message === "string" ? stripHtml(body._error_message) : "") ||
    (body && exceptionText(body.exception)) ||
    (raw instanceof Error ? raw.message : "") ||
    (typeof raw === "string" ? stripHtml(raw) : "");

  if (text) return new FrappeCallError(text, method, status, excType);
  if (status === 0) return new FrappeCallError("Could not reach the server. Check the connection.", method, status);
  if (status === 403) return new FrappeCallError("You do not have permission to see this.", method, status, excType);
  if (status) {
    return new FrappeCallError(`Could not load ${short} (HTTP ${status}${statusText ? ` ${statusText}` : ""}).`, method, status, excType);
  }
  return new FrappeCallError(`Could not load ${short}.`, method, status, excType);
}

/**
 * True for the server's "you may not read this" answer: frappe.PermissionError
 * (frappe.only_for, an HTTP 403 with exc_type "PermissionError"). The ACC
 * dashboard shows its calm no-access panel for it instead of an error.
 */
export function isPermissionError(err: unknown): boolean {
  if (!(err instanceof FrappeCallError)) return false;
  return err.excType === "PermissionError" || err.status === 403;
}

/**
 * GET a whitelisted READ-ONLY method and resolve its `message`.
 *
 * Throws synchronously for a method outside READ_METHODS: that is a
 * programming error the type system already forbids, and it must be loud.
 */
export function call<T>(method: ReadMethod, args?: Record<string, unknown>): Promise<T> {
  if (!READ_METHOD_SET.has(method)) {
    throw new Error(`fps-command-center: "${String(method)}" is not an allowed read-only method.`);
  }
  const frappe = desk();
  if (typeof frappe?.call !== "function") {
    return Promise.reject(new FrappeCallError("The ERPNext desk is not ready (frappe.call is missing).", method));
  }
  const frappeCall = frappe.call;

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const ok = (value: unknown) => {
      if (settled) return;
      settled = true;
      resolve(value as T);
    };
    const fail = (raw: unknown) => {
      if (settled) return;
      settled = true;
      reject(toCallError(raw, method));
    };

    let request: PromiseLike<unknown> | undefined | void;
    try {
      request = frappeCall({
        method,
        args: { ...(args ?? {}) },
        type: "GET",
        silent: true,
        callback: (r) => {
          if (isRecord(r) && r.exc) fail(r);
          else ok(isRecord(r) ? r.message : undefined);
        },
        error: (r) => fail(r),
      });
    } catch (err) {
      fail(err);
      return;
    }

    // Belt and braces: Frappe skips the error callback for some failures
    // (QueryTimeoutError, QueryDeadlockError), but the jqXHR it returns always
    // settles. Our callbacks above normally win the race.
    if (request && typeof request.then === "function") {
      request.then(
        (data) => ok(isRecord(data) ? data.message : undefined),
        (xhr) => fail(xhr),
      );
    }
  });
}

/* ------------------------------------------------------------------------ */
/* Navigation                                                                 */
/* ------------------------------------------------------------------------ */

const DESK_PREFIX = /^\/(?:app|desk)(?:\/|$)/;

/** Resolve a DeskRoute ("/app/x?y", "/desk/x", or a bare "x/y") to a same-origin URL. */
function resolveDeskUrl(route: string): URL | null {
  const trimmed = route.trim();
  if (!trimmed) return null;
  try {
    // A bare sub-path ("job-order/view/report") is a desk route, not a site page.
    const absolute = /^[a-z][a-z0-9+.-]*:|^\/\//i.test(trimmed) || trimmed.startsWith("/") ? trimmed : `/desk/${trimmed}`;
    return new URL(absolute, window.location.origin);
  } catch {
    return null;
  }
}

/**
 * An href for an <a> that should also open in a new tab (middle/ctrl-click).
 * Uses the canonical v16 /desk prefix; the query string is kept, and a fresh
 * desk tab reads its list filters from it.
 */
export function deskHref(route: string): string {
  if (typeof window === "undefined") return route;
  const url = resolveDeskUrl(route);
  if (!url || url.origin !== window.location.origin) return route;
  const path = url.pathname.replace(/^\/app(?=\/|$)/, "/desk");
  return `${path}${url.search}${url.hash}`;
}

/** Navigate inside the desk. Never reloads the page when the router exists. */
export function navigate(route: string): void {
  const url = resolveDeskUrl(route);
  if (!url) {
    console.warn("fps-command-center: ignored an empty or invalid route", route);
    return;
  }
  if (url.origin !== window.location.origin) {
    // Every DeskRoute is internal; anything else is a data bug, not a link to follow.
    console.warn("fps-command-center: refused to navigate off-site", route);
    return;
  }

  const frappe = desk();
  if (!DESK_PREFIX.test(url.pathname) || typeof frappe?.set_route !== "function") {
    window.location.assign(`${url.pathname}${url.search}${url.hash}`);
    return;
  }

  // Strings only (see the file comment): "[...]" values become operator filters.
  const options: Record<string, string> = {};
  url.searchParams.forEach((value, key) => {
    options[key] = value; // a repeated key keeps the last value, like Frappe's own link handler
  });
  // Always overwrite: a stale route_options from an earlier page would otherwise
  // be applied as filters (or as defaults on a new form) at the destination.
  frappe.route_options = Object.keys(options).length > 0 ? options : null;
  if (url.hash) frappe.route_hash = url.hash;

  // Keep the path percent-encoded: set_route splits on "/" and decodes each
  // segment, so a name containing "/" (FPS/JO/2607/023) survives as %2F.
  const subPath = url.pathname.replace(DESK_PREFIX, "").replace(/\/+$/, "");
  try {
    const pending = frappe.set_route(subPath);
    if (pending && typeof pending.then === "function") {
      pending.then(undefined, (err: unknown) => console.error("fps-command-center: set_route failed", err));
    }
  } catch (err) {
    console.error("fps-command-center: set_route failed, falling back to a page load", err);
    window.location.assign(`${url.pathname}${url.search}${url.hash}`);
  }
}

/**
 * Open Frappe's own Toggle Theme dialog (frappe.ui.ThemeSwitcher, the same one
 * the avatar menu and Ctrl+Shift+G open). Returns false when the desk API is
 * missing (dev harness without a mock, a future Frappe without the class).
 */
export function openThemeSwitcher(): boolean {
  const Switcher = desk()?.ui?.ThemeSwitcher;
  if (typeof Switcher !== "function") return false;
  try {
    new Switcher().show?.();
    return true;
  } catch (err) {
    console.error("fps-command-center: theme dialog failed", err);
    return false;
  }
}

/** Open a blank "new" form (or Quick Entry dialog). Nothing is saved here. */
export function newDoc(doctype: string): void {
  const frappe = desk();
  if (typeof frappe?.new_doc === "function") {
    // A leftover route_options would pre-fill the new form; it must open blank.
    frappe.route_options = null;
    try {
      const pending = frappe.new_doc(doctype);
      if (pending && typeof pending.then === "function") {
        pending.then(undefined, (err: unknown) => console.error("fps-command-center: new_doc failed", err));
      }
    } catch (err) {
      console.error("fps-command-center: new_doc failed", err);
    }
    return;
  }
  navigate(`/desk/${doctype.toLowerCase().replace(/ /g, "-")}/new`);
}

/* ------------------------------------------------------------------------ */
/* Desk context                                                               */
/* ------------------------------------------------------------------------ */

/** True when the user has ANY of the roles. */
export function hasRole(...roles: string[]): boolean {
  if (roles.length === 0) return false;
  const frappe = desk();
  if (typeof frappe?.user?.has_role === "function") return Boolean(frappe.user.has_role(roles));
  const held = frappe?.boot?.user?.roles ?? [];
  return roles.some((role) => held.includes(role));
}

export function currentUser(): { email: string; fullName: string } {
  const frappe = desk();
  const session = frappe?.session;
  const email = session?.user_email || session?.user || frappe?.boot?.user?.email || frappe?.boot?.user?.name || "";
  const fullName = session?.user_fullname || frappe?.boot?.user?.full_name || email;
  return { email, fullName };
}

/** Company default currency from frappe.boot.sysdefaults.currency ("AED"). */
export function currency(): string {
  const code = desk()?.boot?.sysdefaults?.currency;
  return typeof code === "string" && code.trim() ? code.trim() : "AED";
}

/** The current desk route, e.g. ["Workspaces", "FPS"] or ["List", "Job Order", "List"]. */
export function getRoute(): string[] {
  const frappe = desk();
  let route: unknown[] | null | undefined;
  try {
    route = typeof frappe?.get_route === "function" ? frappe.get_route() : frappe?.router?.current_route;
  } catch {
    route = null;
  }
  if (!Array.isArray(route)) return [];
  // Route segments can be objects (list route_options); keep the strings only.
  return route.filter((part): part is string => typeof part === "string");
}

const routeSubscribers = new Set<(route: string[]) => void>();
let routerHooked = false;

function hookRouter(): void {
  if (routerHooked) return;
  const router = desk()?.router;
  if (typeof router?.on !== "function") return; // retried on the next subscribe
  router.on("change", () => {
    const route = getRoute();
    for (const cb of Array.from(routeSubscribers)) {
      try {
        cb(route);
      } catch (err) {
        console.error("fps-command-center: route listener failed", err);
      }
    }
  });
  routerHooked = true;
}

/** Subscribe to desk route changes; returns an unsubscribe function. */
export function onRouteChange(cb: (route: string[]) => void): () => void {
  hookRouter();
  routeSubscribers.add(cb);
  return () => {
    routeSubscribers.delete(cb);
  };
}
