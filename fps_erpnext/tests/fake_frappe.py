"""A minimal stand-in for the `frappe` module, for testing the two dashboard
API modules (command_center, acc_dashboard) and the FPS Live Feed (feed)
without a bench.

Only what those modules (and pipeline / customs, which command_center imports)
touch is provided. Every read is recorded in `calls`, so a test can assert what
was -- and was not -- read: the role gate must run before anything, and the OPS
page must never read Sales Invoice or Payment Entry.

    fake = FakeFrappe(user="ops@example.com", roles=["FPS Operations"], rows={...})
    with fake.installed() as modules:
        command_center = modules["command_center"]
        ...

installed() refuses to run when a real frappe is importable (a bench test
run): the tests that use it skip themselves then (see REAL_FRAPPE).
"""

import contextlib
import importlib
import importlib.util
import sys
import types
from datetime import date, datetime

REAL_FRAPPE = importlib.util.find_spec("frappe") is not None

# The app modules that import frappe, purged before and after each use so a
# fake-backed copy never outlives the test.
APP_MODULES = ("command_center", "pipeline", "customs", "acc_dashboard", "feed")


class PermissionError(Exception):  # noqa: A001 -- mirrors frappe.PermissionError
	pass


class ValidationError(Exception):
	pass


class Redirect(Exception):
	"""frappe.Redirect: a www page raises it after setting local.flags.redirect_location."""


class Row(dict):
	"""frappe._dict: attribute access as well as .get()."""

	def __getattr__(self, name):
		return self.get(name)

	def __setattr__(self, name, value):
		self[name] = value


class FakeCache:
	def __init__(self, calls):
		self.store = {}
		self.calls = calls

	def get_value(self, key, user=None, expires=False, **kw):
		self.calls.append(("cache_get", key, user))
		return self.store.get((user, key))

	def set_value(self, key, value, user=None, expires_in_sec=None, **kw):
		self.calls.append(("cache_set", key, user))
		self.store[(user, key)] = value


