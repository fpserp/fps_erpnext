# Handoff: FPS Workspace redesign (ERPNext / Frappe v16)

## Overview

Fast Planet Shipping LLC (freight forwarder + customs broker, Dubai) runs everything
through a single ERPNext tile named **FPS**. This design splits that one tile into a
parent workspace with six child workspaces, adds a status-coloured operations home
page, and redesigns the Job Order list view so a job can be triaged without opening it.

Problems being solved, in the user's words: too many clicks to reach daily tasks, no
sense of status at a glance, plain/grey and dull, hard to train new staff, slow to find
records, reports hard to read.

Three designs are in the bundle:

- **1a — Pipeline first** (the approved direction). Workspace home with a 7-stage
  shipment pipeline strip, 4 number cards, 6 coloured shortcuts, a quick list, a chart,
  and three link cards.
- **1b — Zero custom code.** Same job, built only from stock blocks. Reference/fallback.
- **1c — Job Order list view.** Indicators, column set, saved views, group-by sidebar.

Plus a **build spec panel** at the bottom of the file (`#build`) summarising the same
seven implementation steps described below.

## About the design files

`FPS Workspace.dc.html` is a **design reference created in HTML** — a prototype of the
intended look and behaviour. **Do not ship it, embed it as a web page, or serve it from
`www/`.** The target environment already exists: it is the Frappe/ERPNext desk, and this
design must be recreated using **Frappe v16 workspace primitives**:

| Design region | Frappe primitive |
|---|---|
| Sidebar categories | `Workspace` records with `parent_page` set |
| Coloured tiles with counts | `Workspace Shortcut` child rows (`color`, `stats_filter`) |
| KPI boxes | `Number Card` records (+ `Number Card` workspace blocks) |
| Bar / donut charts | `Dashboard Chart` records (+ `Chart` blocks) |
| Record lists on the home page | `Quick List` blocks |
| Grouped doctype link columns | `Card` (link) blocks / `Workspace Link` rows |
| Page titles and intro copy | `Header` / `Text` (paragraph) blocks |
| The 7-stage pipeline strip | **one** `Custom HTML Block` + one whitelisted API method |
| List view dots, labels, columns | `frappe.listview_settings` in `<doctype>_list.js` |

Everything except the pipeline strip and the list-view JS is editor configuration. The
only new Python is a single whitelisted read method for the strip.

## Fidelity

**High-fidelity for layout, hierarchy, colour semantics and copy. Deliberately NOT
pixel-precise for chrome.** The desk's own navbar, sidebar chrome, fonts, card borders
and grid gutters come from Frappe's CSS and must be left alone — the mock draws
approximations of them so the page can be judged in context.

What must be reproduced exactly:

- the **information architecture** (six categories and their members),
- **which block type** renders each region and in what order,
- the **five status colours and their fixed meanings**,
- the **labels and filter definitions** of every card, shortcut and quick list.

What must NOT be reproduced: the mock's fonts (Space Grotesk / IBM Plex Sans / IBM Plex
Mono are stand-ins — use the desk font), its exact paddings, and its hand-drawn navbar.

## Information architecture

Parent workspace **FPS** (keep the existing record; retitle to *FPS Home*), with children
in this order. HR intentionally uses stock ERPNext HR doctype names so ERPNext's own
permissions, workflows and reports keep working — do not clone them.

| # | Workspace | Members |
|---|---|---|
| 1 | **FPS Home** | the home page described below (no child links) |
| 2 | **Sales** | FPS Enquiry, Quotation, Customer, Rate enquiry log |
| 3 | **Operations** | Job Order, Daily Job Tracker, Customs Tracker (Mirsal), Trucking & delivery, Proof of Delivery |
| 4 | **Accounts** | Sales Invoice, Purchase Invoice, AR / AP Charges, Payment Entry, VAT 5% return |
| 5 | **HR** | Employee, Attendance, Leave Application, Shift Assignment, Expense Claim, Payroll Entry, Salary Slip |
| 6 | **Reports** | FPS Job Tracker, FPS Open Jobs by SOW, FPS Profitability per Job Order, FPS Monthly GP Trend |
| 7 | **Masters & Setup** | Customer, Supplier, Port / Location, Charge Type, Cost Center, Users & Roles |

Set `sequence_id` on each so the order is stable, and restrict each workspace to the
roles that use it (`roles` child table) — an accounts user should not see the Operations
tree.

## Screen 1 — FPS Home (design `1a`)

**Purpose:** answer "what needs me today" in one screen, and teach a new hire the
company's process by showing it left to right.

Block order down the page:

1. **Header + Text**
   - H1: `Fast Planet Shipping — {full name of logged-in user}`
   - Sub-line: `9 jobs need you today · 3 past their customs deadline · 11 delivered but unbilled`
     (counts are live; render from the same API call as the strip).

