"""Put Customer ahead of JO Date in Order Information, so it lands between
the ID and JO Date columns in the Job Order list/report view.

WHY MOVING THE FIELD IS WHAT IT TAKES. Job Order is fully custom (custom=1),
so -- same lesson as reorder_job_order_layout.py -- its native fields have no
insert_after property setter can act on; a Report/List View's default column
set is the doctype's in_list_view fields, in the order they sit in the
doctype's own `fields` table. customer_name already carries in_list_view=1
(Job Order-customer_name-in_list_view, added 2026-09-09), but it sits AFTER
jo_date in that table, so that is where it renders. customer itself is not
flagged in_list_view at all -- the readable name is what belongs in a list,
not the raw Customer link value -- so only customer_name's position matters
here.

WHY customer AND order_cb1 MOVE TOO, not customer_name alone. Moving only
customer_name would put the read-only, auto-fetched name ahead of the
Customer picker that fills it -- backwards on the form. Moving customer
along with it keeps them in their natural fill-in order and keeps the
Order Information section's column grouping sensible: Series / Customer /
Customer Name together in column 1, JO Date alone in column 2 (still a
single field, not an empty column), Client Reference No. / Quotation
Reference unchanged in column 3. Simulated against the live field order
before writing this to confirm no field is lost, duplicated, or left in the
wrong column.

Idempotent: does nothing once naming_series is already immediately followed
by customer, customer_name, order_cb1 (in that order).
"""

import frappe

DOCTYPE = "Job Order"
ANCHOR = "naming_series"
MOVE = ["customer", "customer_name", "order_cb1"]


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	doc = frappe.get_doc("DocType", DOCTYPE)
	by_name = {f.fieldname: f for f in doc.fields}

	if not all(name in by_name for name in [ANCHOR] + MOVE):
		frappe.log_error(title="FPS: Job Order missing expected fields, customer not moved")
		return

	current = [f.fieldname for f in doc.fields]
	anchor_idx = current.index(ANCHOR)
	if current[anchor_idx + 1: anchor_idx + 1 + len(MOVE)] == MOVE:
		return  # already in place

	rest = [f for f in doc.fields if f.fieldname not in MOVE]
	anchor_idx = next(i for i, f in enumerate(rest) if f.fieldname == ANCHOR)
	new_fields = rest[:anchor_idx + 1] + [by_name[n] for n in MOVE] + rest[anchor_idx + 1:]

	assert len(new_fields) == len(doc.fields)
	for i, f in enumerate(new_fields, start=1):
		f.idx = i
	doc.fields = new_fields

	doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.db.commit()
	frappe.logger().info("FPS: moved Customer / Customer Name ahead of JO Date on Job Order")
