"""Unit tests for dashboard routes: CRUD, versions, templates, wizard."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security.dependencies import UserContext, get_current_user
from app.main import app


# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------

def _admin() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1", "ag-2"])


def _security_manager() -> UserContext:
    return UserContext(subject="sm@test.com", role="SecurityManager", asset_group_ids=["ag-1"])


def _app_owner() -> UserContext:
    return UserContext(subject="owner@test.com", role="AppOwner", asset_group_ids=["ag-1"])


def _developer() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])


def _auditor() -> UserContext:
    return UserContext(subject="audit@test.com", role="Auditor", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_DASHBOARD = {
    "id": "d-test-1",
    "name": "Test Dashboard",
    "widgets": [{"type": "kpi_card", "title": "Issues"}],
    "blueprint": {"status": "draft", "visibility": "team"},
    "owner": "admin@test.com",
    "created_at": "2025-01-01T00:00:00+00:00",
    "updated_at": "2025-01-01T00:00:00+00:00",
}

FAKE_VERSION = {
    "id": "dv-test-1",
    "dashboard_id": "d-test-1",
    "version": 1,
    "name": "Test Dashboard",
    "widgets": [{"type": "kpi_card", "title": "Issues"}],
    "owner": "admin@test.com",
    "change_note": "initial creation",
    "created_at": "2025-01-01T00:00:00+00:00",
}

FAKE_TEMPLATE = {
    "id": "dt-test-1",
    "name": "Security Template",
    "description": "A security dashboard template",
    "scope": {},
    "layout": {},
    "widgets": [{"type": "kpi_card", "title": "Issues"}],
    "visibility": "team",
    "created_by": "admin@test.com",
    "created_at": "2025-01-01T00:00:00+00:00",
}


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


@pytest.fixture
def admin_client():
    app.dependency_overrides[get_current_user] = _admin
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def developer_client():
    app.dependency_overrides[get_current_user] = _developer
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auditor_client():
    app.dependency_overrides[get_current_user] = _auditor
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_client():
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ---------------------------------------------------------------------------
# GET /api/v1/dashboards
# ---------------------------------------------------------------------------

class TestListDashboards:
    def test_list_dashboards_returns_200(self, admin_client):
        with patch("app.api.v1.routes.dashboard.list_dashboard_rows", return_value=[FAKE_DASHBOARD]):
            resp = admin_client.get("/api/v1/dashboards")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "d-test-1"

    def test_list_dashboards_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/v1/dashboards")
        assert resp.status_code in (401, 403)

    def test_list_dashboards_returns_empty_list(self, admin_client):
        with patch("app.api.v1.routes.dashboard.list_dashboard_rows", return_value=[]):
            resp = admin_client.get("/api/v1/dashboards")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/v1/dashboards
# ---------------------------------------------------------------------------

class TestCreateDashboard:
    def test_create_dashboard_returns_200(self, admin_client):
        with (
            patch("app.api.v1.routes.dashboard.create_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.append_dashboard_version", return_value=None),
            patch("app.api.v1.routes.dashboard.append_audit_event", return_value=None),
        ):
            resp = admin_client.post(
                "/api/v1/dashboards",
                json={"name": "Test Dashboard", "widgets": [{"type": "kpi_card", "title": "Issues"}]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "d-test-1"

    def test_create_dashboard_forbidden_for_developer(self, developer_client):
        resp = developer_client.post(
            "/api/v1/dashboards",
            json={"name": "Test Dashboard", "widgets": []},
        )
        assert resp.status_code == 403

    def test_create_dashboard_forbidden_for_auditor(self, auditor_client):
        resp = auditor_client.post(
            "/api/v1/dashboards",
            json={"name": "Test Dashboard", "widgets": []},
        )
        assert resp.status_code == 403

    def test_create_dashboard_missing_name_returns_422(self, admin_client):
        resp = admin_client.post("/api/v1/dashboards", json={"widgets": []})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/v1/dashboards/{id}
# ---------------------------------------------------------------------------

class TestUpdateDashboard:
    def test_update_dashboard_returns_200(self, admin_client):
        updated = {**FAKE_DASHBOARD, "name": "Updated Dashboard"}
        with (
            patch("app.api.v1.routes.dashboard.get_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.update_dashboard_row", return_value=updated),
            patch("app.api.v1.routes.dashboard.append_dashboard_version", return_value=None),
            patch("app.api.v1.routes.dashboard.append_audit_event", return_value=None),
        ):
            resp = admin_client.put(
                "/api/v1/dashboards/d-test-1",
                json={"name": "Updated Dashboard"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Dashboard"

    def test_update_dashboard_returns_404_when_not_found(self, admin_client):
        with (
            patch("app.api.v1.routes.dashboard.get_dashboard_row", return_value=None),
            patch("app.api.v1.routes.dashboard.update_dashboard_row", return_value=None),
        ):
            resp = admin_client.put(
                "/api/v1/dashboards/nonexistent",
                json={"name": "Updated"},
            )
        assert resp.status_code == 404

    def test_update_dashboard_forbidden_for_developer(self, developer_client):
        resp = developer_client.put(
            "/api/v1/dashboards/d-test-1",
            json={"name": "Updated"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/v1/dashboards/{id}
# ---------------------------------------------------------------------------

class TestDeleteDashboard:
    def test_delete_dashboard_returns_200(self, admin_client):
        with (
            patch("app.api.v1.routes.dashboard.delete_dashboard_row", return_value=True),
            patch("app.api.v1.routes.dashboard.append_audit_event", return_value=None),
        ):
            resp = admin_client.delete("/api/v1/dashboards/d-test-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["id"] == "d-test-1"

    def test_delete_dashboard_returns_404_when_not_found(self, admin_client):
        with patch("app.api.v1.routes.dashboard.delete_dashboard_row", return_value=False):
            resp = admin_client.delete("/api/v1/dashboards/nonexistent")
        assert resp.status_code == 404

    def test_delete_dashboard_forbidden_for_developer(self, developer_client):
        resp = developer_client.delete("/api/v1/dashboards/d-test-1")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/dashboards/{id}/versions
# ---------------------------------------------------------------------------

class TestDashboardVersions:
    def test_list_dashboard_versions_returns_200(self, admin_client):
        with (
            patch("app.api.v1.routes.dashboard.get_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.list_dashboard_version_rows", return_value=[FAKE_VERSION]),
        ):
            resp = admin_client.get("/api/v1/dashboards/d-test-1/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["version"] == 1

    def test_list_dashboard_versions_returns_404_for_unknown_dashboard(self, admin_client):
        with patch("app.api.v1.routes.dashboard.get_dashboard_row", return_value=None):
            resp = admin_client.get("/api/v1/dashboards/nonexistent/versions")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/dashboards/{id}/rollback/{version}
# ---------------------------------------------------------------------------

class TestRollbackDashboardVersion:
    def test_rollback_dashboard_version_returns_200(self, admin_client):
        with (
            patch("app.api.v1.routes.dashboard.get_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.get_dashboard_version_row", return_value=FAKE_VERSION),
            patch("app.api.v1.routes.dashboard.update_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.append_dashboard_version", return_value=None),
            patch("app.api.v1.routes.dashboard.append_audit_event", return_value=None),
        ):
            resp = admin_client.post("/api/v1/dashboards/d-test-1/rollback/1")
        assert resp.status_code == 200

    def test_rollback_dashboard_version_returns_404_for_unknown_version(self, admin_client):
        with (
            patch("app.api.v1.routes.dashboard.get_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.get_dashboard_version_row", return_value=None),
        ):
            resp = admin_client.post("/api/v1/dashboards/d-test-1/rollback/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/dashboards/widget-registry
# ---------------------------------------------------------------------------

class TestWidgetRegistry:
    def test_list_widget_registry_returns_200(self, admin_client):
        fake_widgets = [
            {"type": "kpi_card", "title": "KPI Card", "category": "metrics",
             "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
             "default_config": {}},
        ]
        with (
            patch("app.api.v1.routes.dashboard.list_widgets", return_value=fake_widgets),
        ):
            resp = admin_client.get("/api/v1/dashboards/widget-registry")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data


# ---------------------------------------------------------------------------
# GET /api/v1/dashboards/templates
# ---------------------------------------------------------------------------

class TestDashboardTemplates:
    def test_list_dashboard_templates_returns_200(self, admin_client):
        with patch("app.api.v1.routes.dashboard.list_dashboard_template_rows", return_value=[FAKE_TEMPLATE]):
            resp = admin_client.get("/api/v1/dashboards/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_create_dashboard_template_forbidden_for_developer(self, developer_client):
        resp = developer_client.post(
            "/api/v1/dashboards/templates",
            json={
                "name": "My Template",
                "description": "A template",
                "widgets": [{"type": "kpi_card", "title": "Issues"}],
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/dashboards/wizard/create
# ---------------------------------------------------------------------------

class TestDashboardWizard:
    def test_create_dashboard_via_wizard_returns_200(self, admin_client):
        fake_widget_map = {
            "kpi_card": {
                "type": "kpi_card",
                "title": "KPI Card",
                "category": "metrics",
                "default_config": {},
            }
        }
        with (
            patch("app.api.v1.routes.dashboard.get_widget_map", return_value=fake_widget_map),
            patch("app.api.v1.routes.dashboard.create_dashboard_row", return_value=FAKE_DASHBOARD),
            patch("app.api.v1.routes.dashboard.append_dashboard_version", return_value=None),
            patch("app.api.v1.routes.dashboard.append_audit_event", return_value=None),
        ):
            resp = admin_client.post(
                "/api/v1/dashboards/wizard/create",
                json={
                    "name": "Wizard Dashboard",
                    "selected_widget_types": ["kpi_card"],
                    "asset_group_ids": ["ag-1"],
                },
            )
        assert resp.status_code == 200

    def test_create_dashboard_via_wizard_requires_valid_widgets(self, admin_client):
        """No valid widgets should return 400."""
        with patch("app.api.v1.routes.dashboard.get_widget_map", return_value={}):
            resp = admin_client.post(
                "/api/v1/dashboards/wizard/create",
                json={
                    "name": "Wizard Dashboard",
                    "selected_widget_types": ["nonexistent_widget"],
                    "asset_group_ids": ["ag-1"],
                },
            )
        assert resp.status_code == 400
        assert "widget" in resp.json()["detail"].lower()
