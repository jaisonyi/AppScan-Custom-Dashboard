"""Unit tests for issues proxy route: GET /issues."""
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


def _developer() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_ISSUES = [
    {
        "id": "i-1",
        "severity": "critical",
        "status": "Open",
        "asset_group_id": "ag-1",
        "application_id": "app-1",
        "vulnerability": "SQL Injection",
    },
    {
        "id": "i-2",
        "severity": "high",
        "status": "Open",
        "asset_group_id": "ag-2",
        "application_id": "app-2",
        "vulnerability": "XSS",
    },
]


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/issues
# ---------------------------------------------------------------------------

class TestListIssues:
    def test_list_issues_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.issues.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ISSUES,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/issues")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_issues_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/issues")
        assert resp.status_code in (401, 403)

    def test_list_issues_filters_by_asset_group_for_non_admin(self):
        """AppOwner with ag-1 only should only see ag-1 issues."""
        app.dependency_overrides[get_current_user] = _app_owner
        with patch(
            "app.api.v1.routes.issues.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ISSUES,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/issues")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        # Only ag-1 items should be returned
        for item in data:
            assert item["asset_group_id"] == "ag-1"

    def test_list_issues_returns_all_for_admin(self):
        """PlatformAdmin should see all issues regardless of asset group."""
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.issues.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ISSUES,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/issues")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(FAKE_ISSUES)

    def test_list_issues_allowed_for_developer(self):
        """Developer role should be able to view issues."""
        app.dependency_overrides[get_current_user] = _developer
        with patch(
            "app.api.v1.routes.issues.aggregate_list",
            new_callable=AsyncMock,
            return_value=[FAKE_ISSUES[0]],  # only ag-1 item
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/issues")
        app.dependency_overrides.clear()
        assert resp.status_code == 200


class TestListIssuesDataSourceIds:
    def test_forwards_data_source_ids(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.issues.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_agg:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/issues?data_source_ids=ds-1&data_source_ids=ds-2")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_agg.assert_called_once()
        assert mock_agg.call_args.kwargs["data_source_ids"] == ["ds-1", "ds-2"]

    def test_no_data_source_ids_passes_none(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.issues.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_agg:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/issues")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_agg.assert_called_once()
        assert mock_agg.call_args.kwargs["data_source_ids"] is None
