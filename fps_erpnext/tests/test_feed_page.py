"""The FPS Live Feed PAGE (/fps-feed): www/fps-feed.html + www/fps_feed.py and
public/feed/ (CSS, JS, manifest) + the apple-touch-icon. Runs without a bench:

    python -m unittest fps_erpnext.tests.test_feed_page

What it pins down (docs/live_feed/SPEC.md section 1 and 3, snapshot.schema.md):
* Frappe v16 renders the template as a complete document, without the website
  base template: TemplatePage.set_properties_from_source only wraps a source
  that neither extends a template nor contains a closing body tag; and the
  page module is found as fps_feed.py (hyphens become underscores).
* get_context (with the stand-in frappe): Guest -> frappe.Redirect to the
  login page, a user outside FEED_USERS -> "private" with nothing read, an
  allowed user -> the snapshot, nothing stored -> one background build queued;
  never in Frappe's website page cache (no_cache).
* Rendering (when jinja2 is importable, configured like Frappe: sandboxed, no
  autoescape, DebugUndefined): no template syntax left, the data script only
  for allowed viewers, people's names escaped.
* Safety and "no external requests": no http(s) URL in any page file, no
  innerHTML / eval in the script, the script is ASCII.
* The palette tokens equal the dashboard's theme.css (Pearl and Matte Black);
  the script's slot rules equal feed_logic's; manifest and icon as specified.
"""

import json
import os
import re
import struct
import sys
import unittest

from fps_erpnext.api import feed_logic

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(APP)
WWW = os.path.join(APP, "www")
FEED = os.path.join(APP, "public", "feed")
TEMPLATE = os.path.join(WWW, "fps-feed.html")
CSS = os.path.join(FEED, "fps-feed.css")
JS = os.path.join(FEED, "fps-feed.js")
MANIFEST = os.path.join(FEED, "manifest.webmanifest")
ICON = os.path.join(APP, "public", "images", "fps-live-icon-180.png")
THEME = os.path.join(REPO, "dashboard", "src", "styles", "theme.css")


def read(path):
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def css_vars(block):
	"""{name: value} of the custom properties declared in a CSS block."""
	out = {}
	for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block):
		out[name] = re.sub(r"\s+", "", value.strip().lower()).replace("0.10)", "0.1)")
	return out


def block_after(text, selector):
	"""The body of the first `selector { ... }` block (no nesting inside)."""
	start = text.index(selector)
	open_ = text.index("{", start)
	return text[open_ + 1:text.index("}", open_)]


# feed token -> dashboard token (DESIGN.md / dashboard/src/styles/theme.css)
TOKEN_MAP = {
	"bg": "fps-bg", "surface-1": "fps-surface-1", "surface-2": "fps-surface-2",
	"surface-solid": "fps-surface-solid", "inset": "fps-surface-inset", "border": "fps-border",
	"border-strong": "fps-border-strong", "highlight": "fps-highlight", "backdrop": "fps-backdrop",
	"electric": "fps-electric", "electric-ui": "fps-electric-ui", "mint": "fps-mint",
	"violet": "fps-violet", "rose": "fps-rose", "amber": "fps-amber", "text": "fps-text",
	"text-2": "fps-text-secondary", "text-3": "fps-text-muted", "grid": "fps-grid",
}


class TestTemplateShape(unittest.TestCase):
	def test_frappe_renders_it_standalone(self):
		source = read(TEMPLATE)
		self.assertTrue(source.lower().startswith("<!doctype html>"))
		# frappe/website/page_renderers/template_page.py, set_properties_from_source:
		# the base template wraps the source only when ALL three are absent.
		self.assertIn("</body>", source)
		self.assertNotIn("{% extends", source)
		self.assertNotIn("{%- extends", source)
		self.assertIn("</html>", source)
		# render_template's safe_render refuses ".__" in a template string
		self.assertNotIn(".__", source)

	def test_page_module_follows_frappes_name_rule(self):
		# TemplatePage.set_pymodule: basename with "-" -> "_" + ".py", same folder
		self.assertTrue(os.path.isfile(os.path.join(WWW, "fps-feed.py".replace("-", "_"))))
		self.assertFalse(os.path.exists(os.path.join(WWW, "fps-feed.py")))
		self.assertTrue(os.path.isfile(os.path.join(WWW, "__init__.py")))

	def test_head_has_the_home_screen_app_tags(self):
		source = read(TEMPLATE)
		for needle in ('name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"',
		               'rel="manifest" href="/assets/fps_erpnext/feed/manifest.webmanifest?v=',
		               'name="apple-mobile-web-app-capable" content="yes"',
		               'name="apple-mobile-web-app-status-bar-style"',
		               'name="apple-mobile-web-app-title" content="FPS Live"',
		               'rel="apple-touch-icon" sizes="180x180" href="/assets/fps_erpnext/images/fps-live-icon-180.png"',
		               '/assets/fps_erpnext/images/fps-logo-v2.svg',
		               'name="robots" content="noindex, nofollow"',
		               'media="(prefers-color-scheme: dark)"'):
			self.assertIn(needle, source)

	def test_data_is_embedded_raw_once(self):
		source = read(TEMPLATE)
		# feed_json is already script-safe (feed_logic.script_json); never re-encoded
		self.assertIn('<script type="application/json" id="fps-feed-data">{{ feed.get("feed_json") or "{}" }}</script>',
		              source)
		self.assertNotIn("tojson", source)
		# every other expression is escaped (Frappe's jinja does not autoescape)
		for expr in re.findall(r"\{\{(.*?)\}\}", source):
			if "feed_json" in expr:
				continue
			self.assertIn("| e", expr, expr)


