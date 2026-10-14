# FPS dashboards (OPS / ACC) — design system

The "AI-look" executive theme for the two FPS dashboards in ERPNext and the FPS
workspace pages around them, in its **Pearl** finish: a matt, muted blue-grey
plane under off-white glass cards, slate ink, and Electric Blue / Soft Violet
accents stepped deep enough to pass on a light surface.

| Page | Workspace · route | Who | What |
|---|---|---|---|
| **FPS OPS Dashboard** (formerly "Command Center") | **FPS** · `/desk/fps` (FPS Home) | every desk user | operations only — **no money for anyone**, finance roles included |
| **FPS ACC Dashboard** (14 Oct 2026) | **FPS ACC** · `/desk/fps-acc` | Accounts Manager only (Administrator, agam@, abhishek@) | invoicing, collections, supplier payments, purchases, receivables / payables / cash / VAT positions, ageing, bank statements |

Both are the same bundle and the same components; the block loader picks the
page (`mount(root, { variant: "ops" | "acc" })`).

> **Scope rule — presentation only.** Everything this file governs changes how
> the dashboard *looks*. It never creates, edits, moves, submits or deletes an
> ERPNext record, never changes a DocType, field, permission, workflow or
> naming series, and never sends anything. Data reaches the UI only through
> read-only, permission-aware `@frappe.whitelist()` methods. A change that needs
> a write is out of scope for this system and needs its own review.

Source of truth for the tokens below: `dashboard/src/styles/theme.css`
(the `:host, .fps-cc` block feeding the Tailwind v4 `@theme`). The desk
stylesheet `fps_erpnext/public/css/fps_theme.css` carries the same `--fps-*`
names and values for the pages around the dashboard. This document explains
them; if any two ever disagree, fix the CSS and this file in the same commit.

---

## 1. Baseline and surfaces

| Token | Value | Use |
|---|---|---|
| `--fps-bg` | `#D9DEE7` | Page plane. Muted blue-grey, OKLCH L 0.90 — matt, never white. |
| `--fps-surface-1` | `rgba(247, 248, 251, 0.62)` | Glass card (default). Effective colour over the plane ≈ `#ECEEF3`. |
| `--fps-surface-2` | `rgba(255, 255, 255, 0.78)` | Raised glass: drawer, tooltip, popover. ≈ `#F7F8FA`. |
| `--fps-surface-solid` | `#F7F8FB` | Fallback when `backdrop-filter` is unavailable or transparency is reduced. |
| `--fps-surface-inset` | `rgba(28, 34, 48, 0.03)` | Sunken tiles: icon wells, hovered rows. |
| `--fps-border` | `rgba(28, 34, 48, 0.10)` | The 1px translucent hairline on every glass surface. |
| `--fps-border-strong` | `rgba(28, 34, 48, 0.18)` | Hover / focus-within border, dividers inside the drawer. |
| `--fps-highlight` | `rgba(255, 255, 255, 0.70)` | 1px inner top highlight (`inset 0 1px 0`) that sells the glass edge. |
| `--fps-backdrop` | `rgba(42, 50, 66, 0.45)` | The drawer's page scrim — slate, never black, so the plane stays pearl under it. |

Every translucent value is slate (`#1C2230`, the ink) or white at an alpha,
never black: on a light plane a black hairline or shadow reads as dirt.

**Ambient light.** Glass needs something to blur. The bento sits on the plane
with two fixed, very low-alpha radial glows — Electric Blue at the top-left and
Soft Violet at the top-right, each ≤ 10% alpha. On the light plane they read as
a soft tint that darkens the top of the dashboard to ≈ `#C6D3E6`. They are
decoration only: no data is ever encoded in them, and they are removed under
`prefers-reduced-transparency` and `forced-colors`. Text that sits directly on
the plane under a glow should use `--fps-text-secondary` or darker (see §5).

## 2. Glassmorphism rules

Every card, banner and drawer is a glass surface built the same way:

```css
.glass {
  background: var(--fps-surface-1);
  backdrop-filter: blur(12px) saturate(140%);
  border: 1px solid var(--fps-border);
  box-shadow: inset 0 1px 0 var(--fps-highlight), 0 8px 24px rgba(28, 34, 48, 0.08);
  border-radius: 16px;
}
```

