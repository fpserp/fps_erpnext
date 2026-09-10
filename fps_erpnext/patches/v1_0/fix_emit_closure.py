"""Stop emit() depending on a closure that DocType Event scripts do not have.

THE ERROR, from the live log:

    File "<serverscript>: ct_boe_to_job_order", line 47, in emit
        code = None
        ref = 'CT:FPS/CT/2607/039:new'
    builtins.NameError: name 'jo' is not defined

  ...while the frame directly above it shows `jo = 'FPS/JO/2607/039'`. The name
  is plainly set, one scope up, and emit still cannot see it.

WHY. For a DocType Event script Frappe calls safe_exec with a separate _locals
dict -- that is how `doc` gets injected -- so the script runs under
exec(code, exec_globals, _locals) with globals and locals as DIFFERENT
dictionaries. A module-level assignment such as `jo = doc.job_order` is stored
in _locals, but a nested `def` resolves its free variables through __globals__,
which never sees _locals. Every free variable in a nested function is therefore
invisible, no matter that the line above it just assigned one.

This does NOT happen in an API-type server script, which gets no _locals, so
globals IS locals and free variables resolve normally. A probe written as an API
script does not reproduce it -- I wrote one, it passed, and it was misleading.
The distinction is the whole bug.

NOT INTRODUCED BY THE RECENT REWRITES. The original emit() bodies referenced
`jo` in exactly the same way, and the Error Log holds 20 of these going back to
the 2026-09-09 go-live. It also explains something that had been noticed and
mis-read earlier: all 371 Job Tracker rows carried fps_source "Backfill" and not
one said "System". That was taken as "no new job orders since go-live". The real
reason is that no emitter has ever succeeded -- each one raised this NameError
and its own `except Exception: frappe.log_error(...)` swallowed it.

THE FIX is to capture the two names as DEFAULT ARGUMENTS:

    def emit(code, ref, text, visible=1, etype="System", jo=jo, doc=doc):

A default argument is evaluated where the `def` statement runs -- module scope,
where both names exist -- and becomes an ordinary parameter inside the function.
Nothing is looked up through globals at call time, so the split cannot bite.
Callers are unaffected: every existing emit(...) call passes positionally and
never reaches these two.

Applied to the live site the moment it was diagnosed; this patch is here so any
other copy of the site gets it too.

Safe to re-run: a signature that already captures them is skipped.
"""

import re

import frappe

# Every DocType Event script with a nested emit() over module-level names.
SCRIPTS = (
	"CT BOE to Job Order",
	"POD Events (Save)",
	"POD Events (Submit)",
	"POD Events (Cancel)",
	"SI Events (Submit)",
	"SI Events (Cancel)",
)

SIGNATURE = re.compile(r"def emit\(([^)]*)\):")
CAPTURE = ", jo=jo, doc=doc"


def execute():
	fixed = 0
	for name in SCRIPTS:
		if not frappe.db.exists("Server Script", name):
			frappe.log_error(title="FPS: Server Script %s missing, emit not fixed" % name)
			continue

		script = frappe.db.get_value("Server Script", name, "script") or ""
		match = SIGNATURE.search(script)
		if not match:
			frappe.log_error(title="FPS: no emit() in %s, not fixed" % name)
			continue

		params = match.group(1)
		if "jo=jo" in params:
			continue

		patched = (script[:match.start()]
		           + "def emit(%s%s):" % (params, CAPTURE)
		           + script[match.end():])

		# Never write something that would not compile. A server script that
		# fails to parse takes out every save on its doctype.
		try:
			compile(patched, "<%s>" % name, "exec")
		except SyntaxError:
			frappe.log_error(title="FPS: emit fix would break %s, skipped" % name)
			continue

		frappe.db.set_value("Server Script", name, "script", patched,
		                    update_modified=False)
		fixed += 1

	if fixed:
		frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info("FPS: captured jo/doc in emit() on %d server scripts" % fixed)
