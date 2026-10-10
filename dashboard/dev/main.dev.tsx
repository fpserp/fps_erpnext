/// <reference types="vite/client" />
/**
 * DEV HARNESS ONLY (npm run dev -> http://localhost:5199).
 *
 * Rebuilds, around the REAL mount() from src/main.tsx, what the ERPNext desk
 * puts around the FPS Overview Custom HTML Block:
 *  - a mock window.frappe (dev/mock-frappe.ts) serving dev/fixtures/*.json;
 *  - the desk chrome (sidebar 1020, sticky navbar 1019) and workspace wrappers,
 *    including EditorJS's `.codex-editor` stacking context (z-index 1);
 *  - a custom element with an OPEN shadow root laid out exactly like
 *    frappe.create_shadow_element: <link desk.bundle.css> FIRST, then the
 *    block's HTML (the real docs/…/custom_blocks/fps_overview.html when present,
 *    with its <div data-fps="cc-root"> mount point), then the block's <style>.
 *    mount() must leave that root alone (the link stays); the dashboard renders
 *    in its own <fps-command-center> shadow root, and the drawer/tooltips in the
 *    body-level <fps-cc-portal> host, exactly as in production.
 *  - Inter: the desk ships InterVariable at document level; the harness gets it
 *    from the @fontsource-variable/inter devDependency (dev only; never in the
 *    bundle) under the same family name.
 *
 * Toolbar: viewer (finance / ops reloads with ?viewer=), "Leave FPS route"
 * (hides the page and fires router "change" like the desk; the drawer and any
 * tooltip must close, which the harness reports), remount (re-runs the "block
 * script" on a fresh element and drops the old one with no teardown, like
 * Frappe), edit mode (EditorJS re-renders the block and overlays its controls),
 * full width, desk theme, simulated failures (?fail=1), a fake Frappe dialog,
 * and "Shadow check" (what the shadow roots, the body and document.head hold).
 */
import "./desk-shell.css";
import interLatinUrl from "@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2?url";
import interLatinExtUrl from "@fontsource-variable/inter/files/inter-latin-ext-opsz-normal.woff2?url";
import { mount, version } from "@/main";
import { installMockFrappe, type Viewer } from "./mock-frappe";

const params = new URLSearchParams(window.location.search);
const viewer: Viewer = params.get("viewer") === "ops" ? "ops" : "finance";

/* ---- Inter, under the desk's family name ------------------------------------ */