1. **Blur is exactly 12px.** Not 8, not 20 — one value so stacked surfaces read
   as one material. Raised surfaces (drawer, tooltip) change the *fill*
   (`--fps-surface-2`) and the *shadow* (the desk's pop shadow,
   `0 16px 40px rgba(28, 34, 48, 0.16), 0 2px 8px rgba(28, 34, 48, 0.08)`),
   never the blur.
2. **Borders are always 1px and translucent** (`--fps-border`). Never a solid
   colour border on glass; a coloured accent is a 2px *top edge* or a glow, not
   the border.
3. **Shadows are slate, soft and short.** `rgba(28, 34, 48, …)` at 0.08 for
   cards and 0.16 for raised glass. Never `rgba(0, 0, 0, …)`, never a glow
   under a card: on Pearl depth comes from the white inner highlight and the
   hairline, the shadow only lifts the edge.
4. **Write `backdrop-filter` unprefixed** in source. The build (Lightning CSS
   inside Tailwind v4) emits the `-webkit-` prefix; hand-writing both has
   broken builds on this team's other projects.
5. **Fallbacks are mandatory.**
   `@supports not (backdrop-filter: blur(1px))` and
   `@media (prefers-reduced-transparency: reduce)` swap the fill to
   `--fps-surface-solid`. `@media (forced-colors: active)` drops glows and
   shadows and lets the system colours draw borders.
6. **Glass never sits on glass more than two deep** (page → card → drawer).
   Text contrast is measured against the *effective* colour of the surface the
   text sits on: `#ECEEF3` for a card, `#F7F8FA` for raised glass, and the
   bare plane `#D9DEE7` (`#C6D3E6` under a glow) for text outside any card,
   see §5.

## 3. The 8px grid

All spacing, sizing and radii are multiples of 8px. 4px is allowed **only** for
icon-to-label gaps, badge padding and hairline offsets.

| Step | px | Tailwind | Typical use |
|---|---|---|---|
| 0.5 | 4 | `1` | icon ↔ label, badge inner padding |
| 1 | 8 | `2` | gaps inside a card row |
| 2 | 16 | `4` | card padding (compact), grid gutter on phones |
| 3 | 24 | `6` | card padding (default), grid gutter ≥ 1024px |
| 4 | 32 | `8` | section separation |
| 5 | 40 | `10` | drawer header height offsets |
| 6 | 48 | `12` | hero number line box |

- Radii: `8px` (badges, buttons, inputs), `12px` (inner tiles), `16px` (cards,
  banner, drawer edge).
- Control heights: 32px (compact) and 40px (default). Hit targets ≥ 24px.
- Phone layout keeps a **16px side gutter** and never scrolls horizontally.

## 4. Executive palette (Pearl steps)

Validated with the dataviz six-checks validator in `--mode light` against the
effective glass card `#ECEEF3` (surface-1 over the plane), the solid card
`#F7F8FB` and white `#FFFFFF` (popups) (OKLab ΔE ×100, Machado 2009 CVD
simulation): **all checks pass** — lightness band L 0.43–0.77, chroma ≥ 0.10,
worst adjacent CVD ΔE **12.3** (deutan; tritan 21.3, target ≥ 8), worst
normal-vision ΔE **20.2** (floor 15), every slot ≥ 3:1 against the surface.
On the bare plane `#D9DEE7` cyan is 2.92:1 — a validator WARN, not a fail —
which is one more reason a chart only ever renders inside a glass card.

### Roles

Contrast figures are text contrast on the glass card `#ECEEF3`.

| Role | Name | Hex | OKLCH | Where |
|---|---|---|---|---|
| **Primary data** | Electric Blue | `#1D6FD8` | L .55 C .18 h257 | series 1, primary sparklines, focus ring, primary buttons (white on it 4.9:1) |
| Electric Blue UI step | — | `#1456B8` | L .47 C .17 h259 | links and icons on glass (5.9:1) |
| **Positive delta** | Mint Green | `#0D6E48` | L .48 C .10 h160 | "up and good" badges, success states (5.4:1) |
| **AI insights / secondary data** | Soft Violet | `#6D4ACB` | L .52 C .19 h291 | AI banner accents, insight icons, shimmer (5.2:1) — UI only, not a chart mark |
| Soft Violet series step | — | `#6D1F9D` | L .43 C .19 h308 | series 2 marks in charts and the money role colour (7.8:1; a lightness step below blue so the pair survives every CVD) |
| Negative delta | Rose | `#B3243E` | L .50 C .18 h17 | "down and bad" badges, critical states (5.6:1; white on it 6.5:1) |
| Warning | Amber | `#8A5007` | L .49 C .11 h63 | warnings, deadlines approaching (5.6:1) |

