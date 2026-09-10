"""One dated update on a Job Tracker.

Child table of Job Tracker. Before this existed, every update was its own Job
Tracker DOCUMENT, which is why 84 job orders had grown 371 trackers between them
-- one job had ten. The tracker is now one record per job, and the history it
used to scatter across sibling documents lives here.

No controller logic: the derivation engine (JT Rollup / FPS Tracker Sweep) reads
these rows, it does not need them to do anything on their own.
"""

from frappe.model.document import Document


class FPSJobUpdate(Document):
	pass
