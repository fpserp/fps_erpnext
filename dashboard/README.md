# FPS dashboards (`dashboard/`)

One React 19 + shadcn/ui + Tailwind v4 + recharts app, prebuilt into **one**
ES module, that renders **two** pages in ERPNext, in the **FPS Pearl** /
**Matte Black** finish (matt plane, glass cards, slate ink):

| Page | Workspace (route) | Block | Mount variant | Who | Contract |
|---|---|---|---|---|---|
| **FPS OPS Dashboard** (was "Command Center") | **FPS** (`/desk/fps`) | FPS Overview | `"ops"` (default) | every desk user — **no money** | `src/types/dashboard.ts` |
| **FPS ACC Dashboard** | **FPS ACC** (`/desk/fps-acc`) | FPS ACC Overview | `"acc"` | **Accounts Manager** only (Administrator, agam@, abhishek@ today) | `src/types/acc.ts` |

Since 14 Oct 2026 the OPS page has no money for anyone (six operations KPIs,
Sales pipeline / Operations trend, no money insights, no Invoices stage tile;
`viewer.finance` is always false). Invoices, collections and the rest of the
accounting moved to the ACC page: Invoiced (net), Collected, Paid to
suppliers (KPI key `paid_out`), Purchases booked; Receivables, Payables, Cash &
bank and VAT positions; Billing / Cash flow trend; bank statement status;
receivables and payables ageing; accounting insights. Design tokens and rules:
`../DESIGN.md`. Build brief: `../docs/acc_dashboard/SPEC.md`.

**How the three reach the ACC page.** On the live Frappe 16.51 the left
sidebar is the site-owned "Sidebar" record "FPS"; the "Workspace Sidebar" file
that `build_workspaces.py` writes (with its "FPS ACC Dashboard" row) is an
archive the desk never reads. So the OPS header shows an **"Open the FPS ACC
Dashboard"** link to `/desk/fps-acc` — only when `hasRole("Accounts Manager")`
(Administrator holds every role); the ACC page links back to OPS. Adding the
sidebar row on the site (desk sidebar editor) is a site customization that
needs Agam's OK.

**Review fixes of 14 Oct 2026 (server side, `acc_dashboard_logic.py`).**
Receivables and payables (card value = ageing total) are net of payments not
yet allocated — the totals of the FPS Customer Receivables / Accounts Payable
reports the cards open; a party's overdue is net of its own credits; VAT is
split by voucher type (sales invoices output, purchase invoices input) with a
caveat when input VAT looks missing; the cash card compares the books with the
latest bank statements and turns critical over a 1 % gap; bank status counts
every unreconciled month since go-live (`open_months` names them).

## The presentation-only rule

This app changes how the dashboard **looks**. It never creates, updates,
deletes, submits, cancels, renames or moves an ERPNext record, DocType, field,
permission, workflow, naming series, number card, chart or setting, and it
never sends mail or messages.

- Data comes only from four read-only, whitelisted GET methods, listed in
  `READ_METHODS` in `src/lib/frappe.ts`:
  `fps_erpnext.api.command_center.get_dashboard` / `…get_metric_detail` (OPS)
  and `fps_erpnext.api.acc_dashboard.get_dashboard` / `…get_metric_detail`
  (ACC; the server checks Accounts Manager before it reads anything).
  `call()` refuses anything else.
- Quick actions only **navigate** (`navigate()` → `frappe.set_route`) or open a
  **blank** form (`newDoc()` → `frappe.new_doc`) that the user saves themselves.
- Never add a write helper (`set_value`, `insert`, `submit`, `xcall` to a write
  method, POST) to `src/lib/frappe.ts`. A change that needs a write is out of
  scope and needs its own review.

## Switching palettes

There are two palettes and **each user picks one for themselves** with
Frappe's own Toggle Theme dialog (avatar menu, Ctrl+Shift+G, or the sun/moon
button in either dashboard's header): Light → **Pearl**, Dark → **Matte
Black**, Automatic → follows the computer. Frappe saves the choice on the
user's own profile (`User.desk_theme`); our code never writes it.