Why two violets: at close lightness Electric Blue and Soft Violet collapse for
protanopes and deuteranopes — they become the same colour. The validated fix
keeps blue at L .55 and steps the *chart* violet down to L .43 (and round to a
more magenta hue), so the two primary series are separated by lightness, which
survives every kind of colour blindness. The UI violet stays for accents, where
it is never the only thing telling two data series apart.

The Pearl trade-off: on a light surface every accent has to go deep to reach
4.5:1, so status colours read as ink, not light (amber is a brown, mint a
forest green). That is by design — do not brighten them for "pop"; a brighter
step fails the text check.

### Categorical order (charts) — fixed, never cycled

| Slot | Hue | Hex |
|---|---|---|
| 1 | Electric Blue | `#1D6FD8` |
| 2 | Soft Violet (series) | `#6D1F9D` |
| 3 | Cyan | `#008F90` |
| 4 | Amber (series) | `#A26000` |

- A fifth series folds into **Other** (`--fps-series-other: #6B7587`). Never
  generate a hue.
- Colour follows the entity, never its rank: a filter that hides a series must
  not repaint the survivors (map series → slot by key, not by index).
- Status colours (mint / amber / rose) are reserved for *state* and always ship
  with an icon and a label, never colour alone. They are never "series 4".

### Delta semantics

A delta badge's colour = direction × whether up is good **for that metric**:

| Metric kind | Up | Down |
|---|---|---|
| Volume / revenue / collections (`goodDirection: "up"`) | Mint ▲ | Rose ▼ |
| Backlog / overdue / past-ETA (`goodDirection: "down"`) | Rose ▲ | Mint ▼ |
| Neutral (`goodDirection: "none"`) | Muted ▲ | Muted ▼ |

Zero change renders a muted `0.0%` badge; "no prior data" (the source does not
reach back far enough to compare) renders a muted `—`; a delta is never
computed against a zero or negative base (show "new" instead of `+∞%`).

## 5. Ink and type

| Token | Hex | Contrast on `#ECEEF3` (glass card) · `#D9DEE7` (plane) |
|---|---|---|
| `--fps-text` | `#1C2230` | 13.7:1 · 11.8:1 |
| `--fps-text-secondary` | `#3F4859` | 7.9:1 · 6.8:1 |
| `--fps-text-muted` | `#566070` | 5.5:1 · 4.7:1 (axis ticks, captions — still ≥ 4.5; under an ambient glow the plane darkens to `#C6D3E6` and this drops to 4.2:1, so a caption that sits on the bare plane uses `--fps-text-secondary`) |
| `--fps-grid` | `#D6DBE4` | gridlines (decorative) |
| `--fps-axis` | `#B8C1CE` | baseline / axis rule (decorative) |

- **Typeface:** the desk's Inter (`InterVariable, Inter, system-ui, sans-serif`)
  inherited into the shadow root — no extra font download. No display or
  serif faces, including the hero number.
- **Scale (px / line-height):** 12/16 caption · 13/20 body-sm · 14/20 body ·
  16/24 title · 20/28 card value · 32/40 KPI value · 48/56 hero.
- **Figures:** proportional for stand-alone big numbers; `tabular-nums` only
  where numbers align in columns (tables, axis ticks, tooltip rows).
- **Text never wears a series colour.** Labels, values and legends use the
  ink tokens; identity comes from a swatch or line-key beside the text.
- Numbers: AED amounts auto-compact (`AED 12.9K`, `AED 1.2M`) on cards; the
  drawer and table view show the full figure (`AED 12,874.50`).

## 6. Data-viz rules (applies to every chart)

- Lines 2px with round joins; area fill is a wash — a vertical gradient from
  18% to 0% of the series colour (average ≈ 10%), never a solid block.
- Bars ≤ 24px thick, 4px rounded data-end, square at the baseline, 2px surface
  gap between stacked segments.
- Gridlines: solid 1px `--fps-grid`, horizontal only. Never dashed. One y-axis
  only — no dual-axis charts; different units go in separate charts or tabs.
