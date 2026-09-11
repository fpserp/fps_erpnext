app_name = "fps_erpnext"
app_title = "FPS"
app_publisher = "Fast Planet Shipping LLC"
app_description = "Custom ERPNext app for Fast Planet Shipping LLC - freight forwarding operations"
app_email = "hello@fastplanet.ae"
app_license = "mit"
# Versioned filename on purpose. Frappe serves /assets with
# "cache-control: max-age=31536000, immutable", so replacing a logo in place is
# invisible to anyone who has already loaded the old one -- the browser never
# re-requests it. Bump the -vN suffix whenever the mark changes.
app_logo_url = "/assets/fps_erpnext/images/fps-logo-v2.svg"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
    {
        "name": "fps_erpnext",
        "logo": "/assets/fps_erpnext/images/fps-logo-v2.svg",
        "title": "FPS",
        "route": "/app/fps",
        "has_permission": "fps_erpnext.api.permission.has_app_permission"
    }
]

# Fixtures
# --------
# Number Card, Dashboard Chart and Custom HTML Block are not in Frappe v16's
# IMPORTABLE_DOCTYPES, so unlike the workspaces under fps_erpnext/fps/ they
# cannot ship as module JSON. sync_fixtures imports fps_erpnext/fixtures/*.json
# on every migrate. The filters below scope any future `bench export-fixtures`
# to FPS-owned records so it cannot slurp the site's ~97 stock number cards.

fixtures = [
    {"dt": "Number Card", "filters": [["module", "=", "FPS"]]},
    {"dt": "Dashboard Chart", "filters": [["module", "=", "FPS"]]},
    {"dt": "Custom HTML Block", "filters": [["name", "in", [
        "FPS Overview", "FPS Job Tracker", "FPS Customs Tracker"]]]},
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
#
# fps_list_chrome.css removes the fixed strip on the right of every LIST row --
# the "1 M" modified stamp, the comment count and the like hearts -- while
# keeping the "629 of 629" record count. Plain CSS under public/, so it is
# symlinked to /assets/fps_erpnext/ and needs no bundle entry.
app_include_css = "/assets/fps_erpnext/css/fps_list_chrome.css"
# app_include_js = "/assets/fps_erpnext/js/fps_erpnext.js"

# include js, css files in header of web template
# web_include_css = "/assets/fps_erpnext/css/fps_erpnext.css"
# web_include_js = "/assets/fps_erpnext/js/fps_erpnext.js"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#     "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "fps_erpnext.install.before_install"
# after_install = "fps_erpnext.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "fps_erpnext.uninstall.before_uninstall"
# after_uninstall = "fps_erpnext.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "fps_erpnext.utils.before_app_install"
# after_app_install = "fps_erpnext.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "fps_erpnext.utils.before_app_uninstall"
# after_app_uninstall = "fps_erpnext.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "fps_erpnext.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#     "Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#     "Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#     "ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
#     "*": {
#         "on_update": "method",
#         "on_cancel": "method",
#         "on_trash": "method"
#     }
# }

# Document Events
# ---------------
# Numbering is an autoname hook rather than something the creating code does, so
# every route in gets the same names -- the auto Customs Tracker below and a
# user clicking New both land on FPS/CT/<job order tail>. Frappe runs doc_events
# for "autoname" before it falls back to the naming series.
#
# Job Order's own update log (fps_updates, a Table of FPS Job Update rows) is
# what used to be a separate "Job Tracker" document per job -- see
# fps_erpnext/api/jobs.py for the full history and why the trigger below is the
# CHILD table's own after_insert rather than anything on Job Order itself: Job
# Order already has a Before Save script that reverts fps_stage changes it did
# not expect, which would fight a rollup that tried to run as part of a Job
# Order save.

doc_events = {
    "Job Order": {
        "after_insert": "fps_erpnext.api.trackers.on_job_order_created",
    },
    "Job Tracker": {
        "autoname": "fps_erpnext.api.trackers.name_from_job_order",
    },
    "Customs Tracker": {
        "autoname": "fps_erpnext.api.trackers.name_from_job_order",
        # Derives the document-submission and MOFA deadlines from the clearance
        # date on every save, so the two dates can never drift out of step with
        # the date they are calculated from. See fps_erpnext/api/customs.py for
        # the windows and the colour thresholds.
        "validate": "fps_erpnext.api.customs.set_deadlines",
    },
    "FPS Job Update": {
        # Proved live before this was written: a standalone child-doctype
        # insert (parenttype="Job Order", not appended via parent.append())
        # fires this independently of any parent save. See
        # fps_erpnext/api/jobs.py::on_update_inserted for what it does and
        # frappe.flags.fps_skip_rollup for how the one-time historical copy
        # (migrate_updates_to_job_order) avoids running it 383 times.
        "after_insert": "fps_erpnext.api.jobs.on_update_inserted",
    },
}

# Scheduled Tasks
# ---------------
# Same cadence as the retired "FPS Tracker Sweep" Server Script it replaces --
# recomputes every open job's stage/progress/next-action from its documents and
# update log, as the safety net for anything the after_insert path above did
# not catch (a row removed from the grid, an edit made some other way).
scheduler_events = {
    "cron": {
        "*/30 * * * *": ["fps_erpnext.api.jobs.sweep"],
    },
}

# Testing
# -------

# before_tests = "fps_erpnext.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#     "frappe.desk.doctype.event.event.get_events": "fps_erpnext.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#     "Task": "fps_erpnext.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = ["fps_erpnext.api.pdf_watermark.install_watermark_patch"]
# after_request = ["fps_erpnext.utils.after_request"]

# Job Events
# ----------
# Install the watermark patch in background workers too (email queue flush,
# scheduled/enqueued PDF generation) — before_request only covers web workers.
before_job = ["fps_erpnext.api.pdf_watermark.install_watermark_patch"]
# after_job = ["fps_erpnext.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#     {
#         "doctype": "{doctype_1}",
#         "filter_by": "{filter_by}",
#         "redact_fields": ["{field_1}", "{field_2}"],
#         "partial": 1,
#     },
#     {
#         "doctype": "{doctype_2}",
#         "filter_by": "{filter_by}",
#         "partial": 1,
#     },
#     {
#         "doctype": "{doctype_3}",
#         "strict": False,
#     },
#     {
#         "doctype": "{doctype_4}"
#     }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#     "fps_erpnext.auth.validate"
# ]

# Automatically update python controller files with type annotations for the
# bench tooling
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
#     "Logging DocType Name": 30  # days to retain logs
# }
