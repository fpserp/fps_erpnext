"""The job-tracking derivation engine, and the one thing that used to live on a
separate document: the dated update log.

WHY THIS MODULE EXISTS. "Job Tracker" was a second document per job that only
ever held two things Job Order didn't already have: the update log
(`fps_updates`, a child table of FPS Job Update rows) and the ~250-line
derivation that reads it. Every OTHER field on Job Tracker was a fetch_from
mirror of Job Order (verified against the live meta before writing a line of
this) -- movement_type, client_reference_no, awb_bl_no, eta, etd, and so on all
already lived on Job Order under their own names. So the update log moves
directly onto Job Order as `fps_updates`, and this module is where the
derivation that reads it now lives -- as real, git-tracked Python, not a
250-line body duplicated across two Server Scripts (JT Rollup and
FPS Tracker Sweep held the identical function, character for character).

THE ONE LINE THAT ACTUALLY CHANGES in the derivation itself: where `evs` comes
from. It used to be looked up via a separate Job Tracker document; it is now a
plain frappe.get_all on FPS Job Update filtered to this Job Order. Every other
line of the ~250-line body is untouched -- the milestone table, the FZ/Oman
routing, the stage machine, the SOW label, all of it.

WHY THIS IS PYTHON AND NOT A SERVER SCRIPT. Two live incidents this project has
already had were both safe_exec footguns: a closure that could not see a
module-level variable (fixed 2026-09-10), and RestrictedPython rejecting
`out["x"] += 1`. The derivation is the single most complex piece of logic in
this app; it does not belong in a sandbox with surprises like those. Moving it
here does not change WHERE it runs from -- see WHAT TRIGGERS IT below -- only
what language it is written in.

WHAT TRIGGERS IT. Not a Job Order save. Job Order already has a Before Save
script -- "JO SOW Classify" -- that explicitly REVERTS fps_stage back to its
previous value whenever it changes to anything other than "Closed"
(`if prev and prev.fps_stage and doc.fps_stage != prev.fps_stage and
doc.fps_stage != "Closed": doc.fps_stage = prev.fps_stage`). If rollup ran as
part of a Job Order save and tried to set fps_stage on the same doc, that guard
would fight it and the stage would never move. So the write here stays a raw
`frappe.db.set_value`, exactly as before, and the trigger is the child table's
OWN "After Insert" event -- proven live before this was written: a standalone
FPS Job Update insert (parenttype="Job Order") fires its own after_insert
independently of any parent save, with no Job Order hook in the blast radius at
all. See hooks.py, doc_events["FPS Job Update"]["after_insert"].

WHAT ABOUT DELETING A ROW FROM THE GRID. Not caught immediately -- removing a
row via the Job Order form's own grid does not insert anything, so nothing
fires. The 30-minute sweep (below) catches it within that window. Every OTHER
way a row is added -- Log update, the six system emitters, Rebuild -- goes
through an insert and recomputes instantly.

THE MILESTONE LIST ITSELF (`ms`, inside rollup()) forks in one place: jobs
with BOTH Customs clearance and Local transport ticked get a different, fixed
order requested 2026-09-12 (docs/MOIAT limit check, arrival, delivery order,
BOE, duty/MOIAT exemption/deposit, customs released, MOFA, transportation,
POD, invoiced, payment) instead of the general-purpose order every other SOW
combination still uses. No new milestone codes were needed -- every step in
the new order reuses a code already in FPS Job Update's `milestone` Select
options, just relabelled and resequenced, so nothing needed adding there.

CLOSED AND PAID ARE TWO SEPARATE STEPS (revised 2026-09-12, the same day as
the original CT+transport reorder above -- the first version made CLOSED
itself require payment, which turned out to conflate two different real-world
moments and was corrected the same day). CLOSED means "all cost has been
entered" and is still the one stage a human may set by hand (or reach via a
logged CLOSED update), exactly as before -- it does NOT check payment. PAID
is new: it can only go "done" once CLOSED already is AND every non-cancelled
invoice on the job shows zero outstanding, and unlike CLOSED it is never
something a human can log by hand (deliberately excluded from the "Log
update" dialog's option list on the Job Order client script) -- it exists
purely so fps_stage can advance to "Completed" on its own once payment
actually clears, never on anyone's say-so. The milestone code is PAID, not
COMPLETED, specifically because COMPLETED already means something else
entirely for a General job (service completed, has nothing to do with
payment) -- reusing it for payment would have silently collided with that
existing milestone in the same dedup pass that builds `codes` below.
"""

