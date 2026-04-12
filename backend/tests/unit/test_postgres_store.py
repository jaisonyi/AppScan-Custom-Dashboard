"""Unit tests for app.repositories.postgres_store — PostgreSQL repository layer.

All tests use fully mocked database connections — no real PostgreSQL required.
The _connect() function is patched to return a MagicMock simulating _CompatConnection.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import app.repositories.postgres_store as store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_conn(fetchone_return=None, fetchall_return=None, rowcount=1):
    """Build a MagicMock that simulates _CompatConnection.

    The mock cursor is returned by conn.execute(), and supports:
    - .fetchone() -> fetchone_return
    - .fetchall() -> fetchall_return or []
    - .rowcount   -> rowcount
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_return
    cursor.fetchall.return_value = fetchall_return if fetchall_return is not None else []
    cursor.rowcount = rowcount

    conn = MagicMock()
    conn.execute.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Pure helper function tests (no DB needed)
# ---------------------------------------------------------------------------


def test_normalize_database_url_strips_psycopg_prefix() -> None:
    """`postgresql+psycopg://...` becomes `postgresql://...`."""
    result = store._normalize_database_url("postgresql+psycopg://user:pass@host/db")
    assert result == "postgresql://user:pass@host/db"


def test_normalize_database_url_leaves_plain_url_unchanged() -> None:
    """`postgresql://...` is returned unchanged."""
    url = "postgresql://user:pass@host/db"
    result = store._normalize_database_url(url)
    assert result == url


def test_normalize_database_url_leaves_postgres_scheme_unchanged() -> None:
    """`postgres://...` is returned unchanged."""
    url = "postgres://user:pass@host/db"
    result = store._normalize_database_url(url)
    assert result == url


def test_utc_now_returns_iso_string() -> None:
    """`_utc_now()` returns a valid ISO 8601 string with timezone info."""
    from datetime import datetime

    result = store._utc_now()
    assert isinstance(result, str)
    dt = datetime.fromisoformat(result)
    assert dt.tzinfo is not None


def test_as_driver_sql_replaces_question_marks() -> None:
    """`?` placeholders become `%s`."""
    result = store._as_driver_sql("SELECT * FROM t WHERE id = ? AND name = ?")
    assert result == "SELECT * FROM t WHERE id = %s AND name = %s"


def test_as_driver_sql_no_placeholders_unchanged() -> None:
    """SQL with no `?` is returned unchanged."""
    sql = "SELECT * FROM t"
    assert store._as_driver_sql(sql) == sql


# ---------------------------------------------------------------------------
# Dashboard CRUD
# ---------------------------------------------------------------------------