How the choice travels: `fps_theme.js` reads Frappe's resolved
`html[data-theme]` and stamps `html[data-fps-theme="pearl" | "black"]` (only
under the FPS tile); `src/lib/palette.ts` copies that value onto the
dashboard's app and portal roots as `data-palette`. Both follow a switch live.

The tokens live in **two** files that must carry the same `--fps-*` names and
values, because the dashboard's shadow roots and the desk around them cannot
see each other's CSS:

- `src/styles/theme.css` — Pearl on `:host, .fps-cc`, Matte Black on
  `.fps-cc[data-palette="black"]`; compiled into the bundle and adopted by
  `<fps-command-center>` and `<fps-cc-portal>`;
- `../fps_erpnext/public/css/fps_theme.css` — the 205 rules both palettes
  share under `html[data-fps-theme]` (Pearl values), 5 Pearl-only rules, and a
  Matte Black section at the end with the 24 rules whose values differ.

To change a palette value: edit it in both files in one commit, re-run the
chart slots through the dataviz validator against that palette's effective
card colour (`--mode light` for Pearl, `dark` for Matte Black), re-run the
contrast report, update `../DESIGN.md`, rebuild (`npm run build` stamps a new
`?v=` into the block loader) and bump `?v=` on `fps_theme.css` and
`fps_theme.js` in `hooks.py` — `/assets` is cached for a year. To add a third
palette: a new `data-fps-theme` value, a new section at the end of
`fps_theme.css`, a new `.fps-cc[data-palette=…]` block, and the mapping in
`fps_theme.js` / `lib/palette.ts`. The first palette, Midnight (plane
`#0B0F19`), is in git history (commit 896a324).

## Architecture

```
Workspace FPS      →  Custom HTML Block "FPS Overview"      → mount(root, { mountPoint })                  → <CommandCenter/>
Workspace FPS ACC  →  Custom HTML Block "FPS ACC Overview"  → mount(root, { mountPoint, variant: "acc" })  → <AccDashboard/>

Workspace FPS  →  Custom HTML Block "FPS Overview"   (the ACC block is laid out the same way)
                     └─ <custom-block-xxxxx>  (Frappe: open shadow root — never modified by us)
                          ├─ <link desk.bundle.css>             ← Frappe's; stays (it cannot reach our own root)
                          ├─ <div> block HTML
                          │    └─ <div data-fps="cc-root">      ← mount point (its placeholder is swapped out while mounted)
                          │         └─ <fps-command-center>     ← our custom element, OWN open shadow root
                          │              #shadow-root: adopted CSS (or <style>), keydown guard
                          │                └─ <div class="fps-cc …">        ← app root (React)
                          └─ <style> block CSS, <script> block loader
document.body
  └─ <fps-cc-portal style="position:fixed;top:0;left:0;width:0;height:0;overflow:visible;z-index:1030">
       #shadow-root: same CSS, keydown guard
         └─ <div class="fps-cc fps-cc-portal …">        ← Radix portal container (drawer, tooltips)
document.head: untouched (no @property registrations, no styles)
```

**Loaders.** Each block's *Script* field (sources:
`docs/design_handoff_fps_workspace/custom_blocks/fps_overview.js` and
`fps_acc_overview.js`, maintained with the blocks, not here) imports the SAME
bundle and calls `mount()`. Frappe wraps that script as
`(function(){ let root_element = …shadowRoot; … })()`, so it uses dynamic
`import()`. The contract they rely on:

```js
var FPS_CC_VERSION = "<12 hex chars, written by scripts/sync-block.mjs>";
import("/assets/fps_erpnext/dashboard/fps-command-center.js?v=" + FPS_CC_VERSION)
  .then((m) => m.mount(root_element, {
    mountPoint: root_element.querySelector('[data-fps="cc-root"]'),
    variant: "acc",            // FPS ACC Overview only; omitted (= "ops") in FPS Overview
  }));
```

