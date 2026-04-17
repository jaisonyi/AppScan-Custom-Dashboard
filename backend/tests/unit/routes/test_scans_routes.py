"""Unit tests for scans proxy route: GET /scans and diagnostics endpoint."""
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

FAKE_SCANS = [
    {
        "id": "s-1",
        "name": "SAST Scan",
        "status": "completed",
        "scan_type": "SAST",
        "asset_group_id": "ag-1",
        "application_id": "app-1",
    },
    {
        "id": "s-2",
        "name": "DAST Scan",
        "status": "completed",
        "scan_type": "DAST",
        "asset_group_id": "ag-2",
        "application_id": "app-2",
    },
]

FAKE_DIAGNOSTICS = {
    "items": [
        {
            "scan_id": "s-1",
            "scan_name": "DAST Scan",
            "asset_group_id": "ag-1",
            "page_coverage": 420,
            "status": "completed",
        },
        {
            "scan_id": "s-2",
            "scan_name": "DAST Scan 2",
            "asset_group_id": "ag-2",
            "page_coverage": 100,
            "status": "completed",
        },
    ],
    "total": 2,
}


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/scans
# ---------------------------------------------------------------------------

class TestListScans:
    def test_list_scans_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.scans.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_SCANS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_scans_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/scans")
        assert resp.status_code in (401, 403)

    def test_list_scans_filters_by_asset_group_for_non_admin(self):
        """AppOwner with ag-1 only should only see ag-1 scans."""
        app.dependency_overrides[get_current_user] = _app_owner
        with patch(
            "app.api.v1.routes.scans.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_SCANS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        # Only ag-1 items should be returned
        for item in data:
            assert item["asset_group_id"] == "ag-1"

    def test_list_scans_returns_all_for_admin(self):
        """PlatformAdmin should see all scans regardless of asset group."""
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.scans.aggregate_list",
            new_callable=AsyncMock,
            return_value=FAKE_SCANS,
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(FAKE_SCANS)


# ---------------------------------------------------------------------------
# GET /api/v1/scans/dast-page-coverage-diagnostics
# ---------------------------------------------------------------------------

class TestDastPageCoverageDiagnostics:
    def test_dast_page_coverage_diagnostics_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        mock_service = MagicMock()
        mock_service.diagnose_dast_page_coverage = AsyncMock(return_value=FAKE_DIAGNOSTICS)
        with (
            patch("app.api.v1.routes.scans.get_endpoint_services", return_value=[mock_service]),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans/dast-page-coverage-diagnostics")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_dast_page_coverage_diagnostics_filters_items_for_non_admin(self):
        """Non-admin should only see items from their permitted asset groups."""
        app.dependency_overrides[get_current_user] = _app_owner
        mock_service = MagicMock()
        mock_service.diagnose_dast_page_coverage = AsyncMock(return_value=FAKE_DIAGNOSTICS)
        with (
            patch("app.api.v1.routes.scans.get_endpoint_services", return_value=[mock_service]),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans/dast-page-coverage-diagnostics")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        # AppOwner with ag-1 should only see ag-1 items
        for item in data.get("items", []):
            assert item.get("asset_group_id") == "ag-1"

    def test_dast_page_coverage_diagnostics_uses_default_service_when_no_endpoints(self):
        """When no endpoint services configured, falls back to default service."""
        app.dependency_overrides[get_current_user] = _admin
        with (
            patch("app.api.v1.routes.scans.get_endpoint_services", return_value=[]),
            patch.object(
                __import__("app.services.asoc_read_service", fromlist=["AsocReadService"]).AsocReadService,
                "diagnose_dast_page_coverage",
                new_callable=AsyncMock,
                return_value={"items": [], "total": 0},
            ),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans/dast-page-coverage-diagnostics")
        app.dependency_overrides.clear()

        assert resp.status_code == 200

    def test_dast_page_coverage_diagnostics_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/scans/dast-page-coverage-diagnostics")
        assert resp.status_code in (401, 403)

    def test_dast_page_coverage_diagnostics_max_scans_param(self):
        """max_scans query param is passed to the service."""
        app.dependency_overrides[get_current_user] = _admin
        mock_service = MagicMock()
        mock_service.diagnose_dast_page_coverage = AsyncMock(return_value={"items": [], "total": 0})
        with (
            patch("app.api.v1.routes.scans.get_endpoint_services", return_value=[mock_service]),
        ):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans/dast-page-coverage-diagnostics?max_scans=3")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        # Verify the service was called with max_scans=3
        mock_service.diagnose_dast_page_coverage.assert_called_once_with(scan_ids=None, max_scans=3)


class TestListScansDataSourceIds:
    def test_forwards_data_source_ids(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.scans.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_agg:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans?data_source_ids=ds-1&data_source_ids=ds-2")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_agg.assert_called_once()
        assert mock_agg.call_args.kwargs["data_source_ids"] == ["ds-1", "ds-2"]

    def test_no_data_source_ids_passes_none(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch(
            "app.api.v1.routes.scans.aggregate_list",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_agg:
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/scans")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_agg.assert_called_once()
        assert mock_agg.call_args.kwargs["data_source_ids"] is None
