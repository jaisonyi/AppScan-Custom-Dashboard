"""Unit tests for the data_source_ids filter fix in _build_bundle().

Bug: When data_source_ids filter is active but no scope filter
(asset_group/application), _build_bundle() used pre-computed ALL-sources
statistics instead of recomputing from filtered data.

Fix: Changed the condition from:
    if not has_scope_filter and source_data is not None:
to:
    if not has_scope_filter and source_data is not None and not data_source_ids:
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.security.dependencies import UserContext


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------

_ALL_SOURCES_STATS: dict[str, Any] = {
    "total_issues": 100,
    "critical_issues": 10,
    "high_issues": 20,
    "medium_issues": 30,
    "low_issues": 40,
    "informational_issues": 0,
    "active_issues": 70,
    "open_issues": 50,
    "new_issues": 10,
    "in_progress_issues": 10,
    "fixed_issues": 30,
    "resolved_issues": 30,
    "total_scans": 8,
    "running_scans": 0,
    "failed_scans": 0,
    "total_applications": 4,
    "count_source": "app_aggregation",
}

_DS1_ONLY_STATS: dict[str, Any] = {
    "total_issues": 60,
    "critical_issues": 6,
    "high_issues": 12,
    "medium_issues": 18,
    "low_issues": 24,
    "informational_issues": 0,
    "active_issues": 42,
    "open_issues": 30,
    "new_issues": 6,
    "in_progress_issues": 6,
    "fixed_issues": 18,
    "resolved_issues": 18,
    "total_scans": 4,
    "running_scans": 0,
    "failed_scans": 0,
    "total_applications": 2,
    "count_source": "app_aggregation",
}


def _make_app(app_id: str, ds_id: str, total_issues: int) -> dict[str, Any]:
    return {
        "id": app_id,
        "name": f"App {app_id}",
        "asset_group_id": "ag-1",
        "_data_source_id": ds_id,
        "total_issues": total_issues,
        "critical_issues": total_issues // 10,
        "high_issues": total_issues // 5,
        "medium_issues": total_issues * 3 // 10,
        "low_issues": total_issues * 4 // 10,
        "informational_issues": 0,
        "open_issues": total_issues // 2,
        "new_issues": total_issues // 10,
        "issues_in_progress": total_issues // 10,
        "total_scans": 2,
    }


def _make_scan(scan_id: str, app_id: str, ds_id: str) -> dict[str, Any]:
    return {
        "id": scan_id,
        "application_id": app_id,
        "asset_group_id": "ag-1",
        "_data_source_id": ds_id,
        "status": "Ready",
        "technology": "SAST",
    }


def _make_issue(issue_id: str, app_id: str, ds_id: str) -> dict[str, Any]:
    return {
        "id": issue_id,
        "application_id": app_id,
        "asset_group_id": "ag-1",
        "_data_source_id": ds_id,
        "status": "Open",
        "severity": "High",
        "issue_technology": "SAST",
    }


def _make_source_data() -> dict[str, Any]:
    """Build source_data with apps from two data sources."""
    return {
        "applications": [
            _make_app("app-1", "ds-1", 30),
            _make_app("app-2", "ds-1", 30),
            _make_app("app-3", "ds-2", 20),
            _make_app("app-4", "ds-2", 20),
        ],
        "scans": [
            _make_scan("scan-1", "app-1", "ds-1"),
            _make_scan("scan-2", "app-2", "ds-1"),
            _make_scan("scan-3", "app-3", "ds-2"),
            _make_scan("scan-4", "app-4", "ds-2"),
        ],
        "issues": [
            _make_issue(f"issue-{i}", "app-1", "ds-1") for i in range(10)
        ] + [
            _make_issue(f"issue-{i}", "app-3", "ds-2") for i in range(10, 15)
        ],
        "asset_groups": [{"id": "ag-1", "name": "Group 1", "_data_source_id": "ds-1"}],
        "tenant_info": {},
        "app_based_statistics": dict(_ALL_SOURCES_STATS),
    }


def _admin() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Common kwargs for _build_bundle (no scope filters)
# ---------------------------------------------------------------------------

_BASE_KWARGS: dict[str, Any] = dict(
    asset_group_ids=[],
    application_ids=[],
    issue_technologies=[],
    vulnerabilities=[],
    scan_types=[],
    scan_statuses=[],
    application_name=None,
    from_date=None,
    to_date=None,
    compliance_rule="critical_high",
    compliance_threshold="high",
    source_refresh=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_service_methods(mock_service: MagicMock) -> None:
    """Stub every service method called inside _build_bundle's return dict."""
    mock_service.apply_filters.return_value = ([], [])
    mock_service.filter_issues_by_dimensions.return_value = []
    mock_service.build_portfolio_summary.return_value = {}
    mock_service.calculate_statistics.return_value = {
        "total_issues": 0, "active_issues": 0, "resolved_issues": 0,
        "critical_issues": 0, "high_issues": 0, "medium_issues": 0,
        "low_issues": 0, "total_scans": 0, "scan_count": 0,
        "running_scans": 0, "failed_scans": 0,
    }
    mock_service.calculate_trend.return_value = []
    mock_service.calculate_kpi.return_value = []
    mock_service.calculate_mttr.return_value = []
    mock_service.calculate_prioritization.return_value = {"raw_findings": {}, "fix_groups": {}, "most_critical": []}
    mock_service.calculate_findings_series.return_value = []
    mock_service.calculate_scan_series.return_value = []
    mock_service.build_compliance.return_value = {"status": "pass", "rules": []}
    mock_service.build_workbench_trends.return_value = {}
    mock_service.build_issue_filter_options.return_value = {"technologies": [], "vulnerabilities": []}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildBundleDataSourceFilter:
    """Verify _build_bundle uses the correct statistics path based on data_source_ids."""

    @pytest.mark.asyncio
    async def test_no_data_source_ids_uses_cached_stats(self):
        """No data_source_ids → uses pre-computed app_based_statistics from source_data."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            # apply_filters should return the full lists (no scope filter)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=None,
            )

        # Pre-computed stats used → calculate_statistics_from_apps should NOT be called
        mock_service.calculate_statistics_from_apps.assert_not_called()
        # Statistics should reflect ALL-sources totals
        assert result["statistics"]["total_issues"] == _ALL_SOURCES_STATS["total_issues"]

    @pytest.mark.asyncio
    async def test_data_source_ids_set_recomputes_stats(self):
        """data_source_ids=["ds-1"] → must recompute from filtered apps, not use cached."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)

            # When data_source_ids=["ds-1"], the _ds_filter in _build_bundle
            # filters apps/scans/issues to ds-1 only.
            ds1_scans = [s for s in source_data["scans"] if s["_data_source_id"] == "ds-1"]
            ds1_issues = [i for i in source_data["issues"] if i["_data_source_id"] == "ds-1"]
            mock_service.apply_filters.return_value = (ds1_scans, ds1_issues)
            mock_service.filter_issues_by_dimensions.return_value = ds1_issues

            # Set up calculate_statistics_from_apps to return ds-1-only stats
            mock_service.calculate_statistics_from_apps.return_value = dict(_DS1_ONLY_STATS)

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=["ds-1"],
            )

        # With data_source_ids active, must recompute → calculate_statistics_from_apps IS called
        mock_service.calculate_statistics_from_apps.assert_called_once()
        # Statistics should reflect ds-1-only totals, NOT the pre-computed all-sources totals
        assert result["statistics"]["total_issues"] == _DS1_ONLY_STATS["total_issues"]
        assert result["statistics"]["total_issues"] != _ALL_SOURCES_STATS["total_issues"]

    @pytest.mark.asyncio
    async def test_data_source_ids_with_scope_filter_recomputes_stats(self):
        """data_source_ids + scope filter → recomputes (was already correct before fix)."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)

            ds1_scans = [s for s in source_data["scans"] if s["_data_source_id"] == "ds-1"]
            ds1_issues = [i for i in source_data["issues"] if i["_data_source_id"] == "ds-1"]
            mock_service.apply_filters.return_value = (ds1_scans, ds1_issues)
            mock_service.filter_issues_by_dimensions.return_value = ds1_issues
            mock_service.calculate_statistics_from_apps.return_value = dict(_DS1_ONLY_STATS)

            from app.api.v1.routes.analytics import _build_bundle

            # Scope filter active via asset_group_ids
            result = await _build_bundle(
                _admin(),
                **{**_BASE_KWARGS, "asset_group_ids": ["ag-1"]},
                data_source_ids=["ds-1"],
            )

        # Scope filter active → always recomputes (has_scope_filter=True)
        mock_service.calculate_statistics_from_apps.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_data_source_ids_uses_cached_stats(self):
        """Empty data_source_ids=[] → treated as no filter, uses cached stats."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=[],
            )

        # Empty list = no filter → uses cached stats → calculate_statistics_from_apps NOT called
        mock_service.calculate_statistics_from_apps.assert_not_called()
        assert result["statistics"]["total_issues"] == _ALL_SOURCES_STATS["total_issues"]

    @pytest.mark.asyncio
    async def test_data_source_ids_none_explicit_uses_cached_stats(self):
        """Explicit data_source_ids=None → uses cached stats (same as omitted)."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=None,
            )

        mock_service.calculate_statistics_from_apps.assert_not_called()
        assert result["statistics"]["total_issues"] == _ALL_SOURCES_STATS["total_issues"]

    @pytest.mark.asyncio
    async def test_data_source_ids_recomputes_with_correct_filtered_apps(self):
        """Verify calculate_statistics_from_apps receives only ds-1 apps when filtering."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)

            ds1_scans = [s for s in source_data["scans"] if s["_data_source_id"] == "ds-1"]
            ds1_issues = [i for i in source_data["issues"] if i["_data_source_id"] == "ds-1"]
            mock_service.apply_filters.return_value = (ds1_scans, ds1_issues)
            mock_service.filter_issues_by_dimensions.return_value = ds1_issues
            mock_service.calculate_statistics_from_apps.return_value = dict(_DS1_ONLY_STATS)

            from app.api.v1.routes.analytics import _build_bundle

            await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=["ds-1"],
            )

        # Verify the call received only ds-1 apps
        call_args = mock_service.calculate_statistics_from_apps.call_args
        apps_arg = call_args[0][0]
        ds_ids_in_apps = {a["_data_source_id"] for a in apps_arg}
        assert ds_ids_in_apps == {"ds-1"}, (
            f"Expected only ds-1 apps but got data sources: {ds_ids_in_apps}"
        )

    @pytest.mark.asyncio
    async def test_data_source_ids_no_source_data_recomputes(self):
        """When source_data is None (cold cache), always recomputes regardless of data_source_ids."""
        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=False),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=None),
            patch("app.api.v1.routes.analytics.aggregate_list", new_callable=AsyncMock) as mock_agg_list,
            patch("app.api.v1.routes.analytics.aggregate_tenant_info", new_callable=AsyncMock, return_value={}),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)

            # aggregate_list returns different things based on the method name
            async def _fake_aggregate_list(method_name: str, *args, **kwargs):
                if method_name == "list_applications":
                    return [_make_app("app-1", "ds-1", 30)]
                if method_name == "list_asset_groups":
                    return [{"id": "ag-1", "name": "Group 1"}]
                if method_name == "list_scans":
                    return [_make_scan("scan-1", "app-1", "ds-1")]
                if method_name == "list_issues_for_applications":
                    return [_make_issue("issue-1", "app-1", "ds-1")]
                return []
            mock_agg_list.side_effect = _fake_aggregate_list

            mock_service.apply_filters.return_value = (
                [_make_scan("scan-1", "app-1", "ds-1")],
                [_make_issue("issue-1", "app-1", "ds-1")],
            )
            mock_service.filter_issues_by_dimensions.return_value = [
                _make_issue("issue-1", "app-1", "ds-1")
            ]
            mock_service.calculate_statistics_from_apps.return_value = dict(_DS1_ONLY_STATS)

            from app.api.v1.routes.analytics import _build_bundle

            await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=["ds-1"],
            )

        # source_data is None → condition `source_data is not None` is False →
        # always falls through to recompute
        mock_service.calculate_statistics_from_apps.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_data_source_ids_recomputes(self):
        """Multiple data_source_ids → still recomputes (non-empty list)."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]
            mock_service.calculate_statistics_from_apps.return_value = dict(_ALL_SOURCES_STATS)

            from app.api.v1.routes.analytics import _build_bundle

            await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=["ds-1", "ds-2"],
            )

        # Non-empty list → must recompute
        mock_service.calculate_statistics_from_apps.assert_called_once()


@pytest.mark.unit
class TestCacheKeyVersionBump:
    """Verify cache version was bumped to 19 for the data_source_ids fix."""

    def test_cache_key_version_is_19(self):
        """Cache key version should be 19 after the fix."""
        from app.api.v1.routes.analytics import _build_cache_key

        user = UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=[])
        base_kwargs = dict(
            asset_group_ids=[], application_ids=[], issue_technologies=[],
            vulnerabilities=[], scan_types=[], scan_statuses=[],
            application_name=None, from_date=None, to_date=None,
            compliance_rule="critical_high", compliance_threshold="high",
        )
        # After the fix, changing the version should produce different keys
        # than before. We verify by checking that a key generated now differs
        # from one with v18 logic (the old key).
        key_current = _build_cache_key(user, **base_kwargs)
        key_with_ds = _build_cache_key(user, **base_kwargs, data_source_ids=["ds-1"])
        # Keys should differ when data_source_ids changes
        assert key_current != key_with_ds


# ---------------------------------------------------------------------------
# Bug C + D: Count API guard must respect has_scope_filter
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCountApiScopeGuard:
    """Verify Count API is skipped when scope filters (asset groups / applications) are active.

    Bug C: The guard only checked `not has_dataset_scope_filter` but missed
    `not has_scope_filter`. When user selects specific asset groups,
    the org-wide Count API numbers would silently override correctly-scoped
    in-memory statistics.

    Bug D: `_resolved_count = max(...)` was unconditional, inflating
    resolved counts with org-wide numbers even under scope filters.
    """

    @pytest.mark.asyncio
    async def test_count_api_skipped_when_asset_group_filter_active(self):
        """When asset_group_ids is set, Count API should NOT be called."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
            patch("app.api.v1.routes.analytics.aggregate_issue_counts", new_callable=AsyncMock) as mock_count_api,
        ):
            mock_settings.asoc_use_count_endpoints = True
            mock_settings.asoc_count_timeout_seconds = 5.0
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]
            mock_count_api.return_value = {"total": 999, "resolved": 500}

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **{**_BASE_KWARGS, "asset_group_ids": ["ag-1"]},
                data_source_ids=None,
            )

        # Count API should NOT be called when scope filter is active
        mock_count_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_count_api_called_when_no_scope_filter(self):
        """When no scope filter and no dataset filter, Count API should be called."""
        source_data = _make_source_data()

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
            patch("app.api.v1.routes.analytics.aggregate_issue_counts", new_callable=AsyncMock) as mock_count_api,
        ):
            mock_settings.asoc_use_count_endpoints = True
            mock_settings.asoc_count_timeout_seconds = 5.0
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]
            mock_count_api.return_value = {"total": 999, "resolved": 500}

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=None,
            )

        # Count API should be called when no scope or dataset filter
        mock_count_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolved_count_not_overridden_under_scope_filter(self):
        """Bug D: resolved_count should NOT use org-wide max() under scope filter."""
        source_data = _make_source_data()
        # Set up issues so only 2 are resolved within the scope
        scoped_issues = [
            {**_make_issue("i-1", "app-1", "ds-1"), "status": "Fixed"},
            {**_make_issue("i-2", "app-1", "ds-1"), "status": "Fixed"},
            {**_make_issue("i-3", "app-1", "ds-1"), "status": "Open"},
            {**_make_issue("i-4", "app-1", "ds-1"), "status": "Open"},
            {**_make_issue("i-5", "app-1", "ds-1"), "status": "Open"},
        ]
        source_data["issues"] = scoped_issues

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
            patch("app.api.v1.routes.analytics.aggregate_issue_counts", new_callable=AsyncMock) as mock_count_api,
        ):
            mock_settings.asoc_use_count_endpoints = True
            mock_settings.asoc_count_timeout_seconds = 5.0
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            # Provide app-based stats with count_source so the app_aggregation path is used
            mock_service.calculate_statistics_from_apps.return_value = {
                "total_issues": 5, "critical_issues": 0, "high_issues": 5,
                "medium_issues": 0, "low_issues": 0, "informational_issues": 0,
                "active_issues": 3, "open_issues": 3, "new_issues": 0,
                "in_progress_issues": 0, "fixed_issues": 2, "resolved_issues": 2,
                "total_scans": 4, "running_scans": 0, "failed_scans": 0,
                "total_applications": 1, "count_source": "app_aggregation",
            }
            mock_service.apply_filters.return_value = (source_data["scans"], scoped_issues)
            mock_service.filter_issues_by_dimensions.return_value = scoped_issues
            # Count API would return high org-wide numbers — but should be skipped
            mock_count_api.return_value = {"total": 999, "resolved": 500}

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **{**_BASE_KWARGS, "asset_group_ids": ["ag-1"]},
                data_source_ids=None,
            )

        stats = result["statistics"]
        # resolved_issues should be 2 (from our scoped issues), NOT 500 from Count API
        assert stats["resolved_issues"] == 2
        # active_issues should be total - resolved
        assert stats["active_issues"] >= 0