def test_list_dashboards_returns_parsed_rows() -> None:
    """Mock cursor returns rows; result is list of dicts with parsed JSON."""
    rows = [
        {
            "id": "d-1",
            "name": "My Dashboard",
            "widgets_json": json.dumps([{"type": "kpi_card"}]),
            "blueprint_json": json.dumps({"status": "draft"}),
            "owner": "admin@test.com",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_dashboards()

    assert len(result) == 1
    assert result[0]["id"] == "d-1"
    assert result[0]["widgets"] == [{"type": "kpi_card"}]
    assert result[0]["blueprint"] == {"status": "draft"}
    assert result[0]["owner"] == "admin@test.com"


def test_list_dashboards_returns_empty_list_when_no_rows() -> None:
    """Empty fetchall returns empty list."""
    conn, _ = _make_mock_conn(fetchall_return=[])

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_dashboards()

    assert result == []


def test_get_dashboard_returns_none_when_not_found() -> None:
    """`fetchone()` returns `None`; function returns `None`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_dashboard("nonexistent-id")

    assert result is None


def test_get_dashboard_returns_parsed_row() -> None:
    """`fetchone()` returns row; result is dict with parsed `widgets` and `blueprint`."""
    row = {
        "id": "d-1",
        "name": "Test",
        "widgets_json": json.dumps([{"type": "kpi_card"}]),
        "blueprint_json": json.dumps({"status": "published"}),
        "owner": "user@test.com",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-02T00:00:00+00:00",
    }
    conn, _ = _make_mock_conn(fetchone_return=row)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_dashboard("d-1")

    assert result is not None
    assert result["id"] == "d-1"
    assert result["widgets"] == [{"type": "kpi_card"}]
    assert result["blueprint"] == {"status": "published"}


def test_get_dashboard_handles_null_blueprint_json() -> None:
    """Row with None blueprint_json returns empty dict for blueprint."""
    row = {
        "id": "d-1",
        "name": "Test",
        "widgets_json": json.dumps([]),
        "blueprint_json": None,
        "owner": "user@test.com",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    conn, _ = _make_mock_conn(fetchone_return=row)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_dashboard("d-1")

    assert result["blueprint"] == {}


def test_create_dashboard_inserts_and_returns_dict() -> None:
    """`execute()` called with INSERT; returns dict with correct fields."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.create_dashboard(
            dashboard_id="d-new",
            name="New Dashboard",
            widgets=[{"type": "kpi_card"}],
            owner="admin@test.com",
            blueprint={"status": "draft"},
        )

    assert result["id"] == "d-new"
    assert result["name"] == "New Dashboard"
    assert result["widgets"] == [{"type": "kpi_card"}]
    assert result["blueprint"] == {"status": "draft"}
    assert result["owner"] == "admin@test.com"
    assert "created_at" in result
    assert "updated_at" in result
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_create_dashboard_uses_empty_blueprint_when_none() -> None:
    """blueprint=None defaults to empty dict."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.create_dashboard(
            dashboard_id="d-new",
            name="New Dashboard",
            widgets=[],
            owner="admin@test.com",
            blueprint=None,
        )

    assert result["blueprint"] == {}


def test_update_dashboard_returns_none_when_not_found() -> None:
    """`get_dashboard` returns `None`; `update_dashboard` returns `None`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.update_dashboard("nonexistent-id", name="New Name")

    assert result is None


def test_update_dashboard_applies_partial_update() -> None:
    """Only `name` provided; widgets remain unchanged."""
    existing_row = {
        "id": "d-1",
        "name": "Old Name",
        "widgets_json": json.dumps([{"type": "kpi_card"}]),
        "blueprint_json": json.dumps({"status": "draft"}),
        "owner": "admin@test.com",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    conn, _ = _make_mock_conn(fetchone_return=existing_row)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.update_dashboard("d-1", name="New Name")

    assert result is not None
    assert result["name"] == "New Name"
    assert result["widgets"] == [{"type": "kpi_card"}]  # unchanged


def test_delete_dashboard_returns_true_on_success() -> None:
    """`rowcount=1` returns `True`."""
    conn, cursor = _make_mock_conn(rowcount=1)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.delete_dashboard("d-1")

    assert result is True
    conn.commit.assert_called_once()


def test_delete_dashboard_returns_false_when_not_found() -> None:
    """`rowcount=0` returns `False`."""
    conn, cursor = _make_mock_conn(rowcount=0)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.delete_dashboard("nonexistent-id")

    assert result is False


# ---------------------------------------------------------------------------
# Dashboard versions
# ---------------------------------------------------------------------------


def test_append_dashboard_version_increments_version() -> None:
    """`_next_dashboard_version` returns max+1."""
    version_row = {"max_version": 2}
    conn = MagicMock()
    cursor_version = MagicMock()
    cursor_version.fetchone.return_value = version_row
    cursor_insert = MagicMock()
    conn.execute.side_effect = [cursor_version, cursor_insert]

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.append_dashboard_version(
            version_id="dv-3",
            dashboard_id="d-1",
            name="My Dashboard",
            widgets=[],
            owner="admin@test.com",
            change_note="Updated layout",
        )

    assert result["version"] == 3
    assert result["id"] == "dv-3"
    assert result["dashboard_id"] == "d-1"


def test_append_dashboard_version_starts_at_1_when_no_versions() -> None:
    """When no versions exist (max_version=None), version starts at 1."""
    version_row = {"max_version": None}
    conn = MagicMock()
    cursor_version = MagicMock()
    cursor_version.fetchone.return_value = version_row
    cursor_insert = MagicMock()
    conn.execute.side_effect = [cursor_version, cursor_insert]

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.append_dashboard_version(
            version_id="dv-1",
            dashboard_id="d-1",
            name="My Dashboard",
            widgets=[],
            owner="admin@test.com",
            change_note="Initial",
        )

    assert result["version"] == 1


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


def test_append_audit_event_inserts_and_returns_dict() -> None:
    """INSERT called; returns dict with all fields."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.append_audit_event(
            event_id="ae-1",
            actor="admin@test.com",
            action="dashboard.create",
            resource_type="dashboard",
            resource_id="d-1",
            details={"name": "Test"},
        )

    assert result["id"] == "ae-1"
    assert result["actor"] == "admin@test.com"
    assert result["action"] == "dashboard.create"
    assert result["resource_type"] == "dashboard"
    assert result["resource_id"] == "d-1"
    assert result["details"] == {"name": "Test"}
    assert "created_at" in result
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_count_audit_events_returns_integer() -> None:
    """`fetchone()` returns `{"c": 42}`; result is `42`."""
    conn, _ = _make_mock_conn(fetchone_return={"c": 42})

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.count_audit_events()

    assert result == 42


def test_count_audit_events_returns_zero_when_none() -> None:
    """`fetchone()` returns `None`; result is `0`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.count_audit_events()

    assert result == 0


def test_list_audit_events_with_limit_and_offset() -> None:
    """Correct SQL params passed for pagination."""
    rows = [
        {
            "id": "ae-1",
            "actor": "admin@test.com",
            "action": "dashboard.create",
            "resource_type": "dashboard",
            "resource_id": "d-1",
            "details_json": json.dumps({}),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, cursor = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_audit_events(limit=10, offset=20)

    assert len(result) == 1
    assert result[0]["id"] == "ae-1"
    assert result[0]["details"] == {}
    # Verify the execute was called with limit and offset params
    call_args = conn.execute.call_args
    params = call_args[0][1]
    assert 10 in params
    assert 20 in params


def test_list_audit_events_parses_details_json() -> None:
    """Rows with details_json are parsed to dict."""
    rows = [
        {
            "id": "ae-1",
            "actor": "user@test.com",
            "action": "report.generate",
            "resource_type": "report",
            "resource_id": "r-1",
            "details_json": json.dumps({"format": "pdf", "filters": {}}),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_audit_events()

    assert result[0]["details"] == {"format": "pdf", "filters": {}}


# ---------------------------------------------------------------------------
# Analytics snapshots
# ---------------------------------------------------------------------------


def test_upsert_analytics_snapshot_calls_upsert_sql() -> None:
    """ON CONFLICT DO UPDATE SQL is executed."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.upsert_analytics_snapshot(
            cache_key="key-1",
            payload={"data": [1, 2, 3]},
            fetched_at="2025-01-01T00:00:00+00:00",
            expires_at="2025-01-01T01:00:00+00:00",
        )

    assert result["cache_key"] == "key-1"
    assert result["payload"] == {"data": [1, 2, 3]}
    assert result["fetched_at"] == "2025-01-01T00:00:00+00:00"
    assert result["expires_at"] == "2025-01-01T01:00:00+00:00"
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()
    sql_called = conn.execute.call_args[0][0]
    assert "ON CONFLICT" in sql_called


def test_get_analytics_snapshot_returns_none_when_missing() -> None:
    """`fetchone()` returns `None`; result is `None`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_analytics_snapshot("missing-key")

    assert result is None


def test_get_analytics_snapshot_parses_payload_json() -> None:
    """Row with `payload_json` returns dict with parsed `payload`."""
    row = {
        "cache_key": "key-1",
        "payload_json": json.dumps({"issues": 42, "scans": 10}),
        "fetched_at": "2025-01-01T00:00:00+00:00",
        "expires_at": "2025-01-01T01:00:00+00:00",
    }
    conn, _ = _make_mock_conn(fetchone_return=row)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_analytics_snapshot("key-1")

    assert result is not None
    assert result["cache_key"] == "key-1"
    assert result["payload"] == {"issues": 42, "scans": 10}
    assert result["fetched_at"] == "2025-01-01T00:00:00+00:00"


def test_purge_expired_analytics_snapshots_returns_rowcount() -> None:
    """`rowcount=3` returns `3`."""
    conn, cursor = _make_mock_conn(rowcount=3)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.purge_expired_analytics_snapshots("2025-01-01T00:00:00+00:00")

    assert result == 3
    conn.commit.assert_called_once()


def test_purge_expired_analytics_snapshots_returns_zero_when_none_deleted() -> None:
    """`rowcount=0` returns `0`."""
    conn, cursor = _make_mock_conn(rowcount=0)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.purge_expired_analytics_snapshots("2025-01-01T00:00:00+00:00")

    assert result == 0


# ---------------------------------------------------------------------------
# Report artifacts
# ---------------------------------------------------------------------------


def test_report_artifact_map_returns_empty_for_empty_ids() -> None:
    """Empty list returns `{}` without DB call."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.report_artifact_map([])

    assert result == {}
    conn.execute.assert_not_called()


def test_report_artifact_map_returns_dict_keyed_by_report_id() -> None:
    """Rows returned are keyed by report_id."""
    rows = [
        {
            "report_id": "r-1",
            "file_name": "report.pdf",
            "file_path": "/exports/report.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1024,
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.report_artifact_map(["r-1"])

    assert "r-1" in result
    assert result["r-1"]["file_name"] == "report.pdf"
    assert result["r-1"]["size_bytes"] == 1024


def test_upsert_report_artifact_calls_upsert_sql() -> None:
    """ON CONFLICT DO UPDATE SQL is executed."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.upsert_report_artifact(
            report_id="r-1",
            file_name="report.pdf",
            file_path="/exports/report.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
        )

    assert result["report_id"] == "r-1"
    assert result["file_name"] == "report.pdf"
    assert result["size_bytes"] == 2048
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()
    sql_called = conn.execute.call_args[0][0]
    assert "ON CONFLICT" in sql_called


def test_get_report_artifact_returns_none_when_not_found() -> None:
    """`fetchone()` returns `None`; result is `None`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_report_artifact("nonexistent-id")

    assert result is None


def test_get_report_artifact_returns_parsed_row() -> None:
    """Row returned is parsed to dict with correct fields."""
    row = {
        "report_id": "r-1",
        "file_name": "report.pdf",
        "file_path": "/exports/report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 4096,
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    conn, _ = _make_mock_conn(fetchone_return=row)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_report_artifact("r-1")

    assert result is not None
    assert result["report_id"] == "r-1"
    assert result["size_bytes"] == 4096


# ---------------------------------------------------------------------------
# Report schedules
# ---------------------------------------------------------------------------


def test_list_due_report_schedules_filters_by_enabled_and_next_run() -> None:
    """SQL WHERE clause filters by enabled=1 and next_run_at <= now_iso."""
    rows = [
        {
            "id": "sched-1",
            "name": "Daily Report",
            "template_id": "rt-1",
            "cron": "0 8 * * *",
            "format": "pdf",
            "enabled": 1,
            "next_run_at": "2025-01-01T08:00:00+00:00",
            "retry_count": 0,
            "last_error": "",
            "last_attempt_at": None,
            "created_by": "admin@test.com",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_due_report_schedules("2025-01-01T09:00:00+00:00")

    assert len(result) == 1
    assert result[0]["id"] == "sched-1"
    assert result[0]["enabled"] is True
    assert result[0]["retry_count"] == 0
    sql_called = conn.execute.call_args[0][0]
    assert "enabled = 1" in sql_called
    assert "next_run_at" in sql_called


def test_list_report_schedules_returns_parsed_rows() -> None:
    """Rows with `enabled=1` return `enabled=True` in result."""
    rows = [
        {
            "id": "sched-1",
            "name": "Weekly Report",
            "template_id": "rt-1",
            "cron": "0 8 * * 1",
            "format": "json",
            "enabled": 1,
            "next_run_at": "2025-01-06T08:00:00+00:00",
            "retry_count": 2,
            "last_error": "timeout",
            "last_attempt_at": "2025-01-05T08:00:00+00:00",
            "created_by": "admin@test.com",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-05T08:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_report_schedules()

    assert len(result) == 1
    assert result[0]["enabled"] is True  # int 1 -> bool True
    assert result[0]["retry_count"] == 2
    assert result[0]["last_error"] == "timeout"


def test_list_report_schedules_enabled_false_for_zero() -> None:
    """Rows with `enabled=0` return `enabled=False` in result."""
    rows = [
        {
            "id": "sched-2",
            "name": "Disabled Report",
            "template_id": None,
            "cron": "0 8 * * *",
            "format": "pdf",
            "enabled": 0,
            "next_run_at": None,
            "retry_count": 0,
            "last_error": None,
            "last_attempt_at": None,
            "created_by": "admin@test.com",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_report_schedules()

    assert result[0]["enabled"] is False
    assert result[0]["last_error"] == ""  # None -> ""


def test_create_report_schedule_inserts_and_returns_dict() -> None:
    """INSERT called; returns dict with correct fields."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.create_report_schedule(
            schedule_id="sched-new",
            name="New Schedule",
            template_id="rt-1",
            cron="0 8 * * *",
            output_format="pdf",
            enabled=True,
            next_run_at="2025-01-02T08:00:00+00:00",
            created_by="admin@test.com",
        )

    assert result["id"] == "sched-new"
    assert result["name"] == "New Schedule"
    assert result["enabled"] is True
    assert result["retry_count"] == 0
    assert result["last_error"] == ""
    assert result["last_attempt_at"] is None
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_delete_report_schedule_returns_true_on_success() -> None:
    """`rowcount=1` returns `True`."""
    conn, cursor = _make_mock_conn(rowcount=1)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.delete_report_schedule("sched-1")

    assert result is True


def test_delete_report_schedule_returns_false_when_not_found() -> None:
    """`rowcount=0` returns `False`."""
    conn, cursor = _make_mock_conn(rowcount=0)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.delete_report_schedule("nonexistent-id")

    assert result is False


def test_update_report_schedule_returns_none_when_not_found() -> None:
    """`fetchone()` returns `None`; `update_report_schedule` returns `None`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.update_report_schedule("nonexistent-id", name="New Name")

    assert result is None


def test_update_report_schedule_applies_partial_update() -> None:
    """Only `enabled` provided; other fields remain unchanged."""
    existing_row = {
        "id": "sched-1",
        "name": "Old Name",
        "template_id": "rt-1",
        "cron": "0 8 * * *",
        "format": "pdf",
        "enabled": 1,
        "next_run_at": "2025-01-02T08:00:00+00:00",
        "retry_count": 0,
        "last_error": "",
        "last_attempt_at": None,
        "created_by": "admin@test.com",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    conn = MagicMock()
    cursor_select = MagicMock()
    cursor_select.fetchone.return_value = existing_row
    cursor_update = MagicMock()
    conn.execute.side_effect = [cursor_select, cursor_update]

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.update_report_schedule("sched-1", enabled=False)

    assert result is not None
    assert result["enabled"] is False
    assert result["name"] == "Old Name"  # unchanged
    assert result["cron"] == "0 8 * * *"  # unchanged


# ---------------------------------------------------------------------------
# Report history
# ---------------------------------------------------------------------------


def test_append_report_history_inserts_and_returns_dict() -> None:
    """INSERT called; returns dict with all fields."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.append_report_history(
            report_id="r-1",
            report_name="Monthly Risk Summary",
            output_format="pdf",
            status="completed",
            requested_by="admin@test.com",
            filters={"severity": ["high", "critical"]},
            message="Report generated successfully",
        )

    assert result["id"] == "r-1"
    assert result["report_name"] == "Monthly Risk Summary"
    assert result["format"] == "pdf"
    assert result["status"] == "completed"
    assert result["requested_by"] == "admin@test.com"
    assert result["filters"] == {"severity": ["high", "critical"]}
    assert result["message"] == "Report generated successfully"
    assert "created_at" in result
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_list_report_history_returns_parsed_rows() -> None:
    """Rows returned are parsed with filters_json decoded."""
    rows = [
        {
            "id": "r-1",
            "report_name": "Monthly Risk Summary",
            "format": "pdf",
            "status": "completed",
            "requested_by": "admin@test.com",
            "filters_json": json.dumps({"severity": ["high"]}),
            "message": "Done",
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_report_history(limit=50)

    assert len(result) == 1
    assert result[0]["id"] == "r-1"
    assert result[0]["filters"] == {"severity": ["high"]}


# ---------------------------------------------------------------------------
# Report templates
# ---------------------------------------------------------------------------


def test_list_report_templates_returns_parsed_rows() -> None:
    """Rows returned are parsed with filters_json decoded."""
    rows = [
        {
            "id": "rt-1",
            "name": "Monthly Risk Summary",
            "filters_json": json.dumps({"severity": ["high", "critical"]}),
            "created_by": "system",
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.list_report_templates()

    assert len(result) == 1
    assert result[0]["id"] == "rt-1"
    assert result[0]["filters"] == {"severity": ["high", "critical"]}


def test_create_report_template_inserts_and_returns_dict() -> None:
    """INSERT called; returns dict with correct fields."""
    conn, _ = _make_mock_conn()

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.create_report_template(
            template_id="rt-new",
            name="New Template",
            filters={"severity": ["critical"]},
            created_by="admin@test.com",
        )

    assert result["id"] == "rt-new"
    assert result["name"] == "New Template"
    assert result["filters"] == {"severity": ["critical"]}
    assert result["created_by"] == "admin@test.com"
    assert "created_at" in result
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_delete_report_template_returns_true_on_success() -> None:
    """`rowcount=1` returns `True`."""
    conn, cursor = _make_mock_conn(rowcount=1)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.delete_report_template("rt-1")

    assert result is True


def test_delete_report_template_returns_false_when_not_found() -> None:
    """`rowcount=0` returns `False`."""
    conn, cursor = _make_mock_conn(rowcount=0)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.delete_report_template("nonexistent-id")

    assert result is False


# ---------------------------------------------------------------------------
# latest_schedule_execution_map
# ---------------------------------------------------------------------------


def test_latest_schedule_execution_map_groups_by_resource_id() -> None:
    """Aggregation query result is parsed correctly."""
    rows = [
        {"resource_id": "sched-1", "last_executed_at": "2025-01-05T08:00:00+00:00"},
        {"resource_id": "sched-2", "last_executed_at": "2025-01-06T08:00:00+00:00"},
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.latest_schedule_execution_map()

    assert result == {
        "sched-1": "2025-01-05T08:00:00+00:00",
        "sched-2": "2025-01-06T08:00:00+00:00",
    }


def test_latest_schedule_execution_map_skips_null_values() -> None:
    """Rows with None resource_id or last_executed_at are skipped."""
    rows = [
        {"resource_id": "sched-1", "last_executed_at": "2025-01-05T08:00:00+00:00"},
        {"resource_id": None, "last_executed_at": "2025-01-06T08:00:00+00:00"},
        {"resource_id": "sched-3", "last_executed_at": None},
    ]
    conn, _ = _make_mock_conn(fetchall_return=rows)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.latest_schedule_execution_map()

    assert len(result) == 1
    assert "sched-1" in result


def test_latest_schedule_execution_map_returns_empty_when_no_rows() -> None:
    """Empty rows returns empty dict."""
    conn, _ = _make_mock_conn(fetchall_return=[])

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.latest_schedule_execution_map()

    assert result == {}


# ---------------------------------------------------------------------------
# get_latest_analytics_snapshot
# ---------------------------------------------------------------------------


def test_get_latest_analytics_snapshot_returns_none_when_empty() -> None:
    """`fetchone()` returns `None`; result is `None`."""
    conn, _ = _make_mock_conn(fetchone_return=None)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_latest_analytics_snapshot()

    assert result is None


def test_get_latest_analytics_snapshot_returns_parsed_row() -> None:
    """Row returned is parsed with payload_json decoded."""
    row = {
        "cache_key": "base_data",
        "payload_json": json.dumps({"scans": [], "issues": []}),
        "fetched_at": "2025-01-01T00:00:00+00:00",
        "expires_at": "2025-01-01T01:00:00+00:00",
    }
    conn, _ = _make_mock_conn(fetchone_return=row)

    with patch("app.repositories.postgres_store._connect", return_value=conn):
        result = store.get_latest_analytics_snapshot()

    assert result is not None
    assert result["cache_key"] == "base_data"
    assert result["payload"] == {"scans": [], "issues": []}


# ---------------------------------------------------------------------------
# _close_connection (atexit cleanup)
# ---------------------------------------------------------------------------


def test_close_connection_sets_global_to_none() -> None:
    """_close_connection() sets _CONNECTION to None after closing."""
    mock_conn = MagicMock()
    mock_conn.closed = False

    original = store._CONNECTION
    store._CONNECTION = mock_conn
    try:
        store._close_connection()
        assert store._CONNECTION is None
        mock_conn.close.assert_called_once()
    finally:
        store._CONNECTION = original


def test_close_connection_is_noop_when_already_none() -> None:
    """_close_connection() does nothing when _CONNECTION is None."""
    original = store._CONNECTION
    store._CONNECTION = None
    try:
        store._close_connection()  # should not raise
        assert store._CONNECTION is None
    finally:
        store._CONNECTION = original


def test_close_connection_is_noop_when_already_closed() -> None:
    """_close_connection() does nothing when connection is already closed."""
    mock_conn = MagicMock()
    mock_conn.closed = True

    original = store._CONNECTION
    store._CONNECTION = mock_conn
    try:
        store._close_connection()
        mock_conn.close.assert_not_called()
    finally:
        store._CONNECTION = original