2. **Custom HTML Block — "Shipment pipeline"**
   - Card header row: title `Shipment pipeline`, helper `live count by stage — click a
     stage to open Job Order filtered to it`, right-aligned `74 jobs · last 90 days`.
   - Then a 7-column equal grid, 1px dividers, each cell with a **3px coloured top
     border**, and three stacked lines: stage label (11.5px/500), count (26px/600), and a
     small sub-line.

   | Stage | Top border | Count | Sub-line |
   |---|---|---|---|
   | Enquiry | `oklch(0.68 0.1 220)` | 39 | 4 unanswered |
   | Quotation | `oklch(0.66 0.11 205)` | 28 | 9 awaiting reply |
   | Job Order open | `oklch(0.62 0.12 195)` | 22 | sea 9 · air 7 · land 6 |
   | Customs / Mirsal | `oklch(0.65 0.14 75)` | 14 (amber numeral) | **3 past deadline** (red) |
   | Trucking | `oklch(0.66 0.1 265)` | 8 | 2 delivering today |
   | POD received | `oklch(0.62 0.12 150)` | 29 | 11 not invoiced |
   | Invoiced | `oklch(0.55 0.12 300)` | 63 | AED 210k open |

   Each cell links to `/app/job-order?status=<stage>` (or the relevant doctype list).
   Must scroll horizontally, not wrap, below ~900px.

3. **Number Card × 4** — tinted surface, 1px border of the same hue, 28px/600 numeral,
   12.5px label, 11.5px query hint.

   | Label | Colour | Value | Definition |
   |---|---|---|---|
   | Jobs past deadline | red | 3 | Job Order, ETA < today, status not Delivered |
   | Awaiting customs clearance | amber | 14 | Customs Tracker, status = Submitted |
   | Delivered, not invoiced | purple | 11 | POD exists, no linked Sales Invoice |
   | GP this month | green | AED 186k | Σ(Sales Invoice − Purchase Invoice) per job, +9% |

   The last two are not expressible as plain list filters. Either make them
   **Report-type** number cards over a query report, or (preferred, and needed for
   sorting anyway) add `billing_status` and `gross_profit` fields to Job Order kept
   current by a `doc_events` hook, then they become ordinary filter cards.

4. **Shortcut × 6** — one row, `color` set, `stats_filter` set so the count badge renders,
   `doc_view = List`. Label on top, count bottom-left in mono 11px.
   New Enquiry (cyan, `4 open`) · New Job Order (blue, `22 open`) ·
   Customs Tracker (orange, `14 pending`) · Proof of Delivery (green, `29 filed`) ·
   Sales Invoice (purple, `63 · 210k open`) · Purchase Invoice (grey, `53 booked`).

5. **Quick List (Job Order) + Chart**, side by side at roughly 1.15fr / 1fr.
   - Quick list "Jobs needing action": filter `status not in (Delivered, Cancelled)`,
     sort by deadline ascending. Row = status dot · mono job id · `Customer — route`
     (ellipsised) · right-aligned deadline pressure (`2d late` in red, `Today` in amber,
     weekday in grey).
   - Chart "Gross profit by month": Dashboard Chart, Sum, monthly interval, bar; last
     bar highlighted in brand cyan, earlier bars in a pale tint.

6. **Card / links × 3** — Sales · Operations · Accounts & reports, four links each. This
   is the low-traffic overflow; anything not in a shortcut lives here or in the sidebar.

## Screen 2 — Job Order list view (design `1c`)

Implement in `fps_erpnext/fps/doctype/job_order/job_order_list.js`:

```js
frappe.listview_settings["Job Order"] = {
  add_fields: ["status", "sow", "eta", "customer", "route", "gross_profit"],
  get_indicator(doc) { /* returns [__(label), colour, "field,=,value"] */ },
  formatters: { gross_profit: (v) => `${v}%` },
};
```

- **Columns, left to right:** indicator dot · Job (mono, 12px/500) · `Customer — route`
  (13px, ellipsised, flexible) · Status (11.5px/600, coloured to match the dot) ·
  SOW (12px grey) · Deadline (mono; red `2d late`, amber `Today`, grey date) ·
  Margin (mono; green normally, red below ~10%).
- **Saved views** as a pill row above the table: `Needs action 9` (active, dark) ·
  `At customs 14` · `In transit 8` · `Unbilled 11` · `Mine 6`.
- **Sidebar group-by:** Assigned to, Status, Scope of work — with counts.
- **Header:** `Job Order`, sub-line `22 of 74 · filter: status not in (Delivered, Cancelled)`.

## The colour system

Five status colours, fixed meanings, reused on **every** FPS doctype. This is the whole
system — do not add a sixth.

| Meaning | Frappe indicator | Mock value |
|---|---|---|
| Late / blocked | `red` | `oklch(0.56 0.17 25)` |
| At customs / waiting on someone | `orange` | `oklch(0.65 0.14 70)` |
| In transit / scheduled | `blue` | `oklch(0.55 0.11 265)` |
| Delivered but unbilled | `purple` | `oklch(0.55 0.12 300)` |
| Closed / collected | `green` | `oklch(0.62 0.12 150)` |