- Hover: crosshair + one tooltip listing every series at that x (value first,
  label second, line-key not box). Same content on keyboard focus.
- ≥ 2 series → a legend is always shown; ≤ 4 series → also direct-label the
  last point. 1 series → no legend box; the title names it.
- Every chart has a **table view** toggle (the accessible twin).
- Refetch keeps the frame: the previous render stays at 60% opacity while
  loading — no skeleton flash after the first paint.
- Sparklines: 7 points (one per day), 2px line in the metric's role colour,
  last point marked with an 8px dot ringed in the surface colour; no axes.

## 7. Motion

- 150ms for hover/press, 200ms for drawer slide, `cubic-bezier(.2,.8,.2,1)`.
- The AI banner's shimmer is a single slow (6s) gradient sweep on its 1px
  border — paused under `prefers-reduced-motion: reduce`.
- No count-up animations on numbers (executives screenshot these; a number
  must be correct in every frame).

## 8. Bento layout

12-column CSS grid, 24px gutters (16px under 768px). Both pages start with the
same header — title ("FPS OPS Dashboard" / "FPS ACC Dashboard") · company ·
as-of date · live status · refresh · appearance — and a text link to the
other page under the subtitle (OPS → ACC only for Accounts Manager holders;
ACC → OPS always).

**FPS OPS Dashboard**, top to bottom:

| Area | lg (≥ 1024) | md (768–1023) | sm (< 768) |
|---|---|---|---|
| AI insight banner | 12 | 12 | 12 |
| KPI metric cards (×6, operations only) | 4 each (3 per row) · xl ≥ 1440: 2 each (6 in a row) | 6 each | 12 each |
| Trend analytics chart (Sales pipeline / Operations tabs) | 8 | 12 | 12 |
| Pipeline stages (the Overview tiles, no Invoices tile) | 4 | 12 | 12 |

Below the bento the page keeps its existing blocks (Job Tracker, quick list),
re-themed by the FPS Pearl desk theme — their content and behaviour are
unchanged.

**FPS ACC Dashboard**, top to bottom:

| Area | lg (≥ 1024) | md (768–1023) | sm (< 768) |
|---|---|---|---|
| AI insight banner | 12 | 12 | 12 |
| Period filter row | 12 | 12 | 12 |
| KPI metric cards (×4: Invoiced (net), Collected, Paid to suppliers, Purchases booked) | 3 each | 6 each | 12 each |
| Balance cards (×4, "Position as of …": Receivables, Payables, Cash & bank, VAT for the quarter) | 3 each | 6 each | 12 each |
| Trend chart (Billing / Cash flow tabs) | 8 | 12 | 12 |
| Bank statements card | 4 | 12 | 12 |
| Ageing panels (receivables, payables) | 6 each | 12 each | 12 each |

**BalanceCard** (a position, not a flow: no sparkline, no delta, ignores the
period). Value 32/40 in ink, a real link to the report behind it; up to four
server-formatted context lines; the data caveat behind an amber "Data caveat"
button. **Severity** is shown twice, never by colour alone and never on the
text: a 2px top edge in the state colour (rule 2 of §2) AND a chip with icon +
label on its own row under the value. `info` adds no emphasis. The server sets
it: receivables **warning** when overdue ≥ 50 % of the total; VAT **warning**
≤ 14 days to the due date, **critical** past it; cash **critical** when the
books differ from a bank's latest statement by more than 1 % at the
statement's closing date (the caveat names the bank and the gap).

**Bank statements card.** One link row per account: label, status chip
(mint Reconciled / amber In progress / rose Missing, each with its icon),
latest month · closing balance, and "Up to date" or an amber clock + "N months
behind"; when behind, a third line names the open months ("Not reconciled:
Jul missing, Aug in progress"). Behind counts every month since go-live up to
last month without a reconciled statement.

**AgeingPanel.** Outstanding and Overdue as links, 7 single-hue bars (the
money role colour; a negative bucket draws no bar and prints its minus sign),
a Table toggle, the top 5 parties as links, and the caveat (payments on
account netted).

## 9. Desk integration (how the theme reaches ERPNext)

Two independent pieces, both presentation only.

**A. The two dashboards (FPS OPS on FPS Home, FPS ACC on Workspace FPS ACC).**

