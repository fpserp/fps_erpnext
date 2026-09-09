# Implementation notes — design 1a

Tracks what has been built against `README.md`, the decisions taken where the
design and the live site disagreed, and what is still open.

Site: `fastplanet.u.frappe.cloud` — Frappe 16.24.1 / ERPNext 16.25.0.

## Status

| README step | State |
|---|---|
| 1. Six child workspaces, retitle, `sequence_id`, `roles` | **Done** |
| 2. Shortcuts with `color` + `stats_filter` + `doc_view` | **Done** |
| 3. Four Number Cards | Not started |
| 4. Two Dashboard Charts + Quick List | Not started |
| 5. `job_order_list.js` | Not started |
| 6. Custom HTML Block + whitelisted method | Not started |
| 7. Ship in the app, not the site | **Done for workspaces** (see below) |

## How this ships (step 7)

`workspace` and `workspace_sidebar` are both in Frappe v16's
`IMPORTABLE_DOCTYPES`, so files under `<app>/<module>/<doctype>/<slug>/<slug>.json`
are imported by `bench migrate`. No `fixtures` hook and no `export-fixtures` run
is needed for these — this is the same mechanism ERPNext uses for its own
workspaces (`erpnext/accounts/workspace/invoicing/invoicing.json`).

    fps_erpnext/fps/workspace/fps/fps.json                             ← home
    fps_erpnext/fps/workspace/fps_sales/fps_sales.json
    fps_erpnext/fps/workspace/fps_operations/fps_operations.json
    fps_erpnext/fps/workspace/fps_accounts/fps_accounts.json
    fps_erpnext/fps/workspace/fps_hr/fps_hr.json
    fps_erpnext/fps/workspace/fps_reports/fps_reports.json
    fps_erpnext/fps/workspace/fps_masters_and_setup/fps_masters_and_setup.json
    fps_erpnext/fps/workspace/payment_receipts/payment_receipts.json   ← under Accounts
    fps_erpnext/fps/workspace_sidebar/fps/fps.json                     ← v16 sidebar

Regenerate with `python docs/design_handoff_fps_workspace/build_workspaces.py`;
edit the generator, not the JSON, so the seven files stay consistent.

Number Card, Dashboard Chart and Custom HTML Block are **not** importable this
way — steps 3, 4 and 6 will need the `fixtures` hook in `hooks.py` plus
`bench export-fixtures`, as the README describes.

**These files take effect on the next deploy** (Frappe Cloud runs `bench migrate`).
Nothing on the live site has been changed by this commit.

The importer skips a file whose `modified` is not newer than the DB row, so
bump `STAMP` in the generator whenever the fixtures change.

## Decisions

### The parent workspace keeps the record name `FPS`

The README says to retitle FPS → *FPS Home*. A public Workspace's `name`,
`label` and `title` are the same string, and `frappe/desk/doctype/workspace/workspace.py`
renames the record when the title changes. Renaming would break three things at
once: `add_to_apps_screen`'s `/app/fps` route in `hooks.py`, `parent_page` on the
existing *Payment Receipts* workspace, and the sidebar's Home item — and the
`hooks.py` half only takes effect on deploy, leaving the FPS tile pointing at a
dead route in between.

So the record stays `FPS` and the **sidebar shows it as "FPS Home"** (a Workspace
Sidebar Item carries its own label). The breadcrumb reads `FPS / Home`, which is
what the 1a mock draws.

### The sidebar is a Workspace Sidebar doc, not a `parent_page` tree

The README maps "sidebar categories" to `Workspace` records with `parent_page`
set. That is v15 behaviour. In v16 the left sidebar under a tile is a separate
**Workspace Sidebar** doc, and it must be named exactly like the Module Def
(`FPS`) or Frappe auto-generates one over the top of it.

Both are built: the six children exist as real workspaces with `parent_page = FPS`
(they carry the link cards and are the pages the "… overview" items open), and
`workspace_sidebar/fps/fps.json` reproduces the mock's sidebar — a Home row, then
six collapsible sections whose members are indented under them. HR, Reports and
Masters & Setup ship with `keep_closed = 1` so the sidebar opens at roughly the
mock's height.

### Payment Receipts is a sub-tab of Accounts, and now ships in the app

It was built in the site DB on 2026-09-05 and lived **only** there — a fresh
install would not have had it at all — and it sat as a seventh sibling of the six
categories, holding `sequence_id = 1` where FPS Sales wanted to be.

It is now adopted into the app from `adopted/payment_receipts.source.json` (a
cleaned copy of the live record) and re-parented to `parent_page = FPS Accounts`
with `sequence_id = 1` among that parent's children. Verified byte-faithful
against the live record: all 15 links, 6 shortcuts, 3 number cards, 2 quick lists
and every content block are identical. The only deliberate changes are
`parent_page` and `roles`.

