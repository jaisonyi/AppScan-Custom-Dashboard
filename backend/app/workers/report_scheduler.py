from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from app.core.config.settings import settings
from app.repositories.postgres_store import (
    append_audit_event,
    append_report_history,
    list_due_report_schedules,
    update_report_schedule,
)
from app.services.report_artifacts import create_report_artifact
from app.workers.schedule_utils import compute_next_run_iso, utc_now

logger = logging.getLogger(__name__)


def _backoff_next_run(retry_count: int) -> str:
    delay = settings.report_scheduler_backoff_base_seconds * (2 ** max(retry_count - 1, 0))
    delay = min(delay, settings.report_scheduler_backoff_max_seconds)
    return (utc_now() + timedelta(seconds=delay)).isoformat()


async def run_scheduler(stop_event: asyncio.Event) -> None:
    logger.info("Report scheduler started (interval=%ss).", settings.report_scheduler_interval_seconds)
    try:
        while not stop_event.is_set():
            now_iso = utc_now().isoformat()
            due_schedules = list_due_report_schedules(now_iso)
            logger.debug("Scheduler tick at %s: %d due schedule(s) found.", now_iso, len(due_schedules))

            for schedule in due_schedules:
                schedule_id = schedule["id"]
                schedule_name = schedule["name"]
                logger.info(
                    "Executing schedule '%s' (id=%s, format=%s).",
                    schedule_name,
                    schedule_id,
                    schedule["format"],
                )
                try:
                    history = append_report_history(
                        report_id=f"r-{uuid4().hex[:8]}",
                        report_name=schedule_name,
                        output_format=schedule["format"],
                        status="completed",
                        requested_by="scheduler",
                        filters={"template_id": schedule.get("template_id")},
                        message="Scheduled report executed by background worker.",
                    )
                    create_report_artifact(
                        history["id"],
                        {
                            "report_id": history["id"],
                            "name": history["report_name"],
                            "format": history["format"],
                            "filters": history["filters"],
                            "status": history["status"],
                            "generated_at": history["created_at"],
                            "generated_by": "scheduler",
                        },
                    )
                    next_run = compute_next_run_iso(schedule["cron"])
                    update_report_schedule(
                        schedule_id=schedule_id,
                        next_run_at=next_run,
                        enabled=schedule["enabled"],
                        retry_count=0,
                        last_error="",
                        last_attempt_at=utc_now().isoformat(),
                    )
                    append_audit_event(
                        event_id=f"ae-{uuid4().hex[:10]}",
                        actor="scheduler",
                        action="report_schedule.execute",
                        resource_type="report_schedule",
                        resource_id=schedule_id,
                        details={
                            "report_id": history["id"],
                            "next_run_at": next_run,
                        },
                    )
                    logger.info(
                        "Schedule '%s' (id=%s) completed successfully. Next run: %s.",
                        schedule_name,
                        schedule_id,
                        next_run,
                    )
                except Exception as exc:
                    retry_count = int(schedule.get("retry_count") or 0) + 1
                    is_maxed = retry_count >= settings.report_scheduler_max_retries
                    next_run = None if is_maxed else _backoff_next_run(retry_count)
                    update_report_schedule(
                        schedule_id=schedule_id,
                        enabled=False if is_maxed else schedule["enabled"],
                        next_run_at=next_run,
                        retry_count=retry_count,
                        last_error=str(exc)[:500],
                        last_attempt_at=utc_now().isoformat(),
                    )
                    append_audit_event(
                        event_id=f"ae-{uuid4().hex[:10]}",
                        actor="scheduler",
                        action="report_schedule.retry" if not is_maxed else "report_schedule.disabled",
                        resource_type="report_schedule",
                        resource_id=schedule_id,
                        details={
                            "retry_count": retry_count,
                            "next_run_at": next_run,
                            "error": str(exc)[:500],
                        },
                    )
                    if is_maxed:
                        logger.error(
                            "Schedule '%s' (id=%s) has reached max retries (%d) and has been disabled. "
                            "Last error: %s",
                            schedule_name,
                            schedule_id,
                            settings.report_scheduler_max_retries,
                            exc,
                            exc_info=True,
                        )
                    else:
                        logger.warning(
                            "Schedule '%s' (id=%s) failed (retry %d/%d). "
                            "Next attempt at %s. Error: %s",
                            schedule_name,
                            schedule_id,
                            retry_count,
                            settings.report_scheduler_max_retries,
                            next_run,
                            exc,
                            exc_info=True,
                        )

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.report_scheduler_interval_seconds)
            except asyncio.TimeoutError:
                continue
    finally:
        logger.info("Report scheduler stopped.")
