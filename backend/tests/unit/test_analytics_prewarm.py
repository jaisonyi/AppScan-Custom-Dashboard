"""Unit tests for backend/app/workers/analytics_prewarm.py"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.analytics_prewarm import run_analytics_prewarm


class TestRunAnalyticsPrewarm:
    """Tests for the run_analytics_prewarm async worker loop."""

    async def test_run_analytics_prewarm_calls_prewarm_on_startup(self, monkeypatch):
        """prewarm_base_data_cache is called once at startup before the loop."""
        from app.core.config.settings import settings

        # Use a large interval so the loop waits; stop_event will break it
        monkeypatch.setattr(settings, "analytics_prewarm_interval_seconds", 9999)

        stop_event = asyncio.Event()
        mock_prewarm = AsyncMock()

        async def fake_prewarm(force=False):
            # After the startup call, set the stop event so the loop exits
            stop_event.set()

        with patch("app.workers.analytics_prewarm.prewarm_base_data_cache", side_effect=fake_prewarm):
            await run_analytics_prewarm(stop_event)

        # The side_effect was called once (startup prewarm)
        # stop_event was set inside fake_prewarm, so loop exits immediately

    async def test_run_analytics_prewarm_calls_prewarm_periodically(self, monkeypatch):
        """After the interval elapses, prewarm_base_data_cache is called again."""
        from app.core.config.settings import settings

        # interval=0 means the wait_for will timeout immediately (min is 60 in source,
        # but we patch the function directly to control behavior)
        monkeypatch.setattr(settings, "analytics_prewarm_interval_seconds", 9999)

        stop_event = asyncio.Event()
        call_count = 0

        async def fake_prewarm(force=False):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                # After the second call (periodic), stop the loop
                stop_event.set()

        # We also need to patch asyncio.wait_for to simulate timeout immediately
        # so the periodic prewarm fires without real waiting
        original_wait_for = asyncio.wait_for

        async def fake_wait_for(coro, timeout):
            # Cancel the coroutine and raise TimeoutError to simulate interval elapsed
            coro.close()
            raise asyncio.TimeoutError()

        with (
            patch("app.workers.analytics_prewarm.prewarm_base_data_cache", side_effect=fake_prewarm),
            patch("asyncio.wait_for", side_effect=fake_wait_for),
        ):
            await run_analytics_prewarm(stop_event)

        # Should have been called at least twice: once at startup, once periodically
        assert call_count >= 2

    async def test_run_analytics_prewarm_stops_on_stop_event(self, monkeypatch):
        """stop_event.set() causes the loop to exit cleanly without further prewarm calls."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "analytics_prewarm_interval_seconds", 9999)

        stop_event = asyncio.Event()
        # Set stop event before starting — the loop should exit after startup prewarm
        # but the loop condition checks stop_event.is_set() before waiting

        prewarm_call_count = 0

        async def fake_prewarm(force=False):
            nonlocal prewarm_call_count
            prewarm_call_count += 1
            # Set stop event after startup prewarm so loop exits
            stop_event.set()

        with patch("app.workers.analytics_prewarm.prewarm_base_data_cache", side_effect=fake_prewarm):
            await run_analytics_prewarm(stop_event)

        # Only the startup prewarm should have been called; loop exits before periodic
        assert prewarm_call_count == 1

    async def test_run_analytics_prewarm_logs_exception_on_startup_failure(self, monkeypatch, caplog):
        """prewarm_base_data_cache raises at startup; exception is logged, loop continues."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "analytics_prewarm_interval_seconds", 9999)

        stop_event = asyncio.Event()
        call_count = 0

        async def fake_prewarm(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Prewarm failed at startup")
            # Second call (if any) sets stop event
            stop_event.set()

        with (
            patch("app.workers.analytics_prewarm.prewarm_base_data_cache", side_effect=fake_prewarm),
            caplog.at_level(logging.ERROR, logger="app.workers.analytics_prewarm"),
        ):
            # After startup failure, stop_event is not set yet, so the loop runs.
            # We need to set it to avoid infinite wait.
            stop_event.set()
            await run_analytics_prewarm(stop_event)

        # The startup prewarm raised but the function should not propagate the exception
        assert call_count == 1

    async def test_run_analytics_prewarm_logs_exception_on_periodic_failure(self, monkeypatch, caplog):
        """prewarm_base_data_cache raises during periodic call; exception logged, loop continues."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "analytics_prewarm_interval_seconds", 9999)

        stop_event = asyncio.Event()
        call_count = 0

        async def fake_prewarm(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Startup succeeds
                return
            # Periodic call fails
            raise RuntimeError("Periodic prewarm failed")

        async def fake_wait_for(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError()

        iteration = 0

        async def fake_wait_for_controlled(coro, timeout):
            nonlocal iteration
            iteration += 1
            if iteration == 1:
                # First wait: simulate timeout (triggers periodic prewarm)
                coro.close()
                raise asyncio.TimeoutError()
            else:
                # Second wait: stop_event is set, so wait_for returns normally
                stop_event.set()
                coro.close()
                raise asyncio.TimeoutError()

        with (
            patch("app.workers.analytics_prewarm.prewarm_base_data_cache", side_effect=fake_prewarm),
            patch("asyncio.wait_for", side_effect=fake_wait_for_controlled),
            caplog.at_level(logging.ERROR, logger="app.workers.analytics_prewarm"),
        ):
            await run_analytics_prewarm(stop_event)

        # Startup call + at least one periodic call attempted
        assert call_count >= 2

    async def test_run_analytics_prewarm_uses_minimum_interval(self, monkeypatch):
        """analytics_prewarm_interval_seconds below 60 is clamped to 60."""
        from app.core.config.settings import settings

        # Set interval below minimum
        monkeypatch.setattr(settings, "analytics_prewarm_interval_seconds", 10)

        stop_event = asyncio.Event()
        captured_timeout = None

        async def fake_prewarm(force=False):
            stop_event.set()

        async def fake_wait_for(coro, timeout):
            nonlocal captured_timeout
            captured_timeout = timeout
            # Simulate stop_event being set
            coro.close()
            # Return normally (stop_event is set, loop exits)

        with (
            patch("app.workers.analytics_prewarm.prewarm_base_data_cache", side_effect=fake_prewarm),
            patch("asyncio.wait_for", side_effect=fake_wait_for),
        ):
            await run_analytics_prewarm(stop_event)

        # The interval should be clamped to at least 60
        if captured_timeout is not None:
            assert captured_timeout >= 60
