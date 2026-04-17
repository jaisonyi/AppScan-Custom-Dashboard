from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.api.v1.routes.analytics import prewarm_base_data_cache
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

_PREWARM_STATUS: dict[str, Any] = {
    "running": False,
    "last_success_at": None,
    "last_error_at": None,
    "last_error": None,
    "run_count": 0,
    "error_count": 0,
    "next_run_at": None,
    "interval_seconds": None,
}


def get_prewarm_status() -> dict[str, Any]:
    """Return a snapshot of the current prewarm worker status."""
    return dict(_PREWARM_STATUS)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_analytics_prewarm(stop_event: asyncio.Event) -> None:
    interval = max(60, int(settings.analytics_prewarm_interval_seconds))
    _PREWARM_STATUS["interval_seconds"] = interval

    # Prime once at startup so the first user request is faster.
    _PREWARM_STATUS["running"] = True
    try:
        await prewarm_base_data_cache(force=True)
        _PREWARM_STATUS["last_success_at"] = _utc_iso()
        _PREWARM_STATUS["run_count"] += 1
    except Exception as exc:
        _PREWARM_STATUS["last_error_at"] = _utc_iso()
        _PREWARM_STATUS["last_error"] = f"{type(exc).__name__}: {exc}"
        _PREWARM_STATUS["error_count"] += 1
        logger.exception("Initial analytics prewarm failed")
    finally:
        _PREWARM_STATUS["running"] = False

    while not stop_event.is_set():
        _PREWARM_STATUS["next_run_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=interval)
        ).isoformat()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

        _PREWARM_STATUS["running"] = True
        try:
            await prewarm_base_data_cache(force=True)
            _PREWARM_STATUS["last_success_at"] = _utc_iso()
            _PREWARM_STATUS["run_count"] += 1
        except Exception as exc:
            _PREWARM_STATUS["last_error_at"] = _utc_iso()
            _PREWARM_STATUS["last_error"] = f"{type(exc).__name__}: {exc}"
            _PREWARM_STATUS["error_count"] += 1
            logger.exception("Periodic analytics prewarm failed")
        finally:
            _PREWARM_STATUS["running"] = False
