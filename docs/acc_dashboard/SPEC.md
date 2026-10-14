# FPS OPS / FPS ACC dashboards — build spec (14 Oct 2026)

Agam, 14 Oct 2026: "Let's keep this current dashboard as a FPS OPS dashboard only — give access to
all, after removing Invoices and collection tabs. And on other hand generate a FPS ACC dashboard
separately — only admin, Agam & Abhishek have the access to. You can add more useful things related
to FPS all accounting."

Standing rules that apply: read-only (nothing on either dashboard writes to ERPNext); the current
look (DESIGN.md, Pearl / Matte Black palettes, glass cards, bento grid) is kept — the ACC page is
built from the same components; money never reaches anyone without access.

Repo: worktree `C:\Users\FPS_AI\fps_erpnext_cc` (branch feat/ai-command-center == origin/main).
Live site: fastplanet.u.frappe.cloud (Frappe/ERPNext v16). Users today:
agam@ and abhishek@ (System Manager + Accounts Manager + Accounts User + FPS Operations …),
ops@ = Suhaib (Desk User, Employee, FPS Operations), hello@ = Azeem (Desk User, Employee,
FPS Customs Access, FPS Viewer), plus integration users alaan@ and n8n@.

---------------------------------------------------------------------------------------------------
## 1. FPS OPS dashboard (the existing Command Center on FPS Home)

* Same page (Workspace "FPS", block "FPS Overview"), same bundle. Workspace "FPS" is public with
  no roles, so every desk user already opens it — no access change needed.
* NO MONEY for anyone, finance roles included:
  - KPIs: the 6 operations KPIs only (enquiries, quotations, jobs, customs_cleared, deliveries,
    job_activity). "Invoiced (net)" and "Collected" are gone from this page.
  - Trend: "pipeline" and "activity" only; the "money" tab is gone.
  - Insights: no money insights (duplicate drafts, invoicing stall, AR ageing); the quotation-drafts
    insight never shows an AED total. delivered_not_invoiced (a job count) stays.
  - Stage strip: drop the "invoices" tile (open Sales Invoices) — it belongs to ACC. Do it in
    command_center (filter the tiles), NOT in pipeline.TILES (the legacy strip and other callers
    keep it).
  - Drawer: get_metric_detail rejects money metrics for everyone; Quotation records never carry
    a value on this page.
  - viewer.finance is always false in this payload.
* Header title becomes "FPS OPS Dashboard" (was "Command Center"); the first-load skeleton always
  shows 6 KPI placeholders.
* Implementation: the simplest correct change is in fps_erpnext/api/command_center.py (pass
  finance=False everywhere, filter the stage tile, reject finance keys in get_metric_detail) and the
  matching tests; keep command_center_logic's money functions — ACC reuses them.

---------------------------------------------------------------------------------------------------
## 2. FPS ACC dashboard (new)

### 2.1 Access
* New Workspace **"FPS ACC"** (title "FPS ACC", parent_page "FPS", public 1,
  roles = ["Accounts Manager"]) — Frappe hides a workspace from users with none of its roles.
  Administrator has every role. Today Accounts Manager = Administrator, agam@, abhishek@ only.
* API gate: every whitelisted method in fps_erpnext/api/acc_dashboard.py starts with
  `frappe.only_for("Accounts Manager")` (Administrator passes). Nothing is read before it.
  Cache keys are per user (frappe.cache().get_value(..., user=user)) like command_center.
* Sidebar "FPS" (docs/design_handoff_fps_workspace/build_workspaces.py SIDEBAR_ITEMS): add
  `s_link("FPS ACC Dashboard", "Workspace", "FPS ACC", icon="accounting", child=0)` right after
  "FPS Home". Check in the Frappe v16 source that a Workspace sidebar link is hidden for users who
  cannot open that workspace; if it is NOT hidden, say so in the report (do not invent a workaround).
* hooks.py fixtures: add "FPS ACC Overview" to the Custom HTML Block name filter.

### 2.2 Page
Workspace "FPS ACC" content: a header ("FPS ACC Dashboard") and one full-width custom block
**"FPS ACC Overview"** (new block: html + css + js under
docs/design_handoff_fps_workspace/custom_blocks/fps_acc_overview.*). Its loader is a copy of
fps_overview.js that imports the SAME bundle and calls `m.mount(scope, { mountPoint, variant: "acc" })`.
Line 1 must be `var FPS_CC_VERSION = "<hash>";` (sync-block stamps it). Its fallback on bundle
failure is a one-line message ("The FPS ACC Dashboard could not load — reload the page."), no
legacy strip. Loading text: "Loading the FPS ACC Dashboard…".

Workspace JSON goes through build_workspaces.py. STAMP: do NOT bump the global STAMP (that rewrites
every workspace/client-script file). Give ONLY the files whose content changes (the new FPS ACC
workspace and the FPS sidebar) a newer `modified` ("2026-10-14 12:00:00.000000") via a per-file
override, so `git diff` shows only intended files. Run the builder and check the diff.