`variant` picks the page (`src/lib/variant.tsx`): `"ops"` (default, also for
any unknown value, with a console warning) renders `CommandCenter`, `"acc"`
renders `AccDashboard`. The element records it as
`<fps-command-center data-variant="…">`, and a `VariantProvider` hands it to
the data hooks and the shared drawer, so each page calls its own methods,
keeps its own caches and closes its overlays when the route leaves ITS
workspace.

Exports of `src/main.tsx`: `mount(shadowRoot, { mountPoint?, variant? }) → { unmount() }`,
`version` (package.json version) and `unmountAll()` (debugging). The same three
are assigned to `window.FPSCommandCenter` when the module runs, so a loader
that looks for a global finds the real API. The file is an ES module: loading
it as a classic `<script>` or with `frappe.require` fails loudly (a SyntaxError
on `export`), never silently. The app renders inside `ShadowProvider` → `LayerDismissProvider` →
Radix `TooltipProvider` (200 ms delay) → an error boundary (a render crash
shows one line in the block instead of an empty gap) → `CommandCenter`
(`src/components/dashboard/CommandCenter.tsx`) or `AccDashboard`
(`src/components/dashboard/AccDashboard.tsx`), both default exports, inside
`VariantProvider`. `StrictMode`
wraps the tree in the dev server only; production renders once.

**Cache-busting.** Frappe Cloud serves `/assets` with
`Cache-Control: max-age=31536000, immutable`. The bundle keeps one filename, so
every build must change the `?v=` in BOTH loaders. `scripts/sync-block.mjs`
writes the first 12 hex chars of the bundle's sha256 into the
`var FPS_CC_VERSION = "…";` line of `fps_overview.js` and `fps_acc_overview.js`
(a loader that is missing or has no such line is skipped with a warning, never
a failure) and regenerates the fixtures.

**Why this output path.** `fps_erpnext/public/dashboard/fps-command-center.js`
is served as `/assets/fps_erpnext/dashboard/fps-command-center.js`. It is not
under `public/dist` (gitignored, and cleaned by `bench build`), and the name has
no `.bundle.` (Frappe's esbuild would try to rebuild it). The build is Vite
library mode, format `es`, one file, no code splitting, no sourcemap, with the
CSS inlined into the JS (`theme.css?inline`). Vite does not whitespace-minify
`es` library output, so `finalizeBundle` in `vite.config.ts` runs the esbuild
Vite ships (`transform`: format esm, target es2020, legal comments none; export
names kept) over the chunk — about 1,337 KB / 314 KB gzip unminified → 870 KB /
256 KB (2026-10-10 build; `sync-block` prints the current figures). The same
plugin fails the build if anything but that one file is
emitted, if a `@property` rule survives, if the `:host` defaults are missing, or
if `mount` / `unmountAll` / `version` are no longer exported.

**What `mount()` does** (`src/main.tsx`). Frappe's block shadow root also
holds a `<link>` to `desk.bundle.css`: Bootstrap 4 and the desk utilities,
UNLAYERED (they beat every Tailwind `@layer` rule) and partly `!important`
(`.hidden`, `.border`, `.shadow*`, `.rounded`, a 7px spacing scale). So the
dashboard never renders in that root, and never touches it:

1. **Its own shadow root.** `mount()` defines the custom element
   `<fps-command-center>` once (`customElements.get` guard) and inserts one into
   the mount point (`[data-fps="cc-root"]` by default), swapping the block's
   loading placeholder out (it comes back on `unmount()`). The element attaches
   its own open shadow root, adopts the shared module-level `CSSStyleSheet`
   (a `<style>` where constructable sheets are missing), creates the React root
   in `connectedCallback` and unmounts it in `disconnectedCallback`. Frappe
   discards the block's DOM with no teardown hook (workspace switch, Edit
   toggle, Save, Discard); `disconnectedCallback` IS the teardown. It is
   deferred one microtask, so a DOM move (remove + insert) keeps the live root.
