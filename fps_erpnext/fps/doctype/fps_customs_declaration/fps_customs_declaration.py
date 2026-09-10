"""One customs declaration (one BOE) inside a Customs Tracker.

Child table of Customs Tracker. Before this, a job that cleared on two BOEs --
an FZ transfer and then an import to local -- needed two whole Customs Tracker
documents, told apart only by a "Leg no." field. Four live jobs are in that
shape. The tracker is now the JOB, and each BOE is a row in it.

FIELDNAMES DELIBERATELY MATCH THE PARENT'S. The rollup engine has always
treated one row as one declaration, so pointing its query at this table instead
of at sibling trackers needs no change to the body that reads them -- c.status,
c.boe_number, c.fps_clearance_type and the rest all still resolve.

No controller logic: the parent rolls these up on save, and the derivation
engine reads them. Neither needs the row to do anything on its own.
"""

from frappe.model.document import Document


class FPSCustomsDeclaration(Document):
	pass
