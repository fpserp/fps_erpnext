"""One vehicle row inside a Proof of Delivery, for a delivery that genuinely
used more than one vehicle at once.

Child table of Proof of Delivery. Additive, not a replacement (2026-09-12):
the existing single vehicle_no / fps_vehicle_type fields, and the older
one-POD-per-leg pattern (fps_leg / fps_final_delivery, "Untick on interim
trucks of a multi-trailer job") both stay exactly as they are and are
untouched by this table -- that pattern is for a job that needs a full,
separate delivery record per truck (different dates, different receivers).
This table is for the simpler case: one delivery event, several vehicles,
recorded together on the one POD.

No controller logic: nothing derives from these rows today, so there is
nothing for the row to do on its own.
"""

from frappe.model.document import Document


class FPSPODVehicle(Document):
	pass