2. **A body-level portal host.** EditorJS makes `.codex-editor` a stacking
   context at z-index 1, so nothing inside the block — however fixed or high its
   z-index — can paint above the desk's sticky page head (6), navbar (1019) or
   sidebar (1020). Radix portals (the drawer, tooltips) therefore render into
   ONE `<fps-cc-portal>` appended to `document.body`, with its own open shadow
   root, the same stylesheet and a `<div class="fps-cc fps-cc-portal">`
   container (`usePortalContainer()`). Its inline style
   (`position:fixed; top:0; left:0; width:0; height:0; overflow:visible;
   z-index:1030`) keeps it out of the body's flex row and stacks it above the
   chrome and below Bootstrap modals (1040/1050). It is reference-counted
   across mounted dashboards and removed when the last one disconnects.
   Because it lives outside the page container the desk hides on navigation,
   the drawer and any open tooltip close as soon as the route leaves the
   workspace (`LayerDismissProvider` / `useDismissSignal` in `lib/shadow.tsx`;
   the drawer then skips its exit animation), and they unmount with the
   dashboard.
3. **Keydown guard** on both shadow roots. Frappe's workspace shortcuts (a–z
   opens the awesomebar, shift+t the System Console, shift+/ the shortcut list)
   decide "is the user typing?" from `document.activeElement`, which is the
   shadow HOST while focus is in a dashboard field. Keydown whose
   `composedPath()[0]` is an `input`, `select`, `textarea` or contenteditable
   element stops at the shadow root. React (listening on its own containers)
   and Radix's Escape handling (document, capture phase) are unaffected;
   Ctrl+S/K/G do not fire from inside dashboard fields.
4. **Tailwind `@property`, at build time.** Tailwind v4 keeps the defaults of
   its `--tw-*` variables in `@property` rules, which browsers ignore inside
   shadow trees, and its plain fallback block sits behind an `@supports` guard
   that only matches old Safari/Firefox. The PostCSS step `tailwindShadowDom`
   in `vite.config.ts` (dev and build) unwraps that `@supports`, adds `:host`
   to the fallback rule, fills in any registered property the fallback misses,
   and drops every `@property`. The defaults stay INSIDE `@layer properties`
   (the lowest layer), so every utility still overrides them. Nothing is
   registered on the document: no desk-wide side effect. The build fails if a
   `@property` rule reaches the bundle or `@layer properties{:host,*` is
   missing.
5. **Idempotent.** `mount()` on a shadow root that already holds a dashboard
   returns the existing handle. A registry on `globalThis` (shared by every
   copy of the bundle) backs `unmountAll()`.

**Data hooks** (`src/hooks/useDashboard.ts`). `useDashboard(period)` (OPS) and
`useAccDashboard(period)` (ACC) share one implementation: poll `get_dashboard`
every 60 s only while the block is visible (connected, rendered, tab in front
— `useHostVisible()`), refetch when the route returns to the page's own
workspace (`Workspaces/FPS` or `Workspaces/FPS ACC`) or the block becomes
visible again, keep the previous payload while refetching (`refreshing:
true`), ignore out-of-order answers, back off after failures (frappe.call opens
a desk dialog on 5xx), and only set `error` when there is no payload at all. A
`PermissionError` (the ACC role gate) sets `denied`, drops the payload and the
page's cached numbers and stops the automatic polls; `AccDashboard` then shows
"You do not have access to the FPS ACC Dashboard." and nothing else.
`useMetricDetail(key, period, dimension)` loads the drawer from the variant in
context; `key = null` means closed. Caches are per page AND per variant (the
OPS and ACC numbers never mix), so a remount (edit toggle) paints the last
numbers at once. Identical requests in flight are
shared (keyed by method + arguments), so StrictMode's dev double-run, two hooks
on the same period or a manual refresh during a poll make ONE `frappe.call`; a
production mount fetches `get_dashboard` once.