1. The **FPS Overview** Custom HTML Block is a short loader
   (`docs/design_handoff_fps_workspace/custom_blocks/fps_overview.js`, compiled
   into `fps_erpnext/fixtures/custom_html_block.json` by `build_workspaces.py`).
   It `import()`s `/assets/fps_erpnext/dashboard/fps-command-center.js?v=<hash>`
   and calls `mount(root_element, { mountPoint })` (variant "ops"). If the
   bundle cannot load, the loader renders the old Overview strip — without its
   Invoices tile — so the page never loses content. The **FPS ACC Overview**
   block (`fps_acc_overview.js`) imports the same bundle with variant "acc";
   its fallback is a one-line "could not load" message, never a money strip.
2. `mount()` inserts a `<fps-command-center>` element with its **own** shadow
   root. Frappe links its Bootstrap desk CSS into every block's shadow root
   (unlayered, with `!important` utilities that would beat Tailwind); the nested
   root keeps that CSS — and Tailwind's preflight — on the right side of the
   wall. `disconnectedCallback` is the teardown Frappe never gives blocks.
3. The drawer and tooltips render into one `<fps-cc-portal>` host on
   `document.body` (fixed, 0×0, `z-index: 1030`): EditorJS makes every block a
   `z-index: 1` stacking context, so anything portaled inside the block would sit
   under the page head, navbar and sidebar. The drawer closes when the route
   leaves the FPS workspace.
4. Tailwind v4's `@property` registrations do not work inside shadow roots; a
   build-time PostCSS step turns them into plain defaults inside
   `@layer properties` instead of registering anything on the desk document.
5. Data comes only from GET, read-only, permission-aware methods: OPS from
   `fps_erpnext.api.command_center.get_dashboard` / `get_metric_detail` (no
   money for anyone since 14 Oct 2026) plus the existing
   `pipeline.get_overview` for the stage strip; ACC from
   `fps_erpnext.api.acc_dashboard.get_dashboard` / `get_metric_detail`, which
   call `frappe.only_for("Accounts Manager")` before reading anything (a
   refused viewer sees "You do not have access to the FPS ACC Dashboard.").
