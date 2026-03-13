"""
Mailjet notifications: slot available and script issue emails.
"""
from __future__ import annotations

import os

from mailjet_rest import Client


def _get_client() -> Client | None:
    api_key = os.environ.get("MJ_APIKEY_PUBLIC")
    api_secret = os.environ.get("MJ_APIKEY_PRIVATE")
    if not api_key or not api_secret:
        return None
    return Client(auth=(api_key, api_secret), version="v3.1")


def _send_mail(
    *,
    from_email: str,
    to_emails: list[str],
    subject: str,
    text_part: str,
    html_part: str | None = None,
) -> tuple[bool, str]:
    """Send one email via Mailjet. Returns (success, error_message)."""
    client = _get_client()
    if not client:
        missing = []
        if not os.environ.get("MJ_APIKEY_PUBLIC"):
            missing.append("MJ_APIKEY_PUBLIC")
        if not os.environ.get("MJ_APIKEY_PRIVATE"):
            missing.append("MJ_APIKEY_PRIVATE")
        return False, f"Mailjet credentials not set: {', '.join(missing)}"
    to_list = [{"Email": email} for email in to_emails]
    data = {
        "Messages": [
            {
                "From": {"Email": from_email},
                "To": to_list,
                "Subject": subject,
                "TextPart": text_part,
                "HTMLPart": html_part or f"<p>{text_part.replace(chr(10), '<br>')}</p>",
            }
        ]
    }
    try:
        result = client.send.create(data=data)
        if result.status_code in (200, 201):
            return True, ""
        err_msg = getattr(result, "reason", None) or getattr(result, "text", None) or str(result)
        return False, f"Mailjet returned {result.status_code}: {err_msg}"
    except Exception as e:
        return False, str(e)


def send_availability_email(
    *,
    from_email: str,
    to_emails: list[str],
    watcher_name: str,
    total: int = 0,
    booking_url: str | None = None,
) -> tuple[bool, str]:
    """
    Send email when at least one slot is available.
    Returns (success, error_message).
    """
    subject = f"Doctolib: slot available – {watcher_name}"
    body = f"At least one appointment slot is available for: {watcher_name}."
    if total > 0:
        body += f" (Total: {total} slot(s))"
    body += "."
    if booking_url:
        body += f"\n\nDoctor page / Book here: {booking_url}"
    if booking_url:
        parts = body.split("\n\n")
        html_paragraphs = [f"<p>{p.replace(chr(10), '<br>')}</p>" for p in parts[:-1]]
        html_paragraphs.append(f'<p><a href="{booking_url}">Doctor page / Book here</a></p>')
        html_part = "\n".join(html_paragraphs)
    else:
        html_part = f"<p>{body.replace(chr(10), '<br>')}</p>"
    return _send_mail(
        from_email=from_email,
        to_emails=to_emails,
        subject=subject,
        text_part=body,
        html_part=html_part,
    )


def send_script_issue_email(
    *,
    from_email: str,
    to_emails: list[str],
    watcher_name: str | None,
    error_summary: str,
    status_code: int | None = None,
    booking_url: str | None = None,
) -> tuple[bool, str]:
    """
    Send email when the monitor hits an error (HTTP, Cloudflare, throttling, etc.).
    Returns (success, error_message).
    """
    subject = "Doctolib monitor: script issue"
    parts = [error_summary]
    if watcher_name:
        parts.append(f"Watcher: {watcher_name}.")
    if status_code is not None:
        parts.append(f"HTTP status: {status_code}.")
    body = " ".join(parts)
    if booking_url:
        body += f"\n\nDoctor page: {booking_url}"
    html_parts = [f"<p>{body.split(chr(10) + chr(10))[0]}</p>"]
    if booking_url:
        html_parts.append(f'<p><a href="{booking_url}">Doctor page</a></p>')
    html_part = "\n".join(html_parts) if booking_url else f"<p>{body}</p>"
    return _send_mail(
        from_email=from_email,
        to_emails=to_emails,
        subject=subject,
        text_part=body,
        html_part=html_part,
    )
