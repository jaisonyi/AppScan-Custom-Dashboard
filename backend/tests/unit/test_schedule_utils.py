"""Unit tests for backend/app/workers/schedule_utils.py"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.workers.schedule_utils import compute_next_run_iso, ensure_valid_cron, utc_now


class TestUtcNow:
    def test_utc_now_returns_utc_datetime(self):
        """utc_now() returns a timezone-aware datetime in UTC."""
        result = utc_now()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc

    def test_utc_now_is_recent(self):
        """utc_now() returns a datetime close to the current time."""
        before = datetime.now(timezone.utc)
        result = utc_now()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


class TestEnsureValidCron:
    def test_ensure_valid_cron_accepts_valid_expression(self):
        """'0 * * * *' is a valid cron expression and raises no exception."""
        # Should not raise
        ensure_valid_cron("0 * * * *")

    def test_ensure_valid_cron_accepts_daily_expression(self):
        """'0 9 * * *' (daily at 9am) is valid and raises no exception."""
        ensure_valid_cron("0 9 * * *")

    def test_ensure_valid_cron_accepts_weekly_expression(self):
        """'0 0 * * 1' (every Monday midnight) is valid."""
        ensure_valid_cron("0 0 * * 1")

    def test_ensure_valid_cron_accepts_monthly_expression(self):
        """'0 0 1 * *' (first of every month) is valid."""
        ensure_valid_cron("0 0 1 * *")

    def test_ensure_valid_cron_raises_for_invalid_expression(self):
        """'not-a-cron' is not a valid cron expression and raises an exception."""
        with pytest.raises(Exception):
            ensure_valid_cron("not-a-cron")

    def test_ensure_valid_cron_raises_for_too_few_fields(self):
        """A cron expression with too few fields raises an exception."""
        with pytest.raises(Exception):
            ensure_valid_cron("* * *")

    def test_ensure_valid_cron_raises_for_out_of_range_minute(self):
        """Minute value 60 is out of range and raises an exception."""
        with pytest.raises(Exception):
            ensure_valid_cron("60 * * * *")


class TestComputeNextRunIso:
    def test_compute_next_run_iso_returns_future_datetime(self):
        """Next run is after the base datetime."""
        base_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run_iso("0 * * * *", base_dt=base_dt)
        next_dt = datetime.fromisoformat(result)
        assert next_dt > base_dt

    def test_compute_next_run_iso_returns_utc_iso_string(self):
        """Result is a valid ISO 8601 string with UTC offset."""
        base_dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = compute_next_run_iso("0 * * * *", base_dt=base_dt)
        # Should be parseable as ISO 8601
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None
        # Should be UTC (offset +00:00)
        assert parsed.utcoffset().total_seconds() == 0

    def test_compute_next_run_iso_uses_provided_base_dt(self):
        """Custom base_dt returns next run relative to it, not current time."""
        # Use a fixed past date as base
        base_dt = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run_iso("0 9 * * *", base_dt=base_dt)
        next_dt = datetime.fromisoformat(result)
        # Next run should be 2020-01-01 09:00:00 UTC
        expected = datetime(2020, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        assert next_dt == expected

    def test_compute_next_run_iso_hourly_cron(self):
        """'0 * * * *' returns next run within 1 hour of base_dt."""
        base_dt = datetime(2025, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        result = compute_next_run_iso("0 * * * *", base_dt=base_dt)
        next_dt = datetime.fromisoformat(result)
        diff_seconds = (next_dt - base_dt).total_seconds()
        assert 0 < diff_seconds <= 3600

    def test_compute_next_run_iso_uses_utc_now_when_no_base_dt(self):
        """When base_dt is None, uses current UTC time as base."""
        before = datetime.now(timezone.utc)
        result = compute_next_run_iso("0 * * * *")
        after = datetime.now(timezone.utc)
        next_dt = datetime.fromisoformat(result)
        # Next run must be after 'before' and within 1 hour of 'after'
        assert next_dt > before
        assert (next_dt - after).total_seconds() <= 3600

    def test_compute_next_run_iso_midnight_cron(self):
        """'0 0 * * *' (midnight daily) returns next midnight after base_dt."""
        base_dt = datetime(2025, 5, 10, 15, 0, 0, tzinfo=timezone.utc)
        result = compute_next_run_iso("0 0 * * *", base_dt=base_dt)
        next_dt = datetime.fromisoformat(result)
        # Next midnight after 2025-05-10 15:00 UTC is 2025-05-11 00:00 UTC
        expected = datetime(2025, 5, 11, 0, 0, 0, tzinfo=timezone.utc)
        assert next_dt == expected

    def test_compute_next_run_iso_end_of_month(self):
        """Cron on last day of month correctly advances to next month."""
        # Base: Jan 31, 2025 at 12:00 UTC
        base_dt = datetime(2025, 1, 31, 12, 0, 0, tzinfo=timezone.utc)
        # Run at midnight on the 1st of each month
        result = compute_next_run_iso("0 0 1 * *", base_dt=base_dt)
        next_dt = datetime.fromisoformat(result)
        # Next run should be Feb 1, 2025 00:00 UTC
        expected = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert next_dt == expected
