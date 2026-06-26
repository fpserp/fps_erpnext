"""FPS Microsoft Settings — app-only Microsoft Graph credentials.

Stores the Azure AD app registration used to download SharePoint / OneDrive
files for outgoing email attachments.
"""

import frappe
from frappe.model.document import Document


class FPSMicrosoftSettings(Document):
    pass


@frappe.whitelist()
def test_connection():
    """Verify the stored credentials can obtain a Graph token."""
    from fps_erpnext.fps.microsoft_graph import get_graph_token

    get_graph_token()
    return {"ok": True, "message": "Successfully obtained a Microsoft Graph token."}