// Frappe declares @font-face "InterVariable" (wght + opsz axes) at document
// level; shadow roots use document-level faces. Same family name here, from the
// fontsource "opsz" files (wght 100-900 + opsz), latin + latin-ext only.
{
  const face = (url: string, range: string) =>
    `@font-face{font-family:InterVariable;font-style:normal;font-display:swap;font-weight:100 900;` +
    `src:url("${url}") format("woff2-variations");unicode-range:${range}}`;
  const style = document.createElement("style");
  style.setAttribute("data-fps-dev", "font");
  style.textContent = [
    face(
      interLatinExtUrl,
      "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF",
    ),
    face(
      interLatinUrl,
      "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    ),
  ].join("\n");
  document.head.append(style);
}

/* ---- host-page CSS: the app's real FPS Pearl desk theme ------------------- */

// fps_theme.css (hooks.py app_include_css) scopes every rule under
// html[data-fps-theme="pearl"], which public/js/fps_theme.js sets on the live
// desk while the FPS sidebar or an FPS workspace route is active. The harness
// is always "on the FPS workspace" (body[data-route="Workspaces/FPS"]), so it
// sets the same attribute directly instead of loading that script. The
// attribute's value names the palette; it must match the sheet's selector.
const hostCss = import.meta.glob<string>("../../fps_erpnext/public/css/fps_theme.css", {
  query: "?url",
  import: "default",
  eager: true,
});
const hostCssUrl = Object.values(hostCss)[0];
if (hostCssUrl) {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = hostCssUrl;
  link.setAttribute("data-fps-dev", "host-css");
  document.head.append(link);
  document.documentElement.setAttribute("data-fps-theme", "pearl");
} else {
  document.body.classList.add("fps-dev-emulate-host");
}

/* ---- the block's own HTML and CSS (read-only), with a fallback copy ------- */

const blockFiles = import.meta.glob<string>("../../docs/design_handoff_fps_workspace/custom_blocks/fps_overview.{html,css}", {
  query: "?raw",
  import: "default",
  eager: true,
});
const blockFile = (ext: string) => Object.entries(blockFiles).find(([file]) => file.endsWith(ext))?.[1];
const BLOCK_HTML =
  blockFile(".html") ??
  '<div data-fps="cc-root" class="fps-cc-mount"><div class="fps-cc-loading" role="status">Loading the FPS Command Center…</div></div>';
const BLOCK_CSS =
  blockFile(".css") ??
  ".fps-cc-mount{display:block}.fps-cc-loading{min-height:96px;padding:24px;font-size:13px;color:var(--text-muted,#7c869c)}";

/* ---- shell ---------------------------------------------------------------- */

const harness = document.getElementById("fps-harness");
if (!harness) throw new Error("index.html is missing #fps-harness");

// Static markup only (no data interpolated), so innerHTML is safe here.
harness.innerHTML = `
<nav class="fps-dev-sidebar" aria-label="Desk sidebar (fake)">
  <h2>FPS</h2>
  <a href="#" aria-current="page">FPS Home</a>
  <div class="fps-dev-section">Sales</div>
  <a href="#">Enquiry</a><a href="#">Quotation</a><a href="#">Customer</a>
  <div class="fps-dev-section">Operations</div>
  <a href="#">Job Order</a><a href="#">Customs Tracker</a><a href="#">Proof of Delivery</a>
  <div class="fps-dev-section">Accounts</div>
  <a href="#">Sales Invoice</a><a href="#">Purchase Invoice</a><a href="#">Payment Receipts</a>
</nav>
<div class="fps-dev-main">
  <header class="fps-dev-navbar">
    <span class="fps-dev-brand">FPS Command Center · harness</span>
    <div class="fps-dev-toolbar" role="toolbar" aria-label="Harness controls">
      <button type="button" data-action="viewer" data-viewer="finance">Viewer: finance</button>
      <button type="button" data-action="viewer" data-viewer="ops">Viewer: ops</button>
      <span class="fps-dev-sep" aria-hidden="true"></span>
      <button type="button" data-action="route">Leave FPS route</button>
      <button type="button" data-action="remount">Remount</button>
      <button type="button" data-action="edit">Edit mode</button>
      <button type="button" data-action="fullwidth">Full width</button>
      <button type="button" data-action="theme">Desk theme: light</button>
      <button type="button" data-action="fail">Fail requests</button>
      <button type="button" data-action="dialog">Desk dialog</button>
      <button type="button" data-action="check">Shadow check</button>
    </div>
    <span class="fps-dev-status" data-role="status"></span>
  </header>
  <div id="page-Workspaces" class="page-container" data-page-route="Workspaces">
    <div class="page-head fps-dev-pagehead">
      <span class="fps-dev-title">FPS</span>
      <span class="fps-dev-crumb">Workspaces / FPS</span>
    </div>
    <div class="container page-body">
      <div class="page-wrapper"><div class="page-content"><div class="layout-main">
        <div class="layout-main-section-wrapper"><div class="layout-main-section">
          <div class="editor-js-container"><div class="codex-editor"><div class="codex-editor__redactor">
            <div class="ce-block col-xs-12"><div class="ce-block__content">
              <div custom_block_name="FPS Overview" data-role="block-slot"></div>
            </div></div>
            <div class="fps-dev-below">Below the bento the live page keeps its other blocks
              (FPS Job Tracker, "Jobs needing action" quick list). Not rendered in the harness.</div>
          </div></div></div>
        </div></div>
      </div></div></div>
    </div>
  </div>
  <div class="fps-dev-away fps-dev-hidden" data-role="away">
    Simulated List / Job Order page. The workspace page is hidden (display:none),
    exactly like the desk does; the dashboard stops polling, and the drawer and
    tooltips (which live in the body-level portal host, outside this page) have
    closed. Use "Return to FPS route" to come back.
  </div>
</div>
<div class="fps-dev-toast" role="status" aria-live="polite" data-role="toast"></div>
`;

function q<T extends Element>(selector: string): T {
  const el = harness?.querySelector<T>(selector);
  if (!el) throw new Error(`harness markup is missing ${selector}`);
  return el;
}

const toastEl = q<HTMLElement>('[data-role="toast"]');
let toastTimer = 0;
function toast(message: string): void {
  toastEl.textContent = message;
  toastEl.dataset.show = "true";
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastEl.dataset.show = "false";
  }, 4500);
}

/* ---- fake Frappe dialog (z 1040/1050), opened by new_doc or the toolbar --- */

function openDeskDialog(title: string): void {
  document.querySelectorAll("[data-fps-dev-modal]").forEach((el) => el.remove());
  const backdrop = document.createElement("div");
  backdrop.className = "fps-dev-modal-backdrop";
  backdrop.setAttribute("data-fps-dev-modal", "");
  const dialog = document.createElement("div");
  dialog.className = "fps-dev-modal";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("data-fps-dev-modal", "");
  const heading = document.createElement("h3");
  heading.textContent = title;
  const label = document.createElement("label");
  label.textContent = "A field (focus must stay here after the drawer closes)";
  const input = document.createElement("input");
  input.type = "text";
  label.append(input);
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Close (nothing is saved)";
  const remove = () => {
    backdrop.remove();
    dialog.remove();
  };
  close.addEventListener("click", remove);
  backdrop.addEventListener("click", remove);
  dialog.append(heading, label, close);
  document.body.append(backdrop, dialog);
  window.setTimeout(() => input.focus(), 0); // like Bootstrap's shown handler
}