A `Workspace Link` cannot point at a Workspace — `link_type` is `DocType / Page /
Report` only — so Accounts links to it with a paragraph block to
`/desk/payment-receipts`, and the sidebar nests it under the Accounts section
(a Workspace Sidebar Item *can* use `link_type = Workspace`). That paragraph
moved off the home page, where it used to sit, onto Accounts.

Refresh the source after any desk-UI edit by re-fetching
`/api/resource/Workspace/Payment%20Receipts` and stripping the volatile fields.

### The home page was not stripped

Step 1 owns the information architecture only. The ten link cards that used to
crowd the home page have moved out to the six children and the three cards from
the design (Sales · Operations · Accounts & reports) took their place, but the
existing shortcuts and number cards stay exactly as they are so the page keeps
working until steps 2–4 restyle them. The pre-redesign record is saved at
`backup/FPS-workspace-before-redesign.json`.

One incidental fix: the old header read `FPS â€” Fast Planet Shipping` — a
double-encoded em dash. The new header is plain `Fast Planet Shipping`.

Nothing from the old page is dropped except four child-table doctypes
(`FPS AR Charge`, `FPS AP Charge`, `FPS Purchase Attachment`, `Qashio Category Map`).
Frappe cannot open a `istable = 1` doctype as a list, so those rows never worked.

### Roles

Verified against the live site on 2026-09-09:

| User | Roles held |
|---|---|
| agam@, abhishek@ | System Manager, Accounts Manager, HR Manager, FPS Operations, … |
| ops@ | Employee, Desk User, **FPS Operations** only |
| hello@ | Desk User, FPS Viewer, FPS Customs Access, Employee |

| Workspace | `roles` |
|---|---|
| FPS (home) | *(none — visible to everyone, unchanged from today)* |
| FPS Sales | FPS Operations, Sales User, Sales Manager, System Manager |
| FPS Operations | FPS Operations, System Manager |
| FPS Accounts | **FPS Operations**, Accounts User, Accounts Manager, System Manager |
| FPS HR | HR User, HR Manager, System Manager |
| FPS Reports | FPS Operations, System Manager |
| FPS Masters & Setup | System Manager |
| Payment Receipts | Accounts User, Accounts Manager, System Manager *(was none)* — deliberately **not** its parent's roles |

**Workspace roles hide navigation only.** They are not an access control: any
user can still reach a hidden page's records by URL, global search or the REST
API. Confidentiality has to come from document and report permissions.

Frappe does the rest by itself — it hides each workspace link, sidebar item and
report the viewer cannot open, and hides a card once all of its links are hidden.
So layout follows permissions, never the reverse, and a page can safely list
things only some viewers will see.

Applied here: **ops@ keeps Accounts**, because they raise invoices and book
supplier costs. They lose HR, Masters & Setup and the Payment Receipts sub-tab.
The owner's actual requirement — ops must not see bank reconciliation, client
receipts, or total outstanding — is a **permissions** change tracked separately;
nothing in these fixtures enforces it.

## Step 2 — the shortcuts

Every filter was probed against live data and then adversarially re-verified by a
second pass: each is accepted by the site, every row is 4 elements, and each
returned count matched. **The design's numbers are placeholders** (it says so) and
no filter was bent to reach them — these are what the badges read today.

| Shortcut | Colour | View | Badge | Filter | Live |
|---|---|---|---|---|---|
| New Enquiry | Cyan | New | `{} open` | `status = Open` | 34 / 39 |
| New Job Order | Blue | New | `{} open` | `fps_stage not in (Closed, Invoiced)` + `docstatus != 2` | 40 / 84 |
| Customs Tracker | Orange | List | `{} pending` | `status not in (Cleared)` | 1 / 46 |
| Proof of Delivery | Green | List | `{} filed` | `docstatus != 2` | 35 / 38 |
| Sales Invoice | Purple | List | `{} open` | `status in (Unpaid, Overdue, Partly Paid)` + `docstatus = 1` | 130 / 628 |
| Purchase Invoice | Grey | List | *(none)* | *(none)* | — |

Two on **FPS Operations** rather than the home page, so the design's six-tile
single row stays intact:

| Shortcut | Colour | View | Badge | Filter | Live |
|---|---|---|---|---|---|
| Daily Job Tracker | Blue | Kanban `FPS Job Tracker` | `{} open` | `fps_stage not in (Closed, Invoiced)` + `docstatus < 2` | 40 / 84 |
| Local trucking & delivery | Orange | List | `{} jobs` | `fps_svc_transport = 1` | 26 / 84 |

### Judgement calls worth knowing about

- **Drafts are counted, everywhere.** 54 of 84 Job Orders and 20 of 38 PODs are
  `docstatus 0`. Adding `docstatus = 1` would collapse the job badge from 40 to 5
  and hide 35 live jobs. This site works in draft.
