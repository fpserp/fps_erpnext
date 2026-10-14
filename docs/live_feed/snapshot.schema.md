# FPS Live Feed — snapshot contract (version 1)

The contract between the builder (`fps_erpnext/api/feed.py` + `feed_logic.py`) and the page
(`/fps-feed`, `fps_erpnext/www/fps-feed.*`). The builder and the page keep to it; change both
together and bump `feed_logic.VERSION` when a field changes meaning (a stored snapshot of another
version is not rendered: the page shows "building" and a fresh one is built).

Example: `docs/live_feed/sample_snapshot.json` is exactly what `get_feed_for_page()` returns for
an allowed viewer (fictional parties; regenerate with
`python -m fps_erpnext.tests.test_feed_logic --write-sample`; a test fails when it drifts).
A live one (real data, scratchpad only, never committed) sits next to the harness.

---------------------------------------------------------------------------------------------------
## 1. Where it lives and who writes it

* Single DocType **FPS Feed Snapshot** (module FPS): `generated_at` (Datetime), `slot` (Data,
  `"12:00"`), `snapshot` (Long Text: the JSON of §3), `previous` (Long Text: the JSON of §5, or
  empty). System Manager may read the form; nobody edits it. That read includes the Accounts
  figures: on 14 Oct 2026 the System Managers are Administrator, agam@ and abhishek@ — abhishek@ is
  outside `FEED_USERS` but is Accounts Manager and sees the same figures on FPS ACC. Removing the
  DocPerm keeps the data to `FEED_USERS` (the page reads the Single without a permission check).
* Written ONLY by `fps_erpnext.api.feed.build_snapshot` — the scheduler at 08:00, 12:00, 16:00 and
  20:00 Asia/Dubai (hooks.py cron `0 8,12,16,20 * * *`, evaluated in the System Settings time
  zone), and once on demand in a background job when the page finds nothing stored.
* Failures are logged with `frappe.log_error(..., defer_insert=True)`: a failed cron run is rolled
  back and a Cron job type keeps no Scheduled Job Log, so a plain Error Log would vanish with it.
  One section failing stores that section with `error`; the recent-document reads failing store
  both sections with a `notice`; both sections failing keeps the previous snapshot.
* Built with Administrator rights from the FPS OPS and FPS ACC dashboards' own code (period 7d).
  What each viewer may OPEN is decided per request (§4), never stored.

## 2. What the page gets — `get_feed_for_page()`