/* ---- mock desk ------------------------------------------------------------ */

const mock = installMockFrappe({
  viewer,
  fail: params.get("fail") === "1",
  notify: toast,
  onNewDoc: (doctype) => openDeskDialog(`New ${doctype} (Quick Entry stand-in)`),
});

/* ---- the block: a faithful copy of frappe.create_shadow_element ------------ */

let blockCount = 0;

function renderBlock(): void {
  const slot = q<HTMLElement>('[data-role="block-slot"]');
  // Frappe discards the previous block DOM with no teardown hook.
  slot.replaceChildren();

  const widget = document.createElement("div");
  widget.className = "widget custom-block-widget-box full-width";
  const head = document.createElement("div");
  head.className = "widget-head";
  const controls = document.createElement("span");
  controls.className = "fps-dev-edit-controls";
  controls.innerHTML = '<span title="Drag">⋮⋮</span><span title="Settings">⚙</span>';
  head.append(controls);
  const body = document.createElement("div");
  body.className = "widget-body";
  widget.append(head, body);
  slot.append(widget);

  blockCount += 1;
  const tag = `custom-block-dev${blockCount}${Math.random().toString(36).slice(2, 7)}`;
  customElements.define(
    tag,
    class extends HTMLElement {
      private ran = false;
      constructor() {
        super();
        const root = this.attachShadow({ mode: "open" });
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/dev-vendor/desk.bundle.css";
        const html = document.createElement("div");
        html.innerHTML = BLOCK_HTML; // the block's own static HTML
        const style = document.createElement("style");
        style.textContent = BLOCK_CSS;
        root.append(link, html, style);
      }
      connectedCallback() {
        if (this.ran || !this.shadowRoot) return; // Frappe's <script> runs once per element
        this.ran = true;
        const root = this.shadowRoot;
        const mountPoint = root.querySelector<HTMLElement>('[data-fps="cc-root"]');
        // The live loader awaits import(); a microtask keeps that ordering.
        queueMicrotask(() => {
          try {
            mount(root, { mountPoint });
          } catch (err) {
            console.error("[harness] mount failed", err);
            toast(`mount() threw: ${String(err)}`);
          }
        });
      }
    },
  );
  body.append(document.createElement(tag));
}

renderBlock();

/* ---- toolbar ---------------------------------------------------------------- */

const page = q<HTMLElement>("#page-Workspaces");
const away = q<HTMLElement>('[data-role="away"]');
const section = q<HTMLElement>(".layout-main-section");
let isAway = false;

function setPressed(action: string, pressed: boolean, label?: string): void {
  const btn = q<HTMLButtonElement>(`[data-action="${action}"]`);
  btn.setAttribute("aria-pressed", String(pressed));
  if (label) btn.textContent = label;
}

harness.querySelectorAll<HTMLButtonElement>("[data-viewer]").forEach((btn) => {
  btn.setAttribute("aria-pressed", String(btn.dataset.viewer === viewer));
});
setPressed("fail", mock.fail);

function liveRoots(): number {
  const reg = (globalThis as unknown as Record<symbol, unknown>)[Symbol.for("fps.command-center.registry")] as
    | { records?: Set<unknown> }
    | undefined;
  return reg?.records?.size ?? 0;
}

/** The body-level portal hosts and what they currently show. */
function portalState(): { hosts: number; drawerOpen: boolean; tooltipOpen: boolean } {
  const hosts = Array.from(document.body.querySelectorAll<HTMLElement>(":scope > fps-cc-portal"));
  const open = (selector: string) => hosts.some((host) => host.shadowRoot?.querySelector(selector));
  return {
    hosts: hosts.length,
    drawerOpen: open('[data-slot="sheet-content"]'),
    tooltipOpen: open('[data-slot="tooltip-content"]'),
  };
}