class TestNoExternalRequestsAndSafeDom(unittest.TestCase):
	def test_no_external_urls(self):
		for path in (TEMPLATE, CSS, JS, MANIFEST):
			text = read(path).replace("http://www.w3.org/2000/svg", "")
			self.assertIsNone(re.search(r"https?://|//[a-z0-9.-]+\.[a-z]{2,}/", text, re.I), path)
			self.assertNotIn("@import", text, path)

	def test_script_never_parses_html(self):
		js = read(JS)
		for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
		               "new Function"):
			self.assertNotIn(banned, js)
		# links only from desk paths, opened outside the feed
		self.assertIn(r"/^\/(app|desk)(\/|\?|$)/", js)
		self.assertIn('"noopener"', js)

	def test_script_is_ascii(self):
		with open(JS, "rb") as fh:
			fh.read().decode("ascii")

	def test_storage_is_wrapped(self):
		js = read(JS)
		self.assertEqual(js.count("localStorage."), 2)
		for m in re.finditer(r"localStorage\.", js):
			before = js[max(0, m.start() - 80):m.start()]
			self.assertIn("try {", before)


class TestStyles(unittest.TestCase):
	def test_tokens_equal_the_dashboard_palettes(self):
		theme = read(THEME)
		pearl = css_vars(block_after(theme, ".fps-cc {"))
		black = css_vars(block_after(theme, '.fps-cc[data-palette="black"] {'))
		css = read(CSS)
		light = css_vars(block_after(css, ":root {"))
		dark_start = css.index("@media (prefers-color-scheme: dark)")
		dark = css_vars(block_after(css[dark_start:], ":root {"))
		for ours, theirs in TOKEN_MAP.items():
			self.assertEqual(light[ours], pearl[theirs], "Pearl " + ours)
			self.assertEqual(dark[ours], black[theirs], "Matte Black " + ours)

	def test_motion_safe_areas_and_fallbacks(self):
		css = read(CSS)
		for needle in ("@media (prefers-reduced-motion: reduce)", "@media (prefers-reduced-transparency: reduce)",
		               "@media (forced-colors: active)", "env(safe-area-inset-top", "env(safe-area-inset-bottom",
		               "env(safe-area-inset-left", "env(safe-area-inset-right",
		               "-webkit-backdrop-filter", "@supports not"):
			self.assertIn(needle, css)
		reduced = css[css.index("@media (prefers-reduced-motion: reduce)"):]
		for selector in (".live-dot::after", ".animate .item", ".sheet"):
			self.assertIn(selector, reduced)

	def test_tap_targets_are_44px(self):
		css = read(CSS)
		# The 32px pill and tabs keep their look; their ::after reaches 44px.
		hit = block_after(css, ".live::after,\n.tab::after {")
		self.assertIn("inset: -7px -5px;", hit)
		for selector in (".live {", ".tab {"):
			self.assertIn("position: relative;", block_after(css, selector), selector)
			self.assertIn("height: 32px;", block_after(css, selector), selector)
		icon_btn = block_after(css, ".icon-btn {")
		self.assertIn("width: 44px;", icon_btn)
		self.assertIn("height: 44px;", icon_btn)

	def test_cards_use_tokens_and_the_full_width_title(self):
		css = read(CSS)
		# NEW is a glow token, never a hard-coded coloured border (DESIGN.md sections 2 and 10).
		new = block_after(css, ".item.is-new {")
		self.assertIn("var(--new-glow)", new)
		self.assertNotIn("border", new)
		item = block_after(css, ".item {")
		self.assertIn("grid-template-columns: 40px minmax(0, 1fr);", item)   # no amount column
		self.assertIn("padding: 16px;", item)
		self.assertIn("-webkit-line-clamp: 3;", block_after(css, ".item-title {"))
		self.assertNotIn(".item-aside", css)
		# Colours outside the token blocks: none.
		body = css[css.index("/* ---------------------------------------------------------------- base */"):]
		self.assertIsNone(re.search(r"#[0-9a-f]{3,6}\b|rgba?\(", body, re.I))


