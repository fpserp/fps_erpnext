"""FPS Feed Snapshot -- the stored FPS Live Feed (the /fps-feed page).

A Single. fps_erpnext.api.feed.build_snapshot writes it four times a day
(08:00, 12:00, 16:00, 20:00 Asia/Dubai, hooks.py scheduler_events) and the page
only reads it. Nothing else writes here; the form is read-only for System
Manager. The JSON contract is docs/live_feed/snapshot.schema.md.
"""

from frappe.model.document import Document


class FPSFeedSnapshot(Document):
	pass