**Radix across two shadow roots.** Every Portal gets
`container={usePortalContainer() ?? undefined}` (see `components/ui/sheet.tsx`,
`tooltip.tsx`): the container in the body-level portal host. Radix 1.6.7's
modal Dialog cannot trap or restore focus inside a shadow root (it reads
`document.activeElement`, which is a shadow host), so `Sheet` defaults to a
**shadowSafe** mode: Radix runs non-modal and `sheet.tsx` provides the overlay
(click closes, swallows page scroll), the Tab/Shift+Tab focus trap (judged with
the portal shadow root's `activeElement`), initial focus on the close button,
and focus return to the opener — a card button in the OTHER shadow root — when
focus was lost or is still on one of our two roots (never stolen back from a
desk dialog). Escape closes. Pass `modal` or `shadowSafe={false}` to opt out;
with a real Radix modal the content stops wheel/touchmove propagation so the
scroll lock cannot block scrolling inside it. Sheets and tooltips close when the
route leaves the workspace.

**Charts** (`components/dashboard/charts.tsx`, recharts 3.10.1). Every axis has
explicit tick props (`fontSize: 12`, `fontFamily: InterVariable, Inter,
sans-serif`): recharts measures tick labels in a hidden span in
`document.body`, with the font size and letter spacing of the first rendered
tick and the body's font family (the desk's same InterVariable). Gradient ids
come from `useId()`, area curves are `monotone` (no overshoot below 0), the
x-axis uses `interval="preserveEnd"` so the still-filling last week keeps its
label, and no ancestor of a chart has `overflow-hidden`.

**Narrow widths.** Layout is driven by container queries on the dashboard's own
width. At 320 px nothing scrolls sideways: cards drop to 16 px padding under a
480 px bento, the insight banner stacks its title and moves its pager controls
to their own row under 480 px, trend tabs shrink and truncate, and every
truncated label keeps its full text in `title`.

## Install, build, deploy

Requirements: Node ≥ 22.18 (Node 24 used here; `check:format` needs built-in
TypeScript stripping) and Python 3 for the fixture generator.

### npm (the committed lockfile is `package-lock.json`)

```sh
cd dashboard
npm ci                      # exact versions from package-lock.json
npm run typecheck           # tsc -b
npm run check:format        # format.ts assertions (no test framework)
npm run check:fixtures      # dev/fixtures/*.json against the payload contract
npm run build               # typecheck + vite build + sync-block
```

### pnpm

There is no `pnpm-lock.yaml`, so `pnpm install --frozen-lockfile` cannot work
until one is created from the npm lockfile:

```sh
cd dashboard
pnpm import                     # one time: writes pnpm-lock.yaml from package-lock.json
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run build
```

pnpm 10 skips dependency build scripts by default; if it reports "Ignored
build scripts" (esbuild, @tailwindcss/oxide), run `pnpm approve-builds`. Keep a
single lockfile in git: if the team moves to pnpm, commit `pnpm-lock.yaml` and
delete `package-lock.json` in the same commit.

### Scripts

| Script | Does |
|---|---|
| `dev` | Harness at http://localhost:5199 (see below) |
| `typecheck` | `tsc -b` over `src/`, `dev/` and `vite.config.ts` |
| `build` | `tsc -b && vite build && node scripts/sync-block.mjs` |
| `build:bundle` | `vite build` only (no loader stamp, no fixtures) |
| `sync-block` | Stamp `FPS_CC_VERSION` in the loader, regenerate fixtures (`--dry-run`, `--no-python`, `--block=<file>`; `PYTHON=` picks the interpreter) |
| `check:format` | Assertions for `src/lib/format.ts` |
| `check:fixtures` | Structural check of `dev/fixtures/*.json` against `src/types/dashboard.ts` and `acc.ts` plus the APIs' promises (7/30/13 points ending on `as_of`, `partial` only last, KPI order, delta rule, NO money anywhere on OPS, no Invoices tile on OPS, insight limits and order, records newest first and unique, drawer = card; ACC: balances / ageing / banks in contract order, ageing total = balance, all 7 buckets summing to total and overdue, top ≤ 5 largest first, a consistent "Missing" bank, no "New" on paid_out / purchases). Optional argument: another fixtures folder |

