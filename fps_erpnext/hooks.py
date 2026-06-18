app_name = "fps_erpnext"
app_title = "FPS"
app_publisher = "Fast Planet Shipping LLC"
app_description = "Custom ERPNext app for Fast Planet Shipping LLC - freight forwarding operations"
app_email = "hello@fastplanet.ae"
app_license = "mit"
app_logo_url = "/assets/fps_erpnext/images/fps-logo.svg"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
    {
        "name": "fps_erpnext",
        "logo": "/assets/fps_erpnext/images/fps-logo.svg",
        "title": "FPS",
        "route": "/app/fps",
        "has_permission": "fps_erpnext.api.permission.has_app_permission"
    }
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/fps_erpnext/css/fps_erpnext.css"
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

# Scheduled Tasks
# ---------------

# scheduler_events = {
#     "all": [
#         "fps_erpnext.tasks.all"
#     ],
#     "daily": [
#         "fps_erpnext.tasks.daily"
#     ],
#     "hourly": [
#         "fps_erpnext.tasks.hourly"
#     ],
#     "weekly": [
#         "fps_erpnext.tasks.weekly"
#     ],
#     "monthly": [
#         "fps_erpnext.tasks.monthly"
#     ],
# }

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