import json

import frappe
from frappe.utils import flt, getdate

UPDATES = "fps_updates"

EVENT_FIELDS = (
	"name", "update_date", "milestone", "status_line", "notes",
	"evidence_ref", "next_action", "follow_up_date", "responsible",
	"owner", "creation", "idx",
)


def on_update_inserted(doc, method=None):
	"""after_insert hook on FPS Job Update. Reruns the derivation for its job.

	frappe.flags.fps_skip_rollup is set by the migration patch while it bulk
	inserts 383 historical rows, so that one-time copy does not fire 383
	redundant rollups -- it does one explicit rollup per job at the end instead.
	"""
	if getattr(frappe.flags, "fps_skip_rollup", False):
		return
	if doc.parenttype != "Job Order" or not doc.parent:
		return
	try:
		rollup(doc.parent)
	except Exception:
		frappe.log_error(title="FPS: rollup for %s" % doc.parent)


def sweep():
	"""Scheduled, every 30 minutes (see hooks.py scheduler_events) -- replaces
	the "FPS Tracker Sweep" Server Script at the same cadence. Recomputes every
	open job regardless of what changed, as the safety net for anything the
	insert-triggered path above did not catch (a deleted grid row, a document
	edited outside the normal flow, this function itself having been down)."""
	jobs = frappe.get_all(
		"Job Order",
		filters={"docstatus": ["<", 2], "fps_stage": ["not in", ["Closed", "Completed"]]},
		fields=["name"],
		limit_page_length=2000,
	)
	for row in jobs:
		try:
			rollup(row.name)
		except Exception:
			frappe.log_error(title="FPS Tracker Sweep %s" % row.name)