Brand, from `fps_erpnext/public/images/fps-logo.svg`: cyan **`#22D3EE`**, deep teal ink
**`#0E2A33`**. Teal is the ink and the one dark surface; cyan is the accent and the
active-state tint. Everything else is a neutral or one of the five status hues.

`oklch()` values in the mock are the intent. Frappe's number cards, shortcuts and
indicators only accept its **named palette**, so map to the nearest name (red, orange,
blue, purple, green, cyan, grey) rather than trying to force exact hexes; use the exact
values only inside the Custom HTML Block, where you control the CSS.

## Typography

The desk font governs. In the mock: Space Grotesk 600 for headings, IBM Plex Sans
400/500/600 for UI text, IBM Plex Mono for ids, counts and code-ish values. Keep only
the last idea — **monospace for record ids, deadlines and amounts** — and let everything
else inherit the desk's font stack.

Scale used, as a guide for the Custom HTML Block: 26–28px/600 big numerals,
23–24px/600 page title, 13.5–14px/600 card titles, 13px body, 12.5px labels,
11.5px sub-lines, 10–11px mono/uppercase eyebrows (0.06–0.12em tracking).

## Spacing, radius, surfaces

- Page padding 22–24px; block gap 22–24px; grid gaps 10–12px.
- Radius: 10px cards and shortcuts, 12px outer containers, 6–8px sidebar rows and pills.
- Surfaces: white cards on white page; 1px `oklch(0.91 0.01 220)` borders; tinted status
  cards use a `~0.965 L` tint of their own hue with a `~0.9 L` border.
- Sidebar: `oklch(0.975 0.005 220)`, active row `oklch(0.91 0.05 195)`, children indented
  25px at 12.5px, category headers 12.5px/600 with a caret.

## Implementation steps

1. Create the six child workspaces (`parent_page = FPS`), retitle FPS → *FPS Home*, set
   `sequence_id` and `roles`.
2. Add shortcuts with `color` + `stats_filter` + `doc_view`.
3. Create the four Number Cards (`is_public = 1`); add `billing_status` / `gross_profit`
   to Job Order if you want cards 3 and 4 as plain filter cards.
4. Create the two Dashboard Charts and the Quick List block.
5. Add `job_order_list.js` with `get_indicator` / `add_fields` / `formatters`.
6. Create the one Custom HTML Block for the pipeline strip, backed by a single
   `@frappe.whitelist()` method in `fps_erpnext/api/` returning the seven counts in one
   grouped query. **Read-only, permission-checked, no writes.**
7. **Ship it in the app, not the site.** Workspaces, number cards, charts and custom
   blocks created in the UI live in the site database. Build on staging, list Workspace /
   Number Card / Dashboard Chart / Custom HTML Block in `fixtures` in `hooks.py`, run
   `bench --site <site> export-fixtures`, and commit the JSON under
   `fps_erpnext/fps/workspace/…` so the layout survives a fresh install and is reviewable
   in git.

## Data / fields this design assumes

- **Job Order**: `status` (select with exactly the values used by the indicators),
  `sow` (Sea / Air / Land / Customs clearance), `eta` (deadline), `customer`, `route`,
  and stored `gross_profit` + `billing_status` so both can be sorted and filtered.
- **Customs Tracker**: `status` including `Submitted`, `Inspection held`, `Duty paid`,
  `Docs incomplete`, and a link to Job Order.
- **Proof of Delivery**: link to Job Order + `pod_date`.
- Job → Sales Invoice / Purchase Invoice links, for the unbilled and GP figures.

All record ids, customer names, routes and amounts in the mock are **illustrative**
(JO-0241, Al Futtaim, AED 186k …). Only the volumes were given as real: 74 Job Orders in
90 days, 63 Sales Invoices, 53 Purchase Invoices, 39 Enquiries, 36 Customs Tracker,
29 POD, 28 Quotations.

## Assets

- `assets/fps-logo.svg` — copied from `fps_erpnext/public/images/fps-logo.svg`, already
  referenced by `app_logo_url` in `hooks.py`. No new assets are required; the design uses
  no icon set and no imagery.

## Files in this bundle

- `FPS Workspace.dc.html` — the design reference (options `1a`, `1b`, `1c` and the build
  spec panel `#build`). Open in a browser; pan/zoom canvas. `support.js` sits beside it
  and must stay there for the file to render.
- `assets/fps-logo.svg` — the logo used in both mock navbars.
- `screenshots/1a-fps-home.png` — **the approved direction**, full page.
- `screenshots/1b-zero-custom-code.png` — the stock-blocks-only alternative.
- `screenshots/1c-job-order-list-view.png` — the list view.
- `screenshots/build-spec.png` — the seven implementation steps as shown in the design.

The screenshots are 2× captures of the HTML above; where they disagree with this README,
the README wins.

## Responsive note

Users are on a mix of desktop, tablet and phone. Frappe's own blocks reflow; the one
thing that will not is the pipeline strip. Give it `overflow-x: auto` with the seven
cells at a minimum width, and on narrow screens consider collapsing it to the three
stages that carry the red and amber counts.
