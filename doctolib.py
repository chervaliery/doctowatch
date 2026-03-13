"""
Doctolib availabilities API: build URL, fetch, parse, and detect availability or errors.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)

AVAILABILITIES_URL = "https://www.doctolib.fr/availabilities.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CLOUDFLARE_INDICATORS = ("cloudflare", "challenge", "Checking your browser")


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

    Returns:
        On success: {"ok": True, "available": bool, "total": int, "availabilities": [...]}
        On error:   {"ok": False, "error": str, "status_code": int | None}
    """
    start_date = start_date or date.today()
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
    available = _has_availability(data)
    total = data.get("total", 0)
    logger.info("Result: available=%s, total=%s", available, total)
    return {
        "ok": True,
        "available": available,
        "total": total,
        "availabilities": data.get("availabilities", []),
    }
