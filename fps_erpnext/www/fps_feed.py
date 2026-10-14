"""/fps-feed -- the FPS Live Feed page (get_context for www/fps-feed.html).

Frappe v16 finds this module by the template's name with hyphens turned into
underscores (frappe/website/page_renderers/template_page.py, set_pymodule:
www/fps-feed.html -> fps_erpnext.www.fps_feed). The template is a complete HTML
document, so Frappe renders it without the website base template (no navbar,
no footer) -- see the note at the top of fps-feed.html.

    Guest                 -> feed.check_page_access() raises frappe.Redirect:
                             302 to /login?redirect-to=/fps-feed
    signed in, not in     -> "This feed is private." (HTTP 200); nothing is
    feed.FEED_USERS          read, not even the snapshot
    allowed               -> feed.get_feed_for_page(): the latest stored
                             snapshot ("ready"), or "building" while the first
                             one is prepared in the background

Everything the page shows comes from that dict (contract:
docs/live_feed/snapshot.schema.md). This module writes nothing.

no_cache: the page differs per viewer (NEW marks, "Open in ERPNext"), so it
must never enter Frappe's website page cache, which is keyed by path only
(frappe.website.utils.cache_html). Frappe copies the module attribute into the
context before get_context runs; get_context sets it again to be sure.

The CSS, JS and manifest are plain files under public/feed/, served from
/assets/fps_erpnext/feed/ with a one-year immutable cache. Their URLs carry
?v=<content hash> computed here once per process (deploys restart the
workers), so a changed file always gets a new URL -- nothing to bump by hand.
"""

import hashlib
import os

from fps_erpnext.api import feed

no_cache = 1
sitemap = 0

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "feed")
ASSET_FILES = ("fps-feed.css", "fps-feed.js", "manifest.webmanifest")
_versions = {}


def asset_version(name):
	"""First 10 hex of the file's SHA-1, memoised per process ("0" if missing)."""
	if name not in _versions:
		try:
			with open(os.path.join(ASSET_DIR, name), "rb") as fh:
				_versions[name] = hashlib.sha1(fh.read()).hexdigest()[:10]
		except OSError:
			_versions[name] = "0"
	return _versions[name]


def guard_toc_markers(feed_json):
	"""TemplatePage.update_toc replaces the literal text "{index}" and "{next}"
	anywhere in the rendered page. They can only occur inside a JSON string
	here (a structural brace is followed by a quote or a closing brace), so
	escaping the brace keeps the JSON identical once parsed."""
	if not feed_json:
		return feed_json
	return feed_json.replace("{index}", "\\u007bindex}").replace("{next}", "\\u007bnext}")


def get_context(context):
	context.no_cache = 1
	context.title = "FPS Live"
	# Guest: raises frappe.Redirect (302 to the login page); Frappe's website
	# renderer turns it into the redirect response.
	allowed = feed.check_page_access()
	if allowed:
		page = feed.get_feed_for_page()
		if page.get("feed_json"):
			page["feed_json"] = guard_toc_markers(page["feed_json"])
	else:
		page = {"state": "private"}
	context.feed = page
	context.feed_assets = {name: asset_version(name) for name in ASSET_FILES}
	return context