### Deploy, step by step

1. `npm run build`. Output:
   `fps_erpnext/public/dashboard/fps-command-center.js` (sizes printed by
   `sync-block`), the two stamped loaders
   `docs/design_handoff_fps_workspace/custom_blocks/fps_overview.js` and
   `fps_acc_overview.js`, and the
   regenerated `fps_erpnext/fixtures/custom_html_block.json` (plus the
   workspace module JSON under `fps_erpnext/fps/` that `build_workspaces.py`
   always rewrites; with `STAMP` unchanged those come out byte-identical).
   If `sync-block` warns that a loader or its `FPS_CC_VERSION` line is
   missing, that block was not stamped (the other one still was); with no
   loader at all, the bundle was built but nothing else changed.
2. Leave `STAMP` in `docs/design_handoff_fps_workspace/build_workspaces.py`
   alone for a dashboard build. The block ships as a **fixture**, and
   `bench migrate` imports every `fps_erpnext/fixtures/*.json` with
   `force=True` (Frappe v16 `frappe/utils/fixtures.py` → `import_doc`), so
   the block is overwritten on every migrate whatever its `modified` says.
   `STAMP` only gates the workspace module JSON under `fps_erpnext/fps/`
   (`sync_all` skips a file whose `modified` is not newer than the database
   row); bump it only when a workspace itself changes, since bumping it
   rewrites every one of those files.
3. Review `git diff --ignore-cr-at-eol`: expect the bundle, both loaders, and
   `fps_erpnext/fixtures/custom_html_block.json`, and nothing else under
   `fps_erpnext/fps` or `fps_erpnext/fixtures`.
4. Commit and push (with Agam's OK). The Frappe Cloud deploy runs
   `bench build` + `bench migrate`, which imports the fixtures.
5. Hard-reload the desk. The block document is cached per session, so open
   tabs keep the old loader until reloaded.
6. Do not edit the FPS Overview or FPS ACC Overview block in the desk UI: the
   next migrate overwrites them from the fixture. Change
   `docs/design_handoff_fps_workspace/custom_blocks/fps_overview.*` /
   `fps_acc_overview.*` and rebuild.

## Dev harness

```sh
npm run dev        # http://localhost:5199
```

`index.html` → `dev/main.dev.tsx` installs `dev/mock-frappe.ts` as
`window.frappe` and builds a page that looks like the desk around the block:
the `#D9DEE7` Pearl plane, a fake 220 px sidebar (hidden under 768 px) and sticky
navbar (`dev/desk-shell.css`), the real workspace wrappers including
`.codex-editor`, and a custom element with an **open shadow root whose first
child is** `<link rel="stylesheet" href="/dev-vendor/desk.bundle.css">`, then
the block's real HTML (`docs/…/custom_blocks/fps_overview.html`, read-only; a
built-in copy if missing) with the `<div data-fps="cc-root">` mount point, then
the block's CSS. It then calls the real `mount()`, so the harness gets the
same `<fps-command-center>` element and body-level `<fps-cc-portal>` as
production. The document scrolls as a whole, like the desk, so nothing is cut
off at any width.

- `dev-vendor/desk.bundle.css` is a copy of the live desk CSS (gitignored).
  Refresh it by downloading `/assets/frappe/dist/css/desk.bundle.<hash>.css`
  from the site (the hash is in `/assets/assets.json`). Without it the harness
  still runs, minus the Bootstrap-leak check.
