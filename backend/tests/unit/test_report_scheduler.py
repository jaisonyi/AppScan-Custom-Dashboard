"""Unit tests for backend/app/workers/report_scheduler.py"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.workers.report_scheduler import _backoff_next_run, run_scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_schedule(
    schedule_id: str = "sched-1",
    name: str = "Daily Report",
    fmt: str = "pdf",
    cron: str = "0 9 * * *",
    enabled: bool = True,
    retry_count: int = 0,
    template_id: str | None = "tmpl-1",
) -> dict:
    return {
        "id": schedule_id,
        "name": name,
        "format": fmt,
        "cron": cron,
        "enabled": enabled,
        "retry_count": retry_count,
        "template_id": template_id,
    }


# ---------------------------------------------------------------------------
# _backoff_next_run tests
# ---------------------------------------------------------------------------


class TestBackoffNextRun:
    def test_backoff_next_run_first_retry(self, monkeypatch):
        """retry_count=1 returns delay equal to backoff_base_seconds."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        fixed_now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.workers.report_scheduler.utc_now", return_value=fixed_now):
            result = _backoff_next_run(retry_count=1)

        result_dt = datetime.fromisoformat(result)
        diff = (result_dt - fixed_now).total_seconds()
        # retry_count=1 → delay = 60 * 2^0 = 60
        assert diff == 60.0

    def test_backoff_next_run_second_retry(self, monkeypatch):
        """retry_count=2 returns delay equal to backoff_base_seconds * 2."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        fixed_now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.workers.report_scheduler.utc_now", return_value=fixed_now):
            result = _backoff_next_run(retry_count=2)

        result_dt = datetime.fromisoformat(result)
        diff = (result_dt - fixed_now).total_seconds()
        # retry_count=2 → delay = 60 * 2^1 = 120
        assert diff == 120.0

    def test_backoff_next_run_caps_at_max(self, monkeypatch):
        """High retry_count caps delay at backoff_max_seconds."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        fixed_now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        with patch("app.workers.report_scheduler.utc_now", return_value=fixed_now):
            result = _backoff_next_run(retry_count=100)

        result_dt = datetime.fromisoformat(result)
        diff = (result_dt - fixed_now).total_seconds()
        # Should be capped at 3600
        assert diff == 3600.0


# ---------------------------------------------------------------------------
# run_scheduler tests
# ---------------------------------------------------------------------------


