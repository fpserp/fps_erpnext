"""Reliable "email a document as PDF" endpoint for FPS.

Background
----------
The WhatsApp/Zoho bot sends mail through Zoho's send API, which can only
attach files that were first uploaded via Zoho's separate "Upload
Attachments" API. That upload step is not available to the bot, so when it
is asked to email a document "with the PDF attached" the body sends but the
PDF is silently dropped.

This module gives the bot (or any caller) a single server-side endpoint that
generates the document's PDF *inside* ERPNext and attaches it itself. The
key guarantee: if the PDF cannot be produced, the email is NOT sent — we
raise instead of quietly delivering an email without its attachment, so the
"missing PDF" failure can never recur silently.
"""

import base64

import frappe
from frappe import _


def _as_email_list(value):
    """Normalise a recipients value (list, or comma/semicolon/newline string)
    into a clean list of addresses."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = str(value).replace(";", ",").replace("\n", ",").split(",")
    return [a.strip() for a in items if a and a.strip()]


@frappe.whitelist()
def send_document_email(
    doctype,
    name,
    recipients,
    subject=None,
    message=None,
    print_format=None,
    cc=None,
    bcc=None,
    file_name=None,
    letterhead=None,
    lang=None,
):
    """Email a document with its PDF attached, generated server-side.

    Unlike sending through an external mail API, the PDF is produced and
    attached here, so the attachment can never be dropped. If PDF generation
    fails or yields empty content, this raises and NO email is sent.

    Args:
        doctype: DocType of the document (e.g. "Sales Invoice", "Quotation").
        name: Document name/ID.
        recipients: To address(es) — list or comma-separated string.
        subject: Email subject. Defaults to "<doctype> <name>".
        message: Email body (HTML). Defaults to a short standard line.
        print_format: Print format name. Defaults to the doctype's default.
        cc, bcc: Optional Cc/Bcc address(es) — list or comma-separated string.
        file_name: Attachment file name (without extension). Defaults to name.
        letterhead: Letter head toggle. Truthy/None keeps the letter head;
            pass "" / 0 / False to print without it.
        lang: Print language. Defaults to the document/system language.

    Returns:
        dict with status, recipients, the attached file name and its size in
        bytes — so the caller can confirm a non-empty PDF was attached.
    """
    recipients = _as_email_list(recipients)
    if not recipients:
        frappe.throw(_("At least one recipient is required."))

    if not frappe.db.exists(doctype, name):
        frappe.throw(_("{0} {1} not found.").format(doctype, name))

    # Respect ERPNext permissions for the calling user.
    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw(
            _("You are not permitted to read {0} {1}.").format(doctype, name),
            frappe.PermissionError,
        )

    # `letterhead` here is a simple on/off toggle: falsy disables the letter
    # head. (frappe.attach_print only exposes the boolean print_letterhead.)
    print_letterhead = letterhead not in (False, 0, "0", "")

    # Generate + attach the PDF. attach_print returns {"fname", "fcontent"}.
    attachment = frappe.attach_print(
        doctype,
        name,
        file_name=(file_name or name),
        print_format=print_format,
        lang=lang,
        print_letterhead=print_letterhead,
    )

    fcontent = (attachment or {}).get("fcontent")
    if not fcontent:
        # Fail loud: never send the email without the PDF.
        frappe.throw(
            _("Could not generate the PDF for {0} {1}; email not sent.").format(
                doctype, name
            )
        )

    frappe.sendmail(
        recipients=recipients,
        cc=_as_email_list(cc),
        bcc=_as_email_list(bcc),
        subject=subject or f"{doctype} {name}",
        message=message or _("Please find the attached {0}.").format(doctype),
        attachments=[attachment],
        reference_doctype=doctype,
        reference_name=name,
        now=True,
    )

    return {
        "status": "sent",
        "doctype": doctype,
        "name": name,
        "recipients": recipients,
        "cc": _as_email_list(cc),
        "bcc": _as_email_list(bcc),
        "attached_file": attachment.get("fname"),
        "attached_bytes": len(fcontent),
    }


@frappe.whitelist()
def send_email(
    recipients,
    subject,
    message=None,
    cc=None,
    bcc=None,
    attachments=None,
    file_names=None,
    reference_doctype=None,
    reference_name=None,
):
    """Send a free-form email with attachment(s), reliably, from ERPNext.

    Use this for emails that are NOT a single ERPNext print (for those use
    send_document_email). The PDF/file is attached server-side, so callers
    that cannot upload attachments (e.g. the WhatsApp/Zoho bot) can still
    send with the file. If the caller asks for attachments but none can be
    prepared, this raises and NO email is sent.

    Args:
        recipients: To address(es) — list or comma-separated string.
        subject: Email subject.
        message: Email body (HTML).
        cc, bcc: Optional Cc/Bcc — list or comma-separated string.
        attachments: list of {"fname": str, "fcontent_base64": str} — inline
            files provided by the caller (base64-encoded content).
        file_names: list of existing File doctype names to attach.
        reference_doctype, reference_name: optional link for the Communication.

    Returns:
        dict with status, recipients and the names of attached files.
    """
    recipients = _as_email_list(recipients)
    if not recipients:
        frappe.throw(_("At least one recipient is required."))

    if isinstance(attachments, str):
        attachments = frappe.parse_json(attachments)
    if isinstance(file_names, str):
        file_names = frappe.parse_json(file_names)
    attachments = attachments or []
    file_names = file_names or []

    requested = bool(attachments or file_names)
    mail_attachments = []

    for a in attachments:
        fname = a.get("fname") or a.get("file_name")
        b64 = a.get("fcontent_base64") or a.get("fcontent")
        if not fname or not b64:
            continue
        try:
            content = base64.b64decode(b64)
        except Exception:
            frappe.throw(_("Attachment {0} is not valid base64.").format(fname))
        if content:
            mail_attachments.append({"fname": fname, "fcontent": content})

    # frappe.sendmail accepts existing files via {"fid": <File name>}.
    for fn in file_names:
        if fn:
            mail_attachments.append({"fid": fn})

    # Fail loud: if attachments were requested but none resolved, don't send
    # a "PDF attached" email with no PDF.
    if requested and not mail_attachments:
        frappe.throw(_("No valid attachment could be prepared; email not sent."))

    frappe.sendmail(
        recipients=recipients,
        cc=_as_email_list(cc),
        bcc=_as_email_list(bcc),
        subject=subject,
        message=message or "",
        attachments=mail_attachments or None,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        now=True,
    )

    return {
        "status": "sent",
        "recipients": recipients,
        "cc": _as_email_list(cc),
        "bcc": _as_email_list(bcc),
        "attachments": [a.get("fname") or a.get("fid") for a in mail_attachments],
    }
