"""Unit tests for analytics routes and helper functions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _developer() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])


def _app_owner() -> UserContext:
    return UserContext(subject="owner@test.com", role="AppOwner", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_BUNDLE = {
    "statistics": {
        "total_issues": 10,
        "active_issues": 7,
        "resolved_issues": 3,
        "critical_issues": 2,
        "high_issues": 3,
        "medium_issues": 2,
        "low_issues": 0,
    },
    "trend_active": [{"month": "2025-01", "issues": 5}],
    "trend_all": [{"month": "2025-01", "issues": 10}],
    "kpi": [{"name": "Critical Exposure", "value": 20.0}],
    "mttr": [{"month": "2025-01", "avg_days": 14.5}],
    "portfolio_summary": {
        "scan_count": 5,
        "application_count": 2,
        "asset_group_count": 2,
        "total_issues": 10,
        "active_issues": 7,
    },
    "prioritization": {"raw_findings": {}, "fix_groups": {}, "most_critical": []},
    "findings_series": {"week": [], "month": [], "year": []},
    "scan_series": {"day": [], "week": [], "month": []},
    "scan_series_by_source": {"derived": {}, "native": {}, "hybrid": {}},
    "workbench_trends": {},
    "issue_filter_options": {"technologies": [], "vulnerabilities": []},
    "generated_at": "2025-01-01T00:00:00+00:00",
}

FAKE_FRESHNESS = {
    "source": "live",
    "generated_at": "2025-01-01T00:00:00+00:00",
    "cached_at": "2025-01-01T00:00:00+00:00",
    "expires_at": "2025-01-01T01:00:00+00:00",
}


@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/statistics
# ---------------------------------------------------------------------------

class TestStatisticsEndpoint:
    def test_statistics_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/statistics")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "total_issues" in data

    def test_statistics_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/analytics/statistics")
        assert resp.status_code in (401, 403)

    def test_statistics_allowed_for_developer(self):
        app.dependency_overrides[get_current_user] = _developer
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/statistics")
        app.dependency_overrides.clear()
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/trend
# ---------------------------------------------------------------------------

class TestTrendEndpoint:
    def test_trend_returns_active_issues_by_default(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/trend")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Default active_only=True returns trend_active
        assert data == FAKE_BUNDLE["trend_active"]

    def test_trend_returns_all_issues_when_active_only_false(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/trend?active_only=false")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data == FAKE_BUNDLE["trend_all"]


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/kpi
# ---------------------------------------------------------------------------

class TestKpiEndpoint:
    def test_kpi_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/kpi")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/mttr
# ---------------------------------------------------------------------------

class TestMttrEndpoint:
    def test_mttr_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/mttr")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/portfolio-summary
# ---------------------------------------------------------------------------

class TestPortfolioSummaryEndpoint:
    def test_portfolio_summary_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with patch("app.api.v1.routes.analytics._get_bundle", new_callable=AsyncMock) as mock_bundle:
            mock_bundle.return_value = (FAKE_BUNDLE, FAKE_FRESHNESS)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/analytics/portfolio-summary")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Helper function tests (pure logic — no HTTP)
# ---------------------------------------------------------------------------

class TestBuildCacheKey:
    def test_build_cache_key_is_deterministic(self):
        from app.api.v1.routes.analytics import _build_cache_key

        user = UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])
        kwargs = dict(
            asset_group_ids=["ag-1"],
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
        )
        key1 = _build_cache_key(user, **kwargs)
        key2 = _build_cache_key(user, **kwargs)
        assert key1 == key2

    def test_build_cache_key_differs_for_different_params(self):
        from app.api.v1.routes.analytics import _build_cache_key

        user = UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])
        base_kwargs = dict(
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
        )
        key1 = _build_cache_key(user, **base_kwargs)
        key2 = _build_cache_key(user, **{**base_kwargs, "asset_group_ids": ["ag-2"]})
        assert key1 != key2


class TestIsSnapshotFresh:
    def test_is_snapshot_fresh_returns_false_for_expired(self):
        from app.api.v1.routes.analytics import _is_snapshot_fresh

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        snapshot = {"expires_at": past, "payload": {}}
        assert _is_snapshot_fresh(snapshot) is False

    def test_is_snapshot_fresh_returns_true_for_valid(self):
        from app.api.v1.routes.analytics import _is_snapshot_fresh

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        snapshot = {"expires_at": future, "payload": {}}
        assert _is_snapshot_fresh(snapshot) is True

    def test_is_snapshot_fresh_returns_false_for_none(self):
        from app.api.v1.routes.analytics import _is_snapshot_fresh

        assert _is_snapshot_fresh(None) is False


class TestNormalizeScanSeveritySource:
    def test_normalize_scan_severity_source_defaults_to_hybrid(self):
        from app.api.v1.routes.analytics import _normalize_scan_severity_source

        assert _normalize_scan_severity_source("unknown_value") == "hybrid"
        assert _normalize_scan_severity_source(None) == "hybrid"
        assert _normalize_scan_severity_source("") == "hybrid"

    def test_normalize_scan_severity_source_accepts_valid_values(self):
        from app.api.v1.routes.analytics import _normalize_scan_severity_source

        assert _normalize_scan_severity_source("derived") == "derived"
        assert _normalize_scan_severity_source("native") == "native"
        assert _normalize_scan_severity_source("hybrid") == "hybrid"


class TestNormalizeComplianceRule:
    def test_normalize_compliance_rule_defaults_to_critical_high(self):
        from app.api.v1.routes.analytics import _normalize_compliance_rule

        assert _normalize_compliance_rule("unknown") == "critical_high"
        assert _normalize_compliance_rule(None) == "critical_high"

    def test_normalize_compliance_rule_accepts_valid_values(self):
        from app.api.v1.routes.analytics import _normalize_compliance_rule

        assert _normalize_compliance_rule("critical_high") == "critical_high"
        assert _normalize_compliance_rule("any_open") == "any_open"
        assert _normalize_compliance_rule("custom") == "custom"


class TestNormalizeIdList:
    def test_normalize_id_list_deduplicates(self):
        from app.api.v1.routes.analytics import _normalize_id_list

        result = _normalize_id_list(["ag-1", "ag-1", "ag-2"], None)
        assert result == ["ag-1", "ag-2"]

    def test_normalize_id_list_splits_comma_separated(self):
        from app.api.v1.routes.analytics import _normalize_id_list

        result = _normalize_id_list(["ag-1,ag-2"], None)
        assert "ag-1" in result
        assert "ag-2" in result


class TestNormalizeIssueTechnologyList:
    def test_normalize_issue_technology_list_filters_invalid(self):
        from app.api.v1.routes.analytics import _normalize_issue_technology_list

        result = _normalize_issue_technology_list(["DAST", "INVALID", "SAST"], None)
        assert "DAST" in result
        assert "SAST" in result
        assert "INVALID" not in result


class TestHydrateBundleDefaults:
    def test_hydrate_bundle_defaults_fills_missing_sections(self):
        from app.api.v1.routes.analytics import _hydrate_bundle_defaults

        minimal_bundle = {
            "statistics": {"total_issues": 5},
            "trend_active": [],
            "trend_all": [],
            "portfolio_summary": {},
        }
        result = _hydrate_bundle_defaults(minimal_bundle)
        assert "kpi" in result
        assert "mttr" in result
        assert "findings_series" in result
        assert "scan_series" in result

    def test_hydrate_bundle_defaults_handles_none_input(self):
        from app.api.v1.routes.analytics import _hydrate_bundle_defaults

        result = _hydrate_bundle_defaults(None)
        assert isinstance(result, dict)
        assert "kpi" in result


class TestResolveScopeFilters:
    def test_resolve_scope_filters_raises_403_for_unauthorized_asset_group(self):
        from fastapi import HTTPException
        from app.api.v1.routes.analytics import _resolve_scope_filters

        # Non-admin user requesting an asset group they don't have access to
        user = UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])
        with pytest.raises(HTTPException) as exc_info:
            _resolve_scope_filters(
                user,
                asset_group_id=None,
                asset_group_ids=["ag-99"],  # not in user's permitted groups
                application_id=None,
                application_ids=None,
            )
        assert exc_info.value.status_code == 403

    def test_resolve_scope_filters_admin_can_access_any_group(self):
        from app.api.v1.routes.analytics import _resolve_scope_filters

        user = UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])
        # Should not raise
        result = _resolve_scope_filters(
            user,
            asset_group_id=None,
            asset_group_ids=["ag-99"],
            application_id=None,
            application_ids=None,
        )
        assert result[0] == ["ag-99"]