### 2.3 Payload (contract: dashboard/src/types/acc.ts — follow it exactly)
Period filter 7d / 30d / 90d like OPS (same period windows, buckets, deltas, sparklines — reuse
command_center_logic: period_windows, bucket_series, summarize, delta_pct, weekly_totals,
format_money_compact, list_route, rank_insights, _insight, …).

**KPIs (period, with sparkline + delta + drawer):**
| key | label | definition |
|---|---|---|
| invoiced | Invoiced (net) | reuse logic.METRICS["invoiced"] / points_invoiced (payment requests and drafts excluded, credit notes included) |
| collected | Collected | reuse logic.METRICS["collected"] / points_collected (+ its receipt-lag caveat) |
| paid_out | Paid out | money that left: submitted Payment Entries of type Pay (base_paid_amount) by posting date, PLUS submitted Purchase Invoices with is_paid = 1 (card spends paid at booking, base_grand_total) by posting date. Dimension: "Paid via" (mode_of_payment, or "Card (paid at booking)") |
| purchases | Purchases booked | submitted Purchase Invoices, base_net_total by posting date (debit notes negative). Dimension: supplier group or supplier (top 5 + Other) |
good_direction: invoiced/collected "up"; paid_out "none"; purchases "none".

**Balances (as of today; no period):**
* receivables — sum outstanding_amount of submitted Sales Invoices (all, incl. legacy FPF/…).
  Context: Overdue (due_date < as_of, outstanding > 0), Open invoices (count), Unallocated receipts
  (sum unallocated_amount of submitted Receive Payment Entries > 0), Drafts waiting (count + AED).
  severity "warning" when overdue/total ≥ 0.5. Route: /app/query-report/FPS%20Customer%20Receivables.
* payables — sum outstanding_amount of submitted Purchase Invoices. Context: Overdue, Open bills,
  Unallocated supplier payments (Pay PEs), Draft bills (count). Route: Accounts Payable report.
* cash — General Ledger balance (debit − credit, is_cancelled = 0, up to as_of) of every leaf
  Account with account_type in ("Bank", "Cash") for the company, plus context lines for the 3
  largest by absolute balance and "Qashio card liability" (balance of Qashio Card Liability - FPS,
  credit − debit) when non-zero. Aggregate in SQL with frappe.qb (functions, not string aggregates —
  v16 rejects "sum(x)" strings). Caveat: "Book balances from ERPNext, not bank statements."
  Route: /app/query-report/General%20Ledger?group_by=Group%20by%20Account (or the Account list).
* vat — UAE VAT Stagger 3 quarters (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec), return due on the 28th of
  the month after the quarter. Show the LAST COMPLETED quarter while its due date has not passed
  (on 14 Oct 2026 that is Jul–Sep 2026, due 28 Oct 2026), otherwise the current quarter to date.
  value = output VAT (credit − debit on "VAT 5% - FPS" in the quarter) − input VAT (debit − credit
  on "Sales Taxes Receivables - FPS" in the quarter). Context: Output VAT, Input VAT, Due date
  ("28 Oct 2026 · 14 days"). severity warning ≤ 14 days to due, critical when past due and the
  quarter is the one shown. Caveat: "From ERPNext postings; the return filed on EmaraTax may differ."
  Route: General Ledger filtered to the two accounts and the quarter.
Resolve account names by account_type/name at run time; if an account does not exist, leave that
part out (never fail the whole payload).

**Ageing (as of today):** receivables and payables, 7 buckets by days past due_date
(not_due = due_date ≥ as_of; then 0–30 … over 365, past-due days = as_of − due_date), counts
per bucket, overdue total, top 5 parties by outstanding (value, overdue, oldest_days, count,
route = Sales/Purchase Invoice list filtered by customer/supplier, docstatus 1, outstanding ≠ 0).
Negative outstanding (credit/debit notes, overpayments) is netted into the party and the bucket of
its own due date.

**Banks:** for bank codes ADCB, WIO, QGEN, QGOV read FPS Bank Statement (name pattern
FPS-BST-<CODE>-<YYMM>; fields status, statement_month / month_code, closing_balance, to_date).
latest = highest YYMM. months_behind = months from latest month to LAST calendar month (0 = up to
date). Route = the statement form, or the FPS Bank Statement list filtered by bank when none.

**Trend:** 12 ISO weeks (reuse weekly_totals / the money TrendMode shape): "billing" (Invoiced
(net) slot 1, Collected slot 2), "cashflow" (Collected slot 1, Paid out slot 2). unit currency.

**Insights (rule-based, ranked + capped at 6 with rank_insights):**
reuse rule_invoicing_stall, rule_duplicate_drafts, rule_ar_ageing, rule_delivered_not_invoiced
(the money rules move here from OPS) and add:
* unallocated_receipts (warning): receipts with unallocated amount > 0 — "AED 100K received but not
  matched to invoices" — route Payment Entry list (Receive, docstatus 1, unallocated_amount > 0).
