"""Unit tests for reports routes: templates, generate, history, schedules, download."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security.dependencies import UserContext, get_current_user
from app.main import app


# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------

def _admin() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])


def _security_manager() -> UserContext:
    return UserContext(subject="sm@test.com", role="SecurityManager", asset_group_ids=["ag-1"])


def _auditor() -> UserContext:
    return UserContext(subject="audit@test.com", role="Auditor", asset_group_ids=["ag-1"])


def _developer() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])


def _app_owner() -> UserContext:
    return UserContext(subject="owner@test.com", role="AppOwner", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_TEMPLATE = {
    "id": "rt-test-1",
    "name": "Security Report",
    "filters": {"asset_group_ids": ["ag-1"]},
    "created_by": "admin@test.com",
    "created_at": "2025-01-01T00:00:00+00:00",
}

FAKE_HISTORY_ROW = {
    "id": "r-test-1",
    "report_name": "Security Report",
    "format": "json",
    "status": "completed",
    "requested_by": "admin@test.com",
    "filters": {},
    "message": "",
    "created_at": "2025-01-01T00:00:00+00:00",
}

FAKE_ARTIFACT = {
    "id": "ra-test-1",
    "report_id": "r-test-1",
    "file_name": "r-test-1.json",
    "file_path": "r-test-1.json",
    "mime_type": "application/json",
    "created_at": "2025-01-01T00:00:00+00:00",
}

FAKE_SCHEDULE = {
    "id": "rs-test-1",
    "name": "Daily Security Report",
    "template_id": None,
    "cron": "0 8 * * *",
    "format": "json",
    "enabled": True,
    "next_run_at": "2025-01-02T08:00:00+00:00",
    "retry_count": 0,
    "last_error": "",
    "last_attempt_at": None,
    "created_by": "admin@test.com",
    "created_at": "2025-01-01T00:00:00+00:00",
}


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/reports/templates
# ---------------------------------------------------------------------------

class TestListReportTemplates:
    def test_list_report_templates_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.reports.list_report_template_rows", return_value=[FAKE_TEMPLATE]):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/reports/templates")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "rt-test-1"

    def test_list_report_templates_forbidden_for_developer(self):
        app.dependency_overrides[get_current_user] = _developer
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/reports/templates")
        app.dependency_overrides.clear()
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/reports/templates
# ---------------------------------------------------------------------------

class TestCreateReportTemplate:
    def test_create_report_template_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.reports.create_report_template_row", return_value=FAKE_TEMPLATE),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/v1/reports/templates",
                    json={"name": "Security Report", "filters": {"asset_group_ids": ["ag-1"]}},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["id"] == "rt-test-1"


# ---------------------------------------------------------------------------
# DELETE /api/v1/reports/templates/{id}
# ---------------------------------------------------------------------------

class TestDeleteReportTemplate:
    def test_delete_report_template_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.reports.delete_report_template_row", return_value=True),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.delete("/api/v1/reports/templates/rt-test-1")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"

    def test_delete_report_template_returns_404(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.reports.delete_report_template_row", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.delete("/api/v1/reports/templates/nonexistent")
        app.dependency_overrides.clear()
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/reports/generate
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_generate_report_returns_200_with_artifact(self):
        app.dependency_overrides[get_current_user] = _admin
        fake_artifact = {"file_name": "r-test-1.json", "report_id": "r-test-1"}
        with (
            patch("app.api.v1.routes.reports.append_report_history", return_value=FAKE_HISTORY_ROW),
            patch("app.api.v1.routes.reports.create_report_artifact", return_value=fake_artifact),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/v1/reports/generate",
                    json={"name": "Security Report", "filters": {}, "format": "json"},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "artifact" in data
        assert data["artifact"]["available"] is True

    def test_generate_report_forbidden_for_app_owner(self):
        app.dependency_overrides[get_current_user] = _app_owner
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/generate",
                json={"name": "Security Report", "filters": {}, "format": "json"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_generate_report_forbidden_for_developer(self):
        app.dependency_overrides[get_current_user] = _developer
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/generate",
                json={"name": "Security Report", "filters": {}, "format": "json"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/reports/history
# ---------------------------------------------------------------------------

class TestListReportHistory:
    def test_list_report_history_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.reports.list_report_history_rows", return_value=[FAKE_HISTORY_ROW]),
            patch("app.api.v1.routes.reports.report_artifact_map", return_value={"r-test-1": FAKE_ARTIFACT}),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/reports/history")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "artifact" in data[0]


# ---------------------------------------------------------------------------
# GET /api/v1/reports/history/{id}/download
# ---------------------------------------------------------------------------

class TestDownloadReportArtifact:
    def test_download_report_artifact_returns_404_when_missing(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.reports.get_report_artifact", return_value=None):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/reports/history/nonexistent/download")
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_download_report_artifact_returns_400_for_path_traversal(self):
        app.dependency_overrides[get_current_user] = _admin
        fake_artifact_bad_path = {**FAKE_ARTIFACT, "file_path": "../../etc/passwd"}
        with (
            patch("app.api.v1.routes.reports.get_report_artifact", return_value=fake_artifact_bad_path),
            patch("app.api.v1.routes.reports.resolve_artifact_path", side_effect=ValueError("path traversal")),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/reports/history/r-test-1/download")
        app.dependency_overrides.clear()
        assert resp.status_code == 400

    def test_download_report_artifact_returns_404_when_file_missing(self, tmp_path):
        app.dependency_overrides[get_current_user] = _admin
        nonexistent_path = tmp_path / "nonexistent.json"
        with (
            patch("app.api.v1.routes.reports.get_report_artifact", return_value=FAKE_ARTIFACT),
            patch("app.api.v1.routes.reports.resolve_artifact_path", return_value=nonexistent_path),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/reports/history/r-test-1/download")
        app.dependency_overrides.clear()
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/reports/schedules
# ---------------------------------------------------------------------------

class TestListReportSchedules:
    def test_list_report_schedules_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.reports.list_report_schedule_rows", return_value=[FAKE_SCHEDULE]):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/reports/schedules")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "rs-test-1"


# ---------------------------------------------------------------------------
# POST /api/v1/reports/schedules
# ---------------------------------------------------------------------------

class TestCreateReportSchedule:
    def test_create_report_schedule_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.reports.create_report_schedule_row", return_value=FAKE_SCHEDULE),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/v1/reports/schedules",
                    json={"name": "Daily Security Report", "cron": "0 8 * * *", "format": "json"},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["id"] == "rs-test-1"

    def test_create_report_schedule_returns_422_for_invalid_cron(self):
        app.dependency_overrides[get_current_user] = _admin
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/schedules",
                json={"name": "Bad Schedule", "cron": "not-a-cron", "format": "json"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_create_report_schedule_forbidden_for_auditor(self):
        app.dependency_overrides[get_current_user] = _auditor
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/reports/schedules",
                json={"name": "Daily Security Report", "cron": "0 8 * * *", "format": "json"},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/v1/reports/schedules/{id}
# ---------------------------------------------------------------------------

class TestUpdateReportSchedule:
    def test_update_report_schedule_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        updated = {**FAKE_SCHEDULE, "name": "Updated Schedule"}
        with (
            patch("app.api.v1.routes.reports.update_report_schedule_row", return_value=updated),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.put(
                    "/api/v1/reports/schedules/rs-test-1",
                    json={"name": "Updated Schedule"},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Schedule"

    def test_update_report_schedule_returns_404(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.reports.update_report_schedule_row", return_value=None):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.put(
                    "/api/v1/reports/schedules/nonexistent",
                    json={"name": "Updated"},
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/reports/schedules/{id}
# ---------------------------------------------------------------------------

class TestDeleteReportSchedule:
    def test_delete_report_schedule_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.reports.delete_report_schedule_row", return_value=True),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.delete("/api/v1/reports/schedules/rs-test-1")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"


# ---------------------------------------------------------------------------
# GET /api/v1/reports/schedules/monitor
# ---------------------------------------------------------------------------

class TestMonitorReportSchedules:
    def test_monitor_report_schedules_returns_health_summary(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.reports.list_report_schedule_rows", return_value=[FAKE_SCHEDULE]),
            patch("app.api.v1.routes.reports.latest_schedule_execution_map", return_value={}),
            patch("app.api.v1.routes.reports.list_report_history_rows", return_value=[]),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/reports/schedules/monitor")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "enabled" in data
        assert "unhealthy" in data
        assert "items" in data


# ---------------------------------------------------------------------------
# POST /api/v1/reports/schedules/{id}/run-now
# ---------------------------------------------------------------------------

class TestRunScheduleNow:
    def test_run_schedule_now_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        fake_artifact = {"file_name": "r-test-1.json", "report_id": "r-test-1"}
        with (
            patch("app.api.v1.routes.reports.list_report_schedule_rows", return_value=[FAKE_SCHEDULE]),
            patch("app.api.v1.routes.reports.append_report_history", return_value=FAKE_HISTORY_ROW),
            patch("app.api.v1.routes.reports.create_report_artifact", return_value=fake_artifact),
            patch("app.api.v1.routes.reports.update_report_schedule_row", return_value=FAKE_SCHEDULE),
            patch("app.api.v1.routes.reports.append_audit_event", return_value=None),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post("/api/v1/reports/schedules/rs-test-1/run-now")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "schedule" in data
        assert "history" in data

    def test_run_schedule_now_returns_404_for_unknown(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.reports.list_report_schedule_rows", return_value=[]):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/v1/reports/schedules/nonexistent/run-now")
        app.dependency_overrides.clear()
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helper function tests (pure logic)
# ---------------------------------------------------------------------------

class TestIsStale:
    def test_is_stale_returns_true_for_old_timestamp(self):
        from app.api.v1.routes.reports import _is_stale

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        assert _is_stale(old_ts) is True

    def test_is_stale_returns_false_for_recent_timestamp(self):
        from app.api.v1.routes.reports import _is_stale

        recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert _is_stale(recent_ts) is False

    def test_is_stale_returns_true_for_none(self):
        from app.api.v1.routes.reports import _is_stale

        assert _is_stale(None) is True

    def test_is_stale_returns_true_for_empty_string(self):
        from app.api.v1.routes.reports import _is_stale

        assert _is_stale("") is True
