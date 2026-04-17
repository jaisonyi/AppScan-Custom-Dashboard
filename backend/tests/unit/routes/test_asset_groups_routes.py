"""Unit tests for asset groups proxy route: GET /asset-groups."""
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


def _security_manager() -> UserContext:
    return UserContext(subject="sm@test.com", role="SecurityManager", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_ASSET_GROUPS = [
    {"id": "ag-1", "name": "Production"},
    {"id": "ag-2", "name": "Staging"},
]


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/asset-groups
# ---------------------------------------------------------------------------

class TestListAssetGroups:
    def test_list_asset_groups_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.asset_groups.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ASSET_GROUPS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/asset-groups")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_asset_groups_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/asset-groups")
        assert resp.status_code in (401, 403)

    def test_list_asset_groups_admin_returns_all(self):
        """PlatformAdmin should see all asset groups."""
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.asset_groups.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ASSET_GROUPS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/asset-groups")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(FAKE_ASSET_GROUPS)

    def test_list_asset_groups_non_admin_filters_to_permitted(self):
        """AppOwner with ag-1 only should only see ag-1."""
        app.dependency_overrides[get_current_user] = _app_owner
        with patch(
            "app.api.v1.routes.asset_groups.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ASSET_GROUPS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/asset-groups")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        # Only ag-1 should be returned
        ids = [item["id"] for item in data]
        assert "ag-1" in ids
        assert "ag-2" not in ids

    def test_list_asset_groups_security_manager_returns_all(self):
        """SecurityManager should see all asset groups (bypasses filter)."""
        app.dependency_overrides[get_current_user] = _security_manager
        with patch(
            "app.api.v1.routes.asset_groups.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_ASSET_GROUPS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/asset-groups")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(FAKE_ASSET_GROUPS)


class TestListAssetGroupsDataSourceIds:
    def test_forwards_data_source_ids(self):
        app.dependency_overrides[get_current_user] = _security_manager
        with patch(
            "app.api.v1.routes.asset_groups.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_agg:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/asset-groups?data_source_ids=ds-1&data_source_ids=ds-2")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_agg.assert_called_once()
        assert mock_agg.call_args.kwargs["data_source_ids"] == ["ds-1", "ds-2"]

    def test_no_data_source_ids_passes_none(self):
        app.dependency_overrides[get_current_user] = _security_manager
        with patch(
            "app.api.v1.routes.asset_groups.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_agg:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/asset-groups")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_agg.assert_called_once()
        assert mock_agg.call_args.kwargs["data_source_ids"] is None
