"""Thin event-log helper.

Every significant engine action (collector state changes, trades,
risk-limit rejections, stale-data skips, ...) is written to the
``system_events`` table so the dashboard can surface a live audit trail.
Events are written on a best-effort basis and never raise.
"""

import logging

from app.core.database import SessionLocal
from app.core.models import SystemEvent

logger = logging.getLogger("app.events")


def log_event(level: str, source: str, message: str):
    try:
        with SessionLocal() as db:
            db.add(
                SystemEvent(
                    level=level.upper(),
                    source=source[:50],
                    message=message[:500],
                )
            )
            db.commit()
    except Exception as error:  # noqa: BLE001 - event log must never crash the engine
        logger.warning("Could not write system event: %s", error)
