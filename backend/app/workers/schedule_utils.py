from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_valid_cron(cron_expr: str) -> None:
    croniter(cron_expr, utc_now())


def compute_next_run_iso(cron_expr: str, base_dt: datetime | None = None) -> str:
    base = base_dt or utc_now()
    itr = croniter(cron_expr, base)
    next_dt = itr.get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=timezone.utc)
    return next_dt.astimezone(timezone.utc).isoformat()