The www page calls `feed.check_page_access()` first (Guest → it raises `frappe.Redirect` to
`/login?redirect-to=/fps-feed`; a user outside `FEED_USERS` → `False`: render "This feed is
private." with HTTP 200 and no data; allowed → `True`), then `feed.get_feed_for_page()`:

| key | type | |
|---|---|---|
| `state` | `"ready" \| "building" \| "private"` | `building`: nothing stored yet (first deploy) or an older version; one background build has been queued. Show a calm "Preparing the first update…" and poll `get_feed_meta` every `poll.building_every_seconds` until `generated_at` is set, then reload. `private`: no data at all (only `state` and `poll`). |
| `user` | `{name, full_name}` | the viewer |
| `meta` | Meta (below) | header facts computed NOW, not at build time |
| `snapshot` | Snapshot (§3) + page-time keys (§4) \| `null` | `null` unless `ready` |
| `feed_json` | string | `{"meta", "snapshot"}` as JSON that is safe inside `<script type="application/json">` (`<`, `>`, `&`, U+2028/9 escaped). Embed it raw (`{{ feed.feed_json }}`), never through `tojson` again. |
| `poll` | `{meta_method, check_every_seconds: 600, building_every_seconds: 10}` | `meta_method` = `fps_erpnext.api.feed.get_feed_meta` |

**Meta** (`feed_logic.feed_meta(generated_at, now)`):

| key | type | example | |
|---|---|---|---|
| `now` | `"YYYY-MM-DD HH:MM:SS"` | `"2026-10-14 12:37:05"` | server time, Asia/Dubai |
| `generated_at` | same \| null | `"2026-10-14 12:00:05"` | |
| `slot` | `"HH:00"` \| null | `"12:00"` | the slot the snapshot belongs to |
| `slot_id` | `"YYYY-MM-DD HH:00"` \| null | `"2026-10-14 12:00"` | before 08:00 it is the previous day's 20:00 |
| `updated_label` | string \| null | `"12:00"`, `"20:00 yesterday"`, `"14:37"`, `"16:00 on 12 Oct"` | "Updated …"; the slot when built within 20 min of it, else the build time |
| `next_slot` | string | `"16:00"`, `"08:00 tomorrow"`, `"08:00"` | "next …"; after midnight it is plain "08:00" |
| `next_at` | `"YYYY-MM-DD HH:MM:SS"` | `"2026-10-14 16:00:00"` | |
| `late` | bool | `false` | the current slot is > 30 min old and the snapshot is from before it (a stuck scheduler) — say "the 16:00 update is late" |
| `time_zone` | string | `"Asia/Dubai"` | informational |

**`get_feed_meta()`** — whitelisted GET, allow-list gated (others: `PermissionError`), reads one
Single, writes nothing: `{generated_at, slot, slot_id, building}`. The page calls it on
`visibilitychange` / `pageshow` and every `poll.check_every_seconds`; when `generated_at` differs
from the one it rendered → `location.reload()`. In the `building` state: `generated_at` set →
reload; `building` false and `generated_at` still null → the first build failed (it is in the Error
Log): stop polling and say "The feed could not be prepared — it will try again at {meta.next_slot}"
(a manual reload queues one more build).

## 3. Snapshot (stored)

Times are Asia/Dubai wall-clock strings without a zone. Money is AED (company currency).

| key | type | |
|---|---|---|
| `version` | int | `1` |
| `generated_at` | `"YYYY-MM-DD HH:MM:SS"` | build time |
| `slot` | `"HH:00"` | slot at build time |
| `slot_id` | `"YYYY-MM-DD HH:00"` | |
| `next_slot` | string | relative to the BUILD time — the page uses `meta.next_slot` instead |
| `updated_label` | string | relative to the build time — the page uses `meta.updated_label` |
| `as_of` | `"YYYY-MM-DD"` | the dashboards' as-of date |
| `period` | `"7d"` | the dashboards' period |
| `time_zone` | `"Asia/Dubai"` | |
| `since` | `"YYYY-MM-DD HH:MM:SS"` | start of the "since the previous update" window: the previous slot's build time, at least the last 24 h, at most 7 days |
| `since_label` | string | `"since 12:00 yesterday"`, `"since 08:00"`, `"since 12 Oct"` |
| `sections` | Section[2] | always `ops` then `acc` |

### Section

| key | type | |
|---|---|---|
| `key` | `"ops" \| "acc"` | |
| `title` | `"Operations" \| "Accounts"` | |
| `definition` | string | for the section-header sheet |
| `error` | string? | present only when that half could not be read at build time ("Operations data could not be read at 12:00."); then `chips` and `items` are empty |
| `notice` | string? | present when the section was built but its recent documents could not be read ("The invoices and receipts since 08:00 could not be read at 12:00.") — a quiet line above the chips |
| `chips` | Chip[] | 0–6, fixed order (below); a chip whose source was unreadable is left out, never 0 |
| `items` | Item[] | 0–25, already ordered (below) |
| `more` | `{kind, count, label}[]` | what the caps cut, e.g. `{"kind":"job","count":3,"label":"3 more jobs opened"}` — show as a quiet footer line |
| `counts` | `{critical, warning, info, positive}` ints | over `items` except the standing lists (most overdue customers, suppliers past due — listed, not alerts); the page adds `new` |
| `detail` | Row[] | figures for the section-header sheet (alerts, critical, warnings, "Events since …" = events whose `at` is in the window, "Earlier job updates shown" when the newest updates reach further back, period) |

**Chips**, in order — `ops`: `open_jobs`, `in_progress`, `customs_open`, `awaiting_invoice`,
`past_eta`, `enquiries_7d`; `acc`: `receivables`, `payables`, `cash`, `vat`, `invoiced_7d`,
`collected_7d`.

### Chip

| key | type | |
|---|---|---|
| `key` | string | stable |
| `label` | string | `"Open jobs"`, `"VAT Jul–Sep 2026"` |
| `value` | number | count (int) or AED (2 dp) — for the count-up animation |
| `display` | string | `"40"`, `"AED 615K"` — show this, not `value` |
| `unit` | `"count" \| "currency"` | |
| `tone` | `"critical" \| "warning" \| "positive" \| "neutral"` | colour of the chip |
| `sub` | string? | short line under the value: `"AED 65.4K overdue"`, `"Due 28 Oct 2026 · 14 days"`, `"Books above statements AED 5.6M"`, `"Last 7 days"`. Receivables / payables: when the overdue (net per party) exceeds the total because some parties are in credit, it is set against what is owed: `"AED 617.5K overdue of AED 725K owed"` (the sheet adds "Owed by the customers who owe" and "Customers in credit") |
| `delta` | Delta? | only on `enquiries_7d`, `invoiced_7d`, `collected_7d` |
| `definition` | string? | for the chip sheet |
| `note` | string? | the honest caveat (cash: books vs statement; VAT; receipt lag) — show it in the sheet, prominently when `tone` is `critical` |
| `detail` | Row[] | sheet rows (money in full: `"AED 6,023,719.62"`). `invoiced_7d` adds "Submitted since …" (the invoices listed in the section: count, total with VAT, how many are back-dated) and names the dashboard's "Last submitted" line for what it is, "Latest posting date" |
| `doctype` | string? | gates "Open in ERPNext" (read on the doctype) |
| `route` | string? | desk path (`/app/...`); removed at page time when the viewer cannot open it |
| `fingerprint` | string | 12 hex |

**Delta**: `{pct: number|null, text: "+100%"|"−20%"|"new"|"—", previous: number, previous_display: string, label: "vs previous 7 days", tone: "positive"|"warning"|"neutral"}`.

### Item

| key | type | |
|---|---|---|
| `key` | string | stable and unique across the snapshot: `ins:ops:<id>`, `ins:acc:<id>`, `jo:<job>`, `jos:<customer>` (several jobs opened for one customer: one card, the jobs as its records), `upd:<row>`, `ct:<tracker>:cleared`, `pod:<pod>`, `si:<invoice>`, `pe:<receipt>`, `odc:<customer>`, `ods:<supplier>`, `bank:statements`, `cash:statement_gap` |
| `kind` | string | `insight`, `job`, `update`, `customs`, `delivery`, `invoice`, `receipt`, `overdue_customer`, `supplier_due`, `bank`, `cash` — pick the icon from it |
| `severity` | `"critical" \| "warning" \| "info" \| "positive"` | one per list: every overdue customer / supplier is `warning` |
| `tag` | string? ≤ 24 | the kind, shown as a small tag beside the time: `"New job"`, `"3 new jobs"`, `"Cleared"`, `"Delivered"`, `"Invoice"`, `"Credit note"`, `"Payment request"`, `"Received"`. Never glued onto the title |
| `title` | string ≤ 80 | what the card is about — the party for an event (`"Harbour Trading (sample)"`), the sentence for an alert (`"5 document submissions are past the Dubai Customs deadline"`), the status line for a job update |
| `subtitle` | string? ≤ 120 | `"FPS/JO/2610/058 · Freight forwarding · PO 4410"` (a reference prefix is joined to its number with U+00A0, so "PO#" never wraps away from "82467"); a settled invoice shows its status (`"Paid"`) instead of a due date |
| `note` | string? ≤ 240 | the longer explanation (an insight's detail sentence) — sheet only |
| `amount` | number? | AED, 2 dp — Accounts only; Operations items never carry money |
| `amount_display` | string? | compact `"AED 615K"` for the card; the sheet's rows carry the full figure |
| `at` | `"YYYY-MM-DD HH:MM:SS"` \| `"YYYY-MM-DD"` ? | when it happened, for "2 h ago" / "today" / "yesterday". A bare date has no time: say "today", never "0 min ago". Absent on standing items (insights, parties, bank, cash). |
| `detail` | Row[] | sheet rows `{label, value}`, values pre-formatted strings, empty ones already dropped |
| `records` | Record[]? | ≤ 8 documents behind an aggregate item (the trackers past their deadline, the invoices a customer owes …) |
| `records_more` | int? | how many more records exist beyond the 8 |
| `doctype` | string? | what "Open in ERPNext" opens: with `name` a form, without it a list / report |
| `name` | string? | |
| `route` | string? | desk path; removed at page time when the viewer cannot open it |
| `fingerprint` | string | 12 hex over what the card shows (kind, severity, tag, title, subtitle, amount; for an overdue party: amount and number of documents, not the growing "oldest N days") |

**Record**: `{title, subtitle?, value? (pre-formatted string, e.g. "AED 9K"), group?, doctype, name?, route?}` +
page-time `can_open`. Without `name` it opens a list (e.g. a supplier's open bills). `group` heads a run
of records in the sheet: the customs alerts list `"Past deadline"` then `"Due soon"`.

**Row**: `{label, value}` — both plain strings.

### Order and caps (already applied — render in the given order)

1. critical items, 2. warnings (alerts), 3. what happened, newest first (jobs opened, job updates,
clearances, deliveries, invoices submitted, receipts — a warning update such as "On hold" stays in
time order), 4. the standing lists (most overdue customers, then suppliers, by amount), 5. quiet
notes (info / positive alerts). Per kind at most: job cards 8 (one per customer; `more` counts jobs), updates 8, clearances 5, deliveries 5,
invoices 8, receipts 8, customers 5, suppliers 5; per section 25 (the oldest events go first, never
an alert). What was cut is in `more`.

What each section holds:

* **ops** — the FPS OPS Dashboard's alerts (customs document / MOFA deadlines, jobs past ETA,
  delivered not invoiced, enquiry silence, swings, quotation drafts; the dashboard's top 6) with
  their records; jobs opened in the window (a customer with several gets one `jos:` card); the newest 8 job updates (not bounded by the window);
  customs clearances and deliveries dated in the window. Update rows that say the same thing as an
  event (opening a job, the clearance, the delivery) are folded into that event's sheet as
  "Also logged" and time it. No money anywhere in this section.
* **acc** — "Books differ from the bank statement" (critical, when the cash card is); the FPS ACC
  Dashboard's alerts (VAT due, duplicate drafts, invoicing stall, unallocated receipts, supplier
  overdue, AR ageing, drafts; its top 6, without delivered-not-invoiced, which is in ops, and the
  statements alert, which becomes the bank item); invoices submitted and receipts booked in the
  window (submitted = their General Ledger entries were created then); the 5 most overdue customers
  and suppliers (net of their credits, as the ACC dashboard); one bank-statements item with a record
  per bank.

## 4. Page-time keys (added by `get_feed_for_page`, never stored)

| where | key | |
|---|---|---|
| Item | `is_new` | bool — the previous slot had no item with this key, or had it with another fingerprint. The first snapshot ever marks nothing. Show the "NEW" badge. |
| Item, Record, Chip | `can_open` | bool — the viewer may read that document (`frappe.has_permission(doctype, "read", doc=name)`) or, without `name`, the doctype; a `/app/query-report/<name>` route also needs the report itself (its roles, `Report.is_permitted()`, and "report" permission on its ref doctype — what `frappe.desk.query_report` checks). When `false` the `route` key is REMOVED: show "Open in ERPNext" only when `can_open` is true and use `route` as the link (`/app/...`, already URL-encoded). For hello@ most Accounts items have no button — intended. |
| Chip | `changed` | bool — the chip's display differs from the previous slot's |
| Chip | `since_previous`, `since_previous_display` | number / string (`"+2"`, `"−1"`, `"+AED 12.3K"`) — only when `changed` and the value moved |
| Section | `counts.new` | int — items with `is_new` |
| Snapshot | `compared_with` | the previous slot's `generated_at`, or `null` |

## 5. `previous` (stored)

`{version, generated_at, slot_id, items: {key: fingerprint}, chips: {key: {fp, value}}}` — the
fingerprints of the snapshot the current one replaced. A rebuild inside the same slot keeps the
older `previous`, so a manual re-run at 12:05 still compares with 08:00.

## 6. Rendering rules the contract relies on

* Every string is plain text from ERPNext (customer names are typed by people). Never inject it as
  HTML: use `textContent` (or escape in Jinja). Jinja on www pages does NOT autoescape in Frappe v16
  (`frappe.utils.jinja`, `SandboxedEnvironment` without autoescape).
* Money: show `amount_display` / `display` on cards; the sheet rows already carry full figures.
  Negative amounts use U+2212 (`−AED 700`).
* Relative times are computed on the phone from `at` against `meta.now` (server clock) — not the
  phone clock alone.
* Severity / tone → palette tokens of DESIGN.md (Pearl light / Matte Black dark); always with an
  icon or text, never colour alone.
