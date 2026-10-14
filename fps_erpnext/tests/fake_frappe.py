"""A minimal stand-in for the `frappe` module, for testing the two dashboard
API modules (command_center, acc_dashboard) without a bench.

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
APP_MODULES = ("command_center", "pipeline", "customs", "acc_dashboard")


class PermissionError(Exception):  # noqa: A001 -- mirrors frappe.PermissionError
	pass


class ValidationError(Exception):
	pass


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
	             readable=None, creatable=(), company="TEST COMPANY", accounts=None):
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

	# -- the module ----------------------------------------------------------

	def build(self):
		fake = self
		m = types.ModuleType("frappe")
		m.PermissionError = PermissionError
		m.ValidationError = ValidationError
		m._ = lambda text, *a, **k: text
		m.whitelist = lambda *a, **k: (lambda fn: fn)
		m.session = types.SimpleNamespace(user=self.user)
		m.local = types.SimpleNamespace(session=m.session)

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

		m.throw = throw
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
		)
		m.defaults = types.SimpleNamespace(
			get_user_default=lambda key, user=None: fake.company,
			get_global_default=lambda key: fake.company,
		)

		utils = types.ModuleType("frappe.utils")
		utils.today = lambda: fake.today
		utils.getdate = lambda d=None: date.fromisoformat(str(d or fake.today)[:10])
		utils.now_datetime = lambda: datetime.fromisoformat(fake.today + " 09:30:00")
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
