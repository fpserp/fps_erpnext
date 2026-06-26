"""FPS Outgoing Email.

Lets a caller send an email *with an attachment* by simply creating a
document (e.g. via the REST resource API / create_document), which the
WhatsApp/Zoho bot can do — unlike calling a whitelisted method or using
Zoho's send API, neither of which lets the bot attach a file.

On creation, the controller builds the attachment (from inline base64
content, or from the PDF print of an ERPNext document) and sends the email
server-side via frappe.sendmail. If no attachment can be prepared, it fails
loudly and records the error instead of sending a "see attached" email with
nothing attached.
"""

import base64

import frappe
from frappe import _
from frappe.model.document import Document


def _as_email_list(value):
    if not value:
        return []
    return [a.strip() for a in str(value).replace(";", ",").replace("\n", ",").split(",") if a.strip()]


class FPSOutgoingEmail(Document):
    def after_insert(self):
        # Only auto-send freshly created, still-pending records.
        if self.status and self.status != "Pending":
            return
        try:
            self._send()
            self.db_set("status", "Sent")
            self.db_set("sent_at", frappe.utils.now())
        except Exception:
            tb = frappe.get_traceback()
            self.db_set("status", "Failed")
            self.db_set("error_message", tb[:1000])
            frappe.log_error(tb, "FPS Outgoing Email: send failed")

    def _send(self):
        recipients = _as_email_list(self.recipients)
        if not recipients:
            frappe.throw(_("At least one recipient is required."))

        attachments = self._build_attachments()
        if not attachments:
            frappe.throw(_("No attachment could be prepared; email not sent."))

        frappe.sendmail(
            recipients=recipients,
            cc=_as_email_list(self.cc),
            bcc=_as_email_list(self.bcc),
            subject=self.subject,
            message=self.message or "",
            attachments=attachments,
            reference_doctype=self.doctype,
            reference_name=self.name,
            now=True,
        )

    def _build_attachments(self):
        """Collect attachments from any of the supported sources: inline
        base64, an ERPNext document's PDF print, or a SharePoint/OneDrive
        file fetched via Microsoft Graph."""
        out = []

        # 1) Inline base64 content supplied by the caller.
        if self.attachment_content and self.attachment_file_name:
            try:
                content = base64.b64decode(self.attachment_content)
            except Exception:
                frappe.throw(_("Attachment content is not valid base64."))
            if content:
                out.append({"fname": self.attachment_file_name, "fcontent": content})

        # 2) PDF print of an ERPNext document.
        if self.attach_print_doctype and self.attach_print_name:
            out.append(
                frappe.attach_print(
                    self.attach_print_doctype,
                    self.attach_print_name,
                    print_format=self.print_format or None,
                )
            )

        # 3) SharePoint / OneDrive file via Microsoft Graph.
        if self.sharepoint_drive_id and self.sharepoint_item_id:
            from fps_erpnext.fps.microsoft_graph import download_drive_item

            name, content = download_drive_item(self.sharepoint_drive_id, self.sharepoint_item_id)
            out.append({"fname": self.attachment_file_name or name, "fcontent": content})
        elif self.sharepoint_file_url:
            from fps_erpnext.fps.microsoft_graph import download_share_url

            name, content = download_share_url(self.sharepoint_file_url)
            out.append({"fname": self.attachment_file_name or name, "fcontent": content})

        return out
