"""Minimal Microsoft Graph (app-only) client for downloading SharePoint /
OneDrive files, used to attach them to outgoing email.

Auth: client-credentials flow against the tenant configured in
"FPS Microsoft Settings". Requires the Azure AD app to have application
permissions Files.Read.All and Sites.Read.All with admin consent.
"""

import base64

import frappe
import requests

GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT = 30
_CONTENT_TIMEOUT = 120


def _settings():
    s = frappe.get_cached_doc("FPS Microsoft Settings")
    if not s.enabled:
        frappe.throw("FPS Microsoft Settings is not enabled.")
    if not (s.tenant_id and s.client_id):
        frappe.throw("FPS Microsoft Settings is missing Tenant ID / Client ID.")
    return s


def get_graph_token():
    """Return an app-only Microsoft Graph access token."""
    s = _settings()
    secret = s.get_password("client_secret")
    if not secret:
        frappe.throw("FPS Microsoft Settings is missing the Client Secret.")
    url = f"https://login.microsoftonline.com/{s.tenant_id}/oauth2/v2.0/token"
    resp = requests.post(
        url,
        data={
            "client_id": s.client_id,
            "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        frappe.throw(f"Graph token request failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()["access_token"]


def _headers():
    return {"Authorization": f"Bearer {get_graph_token()}"}


def download_drive_item(drive_id, item_id):
    """Download a file by drive id + item id. Returns (filename, bytes)."""
    headers = _headers()
    meta = requests.get(f"{GRAPH}/drives/{drive_id}/items/{item_id}", headers=headers, timeout=_TIMEOUT)
    if meta.status_code != 200:
        frappe.throw(f"Graph item lookup failed ({meta.status_code}): {meta.text[:500]}")
    name = meta.json().get("name") or "attachment"
    content = requests.get(
        f"{GRAPH}/drives/{drive_id}/items/{item_id}/content", headers=headers, timeout=_CONTENT_TIMEOUT
    )
    if content.status_code != 200:
        frappe.throw(f"Graph file download failed ({content.status_code}): {content.text[:500]}")
    return name, content.content


def _encode_share_url(share_url):
    # Per Graph "shares" API: base64url-encode, strip '=', prefix 'u!'.
    b64 = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + b64


def download_share_url(share_url):
    """Download a file from a SharePoint/OneDrive web or share URL.
    Returns (filename, bytes)."""
    headers = _headers()
    sid = _encode_share_url(share_url)
    meta = requests.get(f"{GRAPH}/shares/{sid}/driveItem", headers=headers, timeout=_TIMEOUT)
    if meta.status_code != 200:
        frappe.throw(f"Graph share lookup failed ({meta.status_code}): {meta.text[:500]}")
    name = meta.json().get("name") or "attachment"
    content = requests.get(f"{GRAPH}/shares/{sid}/driveItem/content", headers=headers, timeout=_CONTENT_TIMEOUT)
    if content.status_code != 200:
        frappe.throw(f"Graph share download failed ({content.status_code}): {content.text[:500]}")
    return name, content.content