- **Purchase Invoice ships with no badge at all.** "Booked = submitted" is
  well-formed but returns 0 — nobody has ever submitted a Purchase Invoice here,
  and all 53 drafts are Qashio corporate-card overhead, not freight cost. Both
  "0 booked" and "53 draft" would mislead, so it is a plain nav tile.
- **Customs Tracker reads 1, not 14.** 45 of 46 records are already Cleared. Also
  the literal status `Pending` has zero records — ops go straight to In Process —
  so the naive `status = Pending` filter would read 0 forever.
- **Enquiry terminal statuses are dead.** Converted / Lost / Cancelled are all 0
  across 39 records, so "34 open" only ever grows until enquiries get closed out.
  Worth a process fix rather than a filter fix.
- **`stats_filter` cannot express OR.** Rows are ANDed. "Land transport" is
  really `fps_svc_transport = 1 OR fps_svc_crossborder = 1` (31 jobs); a second
  row would give the intersection (1). Hence the honest name *Local* trucking,
  covering 26 of those 31.
- **A badge is a count, never a sum.** The design's "63 · 210k open" cannot be one
  shortcut. The count half ships now; the AED half is a step-3 Number Card
  (Sum over `outstanding_amount`, same filters).
- The ten legacy home shortcuts are replaced. Every target survives on a child
  workspace's link cards, in the sidebar, or on Payment Receipts.

## Design members with no primitive behind them

These are named in the README's IA but have nothing to point at on this site.
None of them are faked with a wrong link.

| README member | Why not built | Where it belongs |
|---|---|---|
| Rate enquiry log | **Still not built.** FPS Enquiry has no enquiry-type, category or service field — its only Selects are `status`, `movement_type` and `enquiry_source`, none of which carries a rate/non-rate meaning. Nothing in the data distinguishes a rate enquiry, so no filter was invented | Needs a field on FPS Enquiry first |
| Daily Job Tracker | **Built in step 2** as an FPS Operations shortcut: `doc_view = Kanban`, `kanban_board = FPS Job Tracker` | Done |
| Trucking & delivery | **Built in step 2** as *Local trucking & delivery*, an FPS Operations shortcut. Renamed because a `stats_filter` cannot express OR, so it covers local transport (26) not local-or-cross-border (31) | Done |
| AR / AP Charges | `FPS AR Charge` / `FPS AP Charge` are child tables of Job Order, not lists | Mapped to the *Accounts Receivable* / *Accounts Payable* reports |
| Port / Location | No doctype. ERPNext's `Location` is an Assets land record, not a seaport | Needs a decision — a new doctype, or drop it |
| Charge Type | Charges are `Item` records in the Services group | Mapped to `Item`, labelled *Charge items* |
| FPS Job Tracker (report) | Not a Report — it is the Kanban board | Kept as the board |

## Field mapping the later steps must use

The README's assumed field names differ from what Job Order and Customs Tracker
actually have. Verified 2026-09-09:

| README assumes | Actual field |
|---|---|
| `Job Order.status` | **`fps_stage`** — `New / Docs / In Progress / Cleared - Ready / Delivered / Invoiced / Closed / On Hold`. The `status` field exists but is `hidden = 1` and carries a different, unused value set |
| `Job Order.sow` | `fps_category` — `CC / FF / LT / XB / GJ`; `fps_subcategory` is the built label |
| `Job Order.eta` | `eta` exists; `fps_next_due` ("Next action due") is the better deadline for *needs action* |
| `Job Order.route` | `pol` + `pod` (Origin / Destination) |
| `Job Order.gross_profit` | **Already exists** (Currency, read-only), alongside `total_sale` / `total_cost`. No new field needed for card 4 |
| `Job Order.billing_status` | Does not exist and is **not needed** — `sales_invoice` is a Link, so *delivered, not invoiced* is `fps_stage = Delivered` and `sales_invoice is not set` |
| `Customs Tracker.status = Submitted` | Values are `Pending / In Process / Cleared / On Hold / Delayed`. *Awaiting customs clearance* is `status in (Pending, In Process)`. There is a separate `fps_doc_submission` field with `Pending / Submitted` |

So both number cards the README flagged as "not expressible as plain list
filters" **are** plain filter cards on this site.

## v16 gotchas that apply to steps 2–4

- `stats_filter`, `quick_list_filter` and Number Card `filters_json` rows must be
  **4-element** `[doctype, field, op, value]`. A 5-element legacy row makes
  `frappe.utils.cleanup_filters` silently drop the last filter.
- Sidebar items with `link_type = URL` always render `target="_blank"` in v16.
- Workspace Sidebar is `@site_cache`d per gunicorn worker; a stale worker can
  serve the auto-generated sidebar until its cache clears. Re-saving Module Def
  `FPS` clears it on the worker that handles the request; a bench restart clears
  all of them.
