"""The FPS Live Feed (/fps-feed): slots, items, chips, NEW marks. Pure Python.

No frappe import. Like command_center_logic and acc_dashboard_logic (which it
builds on and never changes), everything here takes plain values or dict-like
rows and returns plain dicts, lists, strings and numbers, so the whole feed can
be built and checked with a bare `python` and no bench:

    fps_erpnext/tests/test_feed_logic.py       the rules, unit-tested

fps_erpnext.api.feed does the allow-list gate, the reads (the two dashboards'
own readers, plus three small reads of recent documents) and the storage; it
hands the rows and the two dashboard payloads to build_snapshot here. The
snapshot contract is docs/live_feed/snapshot.schema.md -- change both together.

READ-ONLY BY CONSTRUCTION. Nothing in this module can reach the database.

WHAT IT REUSES. Every number and sentence that also appears on a dashboard
comes from that dashboard's payload or its pure helpers, so the feed can never
disagree with the FPS OPS / FPS ACC dashboards: the insights (with their
severity, title and detail), the pipeline tiles, the KPIs and their deltas, the
balance cards (receivables, payables, cash, VAT), the bank statement statuses,
the per-party net overdue (acc_dashboard_logic.overdue_net) and the money
formatting ("AED 615K" compact on an item, "AED 615,028.22" in its sheet).

THE CHOICES THAT ARE NOT OBVIOUS

* Slots. The scheduler builds at 08:00, 12:00, 16:00 and 20:00 (Asia/Dubai,
  the System Settings time zone -- Frappe evaluates cron in it). A snapshot
  belongs to the latest slot at or before its build time, so a build that ran
  a few minutes late still reads "Updated 12:00"; before 08:00 that is the
  previous evening's 20:00. The next slot is the first one strictly after the
  moment asked about; after 20:00 it is "08:00 tomorrow", but after midnight
  it is plain "08:00" (it is today then). feed_meta() recomputes these at
  render time, so a 20:00 snapshot viewed at 00:10 does not say "tomorrow".
* NEW. An item is NEW when the previous slot's snapshot did not have its key,
  or had it with another fingerprint (a hash of what the viewer sees: kind,
  severity, title, subtitle, amount). A rebuild inside the same slot keeps
  comparing with the slot before (next_previous), and the very first snapshot
  marks nothing NEW -- otherwise everything would glow.
* "Since the previous update" (jobs opened, invoices submitted, receipts) is
  the window from the previous slot's build time, but never less than the last
  24 hours and never more than 7 days (recent_since). Invoices and receipts
  count as submitted when their General Ledger entries were created -- the
  documents' own `modified` moves whenever a payment is allocated (all eight
  PMES invoices on 14 Oct 2026 at 16:30), and a draft created days ago is
  submitted today, so neither `creation` nor `modified` is the moment.
  Customs clearances and deliveries only carry a date, so they count from the
  window's first DATE (today and yesterday, at least).
* Order. Critical first, then warnings, then what happened (newest first),
  then the standing lists (most overdue customers and suppliers), then the
  quiet notes. A section keeps at most SECTION_CAP items: the oldest events go
  first, never an alert; what was cut is counted in the section's "more".
* The feed carries money in its Accounts section for both viewers (Agam,
  14 Oct 2026: both agam@ and hello@ see Operations AND Accounts on this page;
  a deliberate exception that applies to the feed only). The Operations
  section is built from the money-free OPS payload and adds no amounts.
* "Open in ERPNext" is decided per viewer at render time (apply_can_open),
  never stored: the snapshot is built once with Administrator rights and read
  by people with very different permissions.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import unquote

from fps_erpnext.api import acc_dashboard_logic as acc
from fps_erpnext.api import command_center_logic as cc
from fps_erpnext.api.customs_clock import to_date

VERSION = 1
PERIOD = "7d"
TIME_ZONE = "Asia/Dubai"   # informational; the clock is the site's (System Settings)

# --------------------------------------------------------------------------
# Slots
# --------------------------------------------------------------------------

SLOT_HOURS = (8, 12, 16, 20)
CRON = "0 8,12,16,20 * * *"           # hooks.py; asserted equal in the tests
# A build up to this long after a slot still reads as the slot ("Updated 12:00").
SLOT_GRACE_MINUTES = 20
# The page says the update is late once the current slot is this old and the
# stored snapshot is from before it (a failed or stuck scheduler run).
LATE_GRACE_MINUTES = 30

RECENT_HOURS = 24
RECENT_MAX_DAYS = 7


def to_datetime(value):
	"""datetime | None from a datetime, a date (midnight) or a 'YYYY-MM-DD[ HH:MM[:SS[.f]]]' string."""
	if not value:
		return None
	if isinstance(value, datetime):
		return value.replace(tzinfo=None)
	if isinstance(value, date):
		return datetime.combine(value, time())
	text = str(value).strip().replace("T", " ")
	for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
		try:
			return datetime.strptime(text[:size], fmt)
		except ValueError:
			continue
	return None


def stamp(value):
	"""'YYYY-MM-DD HH:MM:SS' for a datetime-like value (microseconds dropped)."""
	dt = to_datetime(value)
	return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def hhmm(dt):
	return "%02d:%02d" % (dt.hour, dt.minute)


def slot_start(value):
	"""The latest slot at or before `value` (the previous evening's 20:00 before 08:00)."""
	dt = to_datetime(value)
	for hour in reversed(SLOT_HOURS):
		if dt.time() >= time(hour):
			return datetime.combine(dt.date(), time(hour))
	return datetime.combine(dt.date() - timedelta(days=1), time(SLOT_HOURS[-1]))


def next_slot_start(value):
	"""The first slot strictly after `value`."""
	dt = to_datetime(value)
	for hour in SLOT_HOURS:
		candidate = datetime.combine(dt.date(), time(hour))
		if candidate > dt:
			return candidate
	return datetime.combine(dt.date() + timedelta(days=1), time(SLOT_HOURS[0]))


def slot_label(value):
	"""'12:00' -- the slot a snapshot built at `value` belongs to."""
	return hhmm(slot_start(value))


def slot_id(value):
	"""'2026-10-14 12:00' -- the slot with its date (00:10 belongs to yesterday's 20:00)."""
	return slot_start(value).strftime("%Y-%m-%d %H:%M")


def next_slot_label(value):
	"""'16:00', or '08:00 tomorrow' when the next slot is on the next calendar day."""
	dt = to_datetime(value)
	nxt = next_slot_start(dt)
	return hhmm(nxt) + (" tomorrow" if nxt.date() > dt.date() else "")


def _day_suffix(shown, now):
	days = (now.date() - shown.date()).days
	if days == 0:
		return ""
	if days == 1:
		return " yesterday"
	return " on %s" % cc.short_date(shown)


def updated_label(generated_at, now):
	"""'12:00', '20:00 yesterday', '14:37' (an off-slot build), '16:00 on 12 Oct'."""
	gen = to_datetime(generated_at)
	now = to_datetime(now)
	start = slot_start(gen)
	shown = start if gen - start <= timedelta(minutes=SLOT_GRACE_MINUTES) else gen
	return hhmm(shown) + _day_suffix(shown, now)


def is_late(generated_at, now):
	"""True when the current slot has passed (by LATE_GRACE_MINUTES) and the
	stored snapshot is from before it."""
	gen, now = to_datetime(generated_at), to_datetime(now)
	if not gen:
		return False
	expected = slot_start(now)
	return gen < expected and now - expected > timedelta(minutes=LATE_GRACE_MINUTES)


def feed_meta(generated_at, now):
	"""What the page header says, computed at render time (see the module doc)."""
	now = to_datetime(now)
	gen = to_datetime(generated_at)
	meta = {
		"now": stamp(now),
		"generated_at": stamp(gen) if gen else None,
		"slot": slot_label(gen) if gen else None,
		"slot_id": slot_id(gen) if gen else None,
		"updated_label": updated_label(gen, now) if gen else None,
		"next_slot": next_slot_label(now),
		"next_at": stamp(next_slot_start(now)),
		"late": is_late(gen, now),
		"time_zone": TIME_ZONE,
	}
	return meta


def recent_since(now, previous_generated_at=None):
	"""Start of the "since the previous update" window: the previous slot's
	build time, but at least the last RECENT_HOURS and at most RECENT_MAX_DAYS."""
	now = to_datetime(now)
	since = now - timedelta(hours=RECENT_HOURS)
	prev = to_datetime(previous_generated_at)
	if prev and prev < since:
		since = prev
	return max(since, now - timedelta(days=RECENT_MAX_DAYS))


def since_label(since, now):
	"""'since 20:00 yesterday', 'since 12:00', 'since 12 Oct'."""
	since, now = to_datetime(since), to_datetime(now)
	days = (now.date() - since.date()).days
	if days == 0:
		return "since %s" % hhmm(since)
	if days == 1:
		return "since %s yesterday" % hhmm(since)
	return "since %s" % cc.short_date(since)


# --------------------------------------------------------------------------
# Gate (FEED_USERS lives in fps_erpnext.api.feed)
# --------------------------------------------------------------------------

def gate(user, users):
	"""'allowed' | 'guest' | 'refused'. Emails compare case-insensitively."""
	user = (user or "Guest").strip()
	if user == "Guest":
		return "guest"
	allowed = {u.strip().lower() for u in users or ()}
	return "allowed" if user.lower() in allowed else "refused"


# --------------------------------------------------------------------------
# Items, records, chips
# --------------------------------------------------------------------------

SEVERITIES = ("critical", "warning", "info", "positive")
TONES = ("critical", "warning", "positive", "neutral")

TITLE_MAX = 80
SUBTITLE_MAX = 120
NOTE_MAX = 240
TAG_MAX = 24
RECORDS_CAP = 8
SECTION_CAP = 25
PARTY_TOP = 5

# Per-kind caps applied while composing (newest / largest first).
KIND_CAPS = {
	"job": 8, "update": 8, "customs": 5, "delivery": 5,
	"invoice": 8, "receipt": 8, "overdue_customer": PARTY_TOP, "supplier_due": PARTY_TOP,
}
EVENT_KINDS = frozenset({"job", "update", "customs", "delivery", "invoice", "receipt"})
PARTY_KINDS = frozenset({"overdue_customer", "supplier_due"})
KIND_NOUNS = {
	"job": ("job opened", "jobs opened"),
	"update": ("job update", "job updates"),
	"customs": ("clearance", "clearances"),
	"delivery": ("delivery", "deliveries"),
	"invoice": ("invoice submitted", "invoices submitted"),
	"receipt": ("receipt", "receipts"),
	"overdue_customer": ("overdue customer", "overdue customers"),
	"supplier_due": ("supplier past due", "suppliers past due"),
	"insight": ("alert", "alerts"),
}

ItemKeys = ("key", "kind", "severity", "tag", "title", "subtitle", "note", "amount", "amount_display",
            "at", "detail", "records", "records_more", "doctype", "name", "route", "fingerprint")
RecordKeys = ("title", "subtitle", "value", "group", "doctype", "name", "route")
ChipKeys = ("key", "label", "value", "display", "unit", "tone", "sub", "delta", "definition",
            "note", "detail", "doctype", "route", "fingerprint")


def _text(value):
	return str(value).strip() if value is not None else ""


def _num(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _ordered(d, keys):
	return {k: d[k] for k in keys if k in d and d[k] is not None}


def fingerprint(*parts):
	"""12 hex chars of SHA-1 over the JSON of `parts` -- stable across runs."""
	blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
	return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def item_fingerprint(item, basis=None):
	"""What the viewer sees on the card: a change here makes the item NEW.

	`basis` replaces subtitle + amount for an item whose subtitle moves every day
	without anything happening (an overdue party's "oldest 44 days")."""
	if basis is not None:
		return fingerprint(item.get("kind"), item.get("severity"), item.get("tag"), item.get("title"), *basis)
	return fingerprint(item.get("kind"), item.get("severity"), item.get("tag"), item.get("title"),
	                   item.get("subtitle"), item.get("amount_display"))


def chip_fingerprint(chip):
	return fingerprint(chip.get("display"), chip.get("sub"), chip.get("tone"))


def row(label, value):
	"""One sheet row; None when there is nothing to say (callers filter them out)."""
	value = _text(value)
	return {"label": label, "value": value} if value else None


def _rows(rows):
	return [r for r in rows or () if r]


def record(title, doctype, name=None, *, subtitle=None, value=None, route=None, group=None):
	"""A document behind an aggregate item. route defaults to the form of `name`.
	`group` heads a run of records in the sheet ("Past deadline", "Due soon")."""
	if route is None and name:
		route = cc.form_route(doctype, name)
	return _ordered({
		"title": cc.clip(_text(title) or cc.NO_PARTY, TITLE_MAX),
		"subtitle": nb(cc.clip(subtitle, SUBTITLE_MAX)) if _text(subtitle) else None,
		"value": _text(value) or None,
		"group": _text(group) or None,
		"doctype": doctype,
		"name": _text(name) or None,
		"route": route,
	}, RecordKeys)


# A reference's prefix stays on the same line as its number ("PO# 82467" must
# not wrap between "PO#" and "82467" on a narrow phone).
_REF_PREFIX = re.compile(r"\b(PO\s?#|PO|BOE|Ref|Inv|INV|DO|BL)\s+(?=[\w-]*\d)")


def nb(text):
	"""`text` with a no-break space after a reference prefix (PO#, PO, BOE, Ref …)."""
	text = _text(text)
	return _REF_PREFIX.sub(lambda m: m.group(1) + " ", text) if text else text


def make_item(key, kind, severity, title, *, tag=None, subtitle=None, note=None, amount=None, at=None,
              detail=(), records=(), doctype=None, name=None, route=None, fingerprint_basis=None):
	"""One feed card. `title` is what the card is about (a party, an alert
	sentence, a status line); `tag` is the short kind label shown beside the
	time ("Invoice", "Received", "3 new jobs") -- never glued onto the title,
	so a long party name keeps the whole first lines on a narrow phone."""
	if severity not in SEVERITIES:
		raise ValueError("severity must be one of %s" % ", ".join(SEVERITIES))
	if route is None and doctype and name:
		route = cc.form_route(doctype, name)
	records = list(records or ())
	item = {
		"key": key,
		"kind": kind,
		"severity": severity,
		"tag": cc.clip(tag, TAG_MAX) if _text(tag) else None,
		"title": cc.clip(_text(title) or cc.NO_PARTY, TITLE_MAX),
		"subtitle": nb(cc.clip(subtitle, SUBTITLE_MAX)) if _text(subtitle) else None,
		"note": cc.clip(note, NOTE_MAX) if _text(note) else None,
		"amount": cc.money(amount) if amount is not None else None,
		"amount_display": cc.format_money_compact(amount) if amount is not None else None,
		"at": _at(at),
		"detail": _rows(detail),
		"records": records[:RECORDS_CAP] or None,
		"records_more": max(len(records) - RECORDS_CAP, 0) or None,
		"doctype": doctype,
		"name": _text(name) or None,
		"route": route,
	}
	item["fingerprint"] = item_fingerprint(item, fingerprint_basis)
	return _ordered(item, ItemKeys)


def _at(value):
	"""A datetime (or datetime string) -> 'YYYY-MM-DD HH:MM:SS'; a date -> 'YYYY-MM-DD'."""
	if not value:
		return None
	if isinstance(value, datetime):
		return stamp(value)
	if isinstance(value, date):
		return value.isoformat()
	text = _text(value)
	return stamp(text) if len(text) > 10 else (to_date(text).isoformat() if to_date(text) else None)


def make_chip(key, label, value, display, *, unit="count", tone="neutral", sub=None, delta=None,
              definition=None, note=None, detail=(), doctype=None, route=None):
	if tone not in TONES:
		raise ValueError("tone must be one of %s" % ", ".join(TONES))
	chip = {
		"key": key, "label": label, "value": value, "display": display, "unit": unit,
		"tone": tone, "sub": _text(sub) or None, "delta": delta,
		"definition": _text(definition) or None, "note": _text(note) or None,
		"detail": _rows(detail), "doctype": doctype, "route": route,
	}
	chip["fingerprint"] = chip_fingerprint(chip)
	return _ordered(chip, ChipKeys)


def money_full(value):
	return cc.format_money(value)


def money_compact(value):
	return cc.format_money_compact(value)


def when(value):
	"""'14 Oct, 15:11' for a datetime, '14 Oct' for a date."""
	dt = to_datetime(value)
	if not dt:
		return ""
	if isinstance(value, datetime) or len(_text(value)) > 10:
		return "%s, %s" % (cc.short_date(dt), hhmm(dt))
	return cc.short_date(dt)


def days_from(d, as_of):
	"""'today', 'in 6 days', '67 days ago'."""
	d, as_of = to_date(d), to_date(as_of)
	n = (d - as_of).days
	if n == 0:
		return "today"
	if n > 0:
		return "in %d %s" % (n, cc.plural(n, "day", "days"))
	return "%d %s ago" % (-n, cc.plural(-n, "day", "days"))


def pct_text(pct):
	if pct is None:
		return None
	sign = "+" if pct > 0 else ("−" if pct < 0 else "")
	return "%s%s%%" % (sign, cc._strip_zeros("%.1f" % abs(pct)))


def kpi_delta(kpi, *, caveat=False):
	"""Delta block for a chip built on a dashboard KPI, or None when not comparable."""
	prev = kpi.get("previous")
	if prev is None:
		return None
	pct = kpi.get("delta_pct")
	value = kpi.get("value") or 0
	money = kpi.get("unit") == "currency"
	fmt = money_compact if money else cc.format_count
	if pct is None:
		text = "new" if value and not prev else "—"
		tone = "neutral"
	else:
		text = pct_text(pct)
		good = kpi.get("good_direction")
		if caveat or good not in ("up", "down") or pct == 0:
			tone = "neutral"
		else:
			tone = "positive" if (pct > 0) == (good == "up") else "warning"
	return {"pct": pct, "text": text, "previous": prev, "previous_display": fmt(prev),
	        "label": cc.PERIODS[PERIOD]["compare"], "tone": tone}


# --------------------------------------------------------------------------
# Ordering and caps
# --------------------------------------------------------------------------

_EPOCH = datetime(2000, 1, 1)


def _seconds(item):
	dt = to_datetime(item.get("at"))
	return (dt - _EPOCH).total_seconds() if dt else 0.0


def _group(item):
	if item["severity"] == "critical":
		return 0
	if item["kind"] in EVENT_KINDS:
		return 2
	if item["severity"] == "warning" and item["kind"] not in PARTY_KINDS:
		return 1
	if item["kind"] in PARTY_KINDS:
		return 3
	return 4


def order_items(items):
	"""Critical, warnings, events newest first, the party lists, the quiet notes.
	Inside a group (other than events) the composition order is kept."""
	indexed = list(enumerate(items))
	indexed.sort(key=lambda t: (_group(t[1]),
	                            -_seconds(t[1]) if _group(t[1]) == 2 else 0.0,
	                            t[0]))
	return [item for _i, item in indexed]


def cap_items(items, cap=SECTION_CAP):
	"""(kept, dropped) -- at most `cap` items, the oldest events dropped first,
	then (only when alerts alone exceed the cap) from the end."""
	items = order_items(items)
	if len(items) <= cap:
		return items, []
	events = [i for i in items if i["kind"] in EVENT_KINDS]   # newest first already
	others = [i for i in items if i["kind"] not in EVENT_KINDS]
	keep_events = max(cap - len(others), 0)
	dropped_keys = {i["key"] for i in events[keep_events:]}
	kept = [i for i in items if i["key"] not in dropped_keys]
	dropped = [i for i in items if i["key"] in dropped_keys]
	if len(kept) > cap:
		dropped = kept[cap:] + dropped
		kept = kept[:cap]
	return kept, dropped


def more_lines(counts):
	"""[{kind, count, label}] for what composition caps and the section cap cut."""
	out = []
	for kind, n in counts.items():
		if n > 0:
			one, many = KIND_NOUNS.get(kind, ("item", "items"))
			out.append({"kind": kind, "count": n, "label": "%d more %s" % (n, cc.plural(n, one, many))})
	return out


def _take(rows, kind, more):
	"""rows[:KIND_CAPS[kind]], counting the rest into `more`."""
	cap = KIND_CAPS[kind]
	if len(rows) > cap:
		more[kind] = more.get(kind, 0) + len(rows) - cap
	return rows[:cap]


# --------------------------------------------------------------------------
# Operations section
# --------------------------------------------------------------------------

UPDATE_POSITIVE = frozenset({"DELIVERED", "CLEARED", "FZ_CLEARED", "OMAN_CLEARED", "COMPLETED",
                             "INVOICED", "CLOSED"})
UPDATE_WARNING = frozenset({"HOLD"})

OPS_DEFINITION = ("Operations from the FPS OPS Dashboard: its alerts (last 7 days), the jobs "
                  "opened, job updates, customs clearances and deliveries since the previous "
                  "update. No money.")
ACC_DEFINITION = ("Accounts from the FPS ACC Dashboard: its alerts, the invoices submitted and "
                  "receipts booked since the previous update, the most overdue customers and "
                  "suppliers, and the bank statements.")


def _by_key(rows, key="key"):
	return {r.get(key): r for r in rows or []}


def _sow(category):
	key = _text(category)
	return cc.SOW_SHORT.get(key, key)


def _docstatus_label(row):
	return {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(int(_num(row.get("docstatus"))), "")


def _customer(row):
	return row.get("customer_name") or row.get("customer")


def _open_jobs_past_eta(job_rows, as_of):
	as_of = to_date(as_of)
	return sorted((r for r in cc.open_jobs(job_rows)
	               if to_date(r.get("eta")) and to_date(r.get("eta")) < as_of),
	              key=lambda r: (to_date(r.get("eta")), _text(r.get("name"))))


def ops_chips(payload, raw, as_of):
	"""Open jobs, in progress, customs not cleared, delivered awaiting invoice,
	jobs past ETA, new enquiries (7 days). A chip whose source was not readable
	is left out, never shown as zero."""
	tiles = _by_key((payload.get("stages") or {}).get("tiles"))
	chips = []
	tile_chips = (
		("open_jobs", "Open jobs", "job_order", "Job Order",
		 "Job Orders not Closed, Completed or Invoiced, cancelled ones left out."),
		("in_progress", "In progress", "in_progress", "Job Order",
		 "Job Orders at stage In Progress."),
		("customs_open", "Customs not cleared", "customs", "Customs Tracker",
		 "Customs Trackers whose status is not Cleared."),
		("awaiting_invoice", "Awaiting invoice", "delivered", "Job Order",
		 "Job Orders at stage Delivered: the work is done, the invoice is not."),
	)
	for key, label, tile_key, doctype, definition in tile_chips:
		tile = tiles.get(tile_key)
		if not tile or tile.get("count") is None:
			continue
		n = int(tile["count"])
		chips.append(make_chip(
			key, label, n, cc.format_count(n),
			tone="warning" if key == "awaiting_invoice" and n else "neutral",
			definition=definition,
			detail=[row(label, cc.format_count(n))] + [row("Pipeline", note) for note in
			                                            (payload.get("stages") or {}).get("footnotes") or []
			                                            if key == "open_jobs"],
			doctype=doctype, route=tile.get("route")))

	jobs = raw.get("Job Order")
	if jobs is not None:
		late = _open_jobs_past_eta(jobs, as_of)
		no_eta = sum(1 for r in cc.open_jobs(jobs) if not to_date(r.get("eta")))
		detail = [row("Open jobs past ETA", cc.format_count(len(late)))]
		if late:
			detail.append(row("Oldest", "%s · ETA %s" % (_text(late[0].get("name")),
			                                             cc.short_date(late[0].get("eta")))))
		detail.append(row("Open jobs with no ETA", cc.format_count(no_eta)))
		chips.append(make_chip(
			"past_eta", "Past ETA", len(late), cc.format_count(len(late)),
			tone="warning" if late else "neutral",
			definition="Open jobs whose ETA has passed. Move the job on or update its ETA.",
			detail=detail, doctype="Job Order",
			route=cc.list_route("Job Order", {
				"fps_stage": ["not in", list(cc.CLOSED_JOB_STAGES)],
				"eta": ["between", ["2000-01-01", (to_date(as_of) - timedelta(days=1)).isoformat()]],
				"docstatus": ["<", 2]})))

	kpi = _by_key(payload.get("kpis")).get("enquiries")
	if kpi:
		delta = kpi_delta(kpi)
		chips.append(make_chip(
			"enquiries_7d", "New enquiries", kpi["value"], cc.format_count(kpi["value"]),
			tone=(delta or {}).get("tone", "neutral"), sub=cc.PERIODS[PERIOD]["label"],
			delta=delta, definition=kpi.get("definition"),
			detail=[row(cc.PERIODS[PERIOD]["label"], cc.format_count(kpi["value"]))]
			+ ([row("Previous 7 days", cc.format_count(kpi["previous"]))] if kpi.get("previous") is not None else [])
			+ [row(line["label"], line["value"]) for line in kpi.get("context") or []],
			doctype="FPS Enquiry", route=kpi.get("route")))
	return chips


def _customs_records(trackers, field, as_of):
	"""The trackers behind a customs insight, the ones past the deadline first,
	each run headed in the sheet ("Past deadline", "Due soon") so a tracker that
	is not due yet never reads as overdue under the alert's title."""
	by_name = {_text(r.get("name")): r for r in trackers or []}
	overdue, upcoming = cc.customs_deadlines(trackers, field, as_of)
	what = "Docs" if field == "fps_doc_submission" else "MOFA"
	out = []
	for group, rows_ in (("Past deadline", overdue), ("Due soon", upcoming)):
		for deadline, name in rows_:
			r = by_name.get(name) or {}
			out.append(record(r.get("customer"), "Customs Tracker", name, group=group,
			                  subtitle="%s · %s due %s, %s" % (name, what, cc.short_date(deadline),
			                                                    days_from(deadline, as_of))))
	return out, len(overdue), len(upcoming)


def ops_insight_item(ins, payload, raw, as_of):
	"""An OPS insight as a feed item, with the records behind it."""
	iid = ins["id"]
	doctype, route, records, detail = None, ins.get("route"), [], []
	kpis = _by_key(payload.get("kpis"))
	if iid in ("customs_docs", "customs_mofa"):
		field = "fps_doc_submission" if iid == "customs_docs" else "fps_mofa_status"
		records, n_over, n_soon = _customs_records(raw.get("Customs Tracker"), field, as_of)
		doctype = "Customs Tracker"
		detail = [row("Past the deadline", cc.format_count(n_over)),
		          row("Due in the next %d days" % cc.CUSTOMS_HORIZON_DAYS, cc.format_count(n_soon))]
	elif iid == "jobs_past_eta":
		doctype = "Job Order"
		late = _open_jobs_past_eta(raw.get("Job Order"), as_of)
		records = [record(_customer(r), "Job Order", r.get("name"),
		                  subtitle="%s · ETA %s · %s" % (_text(r.get("name")), cc.short_date(r.get("eta")),
		                                                  _text(r.get("fps_stage")) or "No stage"))
		           for r in late]
		detail = [row("Open jobs past ETA", cc.format_count(len(late)))]
	elif iid == "delivered_not_invoiced":
		doctype = "Job Order"
		jobs = sorted((r for r in raw.get("Job Order") or []
		               if int(_num(r.get("docstatus"))) < 2 and _text(r.get("fps_stage")) == "Delivered"),
		              key=lambda r: (to_date(r.get("jo_date")) or date.max, _text(r.get("name"))))
		records = [record(_customer(r), "Job Order", r.get("name"),
		                  subtitle="%s · opened %s" % (_text(r.get("name")), cc.short_date(r.get("jo_date")))
		                  if to_date(r.get("jo_date")) else _text(r.get("name")))
		           for r in jobs]
		detail = [row("Delivered, not invoiced", cc.format_count(len(jobs)))]
	elif iid == "quotation_drafts":
		doctype = "Quotation"
		drafts = sorted(cc.quotation_drafts(raw.get("Quotation"), as_of),
		                key=lambda r: (to_date(r.get("transaction_date")), _text(r.get("name"))))
		records = [record(r.get("customer_name") or r.get("party_name"), "Quotation", r.get("name"),
		                  subtitle="%s · dated %s" % (_text(r.get("name")),
		                                              cc.short_date(r.get("transaction_date"))))
		           for r in drafts]
		detail = [row("Drafts, last %d days" % cc.QUOTE_DRAFT_DAYS, cc.format_count(len(drafts)))]
	elif iid.startswith("swing:") or ins.get("metric_key"):
		key = ins.get("metric_key") or iid.split(":", 1)[1]
		spec = cc.METRICS.get(key) or {}
		doctype = spec.get("doctype")
		route = route or spec.get("route")
		kpi = kpis.get(key)
		if kpi:
			detail = [row(cc.PERIODS[PERIOD]["label"], cc.format_count(kpi["value"])),
			          row("Previous 7 days", cc.format_count(kpi["previous"]) if kpi.get("previous") is not None else ""),
			          row("Change", pct_text(kpi.get("delta_pct")))]
		if iid == "enquiry_silence":
			last = max((to_date(r.get("enquiry_date")) for r in raw.get("FPS Enquiry") or []
			            if to_date(r.get("enquiry_date")) and _text(r.get("status")) != "Cancelled"
			            and to_date(r.get("enquiry_date")) <= to_date(as_of)), default=None)
			detail = [row("Last enquiry", cc.short_date(last) if last else "None in the window")]
	return make_item("ins:ops:%s" % iid, "insight", ins["severity"], ins["title"], note=ins.get("detail"),
	                 detail=detail, records=records, doctype=doctype, route=route)


def _job_item(r, logged=()):
	"""A job opened in the window. `logged`: the status lines the System wrote
	while opening it (folded in here instead of showing as separate updates)."""
	name = _text(r.get("name"))
	sow = _sow(r.get("fps_category"))
	return make_item(
		"jo:%s" % name, "job", "info", _text(_customer(r)) or cc.NO_PARTY, tag="New job",
		subtitle=cc._join(name, sow, nb(r.get("client_reference_no"))),
		at=r.get("creation") or r.get("jo_date"),
		detail=[row("Job Order", name), row("Customer", _customer(r)), row("Service line", sow),
		        row("Stage", r.get("fps_stage")), row("Client reference", nb(r.get("client_reference_no"))),
		        row("Job date", cc.short_date(r.get("jo_date")) if to_date(r.get("jo_date")) else ""),
		        row("ETA", cc.short_date(r.get("eta")) if to_date(r.get("eta")) else ""),
		        row("Opened", when(r.get("creation"))), row("Status", _docstatus_label(r)),
		        row("Also logged", "; ".join(dict.fromkeys(_text(x) for x in logged if _text(x))))],
		doctype="Job Order", name=name)


def _names_short(names):
	"""'FPS/JO/2610/096 to 102' (consecutive), 'FPS/JO/2610/096, 099' (two),
	'FPS/JO/2610/096, 099 +3' -- job numbers that share a prefix, oldest first."""
	names = sorted(_text(n) for n in names if _text(n))
	if not names:
		return ""
	prefix = names[0].rsplit("/", 1)[0] + "/" if "/" in names[0] else ""
	if not prefix or not all(n.startswith(prefix) for n in names):
		return names[0] if len(names) == 1 else "%s +%d" % (names[0], len(names) - 1)
	tails = [n[len(prefix):] for n in names]
	if len(tails) > 2 and all(t.isdigit() for t in tails) and \
			[int(t) for t in tails] == list(range(int(tails[0]), int(tails[0]) + len(tails))):
		return "%s%s to %s" % (prefix, tails[0], tails[-1])
	shown = ", ".join(tails[:2])
	return prefix + shown + (" +%d" % (len(tails) - 2) if len(tails) > 2 else "")


def _job_group_item(rows):
	"""Several jobs opened in the window for ONE customer: one card ("PREMIER
	MARINE … · 7 new jobs"), the jobs as its records, newest first."""
	rows = _creation_desc(rows)
	party = _text(_customer(rows[0])) or cc.NO_PARTY
	n = len(rows)
	sows = list(dict.fromkeys(_sow(r.get("fps_category")) for r in rows if _text(r.get("fps_category"))))
	created = [to_datetime(r.get("creation")) for r in rows if to_datetime(r.get("creation"))]
	customer_id = _text(rows[0].get("customer"))
	return make_item(
		"jos:%s" % (customer_id or party), "job", "info", party, tag="%d new jobs" % n,
		subtitle=cc._join(_names_short(r.get("name") for r in rows),
		                  sows[0] if len(sows) == 1 else ("%d service lines" % len(sows) if sows else "")),
		at=max(created) if created else rows[0].get("jo_date"),
		detail=[row("Customer", party), row("Jobs opened", cc.format_count(n)),
		        row("Service lines", ", ".join(sows)),
		        row("First opened", when(min(created)) if created else ""),
		        row("Last opened", when(max(created)) if created else "")],
		records=[record(r.get("name"), "Job Order", r.get("name"),
		                subtitle=cc._join(_sow(r.get("fps_category")), nb(r.get("client_reference_no")),
		                                  ("opened " + when(r.get("creation"))) if r.get("creation") else ""))
		         for r in rows],
		doctype="Job Order",
		route=cc.list_route("Job Order", {"name": ["in", [_text(r.get("name")) for r in rows]]}))


def job_count(item):
	"""How many jobs an item stands for (a customer's group card counts each)."""
	if item.get("kind") == "job" and str(item.get("key", "")).startswith("jos:"):
		return len(item.get("records") or []) + int(item.get("records_more") or 0)
	return 1


# System rows written within this many seconds of a job's creation are part of
# opening it (the OPENED milestone, "Customs entry opened" from the auto-created
# Customs Tracker): on 14 Oct 2026 every new job came with both, 0.02 s apart.
OPENING_FOLD_SECONDS = 120


def _opening_rows(updates, opened):
	"""{job name: [update rows written while opening it]} for the jobs opened in
	the window."""
	created = {_text(r.get("name")): to_datetime(r.get("creation")) for r in opened}
	out = {}
	for u in updates or []:
		job = _text(u.get("parent"))
		at = created.get(job)
		if not at:
			continue
		logged = to_datetime(u.get("creation"))
		if _text(u.get("milestone")) == "OPENED" or (
		        _text(u.get("source")) == "System" and logged
		        and abs((logged - at).total_seconds()) <= OPENING_FOLD_SECONDS):
			out.setdefault(job, []).append(u)
	return out


def _update_item(u):
	milestone = _text(u.get("milestone"))
	label = cc.MILESTONE_LABELS.get(milestone, milestone)
	severity = ("positive" if milestone in UPDATE_POSITIVE
	            else "warning" if milestone in UPDATE_WARNING else "info")
	job = _text(u.get("parent"))
	title = _text(u.get("status_line")) or label or "Job update"
	return make_item(
		"upd:%s" % _text(u.get("name")), "update", severity, title,
		subtitle=cc._join(job, u.get("job_customer")),
		at=u.get("creation") or u.get("update_date"),
		detail=[row("Job Order", job), row("Customer", u.get("job_customer")), row("Milestone", label),
		        row("Update", u.get("status_line")),
		        row("Event date", cc.short_date(u.get("update_date")) if to_date(u.get("update_date")) else ""),
		        row("Logged", when(u.get("creation"))), row("Source", u.get("source")),
		        row("Job stage", u.get("job_stage"))],
		doctype="Job Order", name=job)


def _status_with_deadline(status, deadline):
	status = _text(status)
	if to_date(deadline):
		return cc._join(status or "Not set", "due " + cc.short_date(deadline))
	return status


def _logged_at(event_date, logged):
	"""The time the job's own update recorded the event, when it is on the
	event's date: "2 h ago" then reads true. Else the date alone."""
	d = to_date(event_date)
	times = sorted(t for t in (to_datetime(u.get("creation")) for u in logged or []) if t and t.date() == d)
	return times[0] if times else d


def _also_logged(logged):
	return row("Also logged", "; ".join(dict.fromkeys(_text(u.get("status_line")) for u in logged or []
	                                                  if _text(u.get("status_line")))))


def _customs_item(r, logged=()):
	name = _text(r.get("name"))
	boe = _text(r.get("boe_number"))
	return make_item(
		"ct:%s:cleared" % name, "customs", "positive", _text(r.get("customer")) or cc.NO_PARTY, tag="Cleared",
		subtitle=cc._join(name, r.get("fps_clearance_type"), nb("BOE " + boe) if boe else ""),
		at=_logged_at(r.get("clearance_date"), logged),
		detail=[_also_logged(logged), row("Customs Tracker", name), row("Job Order", r.get("job_order")),
		        row("Customer", r.get("customer")), row("Type", r.get("fps_clearance_type")),
		        row("BOE", boe),
		        row("Declared", cc.short_date(r.get("ct_date")) if to_date(r.get("ct_date")) else ""),
		        row("Cleared", cc.short_date(r.get("clearance_date"))),
		        row("Original documents", _status_with_deadline(r.get("fps_doc_submission"), r.get("fps_doc_deadline"))),
		        row("MOFA", _status_with_deadline(r.get("fps_mofa_status"), r.get("fps_mofa_deadline")))],
		doctype="Customs Tracker", name=name)


def _delivery_item(r, logged=()):
	name = _text(r.get("name"))
	return make_item(
		"pod:%s" % name, "delivery", "positive", _text(r.get("customer")) or cc.NO_PARTY, tag="Delivered",
		subtitle=cc._join(name, r.get("job_order"), nb(r.get("client_reference_no"))),
		at=_logged_at(r.get("pod_date"), logged),
		detail=[_also_logged(logged), row("Proof of Delivery", name), row("Job Order", r.get("job_order")),
		        row("Customer", r.get("customer")), row("Movement", r.get("movement_type")),
		        row("Client reference", nb(r.get("client_reference_no"))),
		        row("POD date", cc.short_date(r.get("pod_date"))), row("Status", _docstatus_label(r))],
		doctype="Proof of Delivery", name=name)


def _creation_desc(rows, field="creation"):
	return sorted(rows, key=lambda r: (stamp(r.get(field)) or "", _text(r.get("name"))), reverse=True)


def build_ops_section(payload, raw, recent_jobs, *, since, as_of):
	raw = raw or {}
	since_dt = to_datetime(since)
	more = {}
	items = [ops_insight_item(i, payload, raw, as_of) for i in payload.get("insights") or []]

	day = since_dt.date()
	opened = [r for r in recent_jobs or []
	          if int(_num(r.get("docstatus"))) < 2 and (to_datetime(r.get("creation")) or _EPOCH) >= since_dt]
	cleared = [r for r in raw.get("Customs Tracker") or []
	           if to_date(r.get("clearance_date")) and day <= to_date(r.get("clearance_date")) <= to_date(as_of)]
	cleared.sort(key=lambda r: (to_date(r.get("clearance_date")), _text(r.get("name"))), reverse=True)
	delivered = [r for r in raw.get("Proof of Delivery") or []
	             if int(_num(r.get("docstatus"))) in (0, 1) and _text(r.get("delivery_status")) == "Delivered"
	             and to_date(r.get("pod_date")) and day <= to_date(r.get("pod_date")) <= to_date(as_of)]
	delivered.sort(key=lambda r: (to_date(r.get("pod_date")), _text(r.get("name"))), reverse=True)

	# The job's own update rows that say the same thing as an event item are
	# folded into it ("Also logged"), not repeated as separate updates.
	all_updates = [u for u in raw.get("FPS Job Update") or [] if _text(u.get("source")) != "Backfill"]
	by_job = {}
	for u in all_updates:
		by_job.setdefault(_text(u.get("parent")), []).append(u)
	opening = _opening_rows(all_updates, opened)
	clearing = {_text(r.get("name")): [u for u in by_job.get(_text(r.get("job_order")), [])
	                                   if _text(u.get("milestone")) in CLEARED_MILESTONES
	                                   and to_date(u.get("update_date")) == to_date(r.get("clearance_date"))]
	            for r in cleared}
	delivering = {_text(r.get("name")): [u for u in by_job.get(_text(r.get("job_order")), [])
	                                     if _text(u.get("milestone")) == "DELIVERED"
	                                     and to_date(u.get("update_date")) == to_date(r.get("pod_date"))]
	              for r in delivered}
	folded = {_text(u.get("name")) for group in (opening, clearing, delivering)
	          for rows_ in group.values() for u in rows_}

	# One card per customer: a customer who opened several jobs in the window
	# gets one "N new jobs" card with the jobs as its records (on 14 Oct 2026
	# seven of eight new jobs were PREMIER MARINE's -- seven identical cards).
	by_customer = {}
	for r in _creation_desc(opened):
		by_customer.setdefault(_text(r.get("customer")) or _text(_customer(r)), []).append(r)
	job_items = [_job_item(rows_[0], [u.get("status_line") for u in opening.get(_text(rows_[0].get("name")), [])])
	             if len(rows_) == 1 else _job_group_item(rows_)
	             for rows_ in by_customer.values()]
	cap = KIND_CAPS["job"]
	if len(job_items) > cap:
		more["job"] = more.get("job", 0) + sum(job_count(i) for i in job_items[cap:])
	items += job_items[:cap]
	items += [_customs_item(r, clearing.get(_text(r.get("name")))) for r in _take(cleared, "customs", more)]
	items += [_delivery_item(r, delivering.get(_text(r.get("name")))) for r in _take(delivered, "delivery", more)]

	updates = _creation_desc([u for u in all_updates if _text(u.get("name")) not in folded])
	# "newest 8": not bounded by the window, so the strip never goes empty.
	items += [_update_item(u) for u in updates[:KIND_CAPS["update"]]]

	return _section("ops", "Operations", OPS_DEFINITION, ops_chips(payload, raw, as_of), items, more)


CLEARED_MILESTONES = frozenset({"CLEARED", "FZ_CLEARED", "OMAN_CLEARED"})


# --------------------------------------------------------------------------
# Accounts section
# --------------------------------------------------------------------------

def _line_value(card, label):
	return next((c["value"] for c in card.get("context") or [] if c.get("label") == label), None)


def _card_tone(card):
	return {"critical": "critical", "warning": "warning"}.get(card.get("severity"), "neutral")


ACC_ROUTE_DOCTYPES = {
	acc.ROUTES["receivables"]: "Sales Invoice",
	acc.ROUTES["payables"]: "Purchase Invoice",
}


def _report_doctype(route):
	route = _text(route)
	if route.startswith(acc.ROUTES["general_ledger"]):
		return "GL Entry"
	return ACC_ROUTE_DOCTYPES.get(route.split("?")[0])


def credit_split(kind, rows, payments, as_of):
	"""(owed, in_credit, n_in_credit): what the parties who owe (receivables) or
	are owed (payables) add up to, and the credit of the parties on the other
	side -- the balance card's total is owed - in_credit (acc.party_positions)."""
	docs = acc.ageing_documents(kind, rows, payments)
	values = [p["value"] for p in acc.party_positions(kind, docs, as_of).values()]
	credit = [-v for v in values if v < 0]
	return cc.money(sum(v for v in values if v > 0)), cc.money(sum(credit)), len(credit)


def _balance_sub(card, kind, raw, as_of):
	"""The receivables / payables chip's line under the value. The overdue figure
	is net of each party's own credits, so it can exceed the card's total when
	some parties are in credit ("AED 617.5K overdue" under "AED 615K" read as an
	error on 14 Oct 2026): then it is set against what is owed instead."""
	overdue = _line_value(card, "Overdue")
	if not overdue:
		return None, []
	rows_ = (raw or {}).get("Sales Invoice" if kind == "receivables" else "Purchase Invoice")
	if rows_ is None or not as_of:
		return "%s overdue" % overdue, []
	payments = (raw or {}).get("Payment Entry")
	owed, credit, n_credit = credit_split(kind, rows_, payments, as_of)
	if kind == "receivables":
		extra = [row("Owed by the customers who owe", money_full(owed)),
		         row("Customers in credit", "%s · %s" % (money_compact(credit), cc.format_count(n_credit))
		             if n_credit else "")]
	else:
		extra = [row("Owed to the suppliers we owe", money_full(owed)),
		         row("Suppliers in credit", "%s · %s" % (money_compact(credit), cc.format_count(n_credit))
		             if n_credit else "")]
	overdue_value = acc.overdue_net(kind, acc.ageing_documents(kind, rows_, payments), as_of)[0]
	if overdue_value > _num(card.get("value")) and owed:
		return "%s overdue of %s owed" % (overdue, money_compact(owed)), extra
	return "%s overdue" % overdue, extra


def acc_chips(payload, raw=None, as_of=None, submitted=None, window=None, since=None):
	"""The six Accounts chips. `raw` and `as_of` explain an overdue figure above
	the total; `submitted` (the invoices submitted in the window, as listed in
	the section) and `window` ("since 12:00") add the window's line to the
	"Invoiced, 7 days" sheet, whose own "last" line is by posting date."""
	balances = _by_key(payload.get("balances"))
	kpis = _by_key(payload.get("kpis"))
	chips = []

	for key, label in (("receivables", "Receivables"), ("payables", "Payables")):
		card = balances.get(key)
		if not card:
			continue
		sub, extra = _balance_sub(card, key, raw, as_of)
		chips.append(make_chip(
			key, label, card["value"], money_compact(card["value"]), unit="currency",
			tone=_card_tone(card), sub=sub,
			definition=card.get("definition"),
			detail=[row("Total", money_full(card["value"]))]
			+ [row(c["label"], c["value"]) for c in card.get("context") or []] + extra,
			doctype=_report_doctype(card.get("route")), route=card.get("route")))

	card = balances.get("cash")
	if card:
		gap = next((c for c in card.get("context") or [] if c["label"].startswith("Books ")), None)
		chips.append(make_chip(
			"cash", "Cash & bank", card["value"], money_compact(card["value"]), unit="currency",
			tone=_card_tone(card), sub=("%s %s" % (gap["label"], gap["value"])) if gap else None,
			definition=card.get("definition"), note=card.get("caveat"),
			detail=[row("Book balance", money_full(card["value"]))]
			+ [row(c["label"], c["value"]) for c in card.get("context") or []],
			doctype="GL Entry", route=card.get("route")))

	card = balances.get("vat")
	if card:
		due = _line_value(card, "Due date")
		chips.append(make_chip(
			"vat", card["label"], card["value"], money_compact(card["value"]), unit="currency",
			tone=_card_tone(card), sub=("Due %s" % due) if due else None,
			definition=card.get("definition"), note=card.get("caveat"),
			detail=[row("Net VAT", money_full(card["value"]))]
			+ [row(c["label"], c["value"]) for c in card.get("context") or []],
			doctype="GL Entry", route=card.get("route")))

	for key, label, doctype in (("invoiced", "Invoiced, 7 days", "Sales Invoice"),
	                            ("collected", "Collected, 7 days", "Payment Entry")):
		kpi = kpis.get(key)
		if not kpi:
			continue
		delta = kpi_delta(kpi, caveat=bool(kpi.get("caveat")))
		chips.append(make_chip(
			"%s_7d" % key, label, kpi["value"], money_compact(kpi["value"]), unit="currency",
			tone=(delta or {}).get("tone", "neutral"), delta=delta,
			definition=kpi.get("definition"), note=kpi.get("caveat"),
			detail=[row(cc.PERIODS[PERIOD]["label"], money_full(kpi["value"])),
			        row("Previous 7 days", money_full(kpi["previous"]) if kpi.get("previous") is not None else "")]
			+ [row(KPI_LINE_LABELS.get(c["label"], c["label"]), c["value"]) for c in kpi.get("context") or []]
			+ ([_submitted_row(submitted, window, since)] if key == "invoiced" and submitted is not None else []),
			doctype=doctype, route=kpi.get("route")))
	return chips


# The dashboard's "Last submitted" line is the latest POSTING date of a
# submitted invoice; next to the invoices submitted today it read as a
# contradiction (14 Oct 2026: "Last submitted: 10 Oct" above three invoices
# submitted at 16:07), so the feed names it for what it is.
KPI_LINE_LABELS = {"Last submitted": "Latest posting date"}


def _submitted_row(invoices, window, since=None):
	"""'Submitted since 12:00' -> '3 · AED 35.4K with VAT · 2 back-dated' (the
	invoices listed in the section; back-dated: their posting date is before
	the window's first day, so the 7-day figure by posting date may not show
	them)."""
	invoices = list(invoices or [])
	label = "Submitted %s" % (window or "since the previous update")
	if not invoices:
		return row(label, "None")
	total = sum(_num(r.get("base_grand_total")) for r in invoices)
	first_day = to_datetime(since).date() if to_datetime(since) else None
	back = sum(1 for r in invoices if first_day and to_date(r.get("posting_date"))
	           and to_date(r.get("posting_date")) < first_day)
	return row(label, cc._join(cc.format_count(len(invoices)), "%s with VAT" % money_compact(total),
	                           ("%d back-dated" % back) if back else ""))


def _draft_records(drafts):
	drafts = sorted(drafts, key=lambda r: (to_date(r.get("posting_date")) or date.max, _text(r.get("name"))))
	return [record(_customer(r), "Sales Invoice", r.get("name"),
	               subtitle=cc._join(r.get("name"), r.get("fps_job_order"),
	                                 ("dated " + cc.short_date(r.get("posting_date")))
	                                 if to_date(r.get("posting_date")) else ""),
	               value=money_compact(_num(r.get("base_grand_total"))))
	        for r in drafts]


def _party_records(kind, parties, doctype):
	spec = acc.AGEING_SPEC[kind]
	noun = ("invoice", "invoices") if kind == "receivables" else ("bill", "bills")
	return [record(p["label"], doctype,
	               subtitle="%d %s past due · oldest %d days" % (
	                   len(p["overdue_docs"]), cc.plural(len(p["overdue_docs"]), *noun), p["oldest_days"]),
	               value=money_compact(p["overdue"]),
	               route=cc.list_route(doctype, {spec["party"]: p["party"], "docstatus": 1,
	                                             "outstanding_amount": ["!=", 0]}))
	        for p in parties]


def overdue_parties(kind, rows, payments, as_of):
	"""Parties with net overdue (acc.overdue_net), largest overdue first."""
	docs = acc.ageing_documents(kind, rows, payments)
	_total, parties = acc.overdue_net(kind, docs, as_of)
	return sorted(parties, key=lambda p: (-p["overdue"], p["label"], p["party"]))


def acc_insight_item(ins, payload, raw, as_of):
	iid = ins["id"]
	doctype, route, records, detail = None, ins.get("route"), [], []
	invoices, payments, bills = raw.get("Sales Invoice"), raw.get("Payment Entry"), raw.get("Purchase Invoice")
	balances = _by_key(payload.get("balances"))
	if iid == "vat_due":
		doctype = "GL Entry"
		card = balances.get("vat") or {}
		detail = [row("Net VAT", money_full(card["value"])) if card else None] + \
		         [row(c["label"], c["value"]) for c in card.get("context") or []]
	elif iid == "duplicate_drafts":
		doctype = "Sales Invoice"
		hits = cc.duplicate_drafts(invoices)
		records = _draft_records(hits)
		detail = [row("Drafts", cc.format_count(len(hits))),
		          row("Value", money_full(sum(_num(r.get("base_grand_total")) for r in hits)))]
	elif iid in ("invoicing_stall", "sales_invoice_drafts"):
		doctype = "Sales Invoice"
		route = route or cc.list_route("Sales Invoice", {"docstatus": 0})
		drafts = [r for r in invoices or [] if int(_num(r.get("docstatus"))) == 0]
		records = _draft_records(drafts)
		n, value = acc.drafts_waiting(drafts)
		last = cc.last_submitted_invoice(invoices, as_of)
		detail = [row("Drafts", cc.format_count(n)), row("Value", money_full(value)),
		          row("Last invoice submitted", cc.short_date(last) if last else "")]
	elif iid == "unallocated_receipts":
		doctype = "Payment Entry"
		total, hits = acc.unallocated(payments, "Receive")
		hits = sorted(hits, key=lambda r: (-_num(r.get("unallocated_amount")), _text(r.get("name"))))
		records = [record(r.get("party_name") or r.get("party"), "Payment Entry", r.get("name"),
		                  subtitle=cc._join(r.get("name"), ("posted " + cc.short_date(r.get("posting_date")))
		                                    if to_date(r.get("posting_date")) else ""),
		                  value=money_compact(_num(r.get("unallocated_amount"))))
		           for r in hits]
		detail = [row("Unallocated", money_full(total)), row("Receipts", cc.format_count(len(hits)))]
	elif iid == "supplier_overdue":
		doctype = "Purchase Invoice"
		parties = overdue_parties("payables", bills, payments, as_of)
		records = _party_records("payables", parties, "Purchase Invoice")
		detail = [row("Past due, net", money_full(sum(p["overdue"] for p in parties))),
		          row("Suppliers", cc.format_count(len(parties)))]
	elif iid == "ar_ageing":
		doctype = "Sales Invoice"
		ageing = _by_key(payload.get("ageing")).get("receivables") or {}
		detail = [row("Receivables", money_full(ageing["total"])) if ageing else None] + [
			row(b["label"], "%s · %s" % (money_compact(b["value"]), cc.format_count(b["count"])))
			for b in ageing.get("buckets") or [] if b.get("count")]
	elif iid == "delivered_not_invoiced":
		doctype = "Job Order"
	elif iid == "bank_statements_behind":
		doctype = "FPS Bank Statement"
	if not route and ins.get("metric_key"):
		route = (acc.METRICS.get(ins["metric_key"]) or {}).get("route")
	return make_item("ins:acc:%s" % iid, "insight", ins["severity"], ins["title"], note=ins.get("detail"),
	                 detail=detail, records=records, doctype=doctype, route=route)


def _invoice_item(r):
	name = _text(r.get("name"))
	is_return = int(_num(r.get("is_return"))) == 1
	is_request = int(_num(r.get("fps_is_payment_request"))) == 1
	what = "Credit note" if is_return else ("Payment request" if is_request else "Invoice")
	due = to_date(r.get("due_date"))
	amount = _num(r.get("base_grand_total"))
	settled = abs(_num(r.get("outstanding_amount"))) < 0.005
	# A settled invoice shows its status ("Paid"), not a due date that has
	# passed -- "due 30 Sep" on a paid invoice read as overdue.
	state = (_text(r.get("status")) or "Paid") if settled else (("due " + cc.short_date(due)) if due else "")
	return make_item(
		"si:%s" % name, "invoice", "info" if is_return else "positive",
		_text(_customer(r)) or cc.NO_PARTY, tag=what,
		subtitle=cc._join(name, r.get("fps_job_order"), "" if is_return else state),
		amount=amount, at=r.get("submitted_at") or r.get("posting_date"),
		detail=[row(what, name), row("Customer", _customer(r)), row("Job Order", r.get("fps_job_order")),
		        row("Posting date", cc.short_date(r.get("posting_date")) if to_date(r.get("posting_date")) else ""),
		        row("Due date", cc.short_date(due) if due else ""),
		        row("Net", money_full(_num(r.get("base_net_total")))),
		        row("Grand total", money_full(amount)),
		        row("Outstanding", money_full(_num(r.get("outstanding_amount")))),
		        row("Status", r.get("status")), row("Submitted", when(r.get("submitted_at")))],
		doctype="Sales Invoice", name=name)


def _receipt_item(r):
	name = _text(r.get("name"))
	ref = _text(r.get("reference_no"))
	amount = _num(r.get("base_received_amount"))
	unalloc = _num(r.get("unallocated_amount"))
	return make_item(
		"pe:%s" % name, "receipt", "positive",
		_text(r.get("party_name") or r.get("party")) or cc.NO_PARTY, tag="Received",
		subtitle=cc._join(name, r.get("mode_of_payment"), nb("Ref " + ref) if ref else ""),
		amount=amount, at=r.get("submitted_at") or r.get("posting_date"),
		detail=[row("Receipt", name), row("From", r.get("party_name") or r.get("party")),
		        row("Amount", money_full(amount)),
		        row("Posting date", cc.short_date(r.get("posting_date")) if to_date(r.get("posting_date")) else ""),
		        row("Booked", when(r.get("submitted_at"))), row("Mode", r.get("mode_of_payment")),
		        row("Reference", nb(ref)),
		        row("Not yet allocated", money_full(unalloc) if unalloc > 0 else "")],
		doctype="Payment Entry", name=name)


def _party_item(kind, p):
	customer = kind == "receivables"
	doctype = "Sales Invoice" if customer else "Purchase Invoice"
	spec = acc.AGEING_SPEC[kind]
	noun = ("invoice", "invoices") if customer else ("bill", "bills")
	docs = p["overdue_docs"]
	return make_item(
		"%s:%s" % ("odc" if customer else "ods", p["party"]),
		"overdue_customer" if customer else "supplier_due",
		# One severity for the whole list: every party here is past due. (By
		# amount it gave DUBAI TRADE an amber warning and DONEWELL, 45 days
		# too, a blue note, with nothing to say why.)
		"warning",
		p["label"],
		subtitle="%d %s past due · oldest %d days" % (len(docs), cc.plural(len(docs), *noun), p["oldest_days"]),
		amount=p["overdue"],
		# Not the days: they grow every morning without anything happening.
		fingerprint_basis=(cc.format_money_compact(p["overdue"]), len(docs)),
		detail=[row("Past due (net of credits)", money_full(p["overdue"])),
		        row("Total outstanding", money_full(p["value"])),
		        row("Open %s" % noun[1], cc.format_count(p["count"])),
		        row("Oldest past due", "%d days" % p["oldest_days"])],
		records=[record(name, doctype, name,
		                subtitle="due %s · %d days past due" % (
		                    cc.short_date(to_date(r.get("due_date")) or to_date(r.get("posting_date"))), days),
		                value=money_compact(amount))
		         for days, name, amount, r in docs],
		doctype=doctype,
		route=cc.list_route(doctype, {spec["party"]: p["party"], "docstatus": 1, "outstanding_amount": ["!=", 0]}))


def bank_item(payload, raw, insight=None):
	"""One item for the bank statements: the bank_statements_behind insight when
	it fired, else an "up to date" note; a record per bank."""
	banks = payload.get("banks") or []
	if not banks:
		return None
	latest = acc._latest_statements(raw.get("FPS Bank Statement"))
	records, detail = [], []
	for b in banks:
		name = latest[b["bank"]][0][1] if b["bank"] in latest else None
		state = cc._join(b.get("latest_month") or "No statement", b.get("status"))
		if b.get("months_behind"):
			state = cc._join(state, "%d %s behind" % (b["months_behind"], cc.plural(b["months_behind"], "month", "months")))
		detail.append(row(b["label"], state))
		records.append(record(b["label"], "FPS Bank Statement", name,
		                      subtitle=b.get("open_months") or cc._join(b.get("latest_month"), b.get("status")),
		                      value=money_compact(b["closing_balance"]) if b.get("closing_balance") is not None else None,
		                      route=b.get("route")))
	if insight:
		severity, title, note = insight["severity"], insight["title"], insight.get("detail")
	else:
		severity, title, note = "positive", "Bank statements up to date", None
	return make_item("bank:statements", "bank", severity, title, note=note, detail=detail, records=records,
	                 doctype="FPS Bank Statement", route="/app/fps-bank-statement")


def cash_item(payload):
	card = _by_key(payload.get("balances")).get("cash")
	if not card or card.get("severity") != "critical":
		return None
	gap = next((c for c in card.get("context") or [] if c["label"].startswith("Books ")), None)
	return make_item("cash:statement_gap", "cash", "critical", "Books differ from the bank statement",
	                 subtitle=("%s %s" % (gap["label"], gap["value"])) if gap else None,
	                 note=card.get("caveat"),
	                 detail=[row("Book balance", money_full(card["value"]))]
	                 + [row(c["label"], c["value"]) for c in card.get("context") or []],
	                 doctype="GL Entry", route=card.get("route"))


# The ACC insights the Accounts section does not repeat: delivered_not_invoiced
# is an Operations item (same insight, same records), bank_statements_behind
# becomes the bank item.
ACC_SKIPPED_INSIGHTS = ("delivered_not_invoiced", "bank_statements_behind")


def build_acc_section(payload, raw, recent, *, since, as_of, now=None):
	raw = raw or {}
	recent = recent or {}
	since_dt = to_datetime(since)
	more = {}
	insights = payload.get("insights") or []
	items = [acc_insight_item(i, payload, raw, as_of) for i in insights if i["id"] not in ACC_SKIPPED_INSIGHTS]
	items.append(cash_item(payload))

	def submitted(rows):
		rows = [r for r in rows or [] if (to_datetime(r.get("submitted_at")) or _EPOCH) >= since_dt]
		return _creation_desc(rows, "submitted_at")

	invoices = submitted(r for r in recent.get("Sales Invoice") or [] if int(_num(r.get("docstatus", 1))) == 1)
	items += [_invoice_item(r) for r in _take(invoices, "invoice", more)]
	receipts = submitted(r for r in recent.get("Payment Entry") or []
	                     if int(_num(r.get("docstatus", 1))) == 1 and _text(r.get("payment_type")) == "Receive")
	items += [_receipt_item(r) for r in _take(receipts, "receipt", more)]

	if raw.get("Sales Invoice") is not None:
		parties = overdue_parties("receivables", raw["Sales Invoice"], raw.get("Payment Entry"), as_of)
		items += [_party_item("receivables", p) for p in _take(parties, "overdue_customer", more)]
	if raw.get("Purchase Invoice") is not None:
		parties = overdue_parties("payables", raw["Purchase Invoice"], raw.get("Payment Entry"), as_of)
		items += [_party_item("payables", p) for p in _take(parties, "supplier_due", more)]

	behind = next((i for i in insights if i["id"] == "bank_statements_behind"), None)
	items.append(bank_item(payload, raw, behind))
	chips = acc_chips(payload, raw=raw, as_of=as_of, submitted=invoices if recent.get("Sales Invoice") is not None
	                  else None, window=since_label(since_dt, now) if now else None, since=since_dt)
	return _section("acc", "Accounts", ACC_DEFINITION, chips, [i for i in items if i], more)


# --------------------------------------------------------------------------
# Sections and the snapshot
# --------------------------------------------------------------------------

SectionKeys = ("key", "title", "definition", "error", "notice", "chips", "items", "more", "counts", "detail")
SnapshotKeys = ("version", "generated_at", "slot", "slot_id", "next_slot", "updated_label", "as_of",
                "period", "time_zone", "since", "since_label", "sections")


def _section(key, title, definition, chips, items, more, error=None):
	kept, dropped = cap_items([i for i in items if i])
	for item in dropped:
		more[item["kind"]] = more.get(item["kind"], 0) + job_count(item)
	# The standing lists (most overdue customers, suppliers past due) are listed,
	# not alerts: they are left out of the header's critical / warning counts.
	counted = [i for i in kept if i["kind"] not in PARTY_KINDS]
	counts = {s: sum(1 for i in counted if i["severity"] == s) for s in SEVERITIES}
	return _ordered({
		"key": key, "title": title, "definition": definition, "error": error,
		"chips": chips, "items": kept, "more": more_lines(more), "counts": counts,
	}, SectionKeys)


def in_window(item, since):
	"""True when the item's `at` falls in the window (a bare date: on or after its first day)."""
	at = _text(item.get("at"))
	since = to_datetime(since)
	if not at or not since:
		return False
	if len(at) <= 10:
		return to_date(at) >= since.date()
	return to_datetime(at) >= since


def error_section(key, title, definition, message):
	return _section(key, title, definition, [], [], {}, error=message)


SECTION_TITLES = {"ops": ("Operations", OPS_DEFINITION), "acc": ("Accounts", ACC_DEFINITION)}


def build_snapshot(*, now, ops=None, acc_data=None, recent=None, since=None, errors=None):
	"""The stored snapshot (docs/live_feed/snapshot.schema.md).

	ops       {"payload": OPS DashboardPayload (period 7d), "raw": its raw rows} or None
	acc_data  {"payload": AccPayload (period 7d), "raw": its raw rows} or None
	recent    {"Job Order": [rows + creation], "Sales Invoice": [rows + submitted_at],
	           "Payment Entry": [rows + submitted_at]}
	since     start of the "since the previous update" window (recent_since)
	errors    {"ops" | "acc": message} for a section whose data could not be read
	"""
	now = to_datetime(now)
	as_of = now.date()
	since = to_datetime(since) or recent_since(now)
	recent = recent or {}
	errors = dict(errors or {})
	sections = []
	if ops is not None and "ops" not in errors:
		sections.append(build_ops_section(ops["payload"], ops.get("raw"), recent.get("Job Order"),
		                                  since=since, as_of=as_of))
	else:
		sections.append(error_section("ops", *SECTION_TITLES["ops"],
		                              errors.get("ops") or "Operations data could not be read."))
	if acc_data is not None and "acc" not in errors:
		sections.append(build_acc_section(acc_data["payload"], acc_data.get("raw"), recent,
		                                  since=since, as_of=as_of, now=now))
	else:
		sections.append(error_section("acc", *SECTION_TITLES["acc"],
		                              errors.get("acc") or "Accounts data could not be read."))
	window = since_label(since, now)
	if errors.get("recent"):
		# The recent-document reads failed (feed._read_recent): the sections are
		# built without them and say so, instead of the whole build failing.
		notices = {"ops": "The jobs opened %s could not be read at %s." % (window, hhmm(now)),
		           "acc": "The invoices and receipts %s could not be read at %s." % (window, hhmm(now))}
		sections = [s if s.get("error") else _ordered(dict(s, notice=notices[s["key"]]), SectionKeys)
		            for s in sections]
	for s in sections:
		events = [i for i in s["items"] if i["kind"] in EVENT_KINDS]
		recent_events = [i for i in events if in_window(i, since)]
		s["detail"] = _rows([
			row("Alerts", cc.format_count(sum(1 for i in s["items"] if i["kind"] in ("insight", "cash", "bank")))),
			row("Critical", cc.format_count(s["counts"]["critical"])),
			row("Warnings", cc.format_count(s["counts"]["warning"])),
			row("Events %s" % window, cc.format_count(len(recent_events))),
			# The newest job updates are shown even when older than the window
			# (build_ops_section), so the count above never claims them.
			row("Earlier job updates shown", cc.format_count(len(events) - len(recent_events))
			    if len(events) > len(recent_events) else ""),
			row("Dashboard period", cc.PERIODS[PERIOD]["label"]),
		])
	return _ordered({
		"version": VERSION,
		"generated_at": stamp(now),
		"slot": slot_label(now),
		"slot_id": slot_id(now),
		"next_slot": next_slot_label(now),
		"updated_label": updated_label(now, now),
		"as_of": as_of.isoformat(),
		"period": PERIOD,
		"time_zone": TIME_ZONE,
		"since": stamp(since),
		"since_label": window,
		"sections": sections,
	}, SnapshotKeys)


# --------------------------------------------------------------------------
# NEW marks, previous fingerprints, per-viewer "Open in ERPNext"
# --------------------------------------------------------------------------

def fingerprints_of(snapshot):
	"""What the next build stores as `previous`: keys and fingerprints only."""
	if not snapshot:
		return None
	items, chips = {}, {}
	for s in snapshot.get("sections") or []:
		for i in s.get("items") or []:
			items[i["key"]] = i["fingerprint"]
		for c in s.get("chips") or []:
			chips[c["key"]] = {"fp": c["fingerprint"], "value": c.get("value")}
	return {"version": snapshot.get("version"), "generated_at": snapshot.get("generated_at"),
	        "slot_id": snapshot.get("slot_id"), "items": items, "chips": chips}


def next_previous(stored_snapshot, stored_previous, new_slot_id):
	"""The `previous` to store with a new build.

	A build in another slot compares with the snapshot it replaces. A rebuild in
	the SAME slot keeps comparing with the slot before (stored_previous), so a
	manual re-run at 12:05 does not wipe the 12:00 NEW marks. No stored
	snapshot -> None (nothing is NEW on the first snapshot)."""
	if not stored_snapshot:
		return stored_previous or None
	if stored_snapshot.get("slot_id") == new_slot_id:
		return stored_previous or None
	return fingerprints_of(stored_snapshot)


def _is_number(v):
	return isinstance(v, int | float) and not isinstance(v, bool)


def mark_new(snapshot, previous):
	"""Adds is_new to every item, changed / since_previous to every chip, and
	counts.new to every section. Mutates and returns `snapshot`."""
	prev_items = (previous or {}).get("items")
	prev_chips = (previous or {}).get("chips") or {}
	has_prev = isinstance(prev_items, dict)
	for s in snapshot.get("sections") or []:
		n = 0
		for item in s.get("items") or []:
			item["is_new"] = bool(has_prev and prev_items.get(item["key"]) != item["fingerprint"])
			n += item["is_new"]
		for chip in s.get("chips") or []:
			p = prev_chips.get(chip["key"]) if has_prev else None
			chip["changed"] = bool(p and p.get("fp") != chip["fingerprint"])
			if chip["changed"] and _is_number(chip.get("value")) and _is_number(p.get("value")):
				diff = chip["value"] - p["value"]
				if chip.get("unit") == "currency":
					diff = cc.money(diff)
					text = ("+" if diff > 0 else "") + money_compact(diff)
				else:
					diff = int(round(diff))
					text = ("+%d" % diff) if diff > 0 else ("−%d" % -diff if diff < 0 else "0")
				if diff:
					chip["since_previous"] = diff
					chip["since_previous_display"] = text
		s.setdefault("counts", {})["new"] = n
	snapshot["compared_with"] = (previous or {}).get("generated_at") if has_prev else None
	return snapshot


REPORT_ROUTE = "/app/query-report/"


def report_name(route):
	"""'General Ledger' for '/app/query-report/General%20Ledger?company=…', else None."""
	route = _text(route)
	if not route.startswith(REPORT_ROUTE):
		return None
	return unquote(route[len(REPORT_ROUTE):].split("?", 1)[0].split("/", 1)[0]) or None


def apply_can_open(snapshot, can_read):
	"""can_open on every item, record and chip for this viewer; the route is
	removed where it is False, so the page cannot offer it by mistake.

	can_read(doctype, name=None) -> bool: read on that document (name given) or
	on the doctype (list and report routes). A query-report route also needs
	the report itself: can_read("Report", <report name>) -- the desk refuses a
	report whose roles the viewer lacks even when the doctype is readable.
	Mutates and returns `snapshot`."""
	def decide(entry):
		doctype, route = entry.get("doctype"), entry.get("route")
		ok = bool(route and doctype and can_read(doctype, entry.get("name")))
		report = report_name(route)
		if ok and report:
			ok = bool(can_read("Report", report))
		entry["can_open"] = ok
		if not ok:
			entry.pop("route", None)

	for s in snapshot.get("sections") or []:
		for item in s.get("items") or []:
			decide(item)
			for rec in item.get("records") or []:
				decide(rec)
		for chip in s.get("chips") or []:
			decide(chip)
	return snapshot


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------

def dumps(obj):
	return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(text):
	"""A dict from stored JSON, or None (empty, malformed or not an object)."""
	if not text:
		return None
	if isinstance(text, dict):
		return text
	try:
		value = json.loads(text)
	except (TypeError, ValueError):
		return None
	return value if isinstance(value, dict) else None


def script_json(obj):
	"""JSON safe to place inside <script type="application/json">: '<', '>', '&'
	and the two JS line separators are escaped, so a customer name can never
	close the script element."""
	text = dumps(obj)
	for raw_char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
	                          (" ", "\\u2028"), (" ", "\\u2029")):
		text = text.replace(raw_char, escaped)
	return text
