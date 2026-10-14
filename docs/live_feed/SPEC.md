# FPS Live Feed — build spec (14 Oct 2026)

Agam, 14 Oct 2026: "a live feed tile on phone — with tap working items. It should look like a live
feed but will be refreshed every 04 hours from morning 08 till evening 08." Users: **agam@ and
hello@ only** ("hello@ can only see, as hello@ does not have any permission to
edit/generate/delete anything"). hello@ (Azeem) uses an **iPhone 17** → a home-screen ICON that opens a
full-screen feed (no native widget). Both users see BOTH sections (Operations and Accounts) — a
deliberate exception to "FPS ACC = Accounts Manager only" that applies to this feed only.

Repo: worktree `C:\Users\FPS_AI\fps_erpnext_cc` (branch feat/ai-command-center == origin/main ef94818,
deployed). Site fastplanet.u.frappe.cloud, Frappe 16.51 / ERPNext 16.50, System Settings time_zone
Asia/Dubai, session_expiry 170 h, login_with_email_link on. Read DESIGN.md (palette tokens: Pearl light,
Matte Black dark), docs/acc_dashboard/SPEC.md and the two dashboard APIs before you start.

---------------------------------------------------------------------------------------------------
## 1. Behaviour
* URL **/fps-feed** — a website (www) page served by the fps_erpnext app, NOT the desk: light,
  phone-first, no desk chrome, no navbar. Bare full-screen document (check how Frappe v16 renders a
  www page without the website base template — e.g. a template that is a complete HTML document /
  base_template override — and verify in the v16 source; do not guess).
* Guest → redirect to `/login?redirect-to=/fps-feed`. Logged-in user not in the allow-list → a calm
  "This feed is private." page (HTTP 200, no data). Allowed users: `Administrator`,
  `agam@fastplanet.ae`, `hello@fastplanet.ae` — one constant `FEED_USERS` in
  fps_erpnext/api/feed.py (documented: change it + deploy to add someone).
* SNAPSHOTS, not live queries: a scheduler job builds the feed at **08:00, 12:00, 16:00, 20:00 Dubai**
  (hooks.py scheduler_events cron "0 8,12,16,20 * * *" → fps_erpnext.api.feed.build_snapshot; Frappe
  evaluates cron in the System Settings time zone — verify in v16 source). The page always shows the
  latest stored snapshot. Overnight it keeps showing the 20:00 one ("next update 08:00").
  If no snapshot exists yet (first deploy), the page builds one once on demand and stores it.
* Storage: a new **Single DocType "FPS Feed Snapshot"** in module FPS (app-shipped doctype JSON under
  fps_erpnext/fps/doctype/fps_feed_snapshot/): fields `generated_at` (Datetime), `slot` (Data, e.g.
  "12:00"), `snapshot` (Long Text, JSON), `previous` (Long Text, JSON of the prior snapshot's item
  keys + value fingerprints, for NEW markers). Permissions: System Manager read only (the page reads it
  server-side after the allow-list check). track_changes off. Writing happens ONLY in build_snapshot
  (scheduler, runs as Administrator) — the page itself never writes except the one-time on-demand first
  build.
* The page re-checks for a newer snapshot when it becomes visible again (visibilitychange/pageshow,
  iOS home-screen apps resume from memory) and every 10 minutes while open, via a tiny GET method
  `fps_erpnext.api.feed.get_feed_meta` → {generated_at} (allow-list gated); if newer → location.reload().
* "Looks live": pulsing "LIVE" dot, "Updated 12:00 · next 16:00", a subtle ticker/animated count-up on
  first paint, items stagger in, "NEW" badge on items that are new or changed since the previous
  snapshot, relative times ("2 h ago"). Respect prefers-reduced-motion.
* TAP: every item opens a bottom sheet (in-page, no navigation) with its detail fields from the
  snapshot (label/value rows, amounts, dates, status). The sheet shows **"Open in ERPNext"** ONLY when
  the current user can read that record — decided server-side at render time with
  frappe.has_permission(doctype, "read", name) per item (and for list routes, read on the doctype).
  For hello@ most accounting items will have no button — that is intended (his permissions stay as
  they are). Section headers and KPI chips are tappable too (sheet with the definition + figures).
* Pearl palette when the phone is in light mode, Matte Black in dark mode (prefers-color-scheme);
  same tokens as DESIGN.md. FPS logo in the header (/assets/fps_erpnext/images/fps-logo-v2.svg).
* iPhone home-screen app: `<link rel="manifest">` (display standalone, name "FPS Live", start_url
  /fps-feed, theme/background colours from the palette), `apple-mobile-web-app-capable`,
  `apple-mobile-web-app-status-bar-style`, `apple-mobile-web-app-title` "FPS Live", apple-touch-icon
  180×180 PNG (generate one from fps-logo-512.png into public/images/; keep it crisp), safe-area insets
  (viewport-fit=cover, env(safe-area-inset-*)). Also a one-time "Add to Home Screen" hint for iOS Safari
  when not in standalone mode (dismissible, remembered in localStorage).
* No external network requests (fonts/scripts/CDNs) — everything served by the site.

## 2. Snapshot content (built with Administrator rights; reuse the dashboards' logic)
Build from `fps_erpnext.api.command_center` (OPS payload, period 7d) and
`fps_erpnext.api.acc_dashboard` (ACC payload, period 7d) internals plus a few recent-document reads.
Contract: write `docs/live_feed/snapshot.schema.md` (or a TypedDict in feed_logic.py) and keep the
page and the builder to it. Suggested shape:
```
{ "version": 1, "generated_at": "2026-10-14 12:00:03", "slot": "12:00", "next_slot": "16:00" | "08:00 tomorrow",
  "sections": [
    { "key": "ops", "title": "Operations",
      "chips": [ {key,label,value,display,delta?,tone?,detail:[{label,value}]} … ],   // 4–6 KPI chips
      "items": [ Item … ] },
    { "key": "acc", "title": "Accounts", "chips": [...], "items": [...] } ] }
Item = { key: "si:FPS/INV/2610/102" (stable), kind: "insight|job|update|customs|delivery|invoice|
         receipt|overdue_customer|supplier_due|bank|vat|cash|…", severity: "critical|warning|info|positive",
         title (≤ 80 chars), subtitle?, amount?, amount_display?, at? (datetime/date for "2 h ago"),
         detail: [{label, value}], doctype?, name?, route? (desk route for Open in ERPNext),
         fingerprint (hash of the user-visible values, for NEW) }
```
Operations items (newest/most urgent first, cap ~25): the OPS insights (customs deadlines, MOFA, jobs past
ETA, delivered-not-invoiced, swings) with their records; jobs opened since the previous snapshot (or last
24 h); latest job updates (FPS Job Update rows, newest 8); customs cleared and deliveries in the last
24 h. Chips: open jobs, in progress, customs not cleared, delivered awaiting invoice, jobs past ETA, new
enquiries (7d).
Accounts items (cap ~25): the ACC insights (VAT due, unallocated receipts, overdue suppliers,
statements behind, drafts, AR ageing, duplicate drafts, invoicing stall); invoices submitted in the last
24 h / since previous; receipts in the last 24 h; top 5 overdue customers; top 5 overdue suppliers; bank
statement status. Chips: receivables (+ overdue), payables, cash (with the critical "books vs statement"
note in detail), VAT quarter + days to due, invoiced 7d, collected 7d.
Money formatting: same helpers as the dashboards ("AED 615K" compact on the item, full "AED
615,028.22" in the sheet).

## 3. Code layout
* fps_erpnext/api/feed.py — FEED_USERS, gate helper, `build_snapshot()` (scheduler entry; also callable
  by Administrator for tests), `get_feed_meta()` (whitelisted GET), `get_feed_for_page()` (used by the
  www page: loads the snapshot, marks NEW vs `previous`, adds `can_open` per item for the current user).
* fps_erpnext/api/feed_logic.py — pure: items/chips from the two payloads + raw rows, fingerprints, NEW
  marking, slot / next-slot computation (08/12/16/20, overnight → "08:00 tomorrow"), caps and ordering.
* fps_erpnext/www/fps-feed.html + fps-feed.py (get_context: no_cache, gate, redirect, context.feed);
  CSS/JS inline or under public/feed/ (served from /assets/fps_erpnext/feed/…), manifest under
  public/feed/manifest.webmanifest, icon under public/images/.
* hooks.py: the cron entry.
* Tests: fps_erpnext/tests/test_feed_logic.py (unittest, runnable without bench:
  `python -m unittest fps_erpnext.tests.test_feed_logic`), covering slots (07:59, 08:00, 11:59, 20:00,
  23:30, 00:10), NEW marking (new key, changed fingerprint, unchanged), caps/ordering, gate
  (FEED_USERS, Guest redirect, others refused — using fps_erpnext/tests/fake_frappe.py), can_open
  filtering, money formatting, snapshot JSON round-trip.
* A LOCAL PREVIEW harness (scratchpad, not shipped): render fps-feed.html with jinja2 and a snapshot JSON
  to a static file so the page can be viewed in the Browser pane at iPhone size (390×844) in both colour
  schemes. Build one snapshot from LIVE data (read-only REST, the api.cjs helper in
  C:\Users\FPS_AI\AppData\Local\Temp\claude\C--Users-FPS-AI\33dc4a3f-a1e3-478f-83c8-dfda74e396c2\scratchpad\pf\api.cjs,
  like scratchpad pf/acc/run_live.py does for the ACC payload) and one fictional fixture for the repo.

## 4. Hard limits
* No writes to the live site (no REST POST/PUT/DELETE, no MCP writes); reading live data is allowed
  (GET only; never print the token). No git commit/push — the lead commits.
* Never run headless Chrome/Edge/puppeteer/SwiftShader on this PC; the Browser pane preview tools are
  fine. One build-type process at a time (this PC crashed under parallel builds on 14 Oct).
* Do not change the two dashboards' behaviour; reuse their code read-only (import their functions).
