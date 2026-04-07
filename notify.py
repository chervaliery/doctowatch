"""
Mailjet notifications: slot available and script issue emails.
"""
from __future__ import annotations

import html
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
    slot_lines: list[str] | None = None,
    slot_html: str | None = None,
) -> tuple[bool, str]:
    """
    Send email when at least one slot is available.
    Returns (success, error_message).

    ``slot_lines`` may be pre-formatted lines (e.g. French grouped slots with leading ``*``).
    If ``slot_html`` is set, it is used for the HTML slots block (nested list); otherwise
    a flat list is built from ``slot_lines``.
    """
    subject = f"Doctolib: slot available – {watcher_name}"
    slot_lines = slot_lines or []
    intro = f"At least one appointment slot is available for: {watcher_name}."
    if total > 0:
        intro += f" (Total: {total} slot(s))"
    intro += "."
    text = intro
    if slot_lines:
        text += "\n\nCréneaux disponibles :\n" + "\n".join(slot_lines)
    elif total > 0:
        text += "\n\n(Slots reported by Doctolib but details could not be listed.)"
    if booking_url:
        text += f"\n\nDoctor page / Book here: {booking_url}"

    html_parts: list[str] = [f"<p>{html.escape(intro)}</p>"]
    if slot_html:
        html_parts.append("<p><strong>Créneaux disponibles</strong></p>")
        html_parts.append(slot_html)
    elif slot_lines:
        li_html = "".join(f"<li>{html.escape(line)}</li>" for line in slot_lines)
        html_parts.append("<p><strong>Créneaux disponibles</strong></p>")
        html_parts.append(f"<ul>{li_html}</ul>")
    elif total > 0:
        html_parts.append(
            "<p><em>Slots reported by Doctolib but details could not be listed.</em></p>"
        )
    if booking_url:
        html_parts.append(f'<p><a href="{html.escape(booking_url)}">Doctor page / Book here</a></p>')
    html_part = "\n".join(html_parts)
    return _send_mail(
        from_email=from_email,
        to_emails=to_emails,
        subject=subject,
        text_part=text,
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