* supplier_overdue (info, warning when > AED 50K): overdue payables total and supplier count.
* bank_statements_behind (warning): any bank with months_behind ≥ 1 or latest status In Progress
  for a month older than last month — name the banks.
* vat_due (warning ≤ 14 days, critical past due): "VAT return Jul–Sep 2026 due in 14 days".
* sales_invoice_drafts (info): N drafts worth AED X, oldest D days (skip when the
  duplicate_drafts insight already covers the same drafts, or merge sensibly).
Titles ≤ 90 chars, details ≤ 200, plain text (existing _insight helper enforces).

**Drawer (get_metric_detail):** same MetricDetail shape as OPS for the 4 ACC KPIs — series,
breakdown by dimension, latest ≤ 8 records (with value), actions = open the list behind the number
(no "New" action for paid_out / purchases; Sales Invoice "New" for invoiced like today).

### 2.4 Python structure
* fps_erpnext/api/acc_dashboard.py — whitelisted GET methods, the role gate, frappe reads (get_list
  with permissions; qb for GL sums), per-user cache (key prefix "fps_acc_dashboard:v1:"), nothing
  else. Keep reads bounded (period floor / open documents / current quarter).
* fps_erpnext/api/acc_dashboard_logic.py — pure functions (no frappe import), like
  command_center_logic, reusing it where possible.
* fps_erpnext/tests/test_acc_dashboard_logic.py — unittest, runnable without bench:
  `python -m unittest fps_erpnext.tests.test_acc_dashboard_logic` from the repo root. Cover:
  ageing buckets (boundaries 0/30/31/…/365, negatives), VAT quarter selection + due date + sign,
  bank months_behind, paid_out (PE + is_paid PI, no double count), purchases (returns negative),
  every insight rule (fires / does not fire), payload shape (keys, order, rounding), and that the
  OPS payload carries no money (update test_command_center_logic accordingly).

### 2.5 Frontend (dashboard/, same bundle)
* main.tsx: MountOptions gains `variant?: "ops" | "acc"` (default "ops"); the element records it
  (attribute data-variant) and renders `<CommandCenter/>` (ops) or `<AccDashboard/>` (acc).
* useDashboard: method chosen by variant (GET fps_erpnext.api.acc_dashboard.get_dashboard /
  get_metric_detail for acc; add both to READ_METHODS in lib/frappe.ts); the "route returns to the
  workspace" refetch must work for the FPS ACC workspace too (its route is the workspace name
  "FPS ACC" / slug "fps-acc" — check how getRoute reports it); separate caches per variant.
* A PermissionError answer renders a calm "You do not have access to the FPS ACC Dashboard." panel.
* AccDashboard layout (bento, same tokens, both palettes):
  header "FPS ACC Dashboard" · company · as-of · live status · refresh · appearance button;
  InsightBanner; period filter row; 4 KPI MetricCards (one row at lg); 4 BalanceCards (new
  component: big value, context lines, severity tint, caveat icon, link); TrendChart with the
  billing/cashflow tabs (lg 8) + BankStatus card (lg 4: one row per bank — label, latest month,
  status badge with icon + text, closing balance, "N months behind"); two AgeingPanels side by side
  (lg 6 each: stacked horizontal bar or 7 bars with values, legend, top 5 parties list with links).
  Every number is a link or opens the drawer, like OPS. Accessible: icons + text for status,
  aria labels, keyboard focus, contrast per DESIGN.md (both palettes).
* CommandCenter (OPS): title "FPS OPS Dashboard"; skeleton always 6 KPIs; nothing else changes.
* New components get `.meta.ts` companions like the existing ones; dev harness
  (dashboard/dev) gets `?variant=acc` with realistic fixtures (dev/fixtures/acc.*.json — fictional
  party names like "Key account (sample)", never real customer names).
* scripts/sync-block.mjs stamps the bundle hash into BOTH loaders (fps_overview.js and
  fps_acc_overview.js) then runs build_workspaces.py.
* `npm run build` (tsc + vite + sync-block) must pass. Run builds ONE AT A TIME — this PC crashed
  under parallel builds on 14 Oct. Never run headless Chrome/Edge/puppeteer/SwiftShader.

---------------------------------------------------------------------------------------------------
## 3. Hard limits for every agent
* No writes to the live site (no REST POST/PUT/DELETE, no MCP create/update). Reading the live site
  is allowed: `node` scripts with the token from C:/Users/FPS_AI/.mcp-fps-proxy.cjs (see
  C:\Users\FPS_AI\AppData\Local\Temp\claude\C--Users-FPS-AI\33dc4a3f-a1e3-478f-83c8-dfda74e396c2\scratchpad\pf\api.cjs
  — `get(path, params)`), never print the token.
* No git commit / push / branch changes — the lead commits.
* Stay inside your assigned files; another agent works in the other half of the repo at the same time.
