"""Unit tests for audit routes: GET /audit/events with pagination and RBAC."""
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

FAKE_AUDIT_EVENT = {
    "id": "ae-test-1",
    "actor": "admin@test.com",
    "action": "dashboard.create",
    "resource_type": "dashboard",
    "resource_id": "d-test-1",
    "details": {},
    "created_at": "2025-01-01T00:00:00+00:00",
}


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


def _make_client(user_factory, raise_server_exceptions=True):
    app.dependency_overrides[get_current_user] = user_factory
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return client


# ---------------------------------------------------------------------------
# GET /api/v1/audit/events
# ---------------------------------------------------------------------------

class TestListAuditEvents:
    def test_list_audit_events_returns_paginated_envelope(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.audit.list_audit_event_rows", return_value=[FAKE_AUDIT_EVENT]),
            patch("app.api.v1.routes.audit.count_audit_events", return_value=1),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/audit/events")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "offset" in data
        assert "limit" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_audit_events_default_pagination(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.audit.list_audit_event_rows", return_value=[]) as mock_list,
            patch("app.api.v1.routes.audit.count_audit_events", return_value=0),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/audit/events")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 200
        assert data["offset"] == 0
        # Verify the store was called with default params
        mock_list.assert_called_once_with(limit=200, offset=0)

    def test_list_audit_events_custom_pagination(self):
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.audit.list_audit_event_rows", return_value=[]) as mock_list,
            patch("app.api.v1.routes.audit.count_audit_events", return_value=50),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/audit/events?limit=10&offset=5")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 5
        mock_list.assert_called_once_with(limit=10, offset=5)

    def test_list_audit_events_forbidden_for_developer(self):
        app.dependency_overrides[get_current_user] = _developer
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit/events")
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_list_audit_events_forbidden_for_app_owner(self):
        app.dependency_overrides[get_current_user] = _app_owner
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit/events")
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_list_audit_events_allowed_for_auditor(self):
        app.dependency_overrides[get_current_user] = _auditor
        with (
            patch("app.api.v1.routes.audit.list_audit_event_rows", return_value=[FAKE_AUDIT_EVENT]),
            patch("app.api.v1.routes.audit.count_audit_events", return_value=1),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/audit/events")
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_audit_events_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit/events")
        assert resp.status_code in (401, 403)

    def test_list_audit_events_allowed_for_security_manager(self):
        app.dependency_overrides[get_current_user] = _security_manager
        with (
            patch("app.api.v1.routes.audit.list_audit_event_rows", return_value=[]),
            patch("app.api.v1.routes.audit.count_audit_events", return_value=0),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/audit/events")
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_audit_events_limit_capped_at_1000(self):
        """limit > 1000 should return 422 (FastAPI validation)."""
        app.dependency_overrides[get_current_user] = _admin
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/audit/events?limit=9999")
        app.dependency_overrides.clear()
        assert resp.status_code == 422
