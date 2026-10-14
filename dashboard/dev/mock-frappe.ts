/**
 * DEV HARNESS ONLY — a stand-in for the slice of window.frappe the dashboard
 * uses (see FrappeGlobal in src/lib/frappe.ts). Nothing here talks to a server.
 *
 *  call()      serves dev/fixtures/*.json after ~400 ms:
 *              FPS OPS (command_center.*) - the same payload for every viewer:
 *                get_dashboard(period)                 -> dashboard.<period>.json
 *                get_metric_detail(key, period)        -> metric_detail.<key>.<period>.json
 *                get_metric_detail(key, period, dim)   -> the first of
 *                    metric_detail.<key>.<period>.<slug(dim)>.json  (slug: "CC - Customs Clearance" -> "cc-customs-clearance")
 *                    metric_detail.<key>.<period>.dimension.json   (only if its "dimension" equals dim)
 *                    metric_detail.<key>.<period>.json             (unfiltered sample, logged as such)
 *              FPS ACC (acc_dashboard.*) - Accounts Manager only, like the API:
 *                a viewer without that role gets frappe.PermissionError
 *                (exc_type "PermissionError", as frappe.only_for raises it);
 *                get_dashboard(period)                 -> acc.dashboard.<period>[.<scenario>].json
 *                get_metric_detail(key, period[, dim]) -> acc.metric_detail.<key>.<period>… (same fallbacks)
 *              viewer = "finance" (default: Accounts Manager) or "ops"
 *              (?viewer=ops: no Accounts roles). ?scenario=edge serves the
 *              ACC stress page (acc.dashboard.<period>.edge.json).
 *              ?fail=1 (or the toolbar toggle) answers every call with an error,
 *              shaped like Frappe's (417 + _server_messages).
 *  set_route / new_doc   log, show a toast, and do NOT navigate.
 *  router      a tiny emitter with on / off / trigger (unlike Frappe's, off works).
 *  session     placeholder users only (finance.viewer@example.com,
 *              ops.viewer@example.com), matching the fixtures' full_name.
 */
import type { FrappeCallOptions, FrappeGlobal, FrappeResponse } from "@/lib/frappe";

export type Viewer = "finance" | "ops";

export interface MockOptions {
  viewer: Viewer;
  fail: boolean;
  /** The desk route the page starts on, e.g. ["Workspaces", "FPS ACC"]. */
  route?: string[];
  /** ACC fixture scenario: "" (the default page) or "edge". */
  scenario?: string;
  /** Shown as a toast by the harness shell. */
  notify: (message: string) => void;
  /** Called by new_doc so the shell can open a fake Quick Entry dialog. */
  onNewDoc?: (doctype: string) => void;
  latencyMs?: number;
}

export interface MockController {
  readonly frappe: FrappeGlobal;
  /** Simulate a desk route change (fires router "change"). */
  setRoute(route: string[]): void;
  setFail(fail: boolean): void;
  readonly fail: boolean;
  readonly viewer: Viewer;
  /** Number of call() requests served so far (shown in the toolbar). */
  readonly calls: number;
}

const FIXTURES = import.meta.glob<unknown>("./fixtures/*.json", { import: "default" });

const ROLES: Record<Viewer, string[]> = {
  finance: ["Desk User", "System Manager", "Accounts User", "Accounts Manager", "FPS Operations"],
  ops: ["Desk User", "FPS Operations"],
};

/**
 * Obvious placeholders: the harness never shows a real person or mailbox.
 * (example.com is reserved for documentation, RFC 2606.)
 */
const USERS: Record<Viewer, { email: string; name: string }> = {
  finance: { email: "finance.viewer@example.com", name: "Sample Finance User" },
  ops: { email: "ops.viewer@example.com", name: "Sample Ops User" },
};

function fixtureLoader(file: string): (() => Promise<unknown>) | undefined {
  return FIXTURES[`./fixtures/${file}`];
}

