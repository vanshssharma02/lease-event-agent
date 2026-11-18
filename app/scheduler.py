"""Scheduler module for automated periodic lease monitoring.

Configures an APScheduler background job running daily at the configured hour and timezone.
Identifies in-window leases and executes the LangGraph agent for unrouted leases.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import get_connection
from app.seed import get_leases_in_window
from app.agent import run_agent

logger = logging.getLogger(__name__)


def check_active_event_exists(
    lease_id: str,
    event_type: Optional[str] = None,
    event_date: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Check if an active inbox item already exists for the same lease, event type, and event date.

    Returns the existing active item dict if found, or None if clear.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        # Resolve target event_type and event_date from register if not passed
        if not event_type or not event_date:
            cur.execute(
                "SELECT event_type, expiry_date FROM lease_register WHERE lease_id = ?;",
                (lease_id,),
            )
            reg_row = cur.fetchone()
            if reg_row:
                event_type = event_type or reg_row["event_type"]
                event_date = event_date or reg_row["expiry_date"]

        cur.execute(
            """
            SELECT
                run_id, lease_id, status, created_at,
                json_extract(memo_json, '$.event_type') AS item_event_type,
                json_extract(memo_json, '$.event_date.date') AS item_event_date
            FROM inbox_items
            WHERE lease_id = ?
              AND status IN ('pending_approval', 'approved');
            """,
            (lease_id,),
        )
        rows = cur.fetchall()
        for r in rows:
            r_type = r["item_event_type"]
            r_date = r["item_event_date"]
            if event_type and r_type and r_type != event_type:
                continue
            if event_date and r_date and r_date != event_date:
                continue
            return {
                "run_id": r["run_id"],
                "lease_id": r["lease_id"],
                "status": r["status"],
                "event_type": r_type or event_type,
                "event_date": r_date or event_date,
                "created_at": r["created_at"],
            }
        return None
    finally:
        conn.close()


def is_lease_already_active(
    lease_id: str,
    event_type: Optional[str] = None,
    event_date: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Check if a lease already has an active pending or approved item for the specified event."""
    return check_active_event_exists(lease_id, event_type=event_type, event_date=event_date, db_path=db_path) is not None


def run_in_window_leases(
    days: int = 180,
    force: bool = False,
    db_path: Optional[Union[str, Path]] = None,
    chroma_dir: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Scan the register for in-window leases and run the agent for all eligible leases.

    Skips any lease that already has an item with status pending_approval or approved
    for the same event, unless force=True.
    """
    leases = get_leases_in_window(days=days, db_path=db_path)
    results: List[Dict[str, Any]] = []

    for l in leases:
        lid = l["lease_id"]
        ev_type = l["event_type"]
        ev_date = l["expiry_date"]

        if not force:
            active = check_active_event_exists(lid, event_type=ev_type, event_date=ev_date, db_path=db_path)
            if active:
                logger.info(f"Skipping {lid}: active item already exists for event {ev_type} ({ev_date}).")
                results.append({
                    "lease_id": lid,
                    "status": "SKIPPED_ALREADY_ACTIVE",
                    "event_type": ev_type,
                    "tenant": l["tenant"],
                    "expiry_date": ev_date,
                    "reason": f"Active item already exists (Run: {active['run_id']}, Status: {active['status']})",
                })
                continue

        logger.info(f"Executing agent workflow for {lid} ({ev_type})...")
        state = run_agent(lease_id=lid, db_path=db_path, chroma_dir=chroma_dir)
        results.append({
            "lease_id": lid,
            "run_id": state.get("run_id"),
            "status": state.get("status"),
            "event_type": ev_type,
            "tenant": l["tenant"],
            "expiry_date": ev_date,
            "low_confidence": state.get("low_confidence", False),
            "quarantined_count": len(state.get("quarantined_chunk_ids", [])),
        })

    return results


def start_scheduler(db_path: Optional[Union[str, Path]] = None) -> BackgroundScheduler:
    """Initialize and start the background scheduler."""
    scheduler = BackgroundScheduler(timezone=settings.SCHEDULER_TZ)
    trigger = CronTrigger(hour=settings.SCHEDULER_HOUR, minute=0, timezone=settings.SCHEDULER_TZ)

    scheduler.add_job(
        run_in_window_leases,
        trigger=trigger,
        kwargs={"db_path": db_path},
        id="lease_monitoring_daily_cron",
        name="Daily Commercial Lease Event Monitoring",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler initialized: running daily at {settings.SCHEDULER_HOUR}:00 {settings.SCHEDULER_TZ}"
    )
    return scheduler
