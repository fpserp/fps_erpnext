import frappe


def has_app_permission():
    """Check if user has permission to access the FPS app.

    Returns True if user has any of the FPS-related roles (FPS Viewer,
    Sales User, Sales Manager, Accounts User, Accounts Manager, System Manager).
    """
    allowed_roles = {
        "System Manager",
        "FPS Viewer",
        "FPS Operations",
        "Sales User",
        "Sales Manager",
        "Accounts User",
        "Accounts Manager",
        "Stock User",
        "Stock Manager",
        "Purchase User",
        "Purchase Manager",
    }
    user_roles = set(frappe.get_roles(frappe.session.user))
    return bool(allowed_roles & user_roles)
