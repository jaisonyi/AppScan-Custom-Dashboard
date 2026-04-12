"""Unit tests for applications proxy route: GET /applications."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security.dependencies import UserContext, get_current_user
from app.main import app


# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------

def _admin() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1", "ag-2"])


def _app_owner() -> UserContext:
    """AppOwner only has access to ag-1."""
    return UserContext(subject="owner@test.com", role="AppOwner", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_APPLICATIONS = [
    {"id": "app-1", "name": "Payments API", "asset_group_id": "ag-1"},
    {"id": "app-2", "name": "Portal Web", "asset_group_id": "ag-2"},
]


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/applications
# ---------------------------------------------------------------------------

class TestListApplications:
    def test_list_applications_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.applications.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_APPLICATIONS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/applications")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_applications_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/applications")
        assert resp.status_code in (401, 403)

    def test_list_applications_filters_by_asset_group_for_non_admin(self):
        """AppOwner with ag-1 only should only see ag-1 applications."""
        app.dependency_overrides[get_current_user] = _app_owner
        with patch(
            "app.api.v1.routes.applications.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_APPLICATIONS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/applications")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        # Only ag-1 items should be returned
        for item in data:
            assert item["asset_group_id"] == "ag-1"

    def test_list_applications_returns_all_for_admin(self):
        """PlatformAdmin should see all applications regardless of asset group."""
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.applications.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_APPLICATIONS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/applications")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        # Admin sees all items
        assert len(data) == len(FAKE_APPLICATIONS)

    def test_list_applications_returns_empty_when_no_data(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.applications.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/applications")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json() == []
