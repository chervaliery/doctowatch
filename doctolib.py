"""
Doctolib availabilities API: build URL, fetch, parse, and detect availability or errors.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

AVAILABILITIES_URL = "https://www.doctolib.fr/availabilities.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CLOUDFLARE_INDICATORS = ("cloudflare", "challenge", "Checking your browser")

# Max extra requests when the API points to a later window via `next_slot`.
MAX_NEXT_SLOT_FOLLOWS = 10

# French weekday (Monday=0) and month names for email display.
_WEEKDAYS_FR = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
_MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _normalize_ids(value: str | list[str]) -> str:
    """Convert practice_ids or agenda_ids to a single comma-separated string."""
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def build_availabilities_url(
    *,
    visit_motive_ids: list[int] | list[str],
    agenda_ids: str | list[str],
    practice_ids: str | list[str],
    start_date: date,
    telehealth: bool = False,
    limit: int = 5,
) -> str:
    """Build the Doctolib availabilities.json URL for the given parameters."""
    params: list[tuple[str, str]] = [
        ("telehealth", "true" if telehealth else "false"),
        ("start_date", start_date.isoformat()),
        ("limit", str(limit)),
        ("agenda_ids", _normalize_ids(agenda_ids)),
        ("practice_ids", _normalize_ids(practice_ids)),
    ]
    for vid in visit_motive_ids:
        params.append(("visit_motive_ids", str(vid)))
    query = "&".join(f"{k}={v}" for k, v in params)
    return f"{AVAILABILITIES_URL}?{query}"


def _is_cloudflare_response(text: str) -> bool:
    text_lower = text.lower()
    return any(indicator in text_lower for indicator in CLOUDFLARE_INDICATORS)


def _has_availability(data: dict[str, Any]) -> bool:
    total = data.get("total", 0)
    if total and int(total) > 0:
        return True
    for day in data.get("availabilities") or []:
        slots = day.get("slots") or []
        if slots:
            return True
    return False


def _parse_iso_to_date(s: str) -> date | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        if len(s) >= 10:
            return date.fromisoformat(s[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _slot_date_and_line(slot: Any, day_date: date | None, day_str: str | None) -> tuple[date | None, str]:
    """Return (calendar date for cutoff logic, human-readable line for email)."""
    if isinstance(slot, dict):
        raw = slot.get("start_date") or slot.get("start") or slot.get("date")
        raw_s = str(raw) if raw is not None else ""
        d = _parse_iso_to_date(raw_s) if raw_s else None
        if d is None and day_date is not None:
            d = day_date
        if raw_s:
            line = raw_s.replace("T", " ").split("+")[0].split(".")[0].strip()
            if len(line) > 80:
                line = line[:77] + "..."
        elif day_str:
            line = f"{day_str} (slot)"
        else:
            line = str(slot)[:120]
        return d, line
    if isinstance(slot, str):
        d = _parse_iso_to_date(slot)
        if d is None and day_date is not None:
            d = day_date
        return d, slot
    d = day_date
    return d, str(slot)


def analyze_availabilities(
    availabilities: list[Any] | None,
    cutoff: date | None,
    total: int = 0,
) -> tuple[bool, list[str]]:
    """
    Decide whether to send a notification and build slot lines for the email.

    If cutoff is None, notify iff there is availability (same idea as _has_availability).
    If cutoff is set, notify only if at least one slot falls on or before cutoff,
    unless no slot dates could be parsed but the API still reports slots (then notify).

    Returns:
        (should_notify, slot_lines)
    """
    availabilities = availabilities or []
    slot_lines: list[str] = []
    per_slot_dates: list[date] = []

    for day in availabilities:
        if not isinstance(day, dict):
            continue
        day_str = day.get("date")
        day_date: date | None = None
        if isinstance(day_str, str):
            day_date = _parse_iso_to_date(day_str)

        for slot in day.get("slots") or []:
            d, line = _slot_date_and_line(slot, day_date, day_str if isinstance(day_str, str) else None)
            slot_lines.append(line)
            if d is not None:
                per_slot_dates.append(d)

    has_slot_rows = len(slot_lines) > 0
    has_availability = (total and int(total) > 0) or has_slot_rows

    if cutoff is None:
        return has_availability, slot_lines

    if not has_availability:
        return False, slot_lines

    if not per_slot_dates:
        # API reported slots but we could not parse dates; still notify (edge case).
        return True, slot_lines

    if any(d <= cutoff for d in per_slot_dates):
        return True, slot_lines

    return False, slot_lines


def _parse_slot_to_datetime(slot: Any, day_date: date | None) -> datetime | None:
    """Parse a slot entry to a datetime for sorting and time display."""
    if isinstance(slot, dict):
        raw = slot.get("start_date") or slot.get("start") or slot.get("date")
        if raw is None:
            return None
        s = str(raw).strip()
    elif isinstance(slot, str):
        s = slot.strip()
    else:
        return None
    try:
        if "T" in s or (len(s) > 10 and s[4] == "-"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        if len(s) >= 10:
            d = date.fromisoformat(s[:10])
            return datetime.combine(d, datetime.min.time())
    except ValueError:
        pass
    if day_date is not None:
        return datetime.combine(day_date, datetime.min.time())
    return None


def _fr_date_heading(d: date) -> str:
    wd = _WEEKDAYS_FR[d.weekday()].capitalize()
    month = _MONTHS_FR[d.month - 1].capitalize()
    return f"{wd} {d.day:02d} {month} {d.year}"


def format_availabilities_fr_for_email(
    availabilities: list[Any] | None,
) -> tuple[list[str], str]:
    """
    Build readable French slot listings: grouped by day, times under each day.

    Plain text lines look like::
        * Mardi 07 Juillet 2026
        * * 17:00
        * * 17:30

    Returns:
        (plain_lines, html_fragment) — empty lists/strings if nothing to show.
    """
    availabilities = availabilities or []
    parsed: list[datetime] = []

    for day in availabilities:
        if not isinstance(day, dict):
            continue
        day_str = day.get("date")
        day_date: date | None = None
        if isinstance(day_str, str):
            day_date = _parse_iso_to_date(day_str)

        for slot in day.get("slots") or []:
            dt = _parse_slot_to_datetime(slot, day_date)
            if dt is not None:
                parsed.append(dt)

    if not parsed:
        return [], ""

    parsed.sort()
    by_day: dict[date, list[datetime]] = {}
    for dt in parsed:
        by_day.setdefault(dt.date(), []).append(dt)

    plain_lines: list[str] = []
    html_items: list[str] = []

    for d in sorted(by_day.keys()):
        plain_lines.append(f"* {_fr_date_heading(d)}")
        times_html: list[str] = []
        seen_time: set[tuple[int, int]] = set()
        for dt in sorted(by_day[d], key=lambda x: (x.hour, x.minute, x.second)):
            hm = (dt.hour, dt.minute)
            if hm in seen_time:
                continue
            seen_time.add(hm)
            tlabel = dt.strftime("%H:%M")
            plain_lines.append(f"* * {tlabel}")
            times_html.append(f"<li>{tlabel}</li>")

        heading = html.escape(_fr_date_heading(d))
        inner_ul = "".join(times_html)
        html_items.append(f"<li><strong>{heading}</strong><ul>{inner_ul}</ul></li>")

    html_fragment = f"<ul>{''.join(html_items)}</ul>"
    return plain_lines, html_fragment


def _fetch_availabilities_json(
    *,
    visit_motive_ids: list[int] | list[str],
    agenda_ids: str | list[str],
    practice_ids: str | list[str],
    start_date: date,
    telehealth: bool,
    limit: int,
    timeout: int,
) -> dict[str, Any]:
    """One HTTP GET; returns error dict with ok False, or ok True with parsed `data`."""
    url = build_availabilities_url(
        visit_motive_ids=visit_motive_ids,
        agenda_ids=agenda_ids,
        practice_ids=practice_ids,
        start_date=start_date,
        telehealth=telehealth,
        limit=limit,
    )
    logger.info(
        "Fetching availabilities: practice_ids=%s, agenda_ids=%s, visit_motive_ids=%s, start_date=%s",
        _normalize_ids(practice_ids),
        _normalize_ids(agenda_ids),
        ",".join(str(v) for v in visit_motive_ids),
        start_date,
    )
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    except requests.RequestException as e:
        logger.warning("Request failed: %s: %s", type(e).__name__, e)
        return {
            "ok": False,
            "error": f"Request failed: {type(e).__name__}: {e}",
            "status_code": None,
        }
    text = resp.text
    if _is_cloudflare_response(text):
        logger.warning("Cloudflare/challenge detected in response")
        return {
            "ok": False,
            "error": "Cloudflare/challenge detected",
            "status_code": resp.status_code,
        }
    if resp.status_code != 200:
        logger.warning("HTTP %s from Doctolib", resp.status_code)
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "status_code": resp.status_code,
        }
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON: %s", e)
        return {
            "ok": False,
            "error": f"Invalid JSON: {e}",
            "status_code": resp.status_code,
        }
    if "availabilities" not in data:
        logger.warning("Response missing 'availabilities'")
        return {
            "ok": False,
            "error": "Response missing 'availabilities'",
            "status_code": resp.status_code,
        }
    return {"ok": True, "data": data}


def fetch_availabilities(
    visit_motive_ids: list[int] | list[str],
    agenda_ids: str | list[str],
    practice_ids: str | list[str],
    start_date: date | None = None,
    telehealth: bool = False,
    limit: int = 5,
    timeout: int = 15,
) -> dict[str, Any]:
    """
    Fetch availabilities from Doctolib and return a structured result.

    If the response has no slots but includes ``next_slot``, refetches using that
    timestamp's calendar date as ``start_date`` (up to MAX_NEXT_SLOT_FOLLOWS times).

    Returns:
        On success: {"ok": True, "available": bool, "total": int, "availabilities": [...]}
        On error:   {"ok": False, "error": str, "status_code": int | None}
    """
    current_start = start_date or date.today()
    seen_starts: set[date] = set()
    last_data: dict[str, Any] | None = None

    for _hop in range(MAX_NEXT_SLOT_FOLLOWS + 1):
        if current_start in seen_starts:
            logger.warning("next_slot loop: already fetched start_date=%s; stopping.", current_start)
            break
        seen_starts.add(current_start)

        raw = _fetch_availabilities_json(
            visit_motive_ids=visit_motive_ids,
            agenda_ids=agenda_ids,
            practice_ids=practice_ids,
            start_date=current_start,
            telehealth=telehealth,
            limit=limit,
            timeout=timeout,
        )
        if not raw.get("ok"):
            return raw
        data = raw["data"]
        last_data = data

        available = _has_availability(data)
        total = data.get("total", 0)
        next_slot = data.get("next_slot")
        logger.info(
            "Result: available=%s, total=%s, next_slot=%s",
            available,
            total,
            next_slot,
        )

        if available or not next_slot:
            return {
                "ok": True,
                "available": available,
                "total": total,
                "availabilities": data.get("availabilities", []),
            }

        next_start = _parse_iso_to_date(str(next_slot))
        if next_start is None:
            logger.warning("Could not parse next_slot=%r; returning last response.", next_slot)
            return {
                "ok": True,
                "available": False,
                "total": total,
                "availabilities": data.get("availabilities", []),
            }

        if next_start == current_start:
            logger.warning("next_slot maps to same start_date=%s; stopping.", current_start)
            return {
                "ok": True,
                "available": False,
                "total": total,
                "availabilities": data.get("availabilities", []),
            }

        logger.info("Following next_slot, refetching with start_date=%s", next_start)
        current_start = next_start

    if last_data is not None:
        logger.warning("Stopped after %s next_slot follow(s); returning last response.", MAX_NEXT_SLOT_FOLLOWS)
        return {
            "ok": True,
            "available": _has_availability(last_data),
            "total": last_data.get("total", 0),
            "availabilities": last_data.get("availabilities", []),
        }
    return {
        "ok": True,
        "available": False,
        "total": 0,
        "availabilities": [],
    }