class TestRunScheduler:
    """Tests for the run_scheduler async worker loop."""

    def _make_history(self, report_id: str = "r-abc12345") -> dict:
        return {
            "id": report_id,
            "report_name": "Daily Report",
            "format": "pdf",
            "filters": {"template_id": "tmpl-1"},
            "status": "completed",
            "created_at": "2025-06-01T09:00:00+00:00",
        }

    async def test_run_scheduler_stops_on_stop_event(self, monkeypatch):
        """stop_event.set() causes the scheduler loop to exit cleanly."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)

        stop_event = asyncio.Event()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", return_value=[]) as mock_list,
            patch("app.workers.report_scheduler.append_report_history"),
            patch("app.workers.report_scheduler.create_report_artifact"),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event"),
        ):
            # Set stop event immediately so the loop exits after first iteration
            stop_event.set()
            await run_scheduler(stop_event)

        # list_due_report_schedules should not have been called since stop was set before loop
        mock_list.assert_not_called()

    async def test_run_scheduler_executes_due_schedules(self, monkeypatch):
        """Due schedule triggers append_report_history and create_report_artifact."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 5)

        schedule = _make_schedule()
        history = self._make_history()

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_history = MagicMock(return_value=history)
        mock_artifact = MagicMock()
        mock_update = MagicMock()
        mock_audit = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", mock_history),
            patch("app.workers.report_scheduler.create_report_artifact", mock_artifact),
            patch("app.workers.report_scheduler.update_report_schedule", mock_update),
            patch("app.workers.report_scheduler.append_audit_event", mock_audit),
            patch("app.workers.report_scheduler.compute_next_run_iso", return_value="2025-06-02T09:00:00+00:00"),
        ):
            await run_scheduler(stop_event)

        mock_history.assert_called_once()
        mock_artifact.assert_called_once()

    async def test_run_scheduler_updates_next_run_after_success(self, monkeypatch):
        """Successful execution calls update_report_schedule with new next_run_at."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 5)

        schedule = _make_schedule()
        history = self._make_history()
        next_run = "2025-06-02T09:00:00+00:00"

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_update = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", return_value=history),
            patch("app.workers.report_scheduler.create_report_artifact"),
            patch("app.workers.report_scheduler.update_report_schedule", mock_update),
            patch("app.workers.report_scheduler.append_audit_event"),
            patch("app.workers.report_scheduler.compute_next_run_iso", return_value=next_run),
        ):
            await run_scheduler(stop_event)

        mock_update.assert_called_once_with(
            schedule_id="sched-1",
            next_run_at=next_run,
            enabled=True,
            retry_count=0,
            last_error="",
            last_attempt_at=mock_update.call_args.kwargs["last_attempt_at"],
        )

    async def test_run_scheduler_increments_retry_on_failure(self, monkeypatch):
        """create_report_artifact raises; retry_count is incremented in update."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 5)
        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        schedule = _make_schedule(retry_count=0)
        history = self._make_history()

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_update = MagicMock()
        mock_audit = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", return_value=history),
            patch("app.workers.report_scheduler.create_report_artifact", side_effect=RuntimeError("DB error")),
            patch("app.workers.report_scheduler.update_report_schedule", mock_update),
            patch("app.workers.report_scheduler.append_audit_event", mock_audit),
        ):
            await run_scheduler(stop_event)

        # retry_count should be incremented to 1
        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["retry_count"] == 1
        assert update_kwargs["enabled"] is True  # not yet maxed

    async def test_run_scheduler_disables_schedule_at_max_retries(self, monkeypatch):
        """retry_count >= max_retries sets enabled=False in update."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 3)
        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        # retry_count=2, max_retries=3 → after failure retry_count becomes 3 → maxed
        schedule = _make_schedule(retry_count=2)
        history = self._make_history()

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_update = MagicMock()
        mock_audit = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", return_value=history),
            patch("app.workers.report_scheduler.create_report_artifact", side_effect=RuntimeError("fail")),
            patch("app.workers.report_scheduler.update_report_schedule", mock_update),
            patch("app.workers.report_scheduler.append_audit_event", mock_audit),
        ):
            await run_scheduler(stop_event)

        update_kwargs = mock_update.call_args.kwargs
        assert update_kwargs["enabled"] is False
        assert update_kwargs["retry_count"] == 3
        assert update_kwargs["next_run_at"] is None

    async def test_run_scheduler_appends_audit_event_on_success(self, monkeypatch):
        """Success calls append_audit_event with action='report_schedule.execute'."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 5)

        schedule = _make_schedule()
        history = self._make_history()
        next_run = "2025-06-02T09:00:00+00:00"

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_audit = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", return_value=history),
            patch("app.workers.report_scheduler.create_report_artifact"),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event", mock_audit),
            patch("app.workers.report_scheduler.compute_next_run_iso", return_value=next_run),
        ):
            await run_scheduler(stop_event)

        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "report_schedule.execute"
        assert audit_kwargs["actor"] == "scheduler"
        assert audit_kwargs["resource_id"] == "sched-1"

    async def test_run_scheduler_appends_audit_event_on_retry(self, monkeypatch):
        """Failure (not maxed) calls append_audit_event with action='report_schedule.retry'."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 5)
        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        schedule = _make_schedule(retry_count=0)
        history = self._make_history()

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_audit = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", return_value=history),
            patch("app.workers.report_scheduler.create_report_artifact", side_effect=RuntimeError("fail")),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event", mock_audit),
        ):
            await run_scheduler(stop_event)

        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "report_schedule.retry"
        assert audit_kwargs["actor"] == "scheduler"

    async def test_run_scheduler_appends_audit_event_on_disable(self, monkeypatch):
        """Max retries reached calls append_audit_event with action='report_schedule.disabled'."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 3)
        monkeypatch.setattr(settings, "report_scheduler_backoff_base_seconds", 60)
        monkeypatch.setattr(settings, "report_scheduler_backoff_max_seconds", 3600)

        # retry_count=2 → after failure becomes 3 → maxed
        schedule = _make_schedule(retry_count=2)
        history = self._make_history()

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [schedule]
            stop_event.set()
            return []

        mock_audit = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", return_value=history),
            patch("app.workers.report_scheduler.create_report_artifact", side_effect=RuntimeError("fail")),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event", mock_audit),
        ):
            await run_scheduler(stop_event)

        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "report_schedule.disabled"

    async def test_run_scheduler_handles_no_due_schedules(self, monkeypatch):
        """When no schedules are due, no report history or artifacts are created."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            stop_event.set()
            return []

        mock_history = MagicMock()
        mock_artifact = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", mock_history),
            patch("app.workers.report_scheduler.create_report_artifact", mock_artifact),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event"),
        ):
            await run_scheduler(stop_event)

        mock_history.assert_not_called()
        mock_artifact.assert_not_called()

    async def test_run_scheduler_error_in_list_due_does_not_crash(self, monkeypatch):
        """Exception in list_due_report_schedules propagates out of the scheduler."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)

        stop_event = asyncio.Event()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=RuntimeError("DB down")),
            patch("app.workers.report_scheduler.append_report_history"),
            patch("app.workers.report_scheduler.create_report_artifact"),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event"),
        ):
            with pytest.raises(RuntimeError, match="DB down"):
                await run_scheduler(stop_event)

    async def test_run_scheduler_multiple_due_schedules(self, monkeypatch):
        """Multiple due schedules are all processed in a single tick."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "report_scheduler_interval_seconds", 0)
        monkeypatch.setattr(settings, "report_scheduler_max_retries", 5)

        schedules = [
            _make_schedule(schedule_id="sched-1", name="Report A"),
            _make_schedule(schedule_id="sched-2", name="Report B"),
        ]
        history = self._make_history()

        stop_event = asyncio.Event()
        call_count = 0

        def fake_list_due(now_iso):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return schedules
            stop_event.set()
            return []

        mock_history = MagicMock(return_value=history)
        mock_artifact = MagicMock()

        with (
            patch("app.workers.report_scheduler.list_due_report_schedules", side_effect=fake_list_due),
            patch("app.workers.report_scheduler.append_report_history", mock_history),
            patch("app.workers.report_scheduler.create_report_artifact", mock_artifact),
            patch("app.workers.report_scheduler.update_report_schedule"),
            patch("app.workers.report_scheduler.append_audit_event"),
            patch("app.workers.report_scheduler.compute_next_run_iso", return_value="2025-06-02T09:00:00+00:00"),
        ):
            await run_scheduler(stop_event)

        assert mock_history.call_count == 2
        assert mock_artifact.call_count == 2
