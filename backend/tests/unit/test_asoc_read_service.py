"""Unit tests for backend/app/services/asoc_read_service.py.

Tests cover:
- Module-level helper functions (_extract_items, _parse_dt, _parse_duration_to_seconds,
  _normalize_scan_type, _normalize_scan_status, _normalize_severity, _is_active_issue,
  _period_bucket, _build_app_technology_maps)
- AsocReadService static/class methods (calculate_statistics, calculate_trend,
  calculate_mttr, calculate_kpi, calculate_prioritization, calculate_findings_series,
  calculate_scan_series, apply_filters, filter_issues_by_dimensions,
  build_issue_filter_options, build_portfolio_summary)
- has_credentials property
- _map_issue_items static method
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import module-level helpers via the module so we can test them directly.
import app.services.asoc_read_service as _mod
from app.services.asoc_read_service import AsocReadService

# Aliases for private helpers
_extract_items = _mod._extract_items
_parse_dt = _mod._parse_dt
_parse_duration_to_seconds = _mod._parse_duration_to_seconds
_normalize_scan_type = _mod._normalize_scan_type
_normalize_scan_status = _mod._normalize_scan_status
_normalize_severity = _mod._normalize_severity
_is_active_issue = _mod._is_active_issue
_period_bucket = _mod._period_bucket
_build_app_technology_maps = _mod._build_app_technology_maps


# ===========================================================================
# _extract_items
# ===========================================================================


class TestExtractItems:
    def test_list_input_returns_same_list(self):
        data = [{"id": "1"}, {"id": "2"}]
        result = _extract_items(data)
        assert result == data

    def test_dict_with_Items_key(self):
        data = {"Items": [{"id": "a"}, {"id": "b"}]}
        result = _extract_items(data)
        assert result == [{"id": "a"}, {"id": "b"}]

    def test_dict_with_value_key(self):
        data = {"value": [{"id": "x"}]}
        result = _extract_items(data)
        assert result == [{"id": "x"}]

    def test_dict_with_items_lowercase_key(self):
        data = {"items": [{"id": "y"}]}
        result = _extract_items(data)
        assert result == [{"id": "y"}]

    def test_dict_with_data_key(self):
        data = {"data": [{"id": "z"}]}
        result = _extract_items(data)
        assert result == [{"id": "z"}]

    def test_returns_empty_for_unknown_shape(self):
        data = {"unknown_key": [{"id": "1"}]}
        result = _extract_items(data)
        assert result == []

    def test_returns_empty_for_none(self):
        result = _extract_items(None)
        assert result == []

    def test_filters_non_dict_items_from_list(self):
        data = [{"id": "1"}, "not-a-dict", 42, {"id": "2"}]
        result = _extract_items(data)
        assert result == [{"id": "1"}, {"id": "2"}]


# ===========================================================================
# _parse_dt
# ===========================================================================


class TestParseDt:
    def test_valid_iso_string(self):
        result = _parse_dt("2025-01-15T10:30:00+00:00")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_z_suffix(self):
        result = _parse_dt("2025-01-01T00:00:00Z")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_returns_none_for_empty_string(self):
        result = _parse_dt("")
        assert result is None

    def test_returns_none_for_none(self):
        result = _parse_dt(None)
        assert result is None

    def test_returns_none_for_invalid(self):
        result = _parse_dt("not-a-date")
        assert result is None

    def test_naive_datetime_gets_utc_tzinfo(self):
        result = _parse_dt("2025-06-01T12:00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc


# ===========================================================================
# _parse_duration_to_seconds
# ===========================================================================


class TestParseDurationToSeconds:
    def test_from_int(self):
        assert _parse_duration_to_seconds(120) == 120.0

    def test_from_float(self):
        assert _parse_duration_to_seconds(90.5) == 90.5

    def test_from_hhmmss(self):
        assert _parse_duration_to_seconds("01:30:00") == 5400.0

    def test_from_mmss(self):
        assert _parse_duration_to_seconds("05:30") == 330.0

    def test_returns_none_for_empty_string(self):
        assert _parse_duration_to_seconds("") is None

    def test_returns_none_for_none(self):
        assert _parse_duration_to_seconds(None) is None

    def test_from_numeric_string(self):
        assert _parse_duration_to_seconds("300") == 300.0

    def test_negative_int_returns_none(self):
        assert _parse_duration_to_seconds(-5) is None


# ===========================================================================
# _normalize_scan_type
# ===========================================================================


class TestNormalizeScanType:
    def test_dynamic_returns_dast(self):
        assert _normalize_scan_type({"ScanType": "DYNAMIC"}) == "DAST"

    def test_dast_returns_dast(self):
        assert _normalize_scan_type({"ScanType": "DAST"}) == "DAST"

    def test_static_returns_sast(self):
        assert _normalize_scan_type({"ScanType": "STATIC"}) == "SAST"

    def test_sast_returns_sast(self):
        assert _normalize_scan_type({"ScanType": "SAST"}) == "SAST"

    def test_sca_returns_sca(self):
        assert _normalize_scan_type({"ScanType": "SCA"}) == "SCA"

    def test_iast_returns_iast(self):
        assert _normalize_scan_type({"ScanType": "IAST"}) == "IAST"

    def test_unknown_type_returns_other(self):
        assert _normalize_scan_type({"ScanType": "UNKNOWN_TYPE"}) == "OTHER"

    def test_name_hint_dast(self):
        assert _normalize_scan_type({"Name": "My DAST Scan"}) == "DAST"

    def test_name_hint_sast(self):
        assert _normalize_scan_type({"Name": "My SAST Scan"}) == "SAST"

    def test_type_field_case_insensitive(self):
        assert _normalize_scan_type({"type": "dynamic"}) == "DAST"


# ===========================================================================
# _normalize_scan_status
# ===========================================================================


class TestNormalizeScanStatus:
    def test_completed_variants(self):
        for status in ("finished", "done", "complete", "completed"):
            assert _normalize_scan_status({"Status": status}) == "completed", f"Failed for: {status}"

    def test_ready_variants(self):
        for status in ("ready", "finishedwithwarning", "readywithissues"):
            assert _normalize_scan_status({"Status": status}) == "completed", f"Failed for: {status}"

    def test_failed_variants(self):
        for status in ("aborted", "canceled", "cancelled", "failed", "error"):
            assert _normalize_scan_status({"Status": status}) == "failed", f"Failed for: {status}"

    def test_running(self):
        assert _normalize_scan_status({"Status": "inprogress"}) == "running"
        assert _normalize_scan_status({"Status": "running"}) == "running"

    def test_pending(self):
        assert _normalize_scan_status({"Status": "pending"}) == "pending"
        assert _normalize_scan_status({"Status": "queued"}) == "pending"

    def test_latest_execution_status_used(self):
        item = {"LatestExecution": {"Status": "Completed"}}
        assert _normalize_scan_status(item) == "completed"


# ===========================================================================
# _normalize_severity
# ===========================================================================


class TestNormalizeSeverity:
    def test_critical_variants(self):
        for val in ("critical", "4", "sev4", "sev-4", "veryhigh"):
            assert _normalize_severity(val) == "critical", f"Failed for: {val}"

    def test_high_variants(self):
        for val in ("high", "3", "sev3", "sev-3"):
            assert _normalize_severity(val) == "high", f"Failed for: {val}"

    def test_medium_variants(self):
        for val in ("medium", "moderate", "2", "sev2", "sev-2"):
            assert _normalize_severity(val) == "medium", f"Failed for: {val}"

    def test_low_variants(self):
        for val in ("low", "1", "sev1", "sev-1", "info", "informational", "0"):
            assert _normalize_severity(val) == "low", f"Failed for: {val}"

    def test_unknown_garbage(self):
        assert _normalize_severity("garbage") == "unknown"

    def test_none_returns_unknown(self):
        assert _normalize_severity(None) == "unknown"


# ===========================================================================
# _is_active_issue
# ===========================================================================


class TestIsActiveIssue:
    def test_open_status_is_active(self):
        assert _is_active_issue({"status": "open"}) is True

    def test_closed_status_is_not_active(self):
        assert _is_active_issue({"status": "closed"}) is False

    def test_fixed_status_is_not_active(self):
        assert _is_active_issue({"status": "fixed"}) is False

    def test_resolved_status_is_not_active(self):
        assert _is_active_issue({"status": "resolved"}) is False

    def test_empty_status_is_active(self):
        # Empty string is not in the closed set
        assert _is_active_issue({"status": ""}) is True

    def test_Open_capitalized_is_active(self):
        assert _is_active_issue({"status": "Open"}) is True


# ===========================================================================
# _period_bucket
# ===========================================================================


class TestPeriodBucket:
    def test_month_granularity(self):
        result = _period_bucket("2025-03-15T00:00:00Z", "month")
        assert result == "2025-03"

    def test_week_granularity(self):
        result = _period_bucket("2025-01-06T00:00:00Z", "week")
        # 2025-01-06 is in ISO week 2 of 2025
        assert result is not None
        assert result.startswith("2025-W")

    def test_day_granularity(self):
        result = _period_bucket("2025-06-20T12:00:00Z", "day")
        assert result == "2025-06-20"

    def test_year_granularity(self):
        result = _period_bucket("2025-09-01T00:00:00Z", "year")
        assert result == "2025"

    def test_returns_none_for_invalid_date(self):
        result = _period_bucket("not-a-date", "month")
        assert result is None

    def test_returns_none_for_none(self):
        result = _period_bucket(None, "month")
        assert result is None


# ===========================================================================
# _build_app_technology_maps
# ===========================================================================


class TestBuildAppTechnologyMaps:
    def test_single_type_per_app(self):
        scans = [
            {"application_id": "app-1", "scan_type": "DAST"},
            {"application_id": "app-1", "scan_type": "DAST"},
        ]
        tech_map, primary_map = _build_app_technology_maps(scans)
        assert "DAST" in tech_map["app-1"]
        assert primary_map["app-1"] == "DAST"

    def test_tie_breaker_dast_wins_over_sast(self):
        # Equal counts: DAST priority (4) > SAST priority (3)
        scans = [
            {"application_id": "app-1", "scan_type": "DAST"},
            {"application_id": "app-1", "scan_type": "SAST"},
        ]
        tech_map, primary_map = _build_app_technology_maps(scans)
        assert primary_map["app-1"] == "DAST"

    def test_ignores_unknown_scan_types(self):
        scans = [{"application_id": "app-1", "scan_type": "OTHER"}]
        tech_map, primary_map = _build_app_technology_maps(scans)
        assert "app-1" not in primary_map

    def test_empty_scans(self):
        tech_map, primary_map = _build_app_technology_maps([])
        assert tech_map == {}
        assert primary_map == {}

    def test_multiple_apps(self):
        scans = [
            {"application_id": "app-1", "scan_type": "SAST"},
            {"application_id": "app-2", "scan_type": "SCA"},
        ]
        tech_map, primary_map = _build_app_technology_maps(scans)
        assert primary_map["app-1"] == "SAST"
        assert primary_map["app-2"] == "SCA"


# ===========================================================================
# AsocReadService.calculate_statistics
# ===========================================================================


class TestCalculateStatistics:
    def test_counts_by_severity(self):
        issues = [
            {"severity": "critical", "status": "Open"},
            {"severity": "high", "status": "Open"},
            {"severity": "medium", "status": "Open"},
            {"severity": "low", "status": "Open"},
        ]
        result = AsocReadService.calculate_statistics([], issues)
        assert result["critical_issues"] == 1
        assert result["high_issues"] == 1
        assert result["medium_issues"] == 1
        assert result["low_issues"] == 1
        assert result["total_issues"] == 4

    def test_active_vs_resolved(self):
        issues = [
            {"severity": "high", "status": "Open"},
            {"severity": "medium", "status": "closed"},
            {"severity": "low", "status": "fixed"},
        ]
        result = AsocReadService.calculate_statistics([], issues)
        assert result["active_issues"] == 1
        assert result["resolved_issues"] == 2

    def test_open_scans_counted(self):
        scans = [
            {"status": "running"},
            {"status": "pending"},
            {"status": "completed"},
        ]
        result = AsocReadService.calculate_statistics(scans, [])
        assert result["open_scans"] == 2

    def test_empty_inputs(self):
        result = AsocReadService.calculate_statistics([], [])
        assert result["total_issues"] == 0
        assert result["active_issues"] == 0
        assert result["open_scans"] == 0


# ===========================================================================
# AsocReadService.calculate_trend
# ===========================================================================


class TestCalculateTrend:
    def test_groups_by_month(self):
        issues = [
            {"opened_at": "2025-01-10T00:00:00Z"},
            {"opened_at": "2025-01-20T00:00:00Z"},
            {"opened_at": "2025-02-05T00:00:00Z"},
        ]
        result = AsocReadService.calculate_trend(issues)
        months = {row["month"] for row in result}
        assert "2025-01" in months
        assert "2025-02" in months
        jan_row = next(r for r in result if r["month"] == "2025-01")
        assert jan_row["issues"] == 2

    def test_returns_current_month_when_empty(self):
        result = AsocReadService.calculate_trend([])
        assert len(result) == 1
        assert "month" in result[0]
        assert result[0]["issues"] == 0

    def test_sorted_by_month(self):
        issues = [
            {"opened_at": "2025-03-01T00:00:00Z"},
            {"opened_at": "2025-01-01T00:00:00Z"},
            {"opened_at": "2025-02-01T00:00:00Z"},
        ]
        result = AsocReadService.calculate_trend(issues)
        months = [r["month"] for r in result]
        assert months == sorted(months)


# ===========================================================================
# AsocReadService.calculate_mttr
# ===========================================================================


class TestCalculateMttr:
    def test_averages_by_month(self):
        issues = [
            {"closed_at": "2025-02-20T00:00:00Z", "mttr_days": 30},
            {"closed_at": "2025-02-25T00:00:00Z", "mttr_days": 10},
        ]
        result = AsocReadService.calculate_mttr(issues)
        assert len(result) == 1
        assert result[0]["month"] == "2025-02"
        assert result[0]["days"] == 20.0

    def test_returns_current_month_when_empty(self):
        result = AsocReadService.calculate_mttr([])
        assert len(result) == 1
        assert result[0]["days"] == 0

    def test_skips_issues_without_closed_at(self):
        issues = [
            {"closed_at": "", "mttr_days": 5},
            {"closed_at": "2025-03-01T00:00:00Z", "mttr_days": 10},
        ]
        result = AsocReadService.calculate_mttr(issues)
        assert len(result) == 1
        assert result[0]["month"] == "2025-03"


# ===========================================================================
# AsocReadService.calculate_kpi
# ===========================================================================


class TestCalculateKpi:
    def test_critical_exposure_percentage(self):
        issues = [{"severity": "critical", "status": "Open"}] + \
                 [{"severity": "low", "status": "Open"}] * 9
        result = AsocReadService.calculate_kpi(issues)
        critical_kpi = next(k for k in result if k["kpi"] == "Critical Exposure")
        assert critical_kpi["value"] == 10.0

    def test_remediation_closure_percentage(self):
        issues = [
            {"severity": "high", "status": "fixed"},
            {"severity": "high", "status": "closed"},
            {"severity": "high", "status": "Open"},
            {"severity": "high", "status": "Open"},
        ]
        result = AsocReadService.calculate_kpi(issues)
        closure_kpi = next(k for k in result if k["kpi"] == "Remediation Closure")
        assert closure_kpi["value"] == 50.0

    def test_returns_three_kpis(self):
        result = AsocReadService.calculate_kpi([{"severity": "high", "status": "Open"}])
        assert len(result) == 3
        kpi_names = {k["kpi"] for k in result}
        assert "Critical Exposure" in kpi_names
        assert "High Exposure" in kpi_names
        assert "Remediation Closure" in kpi_names

    def test_empty_issues_no_division_error(self):
        result = AsocReadService.calculate_kpi([])
        # total defaults to 1 to avoid division by zero
        assert all(k["value"] == 0.0 for k in result)


# ===========================================================================
# AsocReadService.calculate_prioritization
# ===========================================================================


class TestCalculatePrioritization:
    def _make_issues(self):
        return [
            {
                "severity": "critical",
                "status": "Open",
                "application_id": "app-1",
                "application_name": "App One",
                "fix_group_id": "fg-1",
                "fix_group_name": "SQL Injection",
                "correlation_key": "sqli",
            },
            {
                "severity": "high",
                "status": "Open",
                "application_id": "app-1",
                "application_name": "App One",
                "fix_group_id": "fg-2",
                "fix_group_name": "XSS",
                "correlation_key": "xss",
            },
            {
                "severity": "medium",
                "status": "Open",
                "application_id": "app-2",
                "application_name": "App Two",
                "fix_group_id": "fg-1",
                "fix_group_name": "SQL Injection",
                "correlation_key": "sqli",
            },
        ]

    def test_top_fix_groups_by_weighted_score(self):
        issues = self._make_issues()
        result = AsocReadService.calculate_prioritization(issues)
        top_groups = result["fix_groups"]["top_groups"]
        assert len(top_groups) > 0
        # SQL Injection group has critical + medium → higher score than XSS (high only)
        assert top_groups[0]["fix_group_name"] == "SQL Injection"

    def test_most_critical_apps(self):
        issues = self._make_issues()
        result = AsocReadService.calculate_prioritization(issues)
        most_critical = result["most_critical"]
        assert len(most_critical) > 0
        # app-1 has critical + high → higher score
        assert most_critical[0]["application_id"] == "app-1"

    def test_raw_findings_totals(self):
        issues = self._make_issues()
        result = AsocReadService.calculate_prioritization(issues)
        raw = result["raw_findings"]
        assert raw["critical"] == 1
        assert raw["high"] == 1
        assert raw["medium"] == 1
        assert raw["total"] == 3

    def test_empty_issues(self):
        result = AsocReadService.calculate_prioritization([])
        assert result["raw_findings"]["total"] == 0
        assert result["fix_groups"]["top_groups"] == []
        assert result["most_critical"] == []


# ===========================================================================
# AsocReadService.calculate_findings_series
# ===========================================================================


class TestCalculateFindingsSeries:
    def test_month_granularity(self):
        issues = [
            {"opened_at": "2025-01-10T00:00:00Z", "severity": "critical"},
            {"opened_at": "2025-01-20T00:00:00Z", "severity": "high"},
            {"opened_at": "2025-02-05T00:00:00Z", "severity": "medium"},
        ]
        result = AsocReadService.calculate_findings_series(issues, "month")
        periods = {r["period"] for r in result}
        assert "2025-01" in periods
        assert "2025-02" in periods
        jan = next(r for r in result if r["period"] == "2025-01")
        assert jan["critical"] == 1
        assert jan["high"] == 1

    def test_week_granularity(self):
        issues = [
            {"opened_at": "2025-01-06T00:00:00Z", "severity": "high"},
        ]
        result = AsocReadService.calculate_findings_series(issues, "week")
        assert len(result) >= 1
        assert "W" in result[0]["period"]

    def test_returns_current_period_when_empty(self):
        result = AsocReadService.calculate_findings_series([], "month")
        assert len(result) == 1
        assert result[0]["total"] == 0

    def test_total_field_is_sum_of_severities(self):
        issues = [
            {"opened_at": "2025-03-01T00:00:00Z", "severity": "critical"},
            {"opened_at": "2025-03-15T00:00:00Z", "severity": "high"},
        ]
        result = AsocReadService.calculate_findings_series(issues, "month")
        row = result[0]
        assert row["total"] == row["critical"] + row["high"] + row["medium"] + row["low"] + row["unknown"]


# ===========================================================================
# AsocReadService.calculate_scan_series
# ===========================================================================


class TestCalculateScanSeries:
    def _make_scans(self):
        return [
            {
                "id": "s-1",
                "created_at": "2025-01-15T00:00:00Z",
                "application_id": "app-1",
                "native_severity": "high",
                "scan_type": "SAST",
            },
            {
                "id": "s-2",
                "created_at": "2025-02-10T00:00:00Z",
                "application_id": "app-2",
                "native_severity": "unknown",
                "scan_type": "DAST",
            },
        ]

    def _make_issues(self):
        return [
            {"application_id": "app-2", "severity": "critical", "status": "Open"},
        ]

    def test_hybrid_mode_uses_native_when_available(self):
        scans = self._make_scans()
        result = AsocReadService.calculate_scan_series(scans, [], "month", "hybrid")
        jan = next((r for r in result if r["period"] == "2025-01"), None)
        assert jan is not None
        assert jan["high"] == 1

    def test_hybrid_mode_falls_back_to_derived(self):
        scans = self._make_scans()
        issues = self._make_issues()
        result = AsocReadService.calculate_scan_series(scans, issues, "month", "hybrid")
        feb = next((r for r in result if r["period"] == "2025-02"), None)
        assert feb is not None
        # app-2 has critical issue → derived severity = critical
        assert feb["critical"] == 1

    def test_native_mode_only(self):
        scans = self._make_scans()
        result = AsocReadService.calculate_scan_series(scans, [], "month", "native")
        jan = next((r for r in result if r["period"] == "2025-01"), None)
        assert jan is not None
        assert jan["high"] == 1

    def test_derived_mode_only(self):
        scans = self._make_scans()
        issues = self._make_issues()
        result = AsocReadService.calculate_scan_series(scans, issues, "month", "derived")
        # app-1 has no issues → unknown; app-2 has critical issue
        feb = next((r for r in result if r["period"] == "2025-02"), None)
        assert feb is not None
        assert feb["critical"] == 1

    def test_returns_current_period_when_empty(self):
        result = AsocReadService.calculate_scan_series([], [], "month")
        assert len(result) == 1
        assert result[0]["total"] == 0


# ===========================================================================
# AsocReadService.apply_filters
# ===========================================================================


class TestApplyFilters:
    def _make_data(self):
        scans = [
            {"id": "s-1", "asset_group_id": "ag-1", "application_id": "app-1",
             "scan_type": "DAST", "status": "completed", "created_at": "2025-01-15T00:00:00Z"},
            {"id": "s-2", "asset_group_id": "ag-2", "application_id": "app-2",
             "scan_type": "SAST", "status": "failed", "created_at": "2025-02-10T00:00:00Z"},
        ]
        issues = [
            {"id": "i-1", "asset_group_id": "ag-1", "application_id": "app-1",
             "severity": "critical", "status": "Open", "opened_at": "2025-01-10T00:00:00Z",
             "vulnerability": "SQL Injection"},
            {"id": "i-2", "asset_group_id": "ag-2", "application_id": "app-2",
             "severity": "high", "status": "Open", "opened_at": "2025-02-01T00:00:00Z",
             "vulnerability": "XSS"},
        ]
        return scans, issues

    def test_filter_by_asset_group(self):
        scans, issues = self._make_data()
        f_scans, f_issues = AsocReadService.apply_filters(
            scans, issues, asset_group_id="ag-1"
        )
        assert all(s["asset_group_id"] == "ag-1" for s in f_scans)
        assert all(i["asset_group_id"] == "ag-1" for i in f_issues)

    def test_filter_by_application_id(self):
        scans, issues = self._make_data()
        f_scans, f_issues = AsocReadService.apply_filters(
            scans, issues, application_id="app-2"
        )
        assert all(s["application_id"] == "app-2" for s in f_scans)
        assert all(i["application_id"] == "app-2" for i in f_issues)

    def test_filter_by_scan_type(self):
        scans, issues = self._make_data()
        f_scans, f_issues = AsocReadService.apply_filters(
            scans, issues, scan_types=["DAST"]
        )
        assert all(s["scan_type"] == "DAST" for s in f_scans)

    def test_filter_by_date_range(self):
        scans, issues = self._make_data()
        f_scans, f_issues = AsocReadService.apply_filters(
            scans, issues,
            from_date="2025-02-01T00:00:00Z",
            to_date="2025-03-01T00:00:00Z",
        )
        assert all(s["id"] == "s-2" for s in f_scans)
        assert all(i["id"] == "i-2" for i in f_issues)

    def test_no_filters_returns_all(self):
        scans, issues = self._make_data()
        f_scans, f_issues = AsocReadService.apply_filters(scans, issues)
        assert len(f_scans) == len(scans)
        assert len(f_issues) == len(issues)


# ===========================================================================
# AsocReadService.filter_issues_by_dimensions
# ===========================================================================


class TestFilterIssuesByDimensions:
    def _make_data(self):
        scans = [
            {"application_id": "app-1", "scan_type": "DAST"},
            {"application_id": "app-2", "scan_type": "SAST"},
        ]
        issues = [
            {"id": "i-1", "application_id": "app-1", "vulnerability": "XSS",
             "issue_technology": "DAST", "status": "Open"},
            {"id": "i-2", "application_id": "app-2", "vulnerability": "SQL Injection",
             "issue_technology": "SAST", "status": "Open"},
        ]
        return scans, issues

    def test_filter_by_technology(self):
        scans, issues = self._make_data()
        result = AsocReadService.filter_issues_by_dimensions(
            scans, issues, issue_technologies=["DAST"]
        )
        assert all(i["issue_technology"] == "DAST" for i in result)
        assert len(result) == 1

    def test_filter_by_vulnerability(self):
        scans, issues = self._make_data()
        result = AsocReadService.filter_issues_by_dimensions(
            scans, issues, vulnerabilities=["xss"]
        )
        assert len(result) == 1
        assert result[0]["id"] == "i-1"

    def test_no_filters_returns_all(self):
        scans, issues = self._make_data()
        result = AsocReadService.filter_issues_by_dimensions(scans, issues)
        assert len(result) == len(issues)


# ===========================================================================
# AsocReadService.build_issue_filter_options
# ===========================================================================


class TestBuildIssueFilterOptions:
    def test_counts_technologies(self):
        scans = [{"application_id": "app-1", "scan_type": "DAST"}]
        issues = [
            {"application_id": "app-1", "issue_technology": "DAST",
             "vulnerability": "XSS", "status": "Open"},
            {"application_id": "app-1", "issue_technology": "DAST",
             "vulnerability": "CSRF", "status": "Open"},
        ]
        result = AsocReadService.build_issue_filter_options(scans, issues)
        tech_items = {t["value"]: t["count"] for t in result["technologies"]}
        assert tech_items["DAST"] == 2

    def test_vulnerability_items_sorted_by_count(self):
        scans = []
        issues = [
            {"application_id": "app-1", "issue_technology": "",
             "vulnerability": "XSS", "status": "Open"},
            {"application_id": "app-1", "issue_technology": "",
             "vulnerability": "XSS", "status": "Open"},
            {"application_id": "app-1", "issue_technology": "",
             "vulnerability": "CSRF", "status": "Open"},
        ]
        result = AsocReadService.build_issue_filter_options(scans, issues)
        vulns = result["vulnerabilities"]
        assert vulns[0]["value"] == "xss"
        assert vulns[0]["count"] == 2

    def test_returns_required_keys(self):
        result = AsocReadService.build_issue_filter_options([], [])
        assert "technologies" in result
        assert "vulnerabilities" in result
        assert "unclassified_count" in result


# ===========================================================================
# AsocReadService.build_portfolio_summary
# ===========================================================================


class TestBuildPortfolioSummary:
    def test_counts_correct(self, fake_scans, fake_issues, fake_applications, fake_asset_groups):
        svc = AsocReadService.__new__(AsocReadService)
        result = svc.build_portfolio_summary(
            scans=fake_scans,
            issues=fake_issues,
            applications=fake_applications,
            asset_groups=fake_asset_groups,
        )
        assert result["scan_count"] == len(fake_scans)
        assert result["total_issues"] == len(fake_issues)
        assert result["application_count"] == len(fake_applications)
        assert result["asset_group_count"] == len(fake_asset_groups)

    def test_active_issues_count(self, fake_issues):
        svc = AsocReadService.__new__(AsocReadService)
        result = svc.build_portfolio_summary(
            scans=[],
            issues=fake_issues,
            applications=[],
            asset_groups=[],
        )
        # fake_issues has 2 Open + 1 closed
        assert result["active_issues"] == 2

    def test_empty_inputs(self):
        svc = AsocReadService.__new__(AsocReadService)
        result = svc.build_portfolio_summary(
            scans=[], issues=[], applications=[], asset_groups=[]
        )
        assert result["scan_count"] == 0
        assert result["total_issues"] == 0
        assert result["active_issues"] == 0


# ===========================================================================
# AsocReadService._map_issue_items
# ===========================================================================


class TestMapIssueItems:
    def test_extracts_severity(self):
        items = [{"Id": "i-1", "Severity": "High", "Status": "Open"}]
        result = AsocReadService._map_issue_items(items)
        assert result[0]["severity"] == "high"

    def test_infers_closed_at_from_last_updated_when_status_closed(self):
        items = [
            {
                "Id": "i-1",
                "Severity": "Medium",
                "Status": "Closed",
                "LastUpdated": "2025-03-01T00:00:00Z",
            }
        ]
        result = AsocReadService._map_issue_items(items)
        assert result[0]["closed_at"] == "2025-03-01T00:00:00Z"

    def test_does_not_overwrite_existing_closed_at(self):
        items = [
            {
                "Id": "i-1",
                "Severity": "Low",
                "Status": "Closed",
                "ClosedAt": "2025-02-01T00:00:00Z",
                "LastUpdated": "2025-03-01T00:00:00Z",
            }
        ]
        result = AsocReadService._map_issue_items(items)
        assert result[0]["closed_at"] == "2025-02-01T00:00:00Z"

    def test_default_app_id_used_when_missing(self):
        items = [{"Id": "i-1", "Severity": "Low", "Status": "Open"}]
        result = AsocReadService._map_issue_items(items, default_app_id="app-default")
        assert result[0]["application_id"] == "app-default"

    def test_fix_group_fallback_to_unassigned(self):
        items = [{"Id": "i-1", "Severity": "Low", "Status": "Open"}]
        result = AsocReadService._map_issue_items(items)
        assert result[0]["fix_group_name"] == "Unassigned"

    def test_maps_all_required_fields(self):
        items = [
            {
                "Id": "i-1",
                "Severity": "Critical",
                "Status": "Open",
                "ApplicationId": "app-1",
                "AssetGroupId": "ag-1",
                "DateCreated": "2025-01-01T00:00:00Z",
                "IssueTypeName": "SQL Injection",
                "Technology": "DAST",
            }
        ]
        result = AsocReadService._map_issue_items(items)
        row = result[0]
        assert row["id"] == "i-1"
        assert row["severity"] == "critical"
        assert row["application_id"] == "app-1"
        assert row["asset_group_id"] == "ag-1"
        assert row["opened_at"] == "2025-01-01T00:00:00Z"
        assert row["vulnerability"] == "SQL Injection"
        assert row["issue_technology"] == "DAST"


# ===========================================================================
# AsocReadService.has_credentials
# ===========================================================================


class TestHasCredentials:
    def test_false_when_no_key(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        svc._client = mock_client
        assert svc.has_credentials is False

    def test_false_when_no_secret(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = ""
        mock_client.base_url = "https://asoc.example.com"
        svc._client = mock_client
        assert svc.has_credentials is False

    def test_false_when_no_url(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = ""
        svc._client = mock_client
        assert svc.has_credentials is False

    def test_true_when_all_set(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        svc._client = mock_client
        assert svc.has_credentials is True


# ===========================================================================
# AsocReadService.get_tenant_info
# ===========================================================================


class TestGetTenantInfo:
    async def test_returns_empty_when_no_credentials(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.api_secret = ""
        mock_client.base_url = ""
        svc._client = mock_client
        result = await svc.get_tenant_info()
        assert result == {}

    async def test_returns_dict_on_success(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        mock_client.get = AsyncMock(return_value={"TenantId": "t-1"})
        svc._client = mock_client
        result = await svc.get_tenant_info()
        assert result == {"TenantId": "t-1"}

    async def test_returns_empty_on_error_when_use_mock_on_error(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        mock_client.get = AsyncMock(side_effect=RuntimeError("network error"))
        svc._client = mock_client
        result = await svc.get_tenant_info(use_mock_on_error=True)
        assert result == {}

    async def test_raises_on_error_when_not_use_mock_on_error(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        mock_client.get = AsyncMock(side_effect=RuntimeError("network error"))
        svc._client = mock_client
        with pytest.raises(RuntimeError):
            await svc.get_tenant_info(use_mock_on_error=False)


# ===========================================================================
# AsocReadService.list_applications
# ===========================================================================


class TestListApplications:
    async def test_returns_mock_when_no_credentials(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.api_secret = ""
        mock_client.base_url = ""
        svc._client = mock_client
        result = await svc.list_applications()
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_maps_fields_correctly(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        mock_client.get = AsyncMock(return_value={
            "Items": [
                {"Id": "app-1", "Name": "My App", "AssetGroupId": "ag-1",
                 "CreatedAt": "2025-01-01T00:00:00Z"}
            ]
        })
        svc._client = mock_client
        result = await svc.list_applications()
        assert len(result) == 1
        assert result[0]["id"] == "app-1"
        assert result[0]["name"] == "My App"
        assert result[0]["asset_group_id"] == "ag-1"


# ===========================================================================
# AsocReadService.list_asset_groups
# ===========================================================================


class TestListAssetGroups:
    async def test_returns_mock_when_no_credentials(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.api_secret = ""
        mock_client.base_url = ""
        svc._client = mock_client
        result = await svc.list_asset_groups()
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_maps_fields_correctly(self):
        svc = AsocReadService.__new__(AsocReadService)
        mock_client = MagicMock()
        mock_client.api_key = "key"
        mock_client.api_secret = "secret"
        mock_client.base_url = "https://asoc.example.com"
        mock_client.get = AsyncMock(return_value={
            "Items": [{"Id": "ag-1", "Name": "Production"}]
        })
        svc._client = mock_client
        result = await svc.list_asset_groups()
        assert len(result) == 1
        assert result[0]["id"] == "ag-1"
        assert result[0]["name"] == "Production"