def rollup(jo_name):
	"""Rebuild the per-job milestone checklist, stage, progress, next action and
	SOW label from the documents on the job (Customs Trackers, PODs, Sales
	Invoices) and this job's own update log. Writes only with
	frappe.db.set_value on the Job Order -- never doc.save() -- so it can never
	recurse into a Job Order hook and can never block one."""

	def todate(v):
		return getdate(v) if v else None

	def dstr(v):
		return str(v)[:10] if v else ""

	jo = frappe.db.get_value(
		"Job Order",
		jo_name,
		["name", "jo_date", "docstatus", "movement_type", "direction", "awb_bl_no",
		 "carrier", "vessel_flight", "etd", "eta", "boe_no", "pol", "pod",
		 "fps_svc_freight", "fps_svc_clearance", "fps_svc_transport",
		 "fps_svc_crossborder", "fps_svc_general", "fps_category",
		 "fps_route_pattern", "fps_stage", "fps_stage_since",
		 "fps_clearance_location", "fps_vehicle_type", "fps_general_job_type",
		 "fps_owner"],
		as_dict=True,
	)
	if not jo or jo.docstatus == 2:
		return
	today = getdate(frappe.utils.today())

	# One tracker per job; each BOE is a row in it. Field names match the
	# tracker's, so everything below reading c.status / c.boe_number /
	# c.fps_clearance_type keeps working untouched.
	ct_names = [c.name for c in frappe.get_all(
		"Customs Tracker", filters={"job_order": jo_name}, fields=["name"])]
	cts = frappe.get_all(
		"FPS Customs Declaration",
		filters={"parenttype": "Customs Tracker", "parent": ["in", ct_names]},
		fields=["name", "status", "boe_number", "fps_leg", "fps_clearance_type",
		        "fps_clearance_location", "fps_mofa_status", "fps_do_status",
		        "fps_duty_paid_on", "clearance_date", "ct_date", "modified", "remarks"],
		order_by="ct_date asc, idx asc",
	) if ct_names else []
	pods = frappe.get_all(
		"Proof of Delivery",
		filters={"job_order": jo_name, "docstatus": ["<", 2]},
		fields=["name", "docstatus", "delivery_status", "pod_date", "vehicle_no",
		        "fps_pickup_datetime", "fps_final_delivery", "received_by",
		        "delivery_location", "creation"],
		order_by="creation asc",
	)
	sis = frappe.get_all(
		"Sales Invoice",
		filters={"fps_job_order": jo_name, "docstatus": 1, "fps_is_payment_request": 0},
		fields=["name", "posting_date", "outstanding_amount"],
		order_by="posting_date asc",
	)

	# THE ONE CHANGED LINE (in spirit -- it was three lines when it had to find
	# a separate tracker document first). Everything below this reads `evs`
	# exactly as it always has: e.milestone, e.update_date, e.evidence_ref,
	# e.next_action, e.follow_up_date, e.responsible, e.owner, e.status_line,
	# e.notes, e.creation.
	evs = frappe.get_all(
		"FPS Job Update",
		filters={"parenttype": "Job Order", "parent": jo_name},
		fields=list(EVENT_FIELDS),
		order_by="idx asc",
	)
	evs = sorted(evs, key=lambda x: (str(x.update_date or "9999-12-31"), x.idx))

	FZ = ("Transfer within FZ", "FZ Transit")
	OM = ("Port Sultan Qaboos (Oman)", "Sohar Port (Oman)")
	fz_names = [c.name for c in cts if (c.fps_clearance_type or "") in FZ]
	om_names = [c.name for c in cts if (c.fps_clearance_location or "") in OM and c.name not in fz_names]
	fz_cts = [c for c in cts if c.name in fz_names]
	om_cts = [c for c in cts if c.name in om_names]
	fin_cts = [c for c in cts if c.name not in fz_names and c.name not in om_names] or om_cts

	ev_done = {}
	hold = None
	for e in evs:
		code = e.milestone
		if code == "HOLD":
			hold = e
		elif code == "RESUME":
			hold = None
		elif code and code not in ev_done:
			ev_done[code] = e.update_date

	F = jo.fps_svc_freight
	C = jo.fps_svc_clearance
	T = jo.fps_svc_transport
	X = jo.fps_svc_crossborder
	G = jo.fps_svc_general
	upd = {}
	if cts and not C:
		C = 1
		upd["fps_svc_clearance"] = 1
	if [p for p in pods if p.vehicle_no] and not T and not X:
		T = 1
		upd["fps_svc_transport"] = 1
	has_fz = len(fz_cts) > 0
	has_om = len(om_cts) > 0
	route = jo.fps_route_pattern or "Direct"
	if has_fz and route == "Direct":
		route = "FZ transfer then import"
		upd["fps_route_pattern"] = route
	if has_om and route == "Direct":
		route = "Oman corridor"
		upd["fps_route_pattern"] = route

	ms = [("OPENED", "Job opened")]
	if C and T:
		# Customs clearance + local transport, both ticked: the one SOW
		# combination that covers most FPS jobs, and the exact order requested
		# for it (2026-09-12) -- a single customs-through-payment sequence,
		# distinct from every other combination below (which keeps its own
		# long-standing order untouched). PICKED_UP is deliberately dropped
		# from this list -- folded into VEHICLE's new "Transportation filed"
		# label -- so it never appears in this flavor's checklist, though the
		# done() call for it further down still runs harmlessly unused.
		ms += [("DOCS", "Shipping docs checked / MOIAT limit checked"),
		       ("ARRIVED", "Cargo arrived")]
		if has_fz:
			ms += [("FZ_BOE", "FZ transfer BOE filed"), ("FZ_CLEARED", "FZ transfer approved")]
		if has_om:
			ms += [("OMAN_BOE", "Oman declaration filed"), ("OMAN_CLEARED", "Cleared at Oman port"),
			       ("TRUCKS_DEPARTED", "Trucks departed Oman"), ("BORDER", "Border crossed")]
		ms += [
			("DO", "Delivery order collected"),
			("BOE", "Declaration filed (BOE)"),
			("DUTY", "Duty / MOIAT (Exemption) / Deposit filed in CT"),
			("CLEARED", "Customs released"),
			("MOFA", "MOFA attestation check"),
			("VEHICLE", "Transportation filed"),
			("DELIVERED", "POD received"),
		]
	else:
		if F:
			ms += [("BOOKED", "Booking confirmed"), ("DOCS", "Shipping docs checked"),
			       ("DEPARTED", "Departed origin"), ("ARRIVED", "Arrived at destination")]
		elif C or (jo.movement_type in ("SEA", "AIR")):
			ms += [("DOCS", "Shipping docs checked"), ("ARRIVED", "Cargo arrived")]
		if C:
			if has_fz:
				ms += [("FZ_BOE", "FZ transfer BOE filed"), ("FZ_CLEARED", "FZ transfer approved")]
			if has_om:
				ms += [("OMAN_BOE", "Oman declaration filed"), ("OMAN_CLEARED", "Cleared at Oman port"),
				       ("TRUCKS_DEPARTED", "Trucks departed Oman"), ("BORDER", "Border crossed")]
			ms += [("MOFA", "MOFA attestation"), ("BOE", "Declaration filed (BOE)"),
			       ("DO", "Delivery order collected"), ("DUTY", "Duty / deposit paid"),
			       ("CLEARED", "Customs released")]
		if T or X:
			ms += [("VEHICLE", "Vehicle assigned"), ("PICKED_UP", "Picked up / loaded")]
			if X and not has_om:
				ms += [("BORDER", "Border crossed")]
		if T or X or F:
			ms += [("DELIVERED", "Delivered")]
		if G:
			ms += [("DOCS_IN", "Documents collected"),
			       ("SUBMITTED", "Application submitted / service scheduled"),
			       ("COMPLETED", "Service completed")]
	ms += [("INVOICED", "Invoiced"), ("CLOSED", "Job closed"), ("PAID", "Payment received")]
	seen = set()
	order = []
	for code, label in ms:
		if code not in seen:
			seen.add(code)
			order.append((code, label))
	codes = [c for c, l in order]
	labels = dict(order)

	st = {}

	def done(code, d, note=""):
		st[code] = ["done", dstr(d), note or ""]

	def na(code, note=""):
		st[code] = ["na", "", note or ""]

	done("OPENED", jo.jo_date)
	if jo.carrier and jo.vessel_flight:
		done("BOOKED", ev_done.get("BOOKED") or jo.jo_date, jo.vessel_flight)
	if jo.awb_bl_no:
		done("DOCS", ev_done.get("DOCS") or jo.jo_date, (jo.awb_bl_no or "")[:40])
	if jo.awb_bl_no and jo.etd and todate(jo.etd) <= today:
		done("DEPARTED", jo.etd, "ETD")
	if cts:
		done("ARRIVED", cts[0].ct_date, "customs entry opened")
	elif pods:
		done("ARRIVED", pods[0].creation, "delivery record exists")
	for c in fz_cts:
		if c.boe_number and "FZ_BOE" not in st:
			done("FZ_BOE", c.ct_date, c.boe_number)
		if c.status == "Cleared":
			done("FZ_CLEARED", c.clearance_date or c.modified, c.boe_number or "")
	for c in om_cts:
		if c.boe_number and "OMAN_BOE" not in st:
			done("OMAN_BOE", c.ct_date, c.boe_number)
		if c.status == "Cleared":
			done("OMAN_CLEARED", c.clearance_date or c.modified, c.boe_number or "")
	mofa_vals = [(c.fps_mofa_status or "") for c in cts]
	if "Completed" in mofa_vals:
		done("MOFA", ev_done.get("MOFA") or [c.modified for c in cts if c.fps_mofa_status == "Completed"][0])
	elif cts and mofa_vals and all(v == "N/A" for v in mofa_vals):
		na("MOFA", "not required")
	boe_cts = [c for c in fin_cts if c.boe_number]
	if boe_cts:
		done("BOE", boe_cts[0].ct_date, ", ".join([c.boe_number for c in boe_cts]))
	do_vals = [(c.fps_do_status or "") for c in cts]
	if "Collected" in do_vals:
		done("DO", ev_done.get("DO") or [c.modified for c in cts if c.fps_do_status == "Collected"][0])
	elif cts and do_vals and all(v == "N/A" for v in do_vals):
		na("DO", "not required")
	duty = [c for c in cts if c.fps_duty_paid_on]
	if duty:
		done("DUTY", duty[0].fps_duty_paid_on)
	elif fin_cts and all((c.fps_clearance_type or "") in
	                     ("Import into Free Zone", "Export from Free Zone", "Export",
	                      "Re-Export", "Transfer within FZ", "FZ Transit") for c in fin_cts):
		na("DUTY", "no duty on this type")
	if fin_cts and all(c.status == "Cleared" for c in fin_cts):
		d = max([dstr(c.clearance_date or c.modified) for c in fin_cts])
		done("CLEARED", d, "BOE " + ", ".join([c.boe_number or "?" for c in fin_cts]))
	veh = [p for p in pods if p.vehicle_no]
	if veh:
		done("VEHICLE", veh[0].creation, veh[0].vehicle_no)
	pk = [p for p in pods if p.fps_pickup_datetime]
	if pk:
		done("PICKED_UP", pk[0].fps_pickup_datetime)
	dl = [p for p in pods if p.docstatus == 1 and p.delivery_status == "Delivered"]
	fin = [p for p in dl if p.fps_final_delivery in (1, None)]
	if fin:
		done("DELIVERED", fin[-1].pod_date, (fin[-1].received_by or fin[-1].delivery_location or "")[:40])
	elif dl:
		st["DELIVERED"] = ["pending", "", "%d partial delivery" % len(dl)]
	elif [p for p in pods if p.docstatus == 0 and p.delivery_status == "Delivered"]:
		st["DELIVERED"] = ["unconfirmed", dstr(pods[-1].pod_date), "POD still in draft"]
	if sis:
		done("INVOICED", sis[0].posting_date, sis[0].name)
	if ev_done.get("CLOSED") or jo.fps_stage in ("Closed", "Completed"):
		done("CLOSED", ev_done.get("CLOSED") or today)
	for code, d in ev_done.items():
		if code in ("HOLD", "RESUME"):
			continue
		if code not in st:
			done(code, d, "logged")

	last_done = -1
	for i, code in enumerate(codes):
		if st.get(code, [""])[0] == "done":
			last_done = i
	for i, code in enumerate(codes):
		if i < last_done and code not in st:
			if code in ("BOOKED", "DOCS", "DEPARTED", "ARRIVED", "TRUCKS_DEPARTED", "BORDER",
			            "PICKED_UP", "VEHICLE", "DOCS_IN", "SUBMITTED", "FZ_BOE", "FZ_CLEARED",
			            "OMAN_BOE", "OMAN_CLEARED", "BOE"):
				st[code] = ["done", "", "implied"]
			elif code in ("MOFA", "DO", "DUTY"):
				st[code] = ["na", "", "not recorded"]

	def isdone(c):
		return st.get(c, [""])[0] == "done"

	# PAID can only go done once CLOSED already is -- payment is checked
	# against reality (every non-cancelled invoice on the job actually shows
	# zero outstanding), never logged by hand, so this has to run down here,
	# after isdone() exists, rather than alongside the other done() calls
	# above.
	paid = bool(sis) and all(flt(s.outstanding_amount) <= 0 for s in sis)
	if isdone("CLOSED") and paid:
		done("PAID", ev_done.get("PAID") or today)

	hold_reason = None
	ct_hold = [c for c in cts if c.status in ("On Hold", "Delayed")]
	pod_fail = [p for p in pods if p.docstatus == 1 and p.delivery_status in ("Failed", "Returned")]
	if hold:
		hold_reason = (hold.status_line or hold.notes or "On hold")[:140]
	elif ct_hold and not isdone("CLEARED"):
		hold_reason = ("Customs %s: %s" % (ct_hold[0].status, (ct_hold[0].remarks or "")))[:140]
	elif pod_fail and not isdone("DELIVERED"):
		hold_reason = "Delivery %s" % pod_fail[-1].delivery_status
	if hold_reason:
		stage = "On Hold"
	elif isdone("PAID"):
		stage = "Completed"
	elif isdone("CLOSED"):
		stage = "Closed"
	elif isdone("INVOICED"):
		stage = "Invoiced"
	elif isdone("DELIVERED") or (G and isdone("COMPLETED") and not (T or X or F)):
		stage = "Delivered"
	elif (C and isdone("CLEARED")) or (F and not C and isdone("ARRIVED")):
		stage = "Cleared - Ready"
	elif cts or pods or isdone("DEPARTED") or isdone("BOOKED") or isdone("SUBMITTED") or isdone("PICKED_UP") or isdone("VEHICLE"):
		stage = "In Progress"
	elif "DOCS" in codes and not isdone("DOCS"):
		stage = "Docs received"
	else:
		stage = "New"

	applicable = [c for c in codes if st.get(c, ["pending"])[0] != "na"]
	n_done = len([c for c in applicable if st.get(c, [""])[0] == "done"])
	progress = "%d / %d" % (n_done, len(applicable))
	pending = [c for c in applicable if st.get(c, ["pending"])[0] != "done"]
	next_action = None
	next_due = None
	real_evs = [e for e in evs if not ((e.evidence_ref or "").endswith(":tracker-enabled") or ":rebuild:" in (e.evidence_ref or ""))]
	last_ev = real_evs[-1] if real_evs else None
	if last_ev and last_ev.next_action and stage not in ("Closed", "Completed"):
		next_action = last_ev.next_action
		next_due = last_ev.follow_up_date
	elif pending and stage not in ("Closed", "Completed"):
		next_action = labels[pending[0]]
	last_update = None
	last_on = None
	if last_ev:
		who = (last_ev.responsible or last_ev.owner or "").split("@")[0]
		last_update = ("%s - %s: %s" % (dstr(last_ev.update_date), who, (last_ev.status_line or last_ev.notes or "")[:160]))
		last_on = last_ev.creation

	cat = jo.fps_category
	if not cat:
		if F:
			cat = "FF - Freight Forwarding"
		elif C:
			cat = "CC - Customs Clearance"
		elif X:
			cat = "XB - Cross-Border Land Transport"
		elif T:
			cat = "LT - Local Land Transport"
		elif G:
			cat = "GJ - General Job"
		if cat:
			upd["fps_category"] = cat
	code2 = (cat or "")[:2]
	parts = [code2 or "?"]
	md = " ".join([x for x in [jo.movement_type, jo.direction] if x])
	if md and code2 in ("CC", "FF"):
		parts.append(md)
	if code2 == "CC" and jo.fps_clearance_location:
		parts.append(jo.fps_clearance_location.split(" (")[0])
	if code2 in ("LT", "XB") and jo.fps_vehicle_type:
		parts.append(jo.fps_vehicle_type)
	if code2 == "GJ" and jo.fps_general_job_type:
		parts.append(jo.fps_general_job_type)
	extras = []
	if C and code2 == "FF":
		extras.append("clearance")
	if (T or X) and code2 in ("CC", "FF", "GJ"):
		extras.append("delivery")
	if route != "Direct":
		extras.append(route.lower())
	label = " - ".join(parts) + (" + " + ", ".join(extras) if extras else "")

	state = [[c, labels[c]] + st.get(c, ["pending", "", ""]) for c in codes]
	upd.update({
		"fps_stage": stage, "fps_progress": progress, "fps_next_action": next_action,
		"fps_next_due": next_due, "fps_last_update": last_update, "fps_last_update_on": last_on,
		"fps_hold_reason": hold_reason, "fps_milestone_state": json.dumps(state),
		"fps_subcategory": label,
	})
	if stage != jo.fps_stage or not jo.fps_stage_since:
		upd["fps_stage_since"] = today
	frappe.db.set_value("Job Order", jo_name, upd)


