"""Give NEW customers an FPS/##### id instead of naming them after the company.

ERPNext decides this in Customer.autoname(), which reads a single global:

    cust_master_name = frappe.defaults.get_global_default("cust_master_name")
    if cust_master_name == "Customer Name":
        self.name = self.get_customer_name()
    else:
        self.name = set_name_by_naming_series(self)

So the series on the Customer field does nothing on its own -- this patch flips
Selling Settings.cust_master_name to "Naming Series". The FPS/.##### option and
its default ship alongside as Property Setters.

READ THIS BEFORE ASSUMING IT DID MORE THAN IT DID.

The 110 customers already on this site KEEP their present ids -- "THE GREEN TEAM
RECYCLING", "PREMIER MARINE ENGINEERING SERVICES LLC" and the rest. Only
customers created from now on get FPS/00001. The customer list is therefore
permanently mixed, and so is the raw `customer` value stored on 630 sales
invoices, 85 job orders and every quotation.

That is mostly invisible day to day, because Customer.title_field is
customer_name: link fields, list views and reports show the company name either
way. Where it WILL show is anywhere the raw id is printed or grouped -- an
export, a pivot on the customer column, a hand-written SQL report.

RENAMING THE EXISTING 110 WAS NOT DONE, DELIBERATELY. It would rewrite the
customer field on every invoice, job order, quotation, payment entry and address
on the site to reach a cosmetic consistency, and it is not reversible in one
step. If it is genuinely wanted it should be a decision of its own, not a side
effect of switching the series on.

TO REVERSE: set Selling Settings.cust_master_name back to "Customer Name". Any
FPS/##### customers created in the meantime keep those ids; nothing else changes.

Safe to re-run.
"""

import frappe

SETTING = "cust_master_name"
WANTED = "Naming Series"


def execute():
	if not frappe.db.exists("DocType", "Selling Settings"):
		return

	current = frappe.db.get_single_value("Selling Settings", SETTING)
	if current == WANTED:
		return

	frappe.db.set_single_value("Selling Settings", SETTING, WANTED)

	# cust_master_name is read through frappe.defaults.get_global_default, which
	# is served from the defaults cache rather than straight off the Singles
	# table -- without clearing it the running workers keep naming customers the
	# old way until something else happens to flush them.
	frappe.clear_cache()

	frappe.logger().info(
		"FPS: Customer naming switched from %r to %r" % (current, WANTED)
	)