class FakeFrappe:
	def __init__(self, *, user="Administrator", roles=(), rows=None, today="2026-10-14",
	             readable=None, creatable=(), company="TEST COMPANY", accounts=None,
	             now=None, singles=None, denied_docs=(), in_job=False, in_request=False, reports=None):
		self.user = user
		self.roles = list(roles)
		self.rows = rows or {}
		self.today = today
		# None: every doctype readable; else the set of readable doctypes.
		self.readable = None if readable is None else set(readable)
		self.creatable = set(creatable)
		self.company = company
		# {account_name: account name} for frappe.db.get_value("Account", ...).
		self.accounts = accounts or {}
		self.calls = []
		self.cache = FakeCache(self.calls)
		# now_datetime(); default: today at 09:30.
		self.now = now or (today + " 09:30:00")
		# {doctype: {field: value}} for the Single read / write helpers.
		self.singles = {k: dict(v) for k, v in (singles or {}).items()}
		# (doctype, name) pairs has_permission(doc=name) refuses.
		self.denied_docs = set(denied_docs)
		# frappe.local.job / frappe.local.request, for code that asks where it runs.
		self.in_job = in_job
		self.in_request = in_request
		# {report name: {"ref_doctype", "roles": [...], "disabled"}} for
		# frappe.get_doc("Report", name); None: every report exists, has no
		# roles of its own and refers to GL Entry.
		self.reports = reports

	# -- the module ----------------------------------------------------------

	def build(self):
		fake = self
		m = types.ModuleType("frappe")
		m.PermissionError = PermissionError
		m.ValidationError = ValidationError
		m.Redirect = Redirect
		m._ = lambda text, *a, **k: text
		m.whitelist = lambda *a, **k: (lambda fn: fn)
		m.session = types.SimpleNamespace(user=self.user)
		m.local = types.SimpleNamespace(session=m.session, flags=types.SimpleNamespace())
		if self.in_job:
			m.local.job = {"method": "test"}
		if self.in_request:
			m.local.request = object()

		def throw(msg, exc=ValidationError, *a, **k):
			raise exc(msg)

		def only_for(roles, message=False):
			fake.calls.append(("only_for", roles))
			if m.session.user == "Administrator":
				return
			if isinstance(roles, str):
				roles = (roles,)
			if set(roles).isdisjoint(fake.roles):
				raise PermissionError("only for %s" % ", ".join(roles))

		def has_permission(doctype, ptype="read", *a, **k):
			fake.calls.append(("has_permission", doctype, ptype))
			if ptype == "create":
				return doctype in fake.creatable
			doc = k.get("doc") if "doc" in k else (a[0] if a else None)
			if doc and (doctype, doc) in fake.denied_docs:
				return False
			return fake.readable is None or doctype in fake.readable

		def get_list(doctype, fields=None, filters=None, or_filters=None, order_by=None,
		             limit_page_length=None, **kw):
			fake.calls.append(("get_list", doctype))
			return [Row(r) for r in fake.rows.get(doctype, [])]

		def get_all(doctype, fields=None, filters=None, order_by=None, **kw):
			fake.calls.append(("get_all", doctype))
			return [Row(r) for r in fake.rows.get(doctype, [])]

		class Meta:
			def get_permlevel_access(self, ptype="read"):
				return [0, 1]

		def get_value(doctype, filters=None, fieldname=None, *a, **k):
			fake.calls.append(("get_value", doctype))
			if doctype == "Account" and isinstance(filters, dict):
				return fake.accounts.get(filters.get("account_name"))
			if doctype == "Company":
				return fake.company
			return None

		def set_user(user):
			fake.calls.append(("set_user", user))
			m.session.user = user

		def enqueue(method, **kw):
			fake.calls.append(("enqueue", method, kw.get("job_id")))

		def log_error(*a, **k):
			fake.calls.append(("log_error", k.get("title") or (a[0] if a else None)))
			if k.get("defer_insert"):
				fake.calls.append(("log_error_deferred", k.get("title") or (a[0] if a else None)))

		class FakeReport(Row):
			def is_permitted(self):
				roles = self.get("roles") or []
				return not roles or not set(roles).isdisjoint(fake.roles)

		def get_doc(doctype, name=None, *a, **k):
			fake.calls.append(("get_doc", doctype, name))
			if doctype != "Report":
				raise NotImplementedError(doctype)
			if fake.reports is None:
				return FakeReport(name=name, ref_doctype="GL Entry", roles=[], disabled=0)
			if name not in fake.reports:
				raise ValidationError("Report %s not found" % name)
			return FakeReport(dict(fake.reports[name], name=name))

		def get_singles_dict(doctype, *a, **k):
			fake.calls.append(("get_singles_dict", doctype))
			return Row(fake.singles.get(doctype) or {})

		def set_single_value(doctype, fieldname, value=None, *a, **k):
			fake.calls.append(("set_single_value", doctype))
			values = fieldname if isinstance(fieldname, dict) else {fieldname: value}
			fake.singles.setdefault(doctype, {}).update(values)

		m.throw = throw
		m.set_user = set_user
		m.enqueue = enqueue
		m.log_error = log_error
		m.get_doc = get_doc
		m.only_for = only_for
		m.has_permission = has_permission
		m.get_list = get_list
		m.get_all = get_all
		m.get_meta = lambda doctype: Meta()
		m.get_roles = lambda user=None: list(fake.roles)
		m.cache = lambda: fake.cache
		m.db = types.SimpleNamespace(
			get_value=get_value,
			count=lambda doctype, filters=None: fake.calls.append(("count", doctype)) or 3,
			get_singles_dict=get_singles_dict,
			set_single_value=set_single_value,
		)
		m.defaults = types.SimpleNamespace(
			get_user_default=lambda key, user=None: fake.company,
			get_global_default=lambda key: fake.company,
		)

		utils = types.ModuleType("frappe.utils")
		utils.today = lambda: fake.today
		utils.getdate = lambda d=None: date.fromisoformat(str(d or fake.today)[:10])
		utils.now_datetime = lambda: datetime.fromisoformat(fake.now)
		utils.get_fullname = lambda user=None: "Test User"
		utils.cint = lambda v: int(v or 0)
		utils.formatdate = lambda d, fmt=None: str(d)
		m.utils = utils
		return {"frappe": m, "frappe.utils": utils}

	# -- install / remove ----------------------------------------------------

	@contextlib.contextmanager
	def installed(self):
		if REAL_FRAPPE:
			raise RuntimeError("a real frappe is importable; use the bench test runner")
		package = importlib.import_module("fps_erpnext.api")
		names = ["frappe", "frappe.utils"] + ["fps_erpnext.api." + n for n in APP_MODULES]
		saved = {n: sys.modules.get(n) for n in names}
		saved_attrs = {n: getattr(package, n, None) for n in APP_MODULES}

		def purge():
			for n in APP_MODULES:
				sys.modules.pop("fps_erpnext.api." + n, None)
				if hasattr(package, n):
					delattr(package, n)

		purge()
		sys.modules.update(self.build())
		try:
			yield {n: importlib.import_module("fps_erpnext.api." + n) for n in APP_MODULES}
		finally:
			purge()
			for n, module in saved.items():
				if module is None:
					sys.modules.pop(n, None)
				else:
					sys.modules[n] = module
			for n, attr in saved_attrs.items():
				if attr is not None:
					setattr(package, n, attr)

	# -- assertions helpers --------------------------------------------------

	def read_doctypes(self):
		"""Doctypes read through get_list / get_all, in order."""
		return [c[1] for c in self.calls if c[0] in ("get_list", "get_all")]