class TestScriptMirrorsFeedLogic(unittest.TestCase):
	def test_slot_rules(self):
		js = read(JS)
		hours = re.search(r"var SLOT_HOURS = \[([^\]]+)\]", js).group(1)
		self.assertEqual(tuple(int(h) for h in hours.split(",")), feed_logic.SLOT_HOURS)
		self.assertIn("var SLOT_GRACE = %d * 60000" % feed_logic.SLOT_GRACE_MINUTES, js)
		self.assertIn("var LATE_GRACE = %d * 60000" % feed_logic.LATE_GRACE_MINUTES, js)
		self.assertIn('"fps_erpnext.api.feed.get_feed_meta"', js)


class TestManifestAndIcon(unittest.TestCase):
	def test_manifest(self):
		m = json.loads(read(MANIFEST))
		self.assertEqual((m["name"], m["short_name"], m["start_url"], m["display"]),
		                 ("FPS Live", "FPS Live", "/fps-feed", "standalone"))
		self.assertEqual(m["background_color"].lower(), "#d9dee7")      # Pearl plane
		self.assertEqual(m["theme_color"].lower(), "#d9dee7")
		for icon in m["icons"]:
			path = os.path.join(APP, "public", icon["src"].replace("/assets/fps_erpnext/", ""))
			self.assertTrue(os.path.isfile(path), icon["src"])
			w, h, _ = png_header(path)
			self.assertEqual("%dx%d" % (w, h), icon["sizes"])

	def test_apple_touch_icon_is_an_opaque_180_png(self):
		w, h, color_type = png_header(ICON)
		self.assertEqual((w, h), (180, 180))
		self.assertEqual(color_type, 2)      # RGB, no alpha: iOS paints transparency black

	def test_maskable_icon_is_opaque_and_declared(self):
		m = json.loads(read(MANIFEST))
		maskable = [i for i in m["icons"] if i.get("purpose") == "maskable"]
		self.assertEqual([i["sizes"] for i in maskable], ["512x512"])
		path = os.path.join(APP, "public", maskable[0]["src"].replace("/assets/fps_erpnext/", ""))
		self.assertEqual(png_header(path), (512, 512, 2))      # RGB on the white tile, no alpha


def png_header(path):
	with open(path, "rb") as fh:
		head = fh.read(33)
	assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", path
	width, height, _depth, color_type = struct.unpack(">IIBB", head[16:26])
	return width, height, color_type


# --------------------------------------------------------------------------
# get_context with the stand-in frappe
# --------------------------------------------------------------------------