/** Frappe's error body for a ValidationError: _server_messages is JSON of JSON strings. */
function errorBody(message: string): FrappeResponse {
  return {
    exc_type: "ValidationError",
    exception: `frappe.exceptions.ValidationError: ${message}`,
    _server_messages: JSON.stringify([JSON.stringify({ message, indicator: "red" })]),
  };
}

/** What frappe.only_for("Accounts Manager") answers (HTTP 403 on the live site). */
function permissionBody(): FrappeResponse {
  const message = "This action is only allowed for Accounts Manager";
  return {
    exc_type: "PermissionError",
    exception: `frappe.exceptions.PermissionError: ${message}`,
    _server_messages: JSON.stringify([JSON.stringify({ message, title: "Not permitted", indicator: "red" })]),
  };
}

/** The role every acc_dashboard method checks first (fps_erpnext/api/acc_dashboard.py). */
const ACC_ROLE = "Accounts Manager";

interface Candidate {
  file: string;
  /** Reject a file whose content does not fit the request. */
  accept?: (data: unknown) => boolean;
  note?: string;
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function pickFixture(method: string, args: Record<string, unknown>, scenario: string): { candidates: Candidate[] } | { error: string } {
  const period = typeof args.period === "string" ? args.period : "7d";
  const prefix = method.startsWith("fps_erpnext.api.acc_dashboard.") ? "acc." : "";
  if (method === "fps_erpnext.api.command_center.get_dashboard") {
    return { candidates: [{ file: `dashboard.${period}.json` }] };
  }
  if (method === "fps_erpnext.api.acc_dashboard.get_dashboard") {
    const files: Candidate[] = [];
    if (scenario) files.push({ file: `acc.dashboard.${period}.${scenario}.json` });
    files.push({
      file: `acc.dashboard.${period}.json`,
      note: scenario ? `no "${scenario}" scenario fixture for ${period}; serving the default page` : undefined,
    });
    return { candidates: files };
  }
  if (method === "fps_erpnext.api.command_center.get_metric_detail" || method === "fps_erpnext.api.acc_dashboard.get_metric_detail") {
    const key = typeof args.key === "string" ? args.key : "";
    if (!key) return { error: "get_metric_detail needs a key" };
    const dim = typeof args.dimension === "string" && args.dimension ? args.dimension : null;
    const base = `${prefix}metric_detail.${key}.${period}`;
    if (!dim) return { candidates: [{ file: `${base}.json` }] };
    return {
      candidates: [
        { file: `${base}.${slug(dim)}.json` },
        {
          file: `${base}.dimension.json`,
          accept: (data) => typeof data === "object" && data !== null && (data as { dimension?: unknown }).dimension === dim,
        },
        { file: `${base}.json`, note: `no fixture for dimension "${dim}"; serving the unfiltered sample` },
      ],
    };
  }
  return { error: `The dev mock does not serve ${method}.` };
}

export function installMockFrappe(options: MockOptions): MockController {
  const latency = options.latencyMs ?? 400;
  let fail = options.fail;
  let calls = 0;
  let currentRoute: string[] = options.route ?? ["Workspaces", "FPS"];
  const scenario = options.scenario ?? "";

  const handlers = new Set<(data?: unknown) => void>();
  const router = {
    get current_route() {
      return currentRoute;
    },
    on(event: "change", handler: (data?: unknown) => void) {
      if (event === "change") handlers.add(handler);
    },
    off(event: "change", handler: (data?: unknown) => void) {
      if (event === "change") handlers.delete(handler);
    },
    trigger(event: "change") {
      if (event !== "change") return;
      for (const handler of Array.from(handlers)) handler(router);
    },
  };

  const roles = ROLES[options.viewer];
  const user = USERS[options.viewer];

  const frappe: FrappeGlobal = {
    call(opts: FrappeCallOptions) {
      calls += 1;
      const args = opts.args ?? {};
      const method = opts.method;
      const failNow = fail;
      return new Promise<unknown>((resolve, reject) => {
        window.setTimeout(async () => {
          let body: FrappeResponse;
          let ok = false;
          if (failNow) {
            body = errorBody("Simulated failure from the dev harness (?fail=1).");
          } else if (method.startsWith("fps_erpnext.api.acc_dashboard.") && !roles.includes(ACC_ROLE)) {
            // Like the live API: the role is checked before anything is read.
            body = permissionBody();
          } else {
            const pick = pickFixture(method, args, scenario);
            if ("error" in pick) {
              body = errorBody(pick.error);
            } else {
              body = errorBody(
                `Fixture dev/fixtures/${pick.candidates[pick.candidates.length - 1].file} is missing. ` +
                  "Generate the fixtures (dev/make_fixtures.py, see dashboard/README.md) or pick another period.",
              );
              for (const candidate of pick.candidates) {
                const load = fixtureLoader(candidate.file);
                if (!load) continue;
                try {
                  const data = await load();
                  if (candidate.accept && !candidate.accept(data)) continue;
                  if (candidate.note) console.info(`[mock frappe] ${candidate.note}`);
                  body = { message: data };
                  ok = true;
                } catch (err) {
                  body = errorBody(`Could not read dev/fixtures/${candidate.file}: ${String(err)}`);
                }
                break;
              }
            }
          }
          if (ok) {
            console.debug("[mock frappe] call", method, args, "->", body.message);
            opts.callback?.(body);
            resolve(body);
          } else {
            console.warn("[mock frappe] call failed", method, args, body);
            opts.error?.(body);
            reject(body);
          }
        }, latency);
      });
    },

    set_route(...route: unknown[]) {
      const target = route.map((part) => (typeof part === "string" ? part : JSON.stringify(part))).join(" / ");
      const filters = frappe.route_options ? ` with route_options ${JSON.stringify(frappe.route_options)}` : "";
      console.info(`[mock frappe] set_route(${target})${filters}`);
      options.notify(`set_route → ${target || "(home)"}${filters}`);
      frappe.route_options = null; // the list view consumes them
      return Promise.resolve();
    },

    get_route() {
      return currentRoute;
    },

    new_doc(doctype: string) {
      console.info(`[mock frappe] new_doc(${doctype})`);
      options.notify(`new_doc → blank ${doctype} form (nothing saved)`);
      options.onNewDoc?.(doctype);
      return Promise.resolve();
    },

    route_options: null,
    route_hash: null,
    router,
    user: {
      name: user.email,
      // Frappe returns true or undefined, never false.
      has_role(role: string | string[]) {
        const wanted = typeof role === "string" ? [role] : role;
        return wanted.some((r) => roles.includes(r)) ? true : undefined;
      },
    },
    // Stand-in for frappe.ui.ThemeSwitcher: instead of a dialog it flips the
    // resolved Light/Dark (html[data-theme]) and, like public/js/fps_theme.js
    // on the live desk, re-stamps html[data-fps-theme] -- so the harness can
    // exercise the Pearl <-> Matte Black switch. Nothing is "saved".
    ui: {
      ThemeSwitcher: class {
        show() {
          const html = document.documentElement;
          const dark = html.getAttribute("data-theme") !== "dark";
          html.setAttribute("data-theme", dark ? "dark" : "light");
          html.setAttribute("data-fps-theme", dark ? "black" : "pearl");
          options.notify(`theme → ${dark ? "Dark (Matte Black)" : "Light (Pearl)"} (mock; nothing saved)`);
        }
      },
    },
    session: { user: user.email, user_email: user.email, user_fullname: user.name },
    boot: {
      sysdefaults: { currency: "AED" },
      user: { roles, full_name: user.name, email: user.email, name: user.email },
    },
  };

  window.frappe = frappe;

  return {
    frappe,
    setRoute(route: string[]) {
      currentRoute = route;
      router.trigger("change");
    },
    setFail(next: boolean) {
      fail = next;
    },
    get fail() {
      return fail;
    },
    viewer: options.viewer,
    get calls() {
      return calls;
    },
  };
}