- Pages: `?variant=ops` (default) is the FPS OPS Dashboard on
  `Workspaces/FPS`; `?variant=acc` is the FPS ACC Dashboard on
  `Workspaces/FPS ACC`, in the real `fps_acc_overview.{html,css}` block when
  present (a built-in copy with the same mount point otherwise).
  `?scenario=edge` serves the ACC stress page: empty payables ageing, a VAT
  quarter past due (critical), every bank behind or Missing, cash overdrawn.
- Fixtures: `dev/fixtures/*.json`, generated by `dev/make_fixtures.py` (OPS,
  through the real `command_center_logic`) and `dev/acc_fixtures.py` (ACC;
  shared helpers from `command_center_logic`, the new ACC pieces per the
  spec): `dashboard.<period>.json`, `metric_detail.<key>.<period>.json` for
  OPS; `acc.dashboard.<period>[.edge].json`,
  `acc.metric_detail.<key>.<period>.json` for ACC. The default ACC page
  carries the edge cases on purpose: a receivables bucket that nets negative
  (an unapplied credit note), a negative bank book balance, a debit-note day,
  refundable VAT, a Missing bank. A missing fixture comes back as a clear
  error.
- `?viewer=ops` gives the mock user no Accounts roles: OPS looks the same
  (it has no money for anyone), and the ACC API answers `PermissionError`, so
  the ACC page shows its no-access panel. `?fail=1` makes every call fail. The
  mock users are placeholders (`finance.viewer@example.com`,
  `ops.viewer@example.com`).
- Inter: the desk declares `InterVariable` at document level; the harness
  registers the same family from the `@fontsource-variable/inter`
  devDependency (latin + latin-ext, wght + opsz axes). It is imported only from
  `dev/`, never by `src/`, so it never reaches the bundle.
- The harness loads the app's real host-page theme,
  `fps_erpnext/public/css/fps_theme.css`, and switches it on the way
  `public/js/fps_theme.js` does on the live desk
  (`html[data-fps-theme="pearl"]`; `?palette=black` starts in Matte Black);
  if the file is missing it emulates it. The dashboard's sun/moon button flips
  the palette through a mock `frappe.ui.ThemeSwitcher` (nothing is saved).
- Toolbar (outside the shadow root): page OPS/ACC, viewer finance/ops, ACC
  scenario default/edge, **Leave route** /
  Return (hides the page and fires router `change`, then reports whether the
  drawer and any tooltip closed), remount (re-runs the block script on a new
  element, no teardown, like Frappe), edit mode (re-render + EditorJS controls
  overlay), full width, desk theme, fail requests, desk dialog (a z-index 1050
  stand-in; `new_doc` opens it too), and shadow check (Frappe's desk link still
  in place, `<fps-command-center>` roots and their sheets, `<fps-cc-portal>`
  hosts in the body, and `@property` rules in `document.head`, expected 0).

## Adding a shadcn/ui component

```sh
cd dashboard
npx shadcn@4.21.4 add <name>
```

Then, before committing:

1. Check the `cn` import. It must be `import { cn } from "@/lib/utils"`. The
   CLI has written `from "cn"` once; fix it if so.
2. If the component renders a Radix **Portal** (Dialog, AlertDialog, Popover,
   DropdownMenu, Select, HoverCard, ContextMenu, Menubar, NavigationMenu …),
   pass the portal container and leave a short comment:

   ```tsx
   import { usePortalContainer } from "@/lib/shadow"
   // FPS: portal into the body-level <fps-cc-portal> shadow root, not document.body.
   const portalContainer = usePortalContainer()
   <XPrimitive.Portal container={portalContainer ?? undefined}>
   ```

3. Modal focus management does not work across shadow roots (see above). For a
   new modal dialog, follow the shadowSafe pattern in `components/ui/sheet.tsx`;
   for popovers and menus prefer `modal={false}`. Anything that stays open must
   close on `useDismissSignal()` (route leave), like `Sheet` and `Tooltip`.
