"""Unit tests for backend/app/services/multi_endpoint.py."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch


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

def _make_source(
    url: str = "https://asoc.example.com",
    key: str = "k",
    secret: str = "s",
    label: str = "Primary",
    ds_id: str | None = None,
) -> dict:
    return {
        "id": ds_id or f"ds-{label.lower()}",
        "url": url,
        "api_key": key,
        "api_secret": secret,
        "label": label,
        "verify_ssl": True,
        "enabled": True,
    }


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
        with patch("app.services.multi_endpoint._load_sources", return_value=[]):
            result = get_endpoint_services()
        assert result == []

    def test_returns_one_per_endpoint(self):
        sources = [
            _make_source("https://ep1.example.com", "k1", "s1", "EP1"),
            _make_source("https://ep2.example.com", "k2", "s2", "EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.side_effect = lambda url, key, secret, **kw: MagicMock(url=url)
            result = get_endpoint_services()
        assert len(result) == 2
        assert mock_cls.for_endpoint.call_count == 2


# ---------------------------------------------------------------------------
# get_endpoint_labels
# ---------------------------------------------------------------------------


class TestGetEndpointLabels:
    def test_returns_url_and_label(self):
        sources = [
            _make_source("https://ep1.example.com", label="Primary"),
            _make_source("https://ep2.example.com", label="Secondary"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources):
            result = get_endpoint_labels()
        assert len(result) == 2
        assert result[0] == {"id": "ds-primary", "url": "https://ep1.example.com", "label": "Primary"}
        assert result[1] == {"id": "ds-secondary", "url": "https://ep2.example.com", "label": "Secondary"}

    def test_returns_empty_when_no_endpoints(self):
        with patch("app.services.multi_endpoint._load_sources", return_value=[]):
            result = get_endpoint_labels()
        assert result == []


# ---------------------------------------------------------------------------
# aggregate_list
# ---------------------------------------------------------------------------


class TestAggregateList:
    async def test_returns_empty_when_no_services(self):
        with patch("app.services.multi_endpoint._load_sources", return_value=[]):
            result = await aggregate_list("list_scans")
        assert result == []

    async def test_merges_results_from_multiple_endpoints(self):
        svc1 = _make_service(list_result=[{"id": "s-1"}, {"id": "s-2"}])
        svc2 = _make_service(list_result=[{"id": "s-3"}, {"id": "s-4"}])
        sources = [
            _make_source("https://ep1.example.com", label="EP1"),
            _make_source("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.side_effect = [svc1, svc2]
            result = await aggregate_list("list_scans")
        assert len(result) == 4
        ids = {item["id"] for item in result}
        assert ids == {"s-1", "s-2", "s-3", "s-4"}

    async def test_skips_failed_endpoints(self):
        svc1 = _make_service(raise_on_list=True)
        svc2 = _make_service(list_result=[{"id": "s-ok"}])
        sources = [
            _make_source("https://ep1.example.com", label="EP1"),
            _make_source("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.side_effect = [svc1, svc2]
            result = await aggregate_list("list_scans")
        assert len(result) == 1
        assert result[0]["id"] == "s-ok"

    async def test_logs_warning_on_failure(self, caplog):
        svc1 = _make_service(raise_on_list=True)
        sources = [_make_source("https://ep1.example.com", label="FailEP")]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.return_value = svc1
            with caplog.at_level(logging.WARNING, logger="app.services.multi_endpoint"):
                await aggregate_list("list_scans")
        assert any("FailEP" in record.message or "aggregate_list" in record.message for record in caplog.records)

    async def test_returns_empty_list_when_all_fail(self):
        svc1 = _make_service(raise_on_list=True)
        svc2 = _make_service(raise_on_list=True)
        sources = [
            _make_source("https://ep1.example.com", label="EP1"),
            _make_source("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.side_effect = [svc1, svc2]
            result = await aggregate_list("list_scans")
        assert result == []


# ---------------------------------------------------------------------------
# aggregate_tenant_info
# ---------------------------------------------------------------------------


class TestAggregateTenantInfo:
    async def test_returns_first_successful(self):
        svc1 = _make_service(tenant_result={"tenant": "acme"})
        sources = [_make_source(label="Primary")]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.return_value = svc1
            result = await aggregate_tenant_info()
        assert result == {"tenant": "acme"}

    async def test_skips_failed_and_tries_next(self):
        svc1 = _make_service(raise_on_tenant=True)
        svc2 = _make_service(tenant_result={"tenant": "fallback"})
        sources = [
            _make_source("https://ep1.example.com", label="EP1"),
            _make_source("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.side_effect = [svc1, svc2]
            result = await aggregate_tenant_info()
        assert result == {"tenant": "fallback"}

    async def test_returns_empty_when_all_fail(self):
        svc1 = _make_service(raise_on_tenant=True)
        svc2 = _make_service(raise_on_tenant=True)
        sources = [
            _make_source("https://ep1.example.com", label="EP1"),
            _make_source("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.side_effect = [svc1, svc2]
            result = await aggregate_tenant_info()
        assert result == {}

    async def test_returns_empty_when_no_services(self):
        with patch("app.services.multi_endpoint._load_sources", return_value=[]):
            result = await aggregate_tenant_info()
        assert result == {}


# ---------------------------------------------------------------------------
# aggregate_base_data
# ---------------------------------------------------------------------------


class TestAggregateBaseData:
    async def test_returns_empty_when_no_services(self):
        with patch("app.services.multi_endpoint._load_sources", return_value=[]), \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[]):
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

        sources = [
            _make_source("https://ep1.example.com", label="EP1"),
            _make_source("https://ep2.example.com", label="EP2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
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

        with patch("app.services.multi_endpoint._load_sources", return_value=[
                _make_source("https://ep1.example.com", label="EP1"),
                _make_source("https://ep2.example.com", label="EP2"),
            ]), \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            result = await aggregate_base_data()

        # First non-empty tenant_info wins
        assert result["tenant_info"]["tenant"] == "first"


# ---------------------------------------------------------------------------
# P1 — _load_sources filtering
# ---------------------------------------------------------------------------


class TestLoadSourcesFiltering:
    """Tests for data_source_ids filtering in _load_sources."""

    def test_none_returns_all(self):
        sources = [
            _make_source(label="EP1", ds_id="ds-1"),
            _make_source(label="EP2", ds_id="ds-2"),
            _make_source(label="EP3", ds_id="ds-3"),
        ]
        with patch("app.services.multi_endpoint.data_source_service.list_all", return_value=sources):
            from app.services.multi_endpoint import _load_sources
            result = _load_sources(data_source_ids=None)
        assert len(result) == 3

    def test_valid_ids_filters(self):
        sources = [
            _make_source(label="EP1", ds_id="ds-1"),
            _make_source(label="EP2", ds_id="ds-2"),
            _make_source(label="EP3", ds_id="ds-3"),
        ]
        with patch("app.services.multi_endpoint.data_source_service.list_all", return_value=sources):
            from app.services.multi_endpoint import _load_sources
            result = _load_sources(data_source_ids=["ds-1", "ds-3"])
        assert len(result) == 2
        ids = {ds["id"] for ds in result}
        assert ids == {"ds-1", "ds-3"}

    def test_unknown_ids_silently_dropped(self):
        sources = [
            _make_source(label="EP1", ds_id="ds-1"),
        ]
        with patch("app.services.multi_endpoint.data_source_service.list_all", return_value=sources):
            from app.services.multi_endpoint import _load_sources
            result = _load_sources(data_source_ids=["ds-nonexistent"])
        assert result == []

    def test_empty_list_returns_all(self):
        sources = [
            _make_source(label="EP1", ds_id="ds-1"),
            _make_source(label="EP2", ds_id="ds-2"),
        ]
        with patch("app.services.multi_endpoint.data_source_service.list_all", return_value=sources):
            from app.services.multi_endpoint import _load_sources
            result = _load_sources(data_source_ids=[])
        assert len(result) == 2

    def test_partial_match(self):
        sources = [
            _make_source(label="EP1", ds_id="ds-1"),
            _make_source(label="EP2", ds_id="ds-2"),
        ]
        with patch("app.services.multi_endpoint.data_source_service.list_all", return_value=sources):
            from app.services.multi_endpoint import _load_sources
            result = _load_sources(data_source_ids=["ds-1", "ds-nonexistent"])
        assert len(result) == 1
        assert result[0]["id"] == "ds-1"

    def test_max_ids_cap(self):
        """Excess IDs beyond _MAX_DATA_SOURCE_IDS are truncated."""
        sources = [_make_source(label=f"EP{i}", ds_id=f"ds-{i}") for i in range(25)]
        ids = [f"ds-{i}" for i in range(25)]
        with patch("app.services.multi_endpoint.data_source_service.list_all", return_value=sources):
            from app.services.multi_endpoint import _load_sources
            result = _load_sources(data_source_ids=ids)
        assert len(result) <= 20


# ---------------------------------------------------------------------------
# P2 — aggregate_base_data tagging
# ---------------------------------------------------------------------------


class TestAggregateBaseDataTagging:
    """Items returned by aggregate_base_data carry _data_source_id/label."""

    async def test_items_tagged_with_data_source_id_and_label(self):
        svc1 = MagicMock()
        svc1.list_scans = AsyncMock(return_value=[{"id": "s-1"}])
        svc1.list_issues = AsyncMock(return_value=[{"id": "i-1"}])
        svc1.list_applications = AsyncMock(return_value=[{"id": "app-1"}])
        svc1.list_asset_groups = AsyncMock(return_value=[{"id": "ag-1"}])
        svc1.get_tenant_info = AsyncMock(return_value={"tenant": "t1"})
        svc1.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        svc2 = MagicMock()
        svc2.list_scans = AsyncMock(return_value=[{"id": "s-2"}])
        svc2.list_issues = AsyncMock(return_value=[{"id": "i-2"}])
        svc2.list_applications = AsyncMock(return_value=[{"id": "app-2"}])
        svc2.list_asset_groups = AsyncMock(return_value=[{"id": "ag-2"}])
        svc2.get_tenant_info = AsyncMock(return_value={"tenant": "t2"})
        svc2.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        sources = [
            _make_source("https://ep1.example.com", label="EP1", ds_id="ds-ep1"),
            _make_source("https://ep2.example.com", label="EP2", ds_id="ds-ep2"),
        ]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1, svc2]):
            result = await aggregate_base_data()

        for collection in ("scans", "issues", "applications", "asset_groups"):
            for item in result[collection]:
                assert "_data_source_id" in item, f"missing _data_source_id on {collection} item {item['id']}"
                assert "_data_source_label" in item, f"missing _data_source_label on {collection} item {item['id']}"

        ep1_scans = [s for s in result["scans"] if s["_data_source_id"] == "ds-ep1"]
        ep2_scans = [s for s in result["scans"] if s["_data_source_id"] == "ds-ep2"]
        assert len(ep1_scans) == 1
        assert ep1_scans[0]["_data_source_label"] == "EP1"
        assert len(ep2_scans) == 1
        assert ep2_scans[0]["_data_source_label"] == "EP2"

    async def test_data_source_ids_filters_sources_in_base_data(self):
        svc1 = MagicMock()
        svc1.list_scans = AsyncMock(return_value=[{"id": "s-1"}])
        svc1.list_issues = AsyncMock(return_value=[{"id": "i-1"}])
        svc1.list_applications = AsyncMock(return_value=[{"id": "app-1"}])
        svc1.list_asset_groups = AsyncMock(return_value=[{"id": "ag-1"}])
        svc1.get_tenant_info = AsyncMock(return_value={"tenant": "t1"})
        svc1.hydrate_dast_page_coverage = AsyncMock(side_effect=lambda scans, **kw: scans)

        sources = [_make_source("https://ep1.example.com", label="EP1", ds_id="ds-ep1")]
        with patch("app.services.multi_endpoint._load_sources", return_value=sources) as mock_load, \
             patch("app.services.multi_endpoint.get_endpoint_services", return_value=[svc1]):
            result = await aggregate_base_data(data_source_ids=["ds-ep1"])

        mock_load.assert_called_once_with(data_source_ids=["ds-ep1"])
        assert len(result["scans"]) == 1
        assert result["scans"][0]["_data_source_id"] == "ds-ep1"


# ---------------------------------------------------------------------------
# P3 — aggregate_list pass-through
# ---------------------------------------------------------------------------


class TestAggregateListDataSourceIds:
    """aggregate_list forwards data_source_ids to _load_sources."""

    async def test_data_source_ids_forwarded_to_load_sources(self):
        sources = [_make_source("https://ep1.example.com", label="EP1", ds_id="ds-1")]
        svc = _make_service(list_result=[{"id": "s-1"}])
        with patch("app.services.multi_endpoint._load_sources", return_value=sources) as mock_load, \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.return_value = svc
            await aggregate_list("list_scans", data_source_ids=["ds-1"])

        mock_load.assert_called_once_with(data_source_ids=["ds-1"])

    async def test_data_source_ids_none_queries_all(self):
        with patch("app.services.multi_endpoint._load_sources", return_value=[]) as mock_load:
            await aggregate_list("list_scans")

        mock_load.assert_called_once_with(data_source_ids=None)

    async def test_single_source_returns_tagged_items(self):
        sources = [_make_source("https://ep1.example.com", label="EP1", ds_id="ds-1")]
        svc = _make_service(list_result=[{"id": "s-1"}, {"id": "s-2"}])
        with patch("app.services.multi_endpoint._load_sources", return_value=sources), \
             patch("app.services.multi_endpoint.AsocReadService") as mock_cls:
            mock_cls.for_endpoint.return_value = svc
            result = await aggregate_list("list_scans", data_source_ids=["ds-1"])

        assert len(result) == 2
        for item in result:
            assert item["_data_source_id"] == "ds-1"
            assert item["_data_source_label"] == "EP1"