6. **Reaching the ACC page.** On Frappe 16.51 the left sidebar is the
   site-owned "Sidebar" record "FPS"; the "Workspace Sidebar" file
   `build_workspaces.py` writes is an archive the desk never reads, so its
   "FPS ACC Dashboard" row does not show. Until the row is added on the site
   (desk sidebar editor, with Agam's OK) the OPS header's "Open the FPS ACC
   Dashboard" link — rendered only for Accounts Manager — is the way in.

**B. The FPS theme — every page under the FPS tile, in two palettes.**

Each user picks a palette for themselves with Frappe's own **Toggle Theme**
dialog (avatar menu, Ctrl+Shift+G, or the sun/moon button in either
dashboard's header): **Light → Pearl** (the base, §1–§5), **Dark → Matte Black**
(neutral near-black `#131416`, matte cards `#1B1C1E` at 90 %, no saturation,
glows at 3–4 %, ink `#E8E8E6`; chart slots `#3C8DEA / #9B63B1 / #1AA598 /
#C8800D`, validated on the card `#1A1B1D`, 382 contrast pairs ≥ minimum),
**Automatic** → follows the computer. Frappe saves the choice on the user's own
profile; nothing in this theme writes.

1. `public/js/fps_theme.js` (via `app_include_js`) only toggles
   `html[data-fps-theme]` — value `pearl` or `black`, read from Frappe's
   resolved `html[data-theme]` and followed live. It is on while the active
   sidebar is the FPS sidebar ("FPS", or a per-user "FPS-<email>" copy) or the
   route is one of the FPS workspaces / Payment Receipts. The sidebar — not the
   URL — is what "under the FPS tile" means in v16: Sales Invoice opened from
   the FPS tile is themed, the same list opened from Accounting is stock
   ERPNext (in the user's own Frappe Light/Dark).
2. `public/css/fps_theme.css` (via `app_include_css`) is scoped entirely under
   that attribute. The 205 rules both palettes share are written once
   (`html[data-fps-theme]`, Pearl values); 5 light-card lifts are Pearl-only;
   a Matte Black section at the end re-states the 24 rules whose values differ
   (`html[data-fps-theme="black"]`, same specificity, later = wins). It re-points Frappe's own CSS variables to these tokens (they
   also inherit into the Job Tracker and Customs Tracker blocks), keeps every
   sticky or layered surface opaque, and uses real `backdrop-filter` glass only
   on workspace widgets — never on forms, grids, list/report views or anything
   that hosts a dropdown.
3. Printing is untouched: print previews restore the stock tokens, and print
   iframes / PDFs never load desk CSS at all.
4. Colours stored in records (number-card and chart colours) are never changed;
   the theme only lifts known low-contrast values on screen.
5. Both files are versioned with `?v=N` in `hooks.py`
   (`fps_theme.css?v=1`, `fps_theme.js?v=1`). Bump it on every change —
   `/assets` is cached for a year.
6. The attribute name is palette-neutral on purpose; its value names the
   palette. In the dashboard, `src/lib/palette.ts` stamps `data-palette` on the
   app and portal roots from the same attribute, and `src/styles/theme.css`
   carries Pearl on `:host, .fps-cc` and Matte Black on
   `.fps-cc[data-palette="black"]`. The first palette, "Midnight" (plane
   `#0B0F19`, neon accents, files `fps_midnight.css/js`), is preserved in git
   history (commit `896a324`).

## 10. Guardrails for future changes (read before prompting)

- Don't add a write path. The dashboard calls only read-only whitelisted
  methods; quick actions only *navigate* (open a filtered list, a report, or a
  blank "new" form that the user saves themselves).
- Don't hard-code a colour in a component. Use a token; add a token here first.
- Don't change a token in one sheet only: `theme.css` and `fps_theme.css`
  carry the same `--fps-*` values. Change both in one commit, re-validate the
  chart slots on the new card colour, and bump `?v=`.
- Don't add a 5th chart series colour, a second y-axis, or a pie/donut.
- Don't put money on the FPS OPS Dashboard — not for finance roles either.
  Money lives on the FPS ACC Dashboard, whose API refuses anyone without
  Accounts Manager before it reads; the UI renders whatever subset it receives
  without gaps.
- Don't rely on the bundle filename being stable — `/assets` is served with a
  one-year immutable cache, so every build gets a new `?v=` hash in the block
  loader (`scripts/sync-block.mjs` does this).
- Each layout component has a `*.meta.ts` file listing its permitted props,
  variants and layout limits. Change the meta file and the component together.

## 11. FPS Live Feed page (`/fps-feed`, phone)

A www page outside the desk (`fps_erpnext/www/fps-feed.html`,
`public/feed/fps-feed.css`): the same Pearl / Matte Black tokens under short
names (`--bg`, `--surface-1`, …; a test keeps them equal to `theme.css`),
chosen by `prefers-color-scheme`. Tokens that exist on this page only:

| Token | Pearl | Matte Black | Use |
|---|---|---|---|
| `--tint-critical / -warning / -positive / -info / -violet` | state colour at 9–10 % | at 13–14 % | icon wells, callouts, tags |
| `--new-bg`, `--new-fg` | `#1D6FD8` / `#FFFFFF` | `#3C8DEA` / `#0E1012` | the "NEW" badge and tab counts |
| `--new-glow` | Electric Blue at 10 % | at 12 % | a NEW card's wash from the top-left (a glow, never a border) |
| `--on-electric` | `#FFFFFF` | `#0E1012` | text on the Electric Blue button |
| `--logo-tile` | transparent | `#FFFFFF` | behind the header mark (its deep blue is dim on Matte Black) |
| `--live`, `--live-ring` | Mint, Mint at 35 % | the same | the LIVE dot and its pulse |
| `--header-bg` | the plane at 78 % | at 80 % | the sticky header's glass |

Deliberate differences from §2–§7, for a scrolling phone list:

- **Cards are not blurred.** Header, sheet, hint and toast use the 12 px glass
  blur; the 40-odd feed cards do not — on a flat plane the blur is invisible
  and costs a compositing layer per card while scrolling on an iPhone (the
  same reason §9 keeps blur off list views).
- **Touch targets are 44 px** (iOS): the 32 px LIVE pill and section tabs keep
  their look and extend their hit area with `::after`; icon buttons are 44 px.
- **Count-up on the chips' first paint** — SPEC §1 asks for it, §7 forbids it
  on the dashboards. Off under `prefers-reduced-motion`; the last frame is
  always the server's figure. The lead decides whether it stays.