4. Keep shadcn's `z-50`: the portal host already sits at 1030.
5. Pin any new dependency to an exact version. Tailwind picks up classes from
   `src/` only (`@import "tailwindcss" source(none)` + `@source "../"` in
   `src/styles/theme.css`); write class names out in full.

## Folder map

```
dashboard/
├─ index.html              dev harness page (never shipped)
├─ vite.config.ts          dev server + library build → ../fps_erpnext/public/dashboard/
├─ package.json            pinned versions; scripts
├─ components.json         shadcn/ui CLI config
├─ dev/                    harness only
│  ├─ main.dev.tsx         fake desk + toolbar, calls the real mount()
│  ├─ mock-frappe.ts       window.frappe stand-in serving fixtures
│  ├─ desk-shell.css       fake desk chrome
│  ├─ make_fixtures.py     fixture generator (OPS; calls acc_fixtures)
│  ├─ acc_fixtures.py      FPS ACC fixtures (fictional, incl. the edge scenario)
│  └─ fixtures/            sample payloads
├─ dev-vendor/             copy of the live desk.bundle.css (gitignored)
├─ scripts/
│  ├─ sync-block.mjs       stamp ?v= into both block loaders, regenerate fixtures
│  ├─ fixtures.check.mjs   fixtures against the payload contract
│  └─ format.check.ts      assertions for lib/format.ts
└─ src/
   ├─ main.tsx             mount()/version: <fps-command-center data-variant>, portal host, keydown guard, registry
   ├─ types/dashboard.ts   payload contract with fps_erpnext/api/command_center.py (shapes shared with ACC)
   ├─ types/acc.ts         payload contract with fps_erpnext/api/acc_dashboard.py
   ├─ styles/theme.css     Tailwind v4 theme = DESIGN.md tokens (Pearl; twin of ../fps_erpnext/public/css/fps_theme.css)
   ├─ lib/frappe.ts        read-only desk bridge (call, navigate, newDoc, roles, routes, isPermissionError)
   ├─ lib/variant.tsx      "ops" | "acc": title, workspace, read methods; VariantProvider
   ├─ lib/format.ts        number/date formatting (en-US, U+2212, AED 12.9K)
   ├─ lib/shadow.tsx       ShadowProvider, usePortalContainer, useHostVisible, LayerDismissProvider
   ├─ lib/utils.ts         cn()
   ├─ hooks/useDashboard.ts useDashboard (OPS) / useAccDashboard (ACC) / useMetricDetail
   └─ components/
      ├─ ui/               shadcn/ui (sheet + tooltip patched for the two shadow roots)
      └─ dashboard/        CommandCenter (OPS), AccDashboard (ACC: BalanceCard, AgeingPanel,
                           BankStatusCard), the shared parts and DashboardChrome (+ *.meta.ts contracts)
```

## Troubleshooting

| Symptom | Look at |
|---|---|
| Tooltip or drawer unstyled / at the page bottom | its Portal lacks `container={usePortalContainer() ?? undefined}` |
| Shadows, rings or slide-in animations missing | the bundle CSS must have 0 `@property` and `@layer properties{:host,*` (the build checks); the root has the adopted sheet or `<style data-fps-cc="styles">` |
| Bootstrap look inside the dashboard (`.btn`, `.card`, borders) | the app rendered outside `<fps-command-center>`'s own shadow root (harness: "Shadow check") |
| New build not showing after deploy | `FPS_CC_VERSION` in the loader changed (and in `custom_html_block.json`)? `bench migrate` ran? desk hard-reloaded? |
| Drawer covered by the sidebar or navbar | `<fps-cc-portal>` missing from `<body>` or its inline `z-index:1030` overridden; a desk modal (1040/1050) is meant to cover it |
| Drawer still showing on a list or form | the route change did not reach `onRouteChange` (frappe.router missing?); `useDismissSignal` closes overlays |
| Typing in a dashboard field opens the awesomebar | the keydown guard is missing on that shadow root (`guardKeydown` in `main.tsx`) |
