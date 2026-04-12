"""Unit tests for backend/app/services/multi_endpoint.py."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.multi_endpoint import (
    aggregate_base_data,
    aggregate_list,
    aggregate_tenant_info,
    get_endpoint_labels,
    get_endpoint_services,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_endpoint(url: str = "https://asoc.example.com", key: str = "k", secret: str = "s", label: str = "Primary") -> dict:
    return {"url": url, "key": key, "secret": secret, "label": label}


def _make_service(list_result=None, tenant_result=None, raise_on_list=False, raise_on_tenant=False):
    """Return a mock AsocReadService with configurable async methods."""
    svc = MagicMock()
    if raise_on_list:
        svc.list_scans = AsyncMock(side_effect=RuntimeError("endpoint down"))
    else:
        svc.list_scans = AsyncMock(return_value=list_result or [])
    if raise_on_tenant:
        svc.get_tenant_info = AsyncMock(side_effect=RuntimeError("tenant down"))
    else:
        svc.get_tenant_info = AsyncMock(return_value=tenant_result or {})

    # Provide all methods used by aggregate_base_data
    svc.list_issues = AsyncMock(return_value=[])
    svc.list_applications = AsyncMock(return_value=[])
    svc.list_asset_groups = AsyncMock(return_value=[])
    svc.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)
    return svc


# ---------------------------------------------------------------------------
# get_endpoint_services
# ---------------------------------------------------------------------------


class TestGetEndpointServices:
    def test_returns_empty_when_no_credentials(self):
        with patch("app.services.multi_endpoint.settings") as mock_settings:
            mock_settings.all_asoc_endpoints.return_value = []
            result = get_endpoint_services()
        assert result == []

    def test_returns_one_per_endpoint(self):
        endpoints = [
            _make_endpoint("https://ep1.example.com", "k1", "s1", "EP1"),
            _make_endpoint("https://ep2.example.com", "k2", "s2", "EP2"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_settings.all_asoc_endpoints.return_value = endpoints
            mock_cls.for_endpoint.side_effect = lambda url, key, secret: MagicMock(url=url)
            result = get_endpoint_services()
        assert len(result) == 2
        assert mock_cls.for_endpoint.call_count == 2


# ---------------------------------------------------------------------------
# get_endpoint_labels
# ---------------------------------------------------------------------------


class TestGetEndpointLabels:
    def test_returns_url_and_label(self):
        endpoints = [
            _make_endpoint("https://ep1.example.com", label="Primary"),
            _make_endpoint("https://ep2.example.com", label="Secondary"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings:
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = get_endpoint_labels()
        assert len(result) == 2
        assert result[0] == {"url": "https://ep1.example.com", "label": "Primary"}
        assert result[1] == {"url": "https://ep2.example.com", "label": "Secondary"}

    def test_returns_empty_when_no_endpoints(self):
        with patch("app.services.multi_endpoint.settings") as mock_settings:
            mock_settings.all_asoc_endpoints.return_value = []
            result = get_endpoint_labels()
        assert result == []


# ---------------------------------------------------------------------------
# aggregate_list
# ---------------------------------------------------------------------------


class TestAggregateList:
    async def test_returns_empty_when_no_services(self):
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[]):
            mock_settings.all_asoc_endpoints.return_value = []
            result = await aggregate_list("list_scans")
        assert result == []

    async def test_merges_results_from_multiple_endpoints(self):
        svc1 = _make_service(list_result=[{"id": "s-1"}, {"id": "s-2"}])
        svc2 = _make_service(list_result=[{"id": "s-3"}, {"id": "s-4"}])
        endpoints = [
            _make_endpoint("https://ep1.example.com", label="EP1"),
            _make_endpoint("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = await aggregate_list("list_scans")
        assert len(result) == 4
        ids = {item["id"] for item in result}
        assert ids == {"s-1", "s-2", "s-3", "s-4"}

    async def test_skips_failed_endpoints(self):
        svc1 = _make_service(raise_on_list=True)
        svc2 = _make_service(list_result=[{"id": "s-ok"}])
        endpoints = [
            _make_endpoint("https://ep1.example.com", label="EP1"),
            _make_endpoint("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = await aggregate_list("list_scans")
        assert len(result) == 1
        assert result[0]["id"] == "s-ok"

    async def test_logs_warning_on_failure(self, caplog):
        svc1 = _make_service(raise_on_list=True)
        endpoints = [_make_endpoint("https://ep1.example.com", label="FailEP")]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            with caplog.at_level(logging.WARNING, logger="app.services.multi_endpoint"):
                await aggregate_list("list_scans")
        assert any("FailEP" in record.message or "aggregate_list" in record.message for record in caplog.records)

    async def test_returns_empty_list_when_all_fail(self):
        svc1 = _make_service(raise_on_list=True)
        svc2 = _make_service(raise_on_list=True)
        endpoints = [
            _make_endpoint("https://ep1.example.com", label="EP1"),
            _make_endpoint("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = await aggregate_list("list_scans")
        assert result == []


# ---------------------------------------------------------------------------
# aggregate_tenant_info
# ---------------------------------------------------------------------------


class TestAggregateTenantInfo:
    async def test_returns_first_successful(self):
        svc1 = _make_service(tenant_result={"tenant": "acme"})
        endpoints = [_make_endpoint(label="Primary")]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = await aggregate_tenant_info()
        assert result == {"tenant": "acme"}

    async def test_skips_failed_and_tries_next(self):
        svc1 = _make_service(raise_on_tenant=True)
        svc2 = _make_service(tenant_result={"tenant": "fallback"})
        endpoints = [
            _make_endpoint("https://ep1.example.com", label="EP1"),
            _make_endpoint("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = await aggregate_tenant_info()
        assert result == {"tenant": "fallback"}

    async def test_returns_empty_when_all_fail(self):
        svc1 = _make_service(raise_on_tenant=True)
        svc2 = _make_service(raise_on_tenant=True)
        endpoints = [
            _make_endpoint("https://ep1.example.com", label="EP1"),
            _make_endpoint("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = endpoints
            result = await aggregate_tenant_info()
        assert result == {}

    async def test_returns_empty_when_no_services(self):
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[]):
            mock_settings.all_asoc_endpoints.return_value = []
            result = await aggregate_tenant_info()
        assert result == {}


# ---------------------------------------------------------------------------
# aggregate_base_data
# ---------------------------------------------------------------------------


class TestAggregateBaseData:
    async def test_returns_empty_when_no_services(self):
        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[]):
            mock_settings.all_asoc_endpoints.return_value = []
            result = await aggregate_base_data()
        assert result["scans"] == []
        assert result["issues"] == []
        assert result["applications"] == []
        assert result["asset_groups"] == []
        assert result["tenant_info"] == {}

    async def test_merges_scans_issues_apps_groups(self):
        svc1 = MagicMock()
        svc1.list_scans = AsyncMock(return_value=[{"id": "s-1"}])
        svc1.list_issues = AsyncMock(return_value=[{"id": "i-1"}])
        svc1.list_applications = AsyncMock(return_value=[{"id": "app-1"}])
        svc1.list_asset_groups = AsyncMock(return_value=[{"id": "ag-1"}])
        svc1.get_tenant_info = AsyncMock(return_value={"tenant": "acme"})
        svc1.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        svc2 = MagicMock()
        svc2.list_scans = AsyncMock(return_value=[{"id": "s-2"}])
        svc2.list_issues = AsyncMock(return_value=[{"id": "i-2"}])
        svc2.list_applications = AsyncMock(return_value=[{"id": "app-2"}])
        svc2.list_asset_groups = AsyncMock(return_value=[{"id": "ag-2"}])
        svc2.get_tenant_info = AsyncMock(return_value={"tenant": "other"})
        svc2.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = [
                _make_endpoint("https://ep1.example.com", label="EP1"),
                _make_endpoint("https://ep2.example.com", label="EP2"),
            ]
            result = await aggregate_base_data()

        assert len(result["scans"]) == 2
        assert len(result["issues"]) == 2
        assert len(result["applications"]) == 2
        assert len(result["asset_groups"]) == 2

    async def test_uses_first_tenant_info(self):
        svc1 = MagicMock()
        svc1.list_scans = AsyncMock(return_value=[])
        svc1.list_issues = AsyncMock(return_value=[])
        svc1.list_applications = AsyncMock(return_value=[])
        svc1.list_asset_groups = AsyncMock(return_value=[])
        svc1.get_tenant_info = AsyncMock(return_value={"tenant": "first"})
        svc1.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        svc2 = MagicMock()
        svc2.list_scans = AsyncMock(return_value=[])
        svc2.list_issues = AsyncMock(return_value=[])
        svc2.list_applications = AsyncMock(return_value=[])
        svc2.list_asset_groups = AsyncMock(return_value=[])
        svc2.get_tenant_info = AsyncMock(return_value={"tenant": "second"})
        svc2.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        with patch("app.services.multi_endpoint.settings") as mock_settings, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            mock_settings.all_asoc_endpoints.return_value = [
                _make_endpoint("https://ep1.example.com", label="EP1"),
                _make_endpoint("https://ep2.example.com", label="EP2"),
            ]
            result = await aggregate_base_data()

        # First non-empty tenant_info wins
        assert result["tenant_info"]["tenant"] == "first"
