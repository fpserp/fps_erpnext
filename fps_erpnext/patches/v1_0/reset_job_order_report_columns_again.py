"""Re-run reset_report_columns.execute(), for Job Order's sake specifically.

WHY A SECOND PATCH FOR THE SAME THING. reset_report_columns.py already covers
Job Order -- it's in that patch's own DOCTYPES tuple -- and is explicitly
documented as safe to re-run. But it already ran once, months before
move_customer_before_jo_date.py existed, and `bench migrate` never re-runs a
patch it has already recorded executing, no matter how safe re-running it
would be. Editing the original file wouldn't do anything either, for the
same reason: Frappe tracks execution by module path, not by content.

So: whoever opened the Job Order Report/List view any time between
2026-09-09 (when customer_name first got in_list_view=1) and today's
Customer-ahead-of-JO-Date reorder has a `__UserSettings` row whose saved
column list still says Customer Name comes after JO Date, because that was
true when Frappe wrote it. Confirmed live -- the doctype's own field order is
correct (Customer, Customer Name, then JO Date), but the saved column list a
returning user's browser is handed overrides it. This is not a new class of
bug; it is the exact one reset_report_columns.py was written to fix, just
triggered by a reorder instead of an in_list_view change this time.

A brand new, never-yet-executed patch module IS something `bench migrate`
will run -- so rather than duplicate reset_report_columns's logic, this one
just calls it again.

Safe to re-run, for the same reasons the function it calls already is.
"""

import fps_erpnext.patches.v1_0.reset_report_columns as reset_report_columns


def execute():
	reset_report_columns.execute()