class TestGetContext(unittest.TestCase):
	def setUp(self):
		from fps_erpnext.tests import fake_frappe
		if fake_frappe.REAL_FRAPPE:
			self.skipTest("a real frappe is importable; covered by the bench test run")
		self.ff = fake_frappe

	def stored(self):
		from fps_erpnext.tests import test_feed_logic as tfl
		snap = tfl.build_sample_snapshot()
		return {"generated_at": snap["generated_at"], "slot": snap["slot"],
		        "snapshot": feed_logic.dumps(snap), "previous": feed_logic.dumps(tfl.sample_previous(snap))}

	def context_for(self, user, stored=None, now="2026-10-14 12:37:05"):
		import importlib
		singles = {"FPS Feed Snapshot": stored} if stored else {}
		fake = self.ff.FakeFrappe(user=user, now=now, today=now[:10], singles=singles)
		with fake.installed():
			sys.modules.pop("fps_erpnext.www.fps_feed", None)
			try:
				page = importlib.import_module("fps_erpnext.www.fps_feed")
				context = self.ff.Row(no_cache=page.no_cache, sitemap=page.sitemap)
				try:
					page.get_context(context)
					error = None
				except self.ff.Redirect:
					error = sys.modules["frappe"].local.flags.redirect_location
			finally:
				sys.modules.pop("fps_erpnext.www.fps_feed", None)
		return context, error, fake.calls

	def test_guest_goes_to_login(self):
		context, error, calls = self.context_for("Guest", self.stored())
		self.assertEqual(error, "/login?redirect-to=/fps-feed")
		self.assertNotIn("feed", context)
		self.assertEqual(calls, [])

	def test_others_get_the_private_page_and_nothing_is_read(self):
		context, error, calls = self.context_for("ops@fastplanet.ae", self.stored())
		self.assertIsNone(error)
		self.assertEqual(context["feed"], {"state": "private"})
		self.assertEqual(calls, [])
		self.assertEqual(context["no_cache"], 1)

	def test_allowed_viewer_gets_the_snapshot(self):
		context, error, calls = self.context_for("hello@fastplanet.ae", self.stored())
		self.assertIsNone(error)
		feed = context["feed"]
		self.assertEqual(feed["state"], "ready")
		self.assertEqual(context["no_cache"], 1)
		data = json.loads(feed["feed_json"])
		self.assertEqual(data["snapshot"]["generated_at"], "2026-10-14 12:00:05")
		self.assertEqual(data["meta"]["updated_label"], "12:00")
		for name in ("fps-feed.css", "fps-feed.js", "manifest.webmanifest"):
			self.assertRegex(context["feed_assets"][name], r"^[0-9a-f]{10}$")
		self.assertFalse([c for c in calls if c[0] == "enqueue"])

	def test_nothing_stored_queues_one_build(self):
		context, error, calls = self.context_for("agam@fastplanet.ae", None)
		self.assertEqual(context["feed"]["state"], "building")
		self.assertIn(("enqueue", "fps_erpnext.api.feed.build_snapshot", "fps_feed_first_snapshot"), calls)

	def test_module_attributes(self):
		import importlib
		fake = self.ff.FakeFrappe(user="Guest")
		with fake.installed():
			sys.modules.pop("fps_erpnext.www.fps_feed", None)
			try:
				page = importlib.import_module("fps_erpnext.www.fps_feed")
				self.assertEqual((page.no_cache, page.sitemap), (1, 0))
				guarded = page.guard_toc_markers(feed_logic.script_json({"t": "a {index} b {next} c"}))
				self.assertNotIn("{index}", guarded)
				self.assertNotIn("{next}", guarded)
				self.assertEqual(json.loads(guarded), {"t": "a {index} b {next} c"})
			finally:
				sys.modules.pop("fps_erpnext.www.fps_feed", None)


# --------------------------------------------------------------------------
# Rendering (jinja2 configured like Frappe v16) -- skipped when jinja2 is absent
# --------------------------------------------------------------------------

try:
	import jinja2
	from jinja2.sandbox import SandboxedEnvironment
except ImportError:  # pragma: no cover - plain python without jinja2
	jinja2 = None


@unittest.skipIf(jinja2 is None, "jinja2 is not installed")
class TestRender(unittest.TestCase):
	def render(self, feed, fullname="Agam <Rana>"):
		env = SandboxedEnvironment(loader=jinja2.FileSystemLoader(WWW), undefined=jinja2.DebugUndefined)
		ctx = {"feed": feed, "feed_assets": {"fps-feed.css": "a" * 10, "fps-feed.js": "b" * 10,
		                                "manifest.webmanifest": "c" * 10},
		       "fullname": fullname, "user": "x@example.com"}
		return env.get_template("fps-feed.html").render(ctx)

	def page(self, state):
		meta = feed_logic.feed_meta("2026-10-14 12:00:05", "2026-10-14 12:37:05")
		snap = {"version": 1, "sections": [], "generated_at": "2026-10-14 12:00:05"} if state == "ready" else None
		return {"state": state, "user": {"name": "a@b.c", "full_name": 'Agam "<b>"'}, "meta": meta,
		        "snapshot": snap, "feed_json": feed_logic.script_json({"meta": meta, "snapshot": snap}),
		        "poll": {"meta_method": "fps_erpnext.api.feed.get_feed_meta", "check_every_seconds": 600,
		                 "building_every_seconds": 10}}

	def test_states(self):
		for state in ("ready", "building"):
			html = self.render(self.page(state))
			self.assertNotIn("{{", html)
			self.assertNotIn("{%", html)
			self.assertIn('id="fps-feed-data"', html)
			self.assertIn('data-state="%s"' % state, html)
			self.assertIn('data-viewer="Agam &#34;&lt;b&gt;&#34;"', html)
			self.assertNotIn("<b>", html)
		ready = self.render(self.page("ready"))
		self.assertIn("Updated 12:00 · next 16:00", ready)
		self.assertIn('id="sheet-root"', ready)
		private = self.render({"state": "private"})
		self.assertIn("This feed is private.", private)
		self.assertIn("You are signed in as Agam &lt;Rana&gt;.", private)
		self.assertNotIn("fps-feed-data", private)
		self.assertNotIn("<script", private)


if __name__ == "__main__":
	unittest.main()