/** What the block roots, the dashboard roots, the body and document.head look like right now. */
function shadowReport(): string {
  const blockHosts = Array.from(document.querySelectorAll<HTMLElement>("[custom_block_name] *")).filter(
    (el) => el.shadowRoot && el.localName.startsWith("custom-block-"),
  );
  const lines = blockHosts.map((host) => {
    const root = host.shadowRoot as ShadowRoot;
    const deskLinks = root.querySelectorAll('link[href*="desk.bundle"]').length;
    const dashboards = Array.from(root.querySelectorAll<HTMLElement>("fps-command-center"));
    const inner = dashboards.map((el) => {
      const own = el.shadowRoot;
      const apps = own?.querySelectorAll('[data-fps-cc="app"]').length ?? 0;
      const adopted = own?.adoptedStyleSheets.length ?? 0;
      const styles = own?.querySelectorAll('style[data-fps-cc="styles"]').length ?? 0;
      return `own root: app=${apps}, adopted sheets=${adopted}, <style>=${styles}`;
    });
    return `${host.localName}: desk.bundle link kept=${deskLinks} (expect 1), <fps-command-center>=${dashboards.length} [${inner.join("; ")}]`;
  });
  const portal = portalState();
  const headProperties = Array.from(document.head.querySelectorAll("style"))
    .map((s) => (s.textContent ?? "").match(/@property\s+--tw-/g)?.length ?? 0)
    .reduce((a, b) => a + b, 0);
  lines.push(
    `body <fps-cc-portal> hosts=${portal.hosts} (expect 1 while mounted); drawer open=${portal.drawerOpen}; ` +
      `document.head @property --tw-* rules=${headProperties} (expect 0); live roots=${liveRoots()}`,
  );
  return lines.join(" | ");
}

harness.addEventListener("click", (event) => {
  const btn = (event.target as Element | null)?.closest<HTMLButtonElement>("[data-action]");
  if (!btn) return;
  switch (btn.dataset.action) {
    case "viewer": {
      const next = new URLSearchParams(window.location.search);
      next.set("viewer", btn.dataset.viewer === "ops" ? "ops" : "finance");
      window.location.search = next.toString(); // a different user = a fresh page load
      break;
    }
    case "route": {
      isAway = !isAway;
      const before = portalState();
      // Like the desk (container.change_to, then router "change"): show the
      // new page first, then fire the route event the dashboard listens to.
      page.classList.toggle("fps-dev-hidden", isAway);
      away.classList.toggle("fps-dev-hidden", !isAway);
      const nextRoute = isAway ? ["List", "Job Order", "List"] : ["Workspaces", "FPS"];
      document.body.dataset.route = nextRoute.join("/"); // like frappe.get_route_str() on page-change
      mock.setRoute(nextRoute);
      setPressed("route", isAway, isAway ? "Return to FPS route" : "Leave FPS route");
      if (!isAway) {
        toast("Back on Workspaces/FPS");
        break;
      }
      // React commits the close asynchronously; check once it has settled.
      window.setTimeout(() => {
        const after = portalState();
        toast(
          `Left Workspaces/FPS (page hidden). Drawer open: ${before.drawerOpen} → ${after.drawerOpen}; ` +
            `tooltip open: ${before.tooltipOpen} → ${after.tooltipOpen}` +
            (after.drawerOpen || after.tooltipOpen ? "  ✗ an overlay is still showing" : "  ✓ overlays closed"),
        );
      }, 120);
      break;
    }
    case "remount": {
      const before = liveRoots();
      renderBlock();
      window.setTimeout(
        () => toast(`Block script re-run on a new element. Live roots before: ${before}, after: ${liveRoots()}; portal hosts: ${portalState().hosts}`),
        50,
      );
      break;
    }
    case "edit": {
      const on = !section.classList.contains("edit-mode");
      section.classList.toggle("edit-mode", on);
      setPressed("edit", on);
      // EditorJS's readOnly.toggle() clears and re-renders every block.
      renderBlock();
      toast(on ? "Edit mode: blocks re-rendered, controls overlay the top-right" : "Edit mode off: blocks re-rendered");
      break;
    }
    case "fullwidth": {
      const on = document.body.classList.toggle("full-width");
      setPressed("fullwidth", on);
      break;
    }
    case "theme": {
      const dark = document.documentElement.dataset.theme !== "dark";
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      document.documentElement.dataset.themeMode = dark ? "dark" : "light";
      setPressed("theme", dark, `Desk theme: ${dark ? "dark" : "light"}`);
      break;
    }
    case "fail": {
      mock.setFail(!mock.fail);
      setPressed("fail", mock.fail);
      toast(mock.fail ? "Every call() now fails" : "Calls succeed again");
      break;
    }
    case "dialog":
      openDeskDialog("Frappe dialog stand-in (z-index 1050)");
      break;
    case "check": {
      const report = shadowReport();
      console.info("[harness] shadow check:", report);
      toast(report);
      break;
    }
  }
});

const statusEl = q<HTMLElement>('[data-role="status"]');
function renderStatus(): void {
  statusEl.textContent = `v${version} · viewer ${viewer} · roots ${liveRoots()} · calls ${mock.calls} · ${document.visibilityState}`;
}
renderStatus();
window.setInterval(renderStatus, 1000);