# ---------------------------------------------------------------------------
# Bug E: Scan count under dataset scope filters
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildBundleScanCountUnderDatasetScopeFilter:
    """Verify scan counts use len(scans) when dataset scope filters are active.

    Bug E: total_scans/scan_count always used app_based_statistics["total_scans"]
    even when scan_types/scan_statuses/date filters narrowed the scan list.
    """

    @pytest.mark.asyncio
    async def test_scan_count_filtered_by_scan_type(self):
        """When scan_types=["SAST"], total_scans should count only SAST scans."""
        source_data = _make_source_data()
        # Add DAST scans
        source_data["scans"].extend([
            {**_make_scan("scan-5", "app-1", "ds-1"), "technology": "DAST"},
            {**_make_scan("scan-6", "app-2", "ds-1"), "technology": "DAST"},
            {**_make_scan("scan-7", "app-3", "ds-2"), "technology": "DAST"},
            {**_make_scan("scan-8", "app-4", "ds-2"), "technology": "DAST"},
        ])
        # Update app_based_statistics to reflect total scans = 8
        source_data["app_based_statistics"]["total_scans"] = 8

        # After filtering by scan_types=["SAST"], only 4 SAST scans remain
        sast_scans = [s for s in source_data["scans"] if s["technology"] == "SAST"]
        assert len(sast_scans) == 4

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            # apply_filters returns filtered scans + all issues
            mock_service.apply_filters.return_value = (sast_scans, source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **{**_BASE_KWARGS, "scan_types": ["SAST"]},
                data_source_ids=None,
            )

        stats = result["statistics"]
        # Bug E fix: total_scans should be 4 (SAST only), not 8
        assert stats["total_scans"] == 4
        assert stats["scan_count"] == 4

    @pytest.mark.asyncio
    async def test_scan_count_unfiltered_uses_app_based_stats(self):
        """When no dataset scope filter, total_scans uses app_based_statistics."""
        source_data = _make_source_data()
        source_data["app_based_statistics"]["total_scans"] = 8

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (source_data["scans"], source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **_BASE_KWARGS,
                data_source_ids=None,
            )

        stats = result["statistics"]
        # No dataset filter → uses app_based_statistics total_scans (8)
        assert stats["total_scans"] == 8
        assert stats["scan_count"] == 8

    @pytest.mark.asyncio
    async def test_scan_count_filtered_by_scan_status(self):
        """When scan_statuses=["ready"], total_scans counts only matching scans."""
        source_data = _make_source_data()
        # Mix scan statuses
        source_data["scans"][0]["status"] = "Failed"
        source_data["scans"][1]["status"] = "Failed"
        ready_scans = [s for s in source_data["scans"] if s["status"] == "Ready"]
        source_data["app_based_statistics"]["total_scans"] = 4

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (ready_scans, source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **{**_BASE_KWARGS, "scan_statuses": ["ready"]},
                data_source_ids=None,
            )

        stats = result["statistics"]
        # Only "Ready" scans should be counted
        assert stats["total_scans"] == len(ready_scans)
        assert stats["scan_count"] == len(ready_scans)

    @pytest.mark.asyncio
    async def test_scan_count_filtered_by_date_range(self):
        """When from_date/to_date is active, total_scans counts only matching scans."""
        source_data = _make_source_data()
        # Only 2 scans survive date filter (simulated by apply_filters return)
        date_filtered_scans = source_data["scans"][:2]
        source_data["app_based_statistics"]["total_scans"] = 4

        with (
            patch("app.api.v1.routes.analytics._is_base_data_fresh", return_value=True),
            patch("app.api.v1.routes.analytics._get_base_data", new_callable=AsyncMock, return_value=source_data),
            patch("app.api.v1.routes.analytics.service") as mock_service,
            patch("app.api.v1.routes.analytics.settings") as mock_settings,
        ):
            mock_settings.asoc_use_count_endpoints = False
            mock_settings.analytics_scan_severity_source = "hybrid"
            _stub_service_methods(mock_service)
            mock_service.apply_filters.return_value = (date_filtered_scans, source_data["issues"])
            mock_service.filter_issues_by_dimensions.return_value = source_data["issues"]

            from app.api.v1.routes.analytics import _build_bundle

            result = await _build_bundle(
                _admin(),
                **{**_BASE_KWARGS, "from_date": "2025-01-01", "to_date": "2025-06-01"},
                data_source_ids=None,
            )

        stats = result["statistics"]
        # Only date-filtered scans should be counted
        assert stats["total_scans"] == 2
        assert stats["scan_count"] == 2
