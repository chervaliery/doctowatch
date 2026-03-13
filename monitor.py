#!/usr/bin/env python3
"""
Doctolib availability monitor: poll availabilities and send SendGrid emails
on slot available or script issue.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from doctolib import fetch_availabilities
from notify import send_availability_email, send_script_issue_email

logger = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    text = path.read_text()
    data = yaml.safe_load(text)
    if not data:
        raise ValueError("Config is empty")
    return data


def normalize_watcher(w: dict) -> dict:
    """Ensure watcher has required keys and normalized types."""
    name = w.get("name") or "Unknown"
    practice_ids = w.get("practice_ids")
    agenda_ids = w.get("agenda_ids")
    visit_motive_ids = w.get("visit_motive_ids") or []
    if isinstance(visit_motive_ids, (int, str)):
        visit_motive_ids = [visit_motive_ids]
    return {
        "name": name,
        "practice_ids": practice_ids,
        "agenda_ids": agenda_ids,
        "visit_motive_ids": list(visit_motive_ids),
        "telehealth": w.get("telehealth", False),
        "booking_url": w.get("booking_url"),
    }


def run_once(config: dict) -> None:
    mailjet_cfg = config.get("mailjet") or {}
    from_email = mailjet_cfg.get("from_email") or "noreply@example.com"
    to_emails = mailjet_cfg.get("to_emails") or []
    if isinstance(to_emails, str):
        to_emails = [to_emails]
    if not to_emails:
        logger.warning("No to_emails in config; notifications will not be sent.")
    limit = config.get("limit", 5)
    start_date_str = config.get("start_date")
    start_date = date.today() if not start_date_str else date.fromisoformat(start_date_str)
    watchers = [normalize_watcher(w) for w in (config.get("watchers") or [])]
    if not watchers:
        logger.warning("No watchers in config.")
        return
    logger.info("Running check for %d watcher(s), start_date=%s, limit=%d", len(watchers), start_date, limit)
    for w in watchers:
        if not w.get("practice_ids") or not w.get("agenda_ids") or not w.get("visit_motive_ids"):
            logger.warning("Skip watcher '%s': missing practice_ids, agenda_ids, or visit_motive_ids.", w["name"])
            continue
        logger.info("Checking watcher: %s", w["name"])
        result = fetch_availabilities(
            visit_motive_ids=w["visit_motive_ids"],
            agenda_ids=w["agenda_ids"],
            practice_ids=w["practice_ids"],
            start_date=start_date,
            telehealth=w["telehealth"],
            limit=limit,
        )
        if not result.get("ok"):
            logger.warning("Error for '%s': %s (status=%s)", w["name"], result.get("error"), result.get("status_code"))
            logger.info("Sending script-issue email for '%s'", w["name"])
            ok, err = send_script_issue_email(
                from_email=from_email,
                to_emails=to_emails,
                watcher_name=w["name"],
                error_summary=result.get("error", "Unknown error"),
                status_code=result.get("status_code"),
                booking_url=w.get("booking_url"),
            )
            if ok:
                logger.info("Script-issue email sent for '%s'", w["name"])
            else:
                logger.error("Failed to send script-issue email: %s", err)
            continue
        if result.get("available"):
            logger.info("Slots available for '%s' (total=%s)", w["name"], result.get("total", 0))
            logger.info("Sending availability email for '%s'", w["name"])
            ok, err = send_availability_email(
                from_email=from_email,
                to_emails=to_emails,
                watcher_name=w["name"],
                total=result.get("total", 0),
                booking_url=w.get("booking_url"),
            )
            if ok:
                logger.info("Availability email sent for '%s'", w["name"])
            else:
                logger.error("Failed to send availability email: %s", err)
        else:
            logger.info("No slots for '%s'", w["name"])


def setup_logging() -> None:
    """Configure console logging with timestamp and level."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Doctolib availability monitor")
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        metavar="FILE",
        help="Path to YAML config (default: config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for cron); default is to loop every interval_seconds",
    )
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        logger.info("Loaded config from %s", args.config)
    except FileNotFoundError as e:
        logger.error("%s", e)
        return 1
    except ValueError as e:
        logger.error("%s", e)
        return 1
    if args.once:
        run_once(config)
        logger.info("Run complete (--once).")
        return 0
    interval = max(60, int(config.get("interval_seconds", 300)))
    logger.info("Monitoring every %ds. Press Ctrl+C to stop.", interval)
    try:
        while True:
            run_once(config)
            logger.info("Next check in %ds.", interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