@frappe.whitelist()
def log_update(job_order, track_date=None, milestone=None, note=None,
               evidence=None, next_action=None, follow_up_date=None,
               customer_visible=1, internal=None):
	"""Add one dated update directly onto a Job Order. The only supported way
	in from the interface (the "Log update" dialog on the Job Order form).

	Permission is the caller's own -- this writes to Job Order, so whoever
	calls it needs write on Job Order. No ignore_permissions on the insert.
	"""
	if not job_order:
		frappe.throw(frappe._("A job order is required to log an update."))

	frappe.has_permission("Job Order", "write", doc=job_order, throw=True)

	is_issue = milestone == "HOLD"
	track_date = track_date or frappe.utils.today()
	status_line = (note or "")[:140]

	count = frappe.db.count("FPS Job Update", {"parenttype": "Job Order", "parent": job_order})
	row = frappe.get_doc({
		"doctype": "FPS Job Update",
		"parent": job_order,
		"parenttype": "Job Order",
		"parentfield": UPDATES,
		"idx": count + 1,
		"update_date": track_date,
		"event_type": "Issue" if is_issue else ("Milestone" if milestone else "Note"),
		"milestone": milestone or None,
		"status_line": status_line,
		"notes": note,
		"issues": internal,
		"evidence_ref": evidence,
		"source": "Manual",
		"customer_visible": 0 if is_issue else frappe.utils.cint(customer_visible),
		"next_action": next_action,
		"follow_up_date": follow_up_date,
		"responsible": frappe.session.user,
		"leg": 1,
	})
	# Standalone insert, not append()+parent.save(): fires FPS Job Update's own
	# after_insert (see hooks.py), which reruns rollup() for this job -- without
	# ever touching a Job Order save and the JO SOW Classify guard described at
	# the top of this file.
	row.insert()
	# The insert above fires FPS Job Update's after_insert -> rollup(job_order),
	# which derives fps_next_action / fps_next_due from whichever real update is
	# now latest BY DATE -- deliberately not always the row just inserted. A
	# back-dated note stays a back-dated note; it does not jump the queue and
	# overwrite "what's next" ahead of something more recent. Same rule the
	# Job Tracker version always applied.
	return row.name


@frappe.whitelist()
def rebuild(job_order):
	"""Re-derive a job from its documents, without logging anything. Direct
	call -- rollup() is a plain function now, no separate document to fetch and
	save just to trigger it."""
	if not job_order:
		frappe.throw(frappe._("A job order is required."))

	frappe.has_permission("Job Order", "write", doc=job_order, throw=True)
	rollup(job_order)
	return job_order
