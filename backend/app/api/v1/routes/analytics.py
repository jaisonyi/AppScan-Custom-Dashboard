from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security.authorization import filter_by_asset_group
from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.repositories import postgres_store as sqlite_store
from app.core.config.settings import settings
from app.services.asoc_read_service import AsocReadService, _build_app_technology_maps, _resolve_issue_technology
from app.services.multi_endpoint import (
    aggregate_base_data,
    aggregate_issue_counts,
    aggregate_list,
    aggregate_tenant_info,
    get_endpoint_services,
)
from app.services import issue_count_service

router = APIRouter()
service = AsocReadService()
_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_CACHE_LOCKS_MAX = 500
_LAST_CACHE_CLEANUP_AT = datetime.min.replace(tzinfo=timezone.utc)
logger = logging.getLogger(__name__)
_BASE_DATA_LOCK = asyncio.Lock()
_BASE_DATA_CACHE: dict[str, Any] = {
    "expires_at": None,
    "payload": None,
    "forced_refreshed_at": None,
}
_FORCED_REFRESH_COALESCE_SECONDS = 20


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_snapshot_fresh(snapshot: dict | None) -> bool:
    if not snapshot:
        return False
    expires_at = _from_iso(str(snapshot.get("expires_at", "")))
    if expires_at is None:
        return False
    return expires_at > _utc_now()


def _build_cache_key(
    user: UserContext,
    *,
    asset_group_ids: list[str],
    application_ids: list[str],
    issue_technologies: list[str],
    vulnerabilities: list[str],
    scan_types: list[str],
    scan_statuses: list[str],
    application_name: str | None,
    from_date: str | None,
    to_date: str | None,
    compliance_rule: str,
    compliance_threshold: str,
) -> str:
    payload = {
        "role": user.role,
        "asset_groups": sorted(user.asset_group_ids),
        "asset_group_ids": sorted(asset_group_ids),
        "application_ids": sorted(application_ids),
        "issue_technologies": sorted(issue_technologies),
        "vulnerabilities": sorted(vulnerabilities),
        "scan_types": sorted(scan_types),
        "scan_statuses": sorted(scan_statuses),
        "application_name": (application_name or "").strip().lower(),
        "from_date": from_date,
        "to_date": to_date,
        "compliance_rule": compliance_rule,
        "compliance_threshold": compliance_threshold,
        "v": 17,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"analytics-bundle:{digest}"


def _get_lock(cache_key: str) -> asyncio.Lock:
    lock = _CACHE_LOCKS.get(cache_key)
    if lock is None:
        if len(_CACHE_LOCKS) >= _CACHE_LOCKS_MAX:
            # Evict the oldest 100 entries to prevent unbounded memory growth.
            keys_to_evict = list(itertools.islice(_CACHE_LOCKS, 100))
            for k in keys_to_evict:
                _CACHE_LOCKS.pop(k, None)
        lock = asyncio.Lock()
        _CACHE_LOCKS[cache_key] = lock
    return lock


def _build_freshness(*, source: str, generated_at: str | None, fetched_at: str | None, expires_at: str | None) -> dict:
    return {
        "source": source,
        "generated_at": generated_at,
        "cached_at": fetched_at,
        "expires_at": expires_at,
    }


def _bundle_has_required_sections(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    required = {
        "statistics",
        "trend_active",
        "trend_all",
        "kpi",
        "mttr",
        "portfolio_summary",
        "prioritization",
        "findings_series",
        "scan_series",
        "scan_series_by_source",
        "workbench_trends",
        "chart_data",
    }
    return required.issubset(set(payload.keys()))


def _normalize_scan_severity_source(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"derived", "native", "hybrid"}:
        return mode
    return "hybrid"


def _normalize_compliance_rule(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"critical_high", "any_open", "custom"}:
        return mode
    return "critical_high"


def _normalize_compliance_threshold(value: str | None) -> str:
    sev = str(value or "").strip().lower()
    if sev in {"critical", "high", "medium", "low"}:
        return sev
    return "high"


def _normalize_id_list(values: list[str] | None, single: str | None) -> list[str]:
    raw: list[str] = []
    if single:
        raw.append(single)
    if values:
        raw.extend(values)

    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw:
        for token in str(value).split(","):
            item = token.strip()
            if not item or item in seen:
                continue
            normalized.append(item)
            seen.add(item)
    return normalized


def _normalize_issue_technology_list(values: list[str] | None, single: str | None) -> list[str]:
    allowed = {"DAST", "SAST", "SCA", "IAST"}
    raw = _normalize_id_list(values, single)
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        normalized = str(value or "").strip().upper()
        if normalized not in allowed or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _normalize_vulnerability_list(values: list[str] | None, single: str | None) -> list[str]:
    raw = _normalize_id_list(values, single)
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _normalize_scan_type_list(values: list[str] | None, single: str | None) -> list[str]:
    allowed = {"DAST", "SAST", "SCA", "IAST", "OTHER"}
    raw = _normalize_id_list(values, single)
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        normalized = str(value or "").strip().upper()
        if normalized not in allowed or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _normalize_scan_status_list(values: list[str] | None, single: str | None) -> list[str]:
    allowed = {"completed", "running", "pending", "failed", "unknown", "queued", "scheduled"}
    raw = _normalize_id_list(values, single)
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        normalized = str(value or "").strip().lower()
        if normalized not in allowed or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _resolve_scope_filters(
    user: UserContext,
    *,
    asset_group_id: str | None,
    asset_group_ids: list[str] | None,
    application_id: str | None,
    application_ids: list[str] | None,
) -> tuple[list[str], list[str]]:
    resolved_asset_group_ids = _normalize_id_list(asset_group_ids, asset_group_id)
    resolved_application_ids = _normalize_id_list(application_ids, application_id)

    if user.role not in {"PlatformAdmin", "SecurityManager"} and resolved_asset_group_ids:
        allowed = set(user.asset_group_ids)
        denied = [item for item in resolved_asset_group_ids if item not in allowed]
        if denied:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied for asset groups: {', '.join(sorted(set(denied)))}",
            )

    return resolved_asset_group_ids, resolved_application_ids


def _resolve_issue_filters(
    *,
    issue_technology: str | None,
    issue_technologies: list[str] | None,
    vulnerability: str | None,
    vulnerabilities: list[str] | None,
) -> tuple[list[str], list[str]]:
    resolved_issue_technologies = _normalize_issue_technology_list(issue_technologies, issue_technology)
    resolved_vulnerabilities = _normalize_vulnerability_list(vulnerabilities, vulnerability)
    return resolved_issue_technologies, resolved_vulnerabilities


def _resolve_scan_filters(
    *,
    scan_type: str | None,
    scan_types: list[str] | None,
    scan_status: str | None,
    scan_statuses: list[str] | None,
) -> tuple[list[str], list[str]]:
    resolved_scan_types = _normalize_scan_type_list(scan_types, scan_type)
    resolved_scan_statuses = _normalize_scan_status_list(scan_statuses, scan_status)
    return resolved_scan_types, resolved_scan_statuses


def _to_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_counts_map(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        out[str(key).lower()] = _to_int(value, 0)
    return out


def _hydrate_statistics_from_summary(bundle: dict) -> dict:
    stats = dict(bundle.get("statistics") or {})
    summary = dict(bundle.get("portfolio_summary") or {})

    scan_count_by_status = _coerce_counts_map(summary.get("scan_count_by_status"))
    scan_count_by_type_raw = summary.get("scan_count_by_type")
    scan_count_by_type = dict(scan_count_by_type_raw) if isinstance(scan_count_by_type_raw, dict) else {}

    running_or_pending_scans = (
        _to_int(scan_count_by_status.get("running"), 0)
        + _to_int(scan_count_by_status.get("pending"), 0)
        + _to_int(scan_count_by_status.get("queued"), 0)
        + _to_int(scan_count_by_status.get("scheduled"), 0)
    )
    failed_scans = _to_int(scan_count_by_status.get("failed"), 0)

    total_issues = _to_int(stats.get("total_issues"), _to_int(summary.get("total_issues"), 0))
    active_issues = _to_int(stats.get("active_issues"), _to_int(summary.get("active_issues"), 0))
    resolved_issues = _to_int(stats.get("resolved_issues"), max(total_issues - active_issues, 0))

    critical_issues = _to_int(stats.get("critical_issues"), 0)
    high_issues = _to_int(stats.get("high_issues"), 0)
    medium_issues = _to_int(stats.get("medium_issues"), 0)
    low_issues = _to_int(
        stats.get("low_issues"),
        max(total_issues - (critical_issues + high_issues + medium_issues), 0),
    )

    stats["total_issues"] = total_issues
    stats["active_issues"] = active_issues
    stats["resolved_issues"] = resolved_issues
    stats["critical_issues"] = critical_issues
    stats["high_issues"] = high_issues
    stats["medium_issues"] = medium_issues
    stats["low_issues"] = low_issues

    stats["open_scans"] = _to_int(stats.get("open_scans"), running_or_pending_scans)
    stats["running_or_pending_scans"] = running_or_pending_scans
    stats["failed_scans"] = failed_scans

    scan_count = _to_int(
        stats.get("total_scans"),
        _to_int(stats.get("scan_count"), _to_int(summary.get("scan_count"), 0)),
    )
    stats["scan_count"] = scan_count
    stats["total_scans"] = scan_count
    stats["application_count"] = _to_int(summary.get("application_count"), 0)
    stats["asset_group_count"] = _to_int(summary.get("asset_group_count"), 0)
    stats["scan_count_by_status"] = scan_count_by_status
    stats["scan_count_by_type"] = scan_count_by_type

    stats["severity"] = {
        "critical": critical_issues,
        "high": high_issues,
        "medium": medium_issues,
        "low": low_issues,
        "total": total_issues,
    }
    return stats


def _hydrate_bundle_defaults(payload: dict | None) -> dict:
    bundle = dict(payload or {})
    statistics = dict(bundle.get("statistics") or {})
    bundle["statistics"] = statistics
    trend_active = list(bundle.get("trend_active") or [])
    trend_all = list(bundle.get("trend_all") or [])
    bundle["trend_active"] = trend_active
    bundle["trend_all"] = trend_all
    bundle.setdefault("kpi", [])
    bundle.setdefault("mttr", [])
    bundle.setdefault("portfolio_summary", {})
    bundle["statistics"] = _hydrate_statistics_from_summary(bundle)
    raw_from_stats = {
        "critical": int(statistics.get("critical_issues") or 0),
        "high": int(statistics.get("high_issues") or 0),
        "medium": int(statistics.get("medium_issues") or 0),
        "low": int(statistics.get("low_issues") or 0),
        "unknown": 0,
    }
    raw_from_stats["total"] = int(statistics.get("total_issues") or sum(raw_from_stats.values()))

    default_series = []
    source_trend = trend_all or trend_active
    for row in source_trend:
        period = str(row.get("month") or row.get("period") or "")
        total = int(row.get("issues") or row.get("total") or 0)
        if not period:
            continue
        default_series.append(
            {
                "period": period,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": total,
                "total": total,
            }
        )

    bundle.setdefault(
        "prioritization",
        {
            "raw_findings": raw_from_stats,
            "fix_groups": {
                "total_groups": 0,
                "totals": {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0},
                "top_groups": [],
            },
            "most_critical": [],
            "correlated_findings": [],
            "highlights": {"critical_hotspot_total": 0, "correlated_high_risk_total": 0},
        },
    )
    findings = bundle.get("findings_series")
    if not isinstance(findings, dict):
        findings = {}
    findings.setdefault("week", default_series)
    findings.setdefault("month", default_series)
    findings.setdefault("year", default_series)
    bundle["findings_series"] = findings

    scans = bundle.get("scan_series")
    if not isinstance(scans, dict):
        scans = {}
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    iso_year, iso_week, _ = now.isocalendar()
    week_key = f"{iso_year}-W{int(iso_week):02d}"
    month_key = now.strftime("%Y-%m")

    scans.setdefault(
        "day",
        [{"period": day_key, "critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0}],
    )
    scans.setdefault(
        "week",
        [{"period": week_key, "critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0}],
    )
    scans.setdefault(
        "month",
        [{"period": month_key, "critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0}],
    )
    bundle["scan_series"] = scans

    by_source = bundle.get("scan_series_by_source")
    if not isinstance(by_source, dict):
        by_source = {}
    for mode in ("derived", "native", "hybrid"):
        mode_series = by_source.get(mode)
        if not isinstance(mode_series, dict):
            mode_series = {}
        mode_series.setdefault("day", list(scans.get("day", [])))
        mode_series.setdefault("week", list(scans.get("week", [])))
        mode_series.setdefault("month", list(scans.get("month", [])))
        by_source[mode] = mode_series
    bundle["scan_series_by_source"] = by_source

    workbench = bundle.get("workbench_trends")
    if not isinstance(workbench, dict):
        workbench = {}

    criticality_series = workbench.get("vulnerabilities_criticality")
    if not isinstance(criticality_series, list):
        criticality_series = list(findings.get("month", []))
    if not criticality_series:
        now_key = datetime.now(timezone.utc).strftime("%Y-%m")
        criticality_series = [
            {
                "period": now_key,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
                "total": 0,
            }
        ]

    cumulative_series = workbench.get("cumulative_vulnerabilities")
    if not isinstance(cumulative_series, list):
        cumulative_total = 0
        cumulative_series = []
        for row in criticality_series:
            total = int(row.get("total", 0) or 0)
            cumulative_total += total
            cumulative_series.append(
                {
                    "period": str(row.get("period", "")),
                    "monthly_total": total,
                    "cumulative_total": cumulative_total,
                }
            )

    compliance_series = workbench.get("application_compliance")
    if not isinstance(compliance_series, list):
        total_apps = int(bundle.get("portfolio_summary", {}).get("application_count", 0) or 0)
        compliance_series = [
            {
                "period": str(row.get("period", "")),
                "total_apps": total_apps,
                "compliant": total_apps,
                "non_compliant": 0,
                "compliance_rate": 100.0 if total_apps > 0 else 0.0,
            }
            for row in criticality_series
        ]

    workbench["vulnerabilities_criticality"] = criticality_series
    workbench["cumulative_vulnerabilities"] = cumulative_series
    workbench["application_compliance"] = compliance_series

    application_onboarded = workbench.get("application_onboarded")
    if not isinstance(application_onboarded, list):
        running = 0
        application_onboarded = []
        for row in compliance_series:
            running += int(row.get("total_apps", 0) or 0)
            application_onboarded.append(
                {
                    "period": str(row.get("period", "")),
                    "onboarded_count": int(row.get("total_apps", 0) or 0),
                    "cumulative_onboarded": running,
                }
            )
    workbench["application_onboarded"] = application_onboarded

    avg_days_to_resolve = workbench.get("average_days_to_resolve")
    if not isinstance(avg_days_to_resolve, list):
        avg_days_to_resolve = [
            {
                "period": str(row.get("period", "")),
                "average_days": 0.0,
                "fixed_count": 0,
            }
            for row in compliance_series
        ]
    workbench["average_days_to_resolve"] = avg_days_to_resolve

    license_consumption = workbench.get("license_consumption")
    if isinstance(license_consumption, dict) and "technologies" not in license_consumption:
        # Legacy shape migration (dast/sast only) -> normalized v2 shape.
        legacy_dast = dict(license_consumption.get("dast") or {})
        legacy_sast = dict(license_consumption.get("sast") or {})
        license_consumption = {
            "detected_model": "unknown",
            "detected_model_label": "Unknown",
            "model_source": "legacy",
            "technologies": [
                {
                    "technology": "DAST",
                    "consumed_units": _to_int(legacy_dast.get("consumed_scans"), 0),
                    "consumed_scans": _to_int(legacy_dast.get("consumed_scans"), 0),
                    "consumed_apps": _to_int(legacy_dast.get("consumed_apps"), 0),
                    "peak_concurrent": 0,
                },
                {
                    "technology": "SAST",
                    "consumed_units": _to_int(legacy_sast.get("consumed_scans"), 0),
                    "consumed_scans": _to_int(legacy_sast.get("consumed_scans"), 0),
                    "consumed_apps": _to_int(legacy_sast.get("consumed_apps"), 0),
                    "peak_concurrent": 0,
                },
                {"technology": "SCA", "consumed_units": 0, "consumed_scans": 0, "consumed_apps": 0, "peak_concurrent": 0},
                {"technology": "IAST", "consumed_units": 0, "consumed_scans": 0, "consumed_apps": 0, "peak_concurrent": 0},
            ],
            "summary": {
                "total_scans": _to_int(legacy_dast.get("consumed_scans"), 0) + _to_int(legacy_sast.get("consumed_scans"), 0),
                "total_apps": _to_int(legacy_dast.get("consumed_apps"), 0) + _to_int(legacy_sast.get("consumed_apps"), 0),
            },
        }
    if not isinstance(license_consumption, dict):
        license_consumption = {
            "detected_model": "unknown",
            "detected_model_label": "Unknown",
            "model_source": "unknown",
            "technologies": [
                {"technology": "DAST", "consumed_units": 0, "consumed_scans": 0, "consumed_apps": 0, "peak_concurrent": 0},
                {"technology": "SAST", "consumed_units": 0, "consumed_scans": 0, "consumed_apps": 0, "peak_concurrent": 0},
                {"technology": "SCA", "consumed_units": 0, "consumed_scans": 0, "consumed_apps": 0, "peak_concurrent": 0},
                {"technology": "IAST", "consumed_units": 0, "consumed_scans": 0, "consumed_apps": 0, "peak_concurrent": 0},
            ],
            "summary": {"total_scans": 0, "total_apps": 0},
        }
    workbench["license_consumption"] = license_consumption

    scan_time_bucket_options = [
        {"key": "lt5", "label": "<5m"},
        {"key": "m5_10", "label": "5-10m"},
        {"key": "m10_30", "label": "10-30m"},
        {"key": "m30_60", "label": "30-60m"},
        {"key": "m60_120", "label": "60-120m"},
        {"key": "m120_240", "label": "120-240m"},
        {"key": "m240_300", "label": "240-300m"},
        {"key": "gte300", "label": ">=300m"},
    ]
    scan_time_bucket_keys = [item["key"] for item in scan_time_bucket_options]

    now_key = datetime.now(timezone.utc)
    scan_time_default_period_values = {
        "week": now_key.strftime("%G-W%V"),
        "month": now_key.strftime("%Y-%m"),
        "year": now_key.strftime("%Y"),
    }

    def _empty_scan_time_bucket_counts() -> dict[str, int]:
        return {"sast": 0, "sca": 0, "dast": 0, "total": 0}

    def _empty_scan_time_row(period_value: str) -> dict[str, Any]:
        row: dict[str, Any] = {"period": period_value}
        for bucket_key in scan_time_bucket_keys:
            row[bucket_key] = _empty_scan_time_bucket_counts()
        return row

    def _normalize_scan_time_rows(rows: Any, period_name: str) -> list[dict[str, Any]]:
        fallback_period = scan_time_default_period_values[period_name]
        source_rows = rows if isinstance(rows, list) and rows else [{"period": fallback_period}]
        normalized: list[dict[str, Any]] = []
        for raw_row in source_rows:
            period_value = str(raw_row.get("period", "") if isinstance(raw_row, dict) else "").strip() or fallback_period
            row = _empty_scan_time_row(period_value)
            if isinstance(raw_row, dict):
                for bucket_key in scan_time_bucket_keys:
                    raw_bucket = raw_row.get(bucket_key)
                    if not isinstance(raw_bucket, dict):
                        continue
                    row[bucket_key] = {
                        "sast": _to_int(raw_bucket.get("sast"), 0),
                        "sca": _to_int(raw_bucket.get("sca"), 0),
                        "dast": _to_int(raw_bucket.get("dast"), 0),
                        "total": _to_int(raw_bucket.get("total"), 0),
                    }
            normalized.append(row)
        return sorted(normalized, key=lambda item: str(item.get("period", "")))

    scan_time_trend = workbench.get("scan_time_trend")
    normalized_scan_time = {
        "default_period": "month",
        "default_bucket": "lt5",
        "period_options": ["week", "month", "year"],
        "bucket_options": scan_time_bucket_options,
        "by_period": {
            "week": [_empty_scan_time_row(scan_time_default_period_values["week"])],
            "month": [_empty_scan_time_row(scan_time_default_period_values["month"])],
            "year": [_empty_scan_time_row(scan_time_default_period_values["year"])],
        },
    }

    if isinstance(scan_time_trend, dict) and isinstance(scan_time_trend.get("by_period"), dict):
        period_options = scan_time_trend.get("period_options")
        if isinstance(period_options, list):
            normalized_scan_time["period_options"] = [
                str(item).lower()
                for item in period_options
                if str(item).lower() in {"week", "month", "year"}
            ] or ["week", "month", "year"]

        default_period = str(scan_time_trend.get("default_period", "month") or "month").lower()
        if default_period not in {"week", "month", "year"}:
            default_period = "month"
        normalized_scan_time["default_period"] = default_period

        default_bucket = str(scan_time_trend.get("default_bucket", "lt5") or "lt5")
        if default_bucket not in set(scan_time_bucket_keys):
            default_bucket = "lt5"
        normalized_scan_time["default_bucket"] = default_bucket

        by_period = scan_time_trend.get("by_period") or {}
        for period_name in ("week", "month", "year"):
            normalized_scan_time["by_period"][period_name] = _normalize_scan_time_rows(by_period.get(period_name), period_name)
    else:
        # Legacy shape migration from older monthly scan-time payloads.
        legacy_sast_sca = scan_time_trend.get("sast_sca") if isinstance(scan_time_trend, dict) else []
        legacy_dast = scan_time_trend.get("dast") if isinstance(scan_time_trend, dict) else []

        legacy_periods = sorted(
            {
                str(row.get("period", "")).strip()
                for row in (legacy_sast_sca or []) + (legacy_dast or [])
                if isinstance(row, dict) and str(row.get("period", "")).strip()
            }
        )
        if not legacy_periods:
            legacy_periods = [scan_time_default_period_values["month"]]

        month_rows: list[dict[str, Any]] = []
        for period_value in legacy_periods:
            row = _empty_scan_time_row(period_value)

            sast_sca_row = next(
                (
                    item
                    for item in (legacy_sast_sca or [])
                    if isinstance(item, dict) and str(item.get("period", "")).strip() == period_value
                ),
                {},
            )
            dast_row = next(
                (
                    item
                    for item in (legacy_dast or [])
                    if isinstance(item, dict) and str(item.get("period", "")).strip() == period_value
                ),
                {},
            )

            # Legacy SAST/SCA was combined; split evenly as compatibility fallback.
            for key in ("lt5", "m5_10", "m10_30", "m30_60", "m60_120"):
                combined = _to_int(sast_sca_row.get(key), 0)
                sast_count = combined // 2
                sca_count = combined - sast_count
                row[key]["sast"] = sast_count
                row[key]["sca"] = sca_count

            # Legacy tail bucket maps to >=300m as conservative fallback.
            combined_tail = _to_int(sast_sca_row.get("gte120"), 0)
            sast_tail = combined_tail // 2
            sca_tail = combined_tail - sast_tail
            row["gte300"]["sast"] = sast_tail
            row["gte300"]["sca"] = sca_tail

            row["m10_30"]["dast"] = _to_int(dast_row.get("lt30"), 0)
            row["m30_60"]["dast"] = _to_int(dast_row.get("m30_60"), 0)
            row["m60_120"]["dast"] = _to_int(dast_row.get("m60_120"), 0)
            row["m120_240"]["dast"] = _to_int(dast_row.get("m120_240"), 0)
            row["gte300"]["dast"] += _to_int(dast_row.get("gte240"), 0)

            for bucket_key in scan_time_bucket_keys:
                bucket = row[bucket_key]
                bucket["total"] = _to_int(bucket.get("sast"), 0) + _to_int(bucket.get("sca"), 0) + _to_int(bucket.get("dast"), 0)

            month_rows.append(row)

        normalized_scan_time["by_period"]["month"] = month_rows
        normalized_scan_time["by_period"]["week"] = [_empty_scan_time_row(scan_time_default_period_values["week"])]
        normalized_scan_time["by_period"]["year"] = [_empty_scan_time_row(scan_time_default_period_values["year"])]

    workbench["scan_time_trend"] = normalized_scan_time

    size_bucket_options = [
        {"key": "lt1", "label": "<1MB", "color": "#b91c1c"},
        {"key": "m1_5", "label": "1-5MB", "color": "#dc2626"},
        {"key": "m5_10", "label": "5-10MB", "color": "#ea580c"},
        {"key": "m10_20", "label": "10-20MB", "color": "#d97706"},
        {"key": "m20_100", "label": "20-100MB", "color": "#ca8a04"},
        {"key": "m100_500", "label": "100-500MB", "color": "#65a30d"},
        {"key": "m500_1g", "label": "500MB-1GB", "color": "#0f766e"},
        {"key": "gt1g", "label": ">1GB", "color": "#1d4ed8"},
    ]
    size_bucket_keys = [item["key"] for item in size_bucket_options]
    size_bucket_aliases = {
        "lt1": "lt1",
        "m1_5": "m1_5",
        "m5_10": "m5_10",
        "m10_20": "m10_20",
        "m20_100": "m20_100",
        "m100_500": "m100_500",
        "m500_1g": "m500_1g",
        "gt1g": "gt1g",
        "m10_50": "m20_100",
        "m50_100": "m20_100",
        "m100_300": "m100_500",
        "m300_500": "m100_500",
        "m500_1000": "m500_1g",
        "gte1000": "gt1g",
    }
    size_default_period_values = {
        "week": now_key.strftime("%G-W%V"),
        "month": now_key.strftime("%Y-%m"),
        "year": now_key.strftime("%Y"),
    }

    def _resolve_size_bucket_key(raw_key: str, raw_bucket: str) -> str | None:
        key = str(raw_key or "").strip().lower()
        bucket = str(raw_bucket or "").strip().lower()
        if key in size_bucket_aliases:
            return size_bucket_aliases[key]
        if "<1" in bucket:
            return "lt1"
        if "1-5" in bucket:
            return "m1_5"
        if "5-10" in bucket:
            return "m5_10"
        if "10-20" in bucket:
            return "m10_20"
        if "20-100" in bucket:
            return "m20_100"
        if "100-500" in bucket:
            return "m100_500"
        if "500" in bucket and ("1gb" in bucket or "1000" in bucket):
            return "m500_1g"
        if ">1gb" in bucket or ">=1000" in bucket:
            return "gt1g"
        return None

    def _empty_size_bucket_counts() -> dict[str, int]:
        return {"sast": 0, "sca": 0, "total": 0}

    def _empty_size_row(period_value: str) -> dict[str, Any]:
        row: dict[str, Any] = {"period": period_value}
        for bucket_key in size_bucket_keys:
            row[bucket_key] = _empty_size_bucket_counts()
        return row

    def _normalize_size_rows(rows: Any, period_name: str) -> list[dict[str, Any]]:
        fallback_period = size_default_period_values[period_name]
        source_rows = rows if isinstance(rows, list) and rows else [{"period": fallback_period}]
        normalized: list[dict[str, Any]] = []
        for raw_row in source_rows:
            period_value = str(raw_row.get("period", "") if isinstance(raw_row, dict) else "").strip() or fallback_period
            row = _empty_size_row(period_value)
            if isinstance(raw_row, dict):
                for bucket_key in size_bucket_keys:
                    raw_bucket = raw_row.get(bucket_key)
                    if not isinstance(raw_bucket, dict):
                        continue
                    sast = _to_int(raw_bucket.get("sast"), 0)
                    sca = _to_int(raw_bucket.get("sca"), 0)
                    total = _to_int(raw_bucket.get("total"), sast + sca)
                    row[bucket_key] = {
                        "sast": sast,
                        "sca": sca,
                        "total": total,
                    }
            normalized.append(row)
        return sorted(normalized, key=lambda item: str(item.get("period", "")))

    size_profile = workbench.get("application_file_size_profile")
    default_size_bins = [
        {"bucket": item["label"], "key": item["key"], "sast": 0, "sca": 0}
        for item in size_bucket_options
    ]
    normalized_size_profile = {
        "bins": list(default_size_bins),
        "top10": [],
        "default_period": "month",
        "default_bucket": "lt1",
        "period_options": ["week", "month", "year"],
        "bucket_options": size_bucket_options,
        "by_period": {
            "week": [_empty_size_row(size_default_period_values["week"])],
            "month": [_empty_size_row(size_default_period_values["month"])],
            "year": [_empty_size_row(size_default_period_values["year"])],
        },
    }

    if not isinstance(size_profile, dict):
        legacy_top = size_profile if isinstance(size_profile, list) else []
        normalized_size_profile["top10"] = list(legacy_top)
        workbench["application_file_size_profile"] = normalized_size_profile
    else:
        bins = size_profile.get("bins")
        if isinstance(bins, list):
            normalized_size_profile["bins"] = [
                {
                    "bucket": str(row.get("bucket") or row.get("key") or "Unknown"),
                    "key": str(row.get("key") or ""),
                    "sast": _to_int(row.get("sast"), 0),
                    "sca": _to_int(row.get("sca"), 0),
                }
                for row in bins
                if isinstance(row, dict)
            ] or list(default_size_bins)

        top10 = size_profile.get("top10")
        if isinstance(top10, list):
            normalized_size_profile["top10"] = top10

        period_options = size_profile.get("period_options")
        if isinstance(period_options, list):
            normalized_size_profile["period_options"] = [
                str(item).lower()
                for item in period_options
                if str(item).lower() in {"week", "month", "year"}
            ] or ["week", "month", "year"]

        default_period = str(size_profile.get("default_period", "month") or "month").lower()
        if default_period in {"week", "month", "year"}:
            normalized_size_profile["default_period"] = default_period

        default_bucket = str(size_profile.get("default_bucket", "lt1") or "lt1")
        if default_bucket in set(size_bucket_keys):
            normalized_size_profile["default_bucket"] = default_bucket

        bucket_options = size_profile.get("bucket_options")
        if isinstance(bucket_options, list):
            normalized_bucket_options = []
            for item in bucket_options:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if key not in set(size_bucket_keys):
                    continue
                normalized_bucket_options.append(
                    {
                        "key": key,
                        "label": str(item.get("label") or key),
                        "color": str(item.get("color") or ""),
                    }
                )
            if normalized_bucket_options:
                normalized_size_profile["bucket_options"] = normalized_bucket_options

        by_period = size_profile.get("by_period")
        if isinstance(by_period, dict):
            for period_name in ("week", "month", "year"):
                normalized_size_profile["by_period"][period_name] = _normalize_size_rows(by_period.get(period_name), period_name)
        elif isinstance(normalized_size_profile.get("bins"), list):
            seeded_month_row = _empty_size_row(size_default_period_values["month"])
            for item in normalized_size_profile["bins"]:
                if not isinstance(item, dict):
                    continue
                bucket_key = _resolve_size_bucket_key(
                    str(item.get("key") or ""),
                    str(item.get("bucket") or ""),
                )
                if not bucket_key:
                    continue
                sast_count = _to_int(item.get("sast"), 0)
                sca_count = _to_int(item.get("sca"), 0)
                seeded_month_row[bucket_key]["sast"] += sast_count
                seeded_month_row[bucket_key]["sca"] += sca_count
                seeded_month_row[bucket_key]["total"] += sast_count + sca_count
            normalized_size_profile["by_period"]["month"] = [seeded_month_row]

        workbench["application_file_size_profile"] = normalized_size_profile

    coverage_bucket_options = [
        {"key": "lt10", "label": "<10", "color": "#b91c1c"},
        {"key": "m10_50", "label": "10-50", "color": "#dc2626"},
        {"key": "m50_100", "label": "50-100", "color": "#ea580c"},
        {"key": "m100_500", "label": "100-500", "color": "#d97706"},
        {"key": "m500_1000", "label": "500-1000", "color": "#65a30d"},
        {"key": "gte1000", "label": ">=1000", "color": "#0f766e"},
    ]
    coverage_bucket_keys = [item["key"] for item in coverage_bucket_options]
    coverage_bucket_aliases = {
        "lt10": "lt10",
        "m10_50": "m10_50",
        "m50_100": "m50_100",
        "m100_500": "m100_500",
        "m500_1000": "m500_1000",
        "gte1000": "gte1000",
        "m100_200": "m100_500",
        "m200_500": "m100_500",
    }
    coverage_default_period_values = {
        "week": now_key.strftime("%G-W%V"),
        "month": now_key.strftime("%Y-%m"),
        "year": now_key.strftime("%Y"),
    }

    def _resolve_coverage_bucket_key(raw_key: str, raw_bucket: str) -> str | None:
        key = str(raw_key or "").strip().lower()
        bucket = str(raw_bucket or "").strip().lower()
        if key in coverage_bucket_aliases:
            return coverage_bucket_aliases[key]
        if "<10" in bucket:
            return "lt10"
        if "10-50" in bucket:
            return "m10_50"
        if "50-100" in bucket:
            return "m50_100"
        if "100-500" in bucket:
            return "m100_500"
        if "500-1000" in bucket:
            return "m500_1000"
        if ">=1000" in bucket or ">1000" in bucket:
            return "gte1000"
        return None

    def _empty_coverage_bucket_counts() -> dict[str, int]:
        return {"scan_count": 0, "page_count": 0}

    def _empty_coverage_row(period_value: str) -> dict[str, Any]:
        row: dict[str, Any] = {"period": period_value}
        for bucket_key in coverage_bucket_keys:
            row[bucket_key] = _empty_coverage_bucket_counts()
        return row

    def _normalize_coverage_rows(rows: Any, period_name: str) -> list[dict[str, Any]]:
        fallback_period = coverage_default_period_values[period_name]
        source_rows = rows if isinstance(rows, list) and rows else [{"period": fallback_period}]
        normalized: list[dict[str, Any]] = []
        for raw_row in source_rows:
            period_value = str(raw_row.get("period", "") if isinstance(raw_row, dict) else "").strip() or fallback_period
            row = _empty_coverage_row(period_value)
            if isinstance(raw_row, dict):
                for bucket_key in coverage_bucket_keys:
                    raw_bucket = raw_row.get(bucket_key)
                    if isinstance(raw_bucket, dict):
                        row[bucket_key] = {
                            "scan_count": _to_int(raw_bucket.get("scan_count", raw_bucket.get("count")), 0),
                            "page_count": _to_int(raw_bucket.get("page_count", raw_bucket.get("pages")), 0),
                        }
                    elif raw_bucket is not None:
                        row[bucket_key] = {
                            "scan_count": _to_int(raw_bucket, 0),
                            "page_count": 0,
                        }
            normalized.append(row)
        return sorted(normalized, key=lambda item: str(item.get("period", "")))

    coverage_profile = workbench.get("top_dast_page_coverage")
    default_coverage_bins = [
        {"bucket": item["label"], "key": item["key"], "count": 0}
        for item in coverage_bucket_options
    ]
    normalized_coverage_profile = {
        "bins": list(default_coverage_bins),
        "top10": [],
        "default_period": "month",
        "default_bucket": "lt10",
        "period_options": ["week", "month", "year"],
        "bucket_options": coverage_bucket_options,
        "by_period": {
            "week": [_empty_coverage_row(coverage_default_period_values["week"])],
            "month": [_empty_coverage_row(coverage_default_period_values["month"])],
            "year": [_empty_coverage_row(coverage_default_period_values["year"])],
        },
    }

    if not isinstance(coverage_profile, dict):
        legacy_top = coverage_profile if isinstance(coverage_profile, list) else []
        normalized_coverage_profile["top10"] = list(legacy_top)
    else:
        bin_counts = {key: {"scan_count": 0, "page_count": 0} for key in coverage_bucket_keys}
        bins = coverage_profile.get("bins")
        if isinstance(bins, list):
            for item in bins:
                if not isinstance(item, dict):
                    continue
                resolved_key = _resolve_coverage_bucket_key(
                    str(item.get("key") or ""),
                    str(item.get("bucket") or ""),
                )
                if not resolved_key:
                    continue
                bin_counts[resolved_key]["scan_count"] += _to_int(item.get("scan_count", item.get("count")), 0)
                bin_counts[resolved_key]["page_count"] += _to_int(item.get("page_count", item.get("pages")), 0)
            normalized_coverage_profile["bins"] = [
                {
                    "bucket": next((opt["label"] for opt in coverage_bucket_options if opt["key"] == key), key),
                    "key": key,
                    "count": bin_counts[key]["scan_count"],
                    "scan_count": bin_counts[key]["scan_count"],
                    "page_count": bin_counts[key]["page_count"],
                }
                for key in coverage_bucket_keys
            ]

        top10 = coverage_profile.get("top10")
        if isinstance(top10, list):
            normalized_coverage_profile["top10"] = top10

        period_options = coverage_profile.get("period_options")
        if isinstance(period_options, list):
            normalized_coverage_profile["period_options"] = [
                str(item).lower()
                for item in period_options
                if str(item).lower() in {"week", "month", "year"}
            ] or ["week", "month", "year"]

        default_period = str(coverage_profile.get("default_period", "month") or "month").lower()
        if default_period in {"week", "month", "year"}:
            normalized_coverage_profile["default_period"] = default_period

        default_bucket = str(coverage_profile.get("default_bucket", "lt10") or "lt10")
        if default_bucket in set(coverage_bucket_keys):
            normalized_coverage_profile["default_bucket"] = default_bucket

        bucket_options = coverage_profile.get("bucket_options")
        if isinstance(bucket_options, list):
            normalized_bucket_options = []
            for item in bucket_options:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if key not in set(coverage_bucket_keys):
                    continue
                normalized_bucket_options.append(
                    {
                        "key": key,
                        "label": str(item.get("label") or key),
                        "color": str(item.get("color") or ""),
                    }
                )
            if normalized_bucket_options:
                normalized_coverage_profile["bucket_options"] = normalized_bucket_options

        by_period = coverage_profile.get("by_period")
        if isinstance(by_period, dict):
            for period_name in ("week", "month", "year"):
                normalized_coverage_profile["by_period"][period_name] = _normalize_coverage_rows(by_period.get(period_name), period_name)
        else:
            seeded_month_row = _empty_coverage_row(coverage_default_period_values["month"])
            for key in coverage_bucket_keys:
                seeded_month_row[key]["scan_count"] = bin_counts[key]["scan_count"]
                seeded_month_row[key]["page_count"] = bin_counts[key]["page_count"]
            normalized_coverage_profile["by_period"]["month"] = [seeded_month_row]

    workbench["top_dast_page_coverage"] = normalized_coverage_profile

    if not isinstance(workbench.get("most_frequently_rescanned"), list):
        workbench["most_frequently_rescanned"] = []

    bundle["workbench_trends"] = workbench

    options = bundle.get("issue_filter_options")
    if not isinstance(options, dict):
        options = {}
    options.setdefault("technologies", [])
    options.setdefault("vulnerabilities", [])
    options.setdefault("unclassified_count", 0)
    bundle["issue_filter_options"] = options
    return bundle


def _apply_scope_filters_to_catalog(
    applications: list[dict],
    asset_groups: list[dict],
    *,
    asset_group_ids: list[str],
    application_ids: list[str],
    application_name: str | None,
) -> tuple[list[dict], list[dict]]:
    apps = applications
    groups = asset_groups
    if asset_group_ids:
        allowed_groups = set(asset_group_ids)
        apps = [item for item in apps if str(item.get("asset_group_id", "")) in allowed_groups]
        groups = [item for item in groups if str(item.get("id", "")) in allowed_groups]
    if application_ids:
        allowed_apps = set(application_ids)
        apps = [item for item in apps if str(item.get("id", "")) in allowed_apps]
    if application_name:
        needle = application_name.lower()
        apps = [item for item in apps if needle in str(item.get("name", "")).lower()]
    return apps, groups


async def _cleanup_cache_if_needed() -> None:
    global _LAST_CACHE_CLEANUP_AT
    now = _utc_now()
    elapsed = (now - _LAST_CACHE_CLEANUP_AT).total_seconds()
    if elapsed < settings.analytics_cache_cleanup_interval_seconds:
        return
    # Keep expired snapshots for a grace window so UI can use stale-while-refresh
    # instead of blocking on expensive rebuilds during peak loads.
    retention_seconds = max(settings.analytics_cache_ttl_seconds * 50, 7 * 24 * 60 * 60)
    cutoff = now - timedelta(seconds=retention_seconds)
    sqlite_store.purge_expired_analytics_snapshots(_to_iso(cutoff))
    _LAST_CACHE_CLEANUP_AT = now


def _is_base_data_fresh() -> bool:
    expires_at = _BASE_DATA_CACHE.get("expires_at")
    if not isinstance(expires_at, datetime):
        return False
    return expires_at > _utc_now()


async def _get_base_data(*, refresh: bool) -> dict[str, Any]:
    if not refresh and _is_base_data_fresh() and isinstance(_BASE_DATA_CACHE.get("payload"), dict):
        cached_payload = dict(_BASE_DATA_CACHE["payload"])
        cached_scans = cached_payload.get("scans")
        if isinstance(cached_scans, list):
            _primary_svc = next(iter(get_endpoint_services()), service)
            cached_payload["scans"] = await _primary_svc.hydrate_dast_page_coverage(cached_scans, schedule_refresh=True)
        return cached_payload

    async with _BASE_DATA_LOCK:
        if refresh and isinstance(_BASE_DATA_CACHE.get("payload"), dict):
            forced_refreshed_at = _BASE_DATA_CACHE.get("forced_refreshed_at")
            if isinstance(forced_refreshed_at, datetime):
                elapsed = (_utc_now() - forced_refreshed_at).total_seconds()
                if elapsed <= _FORCED_REFRESH_COALESCE_SECONDS:
                    cached_payload = dict(_BASE_DATA_CACHE["payload"])
                    cached_scans = cached_payload.get("scans")
                    if isinstance(cached_scans, list):
                        _primary_svc = next(iter(get_endpoint_services()), service)
                        cached_payload["scans"] = await _primary_svc.hydrate_dast_page_coverage(cached_scans, schedule_refresh=True)
                    return cached_payload

        if not refresh and _is_base_data_fresh() and isinstance(_BASE_DATA_CACHE.get("payload"), dict):
            cached_payload = dict(_BASE_DATA_CACHE["payload"])
            cached_scans = cached_payload.get("scans")
            if isinstance(cached_scans, list):
                _primary_svc = next(iter(get_endpoint_services()), service)
                cached_payload["scans"] = await _primary_svc.hydrate_dast_page_coverage(cached_scans, schedule_refresh=True)
            return cached_payload

        payload = await aggregate_base_data()
        now = _utc_now()
        ttl = max(900, int(settings.analytics_cache_ttl_seconds) * 3)
        _BASE_DATA_CACHE["payload"] = payload
        _BASE_DATA_CACHE["expires_at"] = now + timedelta(seconds=ttl)
        if refresh:
            _BASE_DATA_CACHE["forced_refreshed_at"] = now
        return dict(payload)


async def _warm_base_data_background() -> None:
    if _is_base_data_fresh():
        return
    try:
        await _get_base_data(refresh=False)
    except Exception:
        logger.exception("Background base-data warmup failed")


async def prewarm_base_data_cache(force: bool = True) -> bool:
    if not settings.analytics_prewarm_enabled:
        return False
    if not get_endpoint_services():
        return False
    await _get_base_data(refresh=force)
    return True


async def _build_bundle(
    user: UserContext,
    *,
    asset_group_ids: list[str],
    application_ids: list[str],
    issue_technologies: list[str],
    vulnerabilities: list[str],
    scan_types: list[str],
    scan_statuses: list[str],
    application_name: str | None,
    from_date: str | None,
    to_date: str | None,
    compliance_rule: str = "critical_high",
    compliance_threshold: str = "high",
    source_refresh: bool = False,
) -> dict:
    has_scope_filter = bool(asset_group_ids or application_ids or (application_name or "").strip())

    source_data: dict[str, Any] | None = None
    if source_refresh or _is_base_data_fresh() or not has_scope_filter:
        source_data = await _get_base_data(refresh=source_refresh)

    tenant_info: dict[str, Any] = {}
    if source_data is None:
        # Fast path for scoped requests: avoid full organisation issue pull when source
        # cache is cold — fetch scoped data from all endpoints concurrently.
        _raw_apps, _raw_groups, _raw_scans, tenant_info = await asyncio.gather(
            aggregate_list("list_applications", use_mock_on_error=False),
            aggregate_list("list_asset_groups", use_mock_on_error=False),
            aggregate_list("list_scans", use_mock_on_error=False),
            aggregate_tenant_info(),
        )
        all_apps = filter_by_asset_group(
            _raw_apps,
            user.asset_group_ids,
            user.role,
            ["asset_group_id"],
        )
        raw_asset_groups = _raw_groups
        if user.role in {"PlatformAdmin", "SecurityManager"}:
            all_asset_groups = raw_asset_groups
        else:
            allowed = set(user.asset_group_ids)
            all_asset_groups = [item for item in raw_asset_groups if str(item.get("id", "")) in allowed]
        apps, groups = _apply_scope_filters_to_catalog(
            all_apps,
            all_asset_groups,
            asset_group_ids=asset_group_ids,
            application_ids=application_ids,
            application_name=application_name,
        )
        scoped_application_ids = sorted(
            {
                *application_ids,
                *[
                    str(item.get("id", ""))
                    for item in apps
                    if str(item.get("id", ""))
                ],
            }
        )

        all_scans = filter_by_asset_group(
            _raw_scans,
            user.asset_group_ids,
            user.role,
            ["asset_group_id"],
        )
        all_issues = filter_by_asset_group(
            await aggregate_list("list_issues_for_applications", scoped_application_ids, use_mock_on_error=False),
            user.asset_group_ids,
            user.role,
            ["asset_group_id"],
        )
    else:
        all_scans = filter_by_asset_group(
            list(source_data.get("scans") or []), user.asset_group_ids, user.role, ["asset_group_id"]
        )
        all_issues = filter_by_asset_group(
            list(source_data.get("issues") or []), user.asset_group_ids, user.role, ["asset_group_id"]
        )
        all_apps = filter_by_asset_group(
            list(source_data.get("applications") or []), user.asset_group_ids, user.role, ["asset_group_id"]
        )

        raw_asset_groups = list(source_data.get("asset_groups") or [])
        if user.role in {"PlatformAdmin", "SecurityManager"}:
            all_asset_groups = raw_asset_groups
        else:
            allowed = set(user.asset_group_ids)
            all_asset_groups = [item for item in raw_asset_groups if str(item.get("id", "")) in allowed]
        tenant_info = dict(source_data.get("tenant_info") or {})

    apps, groups = _apply_scope_filters_to_catalog(
        all_apps,
        all_asset_groups,
        asset_group_ids=asset_group_ids,
        application_ids=application_ids,
        application_name=application_name,
    )
    if has_scope_filter:
        scoped_application_ids = sorted(
            {
                *application_ids,
                *[
                    str(item.get("id", ""))
                    for item in apps
                    if str(item.get("id", ""))
                ],
            }
        )
    else:
        scoped_application_ids = list(application_ids)

    issues_source = all_issues
    if has_scope_filter:
        if scoped_application_ids:
            # `all_issues` is already scoped in the cold-cache path and organization-scoped
            # in the warm-cache path. Filter in-memory to avoid duplicate remote fetches
            # per filter apply, which can significantly delay scoped responses.
            scoped_issue_app_ids = set(scoped_application_ids)
            issues_source = [
                item
                for item in all_issues
                if str(item.get("application_id", "")) in scoped_issue_app_ids
            ]
        else:
            issues_source = []

    option_scans, option_issues = service.apply_filters(
        all_scans,
        issues_source,
        asset_group_ids=asset_group_ids,
        application_ids=scoped_application_ids,
        application_name=application_name,
        scan_types=scan_types,
        scan_statuses=scan_statuses,
        from_date=from_date,
        to_date=to_date,
    )

    scans = option_scans
    issues = service.filter_issues_by_dimensions(
        option_scans,
        option_issues,
        issue_technologies=issue_technologies,
        vulnerabilities=vulnerabilities,
    )

    active_issues = [
        item
        for item in issues
        if str(item.get("status", "")).strip().lower() not in {"closed", "fixed", "resolved"}
    ]

    has_dataset_scope_filter = bool(
        issue_technologies
        or vulnerabilities
        or scan_types
        or scan_statuses
        or from_date
        or to_date
    )

    summary_applications = apps
    summary_asset_groups = groups
    if has_dataset_scope_filter:
        effective_app_ids: set[str] = {
            str(item.get("application_id", ""))
            for item in scans
            if str(item.get("application_id", ""))
        }
        effective_app_ids.update(
            {
                str(item.get("application_id", ""))
                for item in issues
                if str(item.get("application_id", ""))
            }
        )

        summary_applications = [
            item
            for item in apps
            if str(item.get("id", "")) in effective_app_ids
        ]

        effective_group_ids: set[str] = {
            str(item.get("asset_group_id", ""))
            for item in summary_applications
            if str(item.get("asset_group_id", ""))
        }
        effective_group_ids.update(
            {
                str(item.get("asset_group_id", ""))
                for item in scans
                if str(item.get("asset_group_id", ""))
            }
        )
        effective_group_ids.update(
            {
                str(item.get("asset_group_id", ""))
                for item in issues
                if str(item.get("asset_group_id", ""))
            }
        )

        summary_asset_groups = [
            item
            for item in groups
            if str(item.get("id", "")) in effective_group_ids
        ]

    # Compute app-based statistics from the filtered application list.
    # When no scope filter is active, use the pre-computed stats from base data
    # (most efficient — already computed during aggregate_base_data()).
    # When a scope filter is active, recompute from the filtered apps list.
    app_based_statistics: dict[str, Any] = {}
    if not has_scope_filter and source_data is not None:
        app_based_statistics = dict(source_data.get("app_based_statistics") or {})
    if not app_based_statistics:
        # Recompute from the filtered apps list (handles scoped requests)
        app_based_statistics = service.calculate_statistics_from_apps(
            summary_applications, scans
        )

    # Fetch accurate counts in parallel using /Count endpoints when enabled.
    # These are used as a fallback when app-based stats are unavailable.
    # The Count API does not support dimension filters (issue_technologies, scan_types,
    # scan_statuses, date range).  When those filters are active the Count API would
    # return org-wide counts that would silently override our correctly-filtered
    # in-memory statistics — skip the call in those cases.
    count_overrides: dict[str, int] = {}
    if settings.asoc_use_count_endpoints and not has_dataset_scope_filter:
        try:
            count_overrides = await asyncio.wait_for(
                aggregate_issue_counts(),
                timeout=settings.asoc_count_timeout_seconds,
            )
        except Exception as _count_exc:
            logger.warning(
                "_build_bundle: issue count fetch failed; falling back to app-based or pagination-derived counts: %s",
                _count_exc,
            )

    summary = service.build_portfolio_summary(
        scans=scans,
        issues=issues,
        applications=summary_applications,
        asset_groups=summary_asset_groups,
        count_overrides=count_overrides or None,
        app_based_statistics=app_based_statistics or None,
    )
    summary["filters"] = {
        "asset_group_ids": asset_group_ids,
        "application_ids": scoped_application_ids,
        "application_name": application_name,
        "from_date": from_date,
        "to_date": to_date,
    }

    # Build statistics using priority: app-based > count_overrides > pagination
    # App-based aggregation is the most reliable — directly from /api/v4/Apps,
    # no pagination issues, no extra API calls needed.
    if app_based_statistics.get("count_source") == "app_aggregation":
        # Use app-based stats as primary source; supplement with scan-derived open_scans
        open_scans = sum(
            1
            for scan in scans
            if str(scan.get("status", "")).lower() in {"running", "pending", "queued", "scheduled"}
        )
        # Derive technology breakdown and resolved count from the loaded issues list.
        # App-aggregation totals/severity are trusted; technology and resolved counts
        # are more accurately computed from the full per-app issue list.
        # _resolve_issue_technology falls back to scan-based app technology maps
        # when individual issues lack an explicit issue_technology value.
        _app_tech_map, _app_primary_tech = _build_app_technology_maps(scans)
        _resolved_statuses = {"closed", "fixed", "resolved"}
        _tech_counts: dict[str, int] = {"SAST": 0, "DAST": 0, "SCA": 0, "IAST": 0}
        _resolved_count = 0
        # Chart data accumulators (status distribution + severity×tech heatmap)
        _SEVERITIES_ORDERED = ("Critical", "High", "Medium", "Low")
        _sev_norm: dict[str, str] = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
        _status_counts: dict[str, int] = {"Open": 0, "Fixed": 0, "InProgress": 0, "Noise": 0}
        _heatmap: dict[str, dict[str, int]] = {
            sev: {"sast": 0, "dast": 0, "sca": 0, "iast": 0} for sev in _SEVERITIES_ORDERED
        }
        for _issue in issues:
            _tech = _resolve_issue_technology(_issue, _app_tech_map, _app_primary_tech)
            if _tech in _tech_counts:
                _tech_counts[_tech] += 1
            _st_lower = str(_issue.get("status", "") or "").strip().lower()
            if _st_lower in _resolved_statuses:
                _resolved_count += 1
            # Status distribution
            if _st_lower == "open":
                _status_counts["Open"] += 1
            elif _st_lower in ("fixed", "resolved", "closed"):
                _status_counts["Fixed"] += 1
            elif _st_lower in ("inprogress", "in_progress"):
                _status_counts["InProgress"] += 1
            elif _st_lower == "noise":
                _status_counts["Noise"] += 1
            # Risk heatmap (severity × technology)
            _sev_key = _sev_norm.get(str(_issue.get("severity", "") or "").strip().lower())
            _tech_lower = _tech.lower()
            if _sev_key and _tech_lower in ("sast", "dast", "sca", "iast"):
                _heatmap[_sev_key][_tech_lower] += 1
        # Prefer the Count-API resolved count (explicit Fixed-status query) when
        # it's available and larger than the per-issue-list count.  The per-issue list
        # only covers apps the credential can access; count_overrides covers the full
        # org-level Fixed count when the Count endpoint is reachable.
        _resolved_count = max(_resolved_count, count_overrides.get("resolved", 0))
        # When dimension filters (issue_technologies, scan_types, etc.) are active,
        # app_based_statistics reflect the full org (unfiltered by these dimensions).
        # Use per-issue-list counts in that case so filter selections are reflected.
        if has_dataset_scope_filter:
            _total_issues = len(issues)
            _critical_count = sum(
                1 for _i in issues
                if str(_i.get("severity", "") or "").strip().lower() == "critical"
            )
            _high_count = sum(
                1 for _i in issues
                if str(_i.get("severity", "") or "").strip().lower() == "high"
            )
            _medium_count = sum(
                1 for _i in issues
                if str(_i.get("severity", "") or "").strip().lower() == "medium"
            )
            _low_count = max(_total_issues - _critical_count - _high_count - _medium_count, 0)
        else:
            _total_issues = int(app_based_statistics.get("total_issues", 0))
            _critical_count = int(app_based_statistics.get("critical_issues", 0))
            _high_count = int(app_based_statistics.get("high_issues", 0))
            _medium_count = int(app_based_statistics.get("medium_issues", 0))
            _low_count = int(app_based_statistics.get("low_issues", 0))
        statistics = {
            "total_issues": _total_issues,
            "active_issues": max(_total_issues - _resolved_count, 0),
            "resolved_issues": _resolved_count,
            "critical_issues": _critical_count,
            "high_issues": _high_count,
            "medium_issues": _medium_count,
            "low_issues": _low_count,
            "total_scans": int(app_based_statistics.get("total_scans", len(scans))),
            "scan_count": int(app_based_statistics.get("total_scans", len(scans))),
            "running_scans": int(app_based_statistics.get("running_scans", open_scans)),
            "failed_scans": int(app_based_statistics.get("failed_scans", 0)),
            "open_scans": open_scans,
            "sast_issues": _tech_counts["SAST"],
            "dast_issues": _tech_counts["DAST"],
            "sca_issues": _tech_counts["SCA"],
            "iast_issues": _tech_counts["IAST"],
            "count_source": "app_aggregation",
        }
        logger.debug(
            "_build_bundle: using app-based statistics (total_issues=%d, critical=%d, high=%d)",
            statistics["total_issues"],
            statistics["critical_issues"],
            statistics["high_issues"],
        )
    else:
        statistics = service.calculate_statistics(
            scans=scans,
            issues=issues,
            count_overrides=count_overrides or None,
        )
        # Compute chart data accumulators for non-app-aggregation path
        _app_tech_map, _app_primary_tech = _build_app_technology_maps(scans)
        _SEVERITIES_ORDERED = ("Critical", "High", "Medium", "Low")
        _sev_norm: dict[str, str] = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
        _status_counts: dict[str, int] = {"Open": 0, "Fixed": 0, "InProgress": 0, "Noise": 0}
        _heatmap: dict[str, dict[str, int]] = {
            sev: {"sast": 0, "dast": 0, "sca": 0, "iast": 0} for sev in _SEVERITIES_ORDERED
        }
        for _issue in issues:
            _tech = _resolve_issue_technology(_issue, _app_tech_map, _app_primary_tech)
            _st_lower = str(_issue.get("status", "") or "").strip().lower()
            if _st_lower == "open":
                _status_counts["Open"] += 1
            elif _st_lower in ("fixed", "resolved", "closed"):
                _status_counts["Fixed"] += 1
            elif _st_lower in ("inprogress", "in_progress"):
                _status_counts["InProgress"] += 1
            elif _st_lower == "noise":
                _status_counts["Noise"] += 1
            _sev_key = _sev_norm.get(str(_issue.get("severity", "") or "").strip().lower())
            _tech_lower = _tech.lower()
            if _sev_key and _tech_lower in ("sast", "dast", "sca", "iast"):
                _heatmap[_sev_key][_tech_lower] += 1

    # Build chart_data from in-memory issues + apps (no Count API calls needed)
    _CHART_TOP_N = 20
    _top_apps_sorted = sorted(
        apps,
        key=lambda a: int(a.get("total_issues", 0) or 0),
        reverse=True,
    )
    _top_apps_list = [
        {
            "app_id": str(a.get("id", "")),
            "app_name": str(a.get("name", "") or a.get("id", "")),
            "total": int(a.get("total_issues", 0) or 0),
            "critical": int(a.get("critical_issues", 0) or 0),
            "high": int(a.get("high_issues", 0) or 0),
        }
        for a in _top_apps_sorted[:_CHART_TOP_N]
        if int(a.get("total_issues", 0) or 0) > 0
    ]
    _chart_data = {
        "status_distribution": {
            "statuses": [{"status": s, "count": _status_counts[s]} for s in ("Open", "Fixed", "InProgress", "Noise")],
        },
        "risk_heatmap": {
            "matrix": [{"severity": sev, **_heatmap[sev]} for sev in _SEVERITIES_ORDERED],
            "totals": {
                tech: sum(_heatmap[sev][tech] for sev in _SEVERITIES_ORDERED)
                for tech in ("sast", "dast", "sca", "iast")
            },
        },
        "top_apps": {"apps": _top_apps_list},
    }

    return {
        "statistics": statistics,
        "trend_active": service.calculate_trend(active_issues),
        "trend_all": service.calculate_trend(issues),
        "kpi": service.calculate_kpi(issues),
        "mttr": service.calculate_mttr(issues),
        "prioritization": service.calculate_prioritization(issues),
        "findings_series": {
            "week": service.calculate_findings_series(issues, "week"),
            "month": service.calculate_findings_series(issues, "month"),
            "year": service.calculate_findings_series(issues, "year"),
        },
        "scan_series": {
            "day": service.calculate_scan_series(
                scans,
                issues,
                "day",
                severity_source=_normalize_scan_severity_source(settings.analytics_scan_severity_source),
            ),
            "week": service.calculate_scan_series(
                scans,
                issues,
                "week",
                severity_source=_normalize_scan_severity_source(settings.analytics_scan_severity_source),
            ),
            "month": service.calculate_scan_series(
                scans,
                issues,
                "month",
                severity_source=_normalize_scan_severity_source(settings.analytics_scan_severity_source),
            ),
        },
        "scan_series_by_source": {
            "derived": {
                "day": service.calculate_scan_series(scans, issues, "day", severity_source="derived"),
                "week": service.calculate_scan_series(scans, issues, "week", severity_source="derived"),
                "month": service.calculate_scan_series(scans, issues, "month", severity_source="derived"),
            },
            "native": {
                "day": service.calculate_scan_series(scans, issues, "day", severity_source="native"),
                "week": service.calculate_scan_series(scans, issues, "week", severity_source="native"),
                "month": service.calculate_scan_series(scans, issues, "month", severity_source="native"),
            },
            "hybrid": {
                "day": service.calculate_scan_series(scans, issues, "day", severity_source="hybrid"),
                "week": service.calculate_scan_series(scans, issues, "week", severity_source="hybrid"),
                "month": service.calculate_scan_series(scans, issues, "month", severity_source="hybrid"),
            },
        },
        "portfolio_summary": summary,
        "issue_filter_options": service.build_issue_filter_options(option_scans, option_issues),
        "workbench_trends": service.calculate_workbench_trends(
            scans,
            issues,
            apps,
            compliance_rule=compliance_rule,
            compliance_threshold=compliance_threshold,
            tenant_info=tenant_info,
        ),
        "chart_data": _chart_data,
        "generated_at": _to_iso(_utc_now()),
    }


async def _refresh_snapshot_background(
    cache_key: str,
    user: UserContext,
    *,
    asset_group_ids: list[str],
    application_ids: list[str],
    issue_technologies: list[str],
    vulnerabilities: list[str],
    scan_types: list[str],
    scan_statuses: list[str],
    application_name: str | None,
    from_date: str | None,
    to_date: str | None,
    compliance_rule: str,
    compliance_threshold: str,
) -> None:
    lock = _get_lock(cache_key)
    async with lock:
        cached = sqlite_store.get_analytics_snapshot(cache_key)
        if _is_snapshot_fresh(cached):
            return

        try:
            bundle = await _build_bundle(
                user,
                asset_group_ids=asset_group_ids,
                application_ids=application_ids,
                issue_technologies=issue_technologies,
                vulnerabilities=vulnerabilities,
                scan_types=scan_types,
                scan_statuses=scan_statuses,
                application_name=application_name,
                from_date=from_date,
                to_date=to_date,
                compliance_rule=compliance_rule,
                compliance_threshold=compliance_threshold,
                source_refresh=False,
            )
            fetched_at = _utc_now()
            _bundle_total_issues = int(
                (bundle.get("portfolio_summary") or {}).get("total_issues") or 0
            )
            _effective_ttl = (
                30 if _bundle_total_issues == 0 else max(15, settings.analytics_cache_ttl_seconds)
            )
            expires_at = fetched_at + timedelta(seconds=_effective_ttl)
            sqlite_store.upsert_analytics_snapshot(
                cache_key=cache_key,
                payload=bundle,
                fetched_at=_to_iso(fetched_at),
                expires_at=_to_iso(expires_at),
            )
        except Exception:
            logger.exception("Background analytics snapshot refresh failed for key %s", cache_key)


async def _get_bundle(
    user: UserContext,
    *,
    asset_group_ids: list[str],
    application_ids: list[str],
    issue_technologies: list[str],
    vulnerabilities: list[str],
    scan_types: list[str],
    scan_statuses: list[str],
    application_name: str | None,
    from_date: str | None,
    to_date: str | None,
    compliance_rule: str = "critical_high",
    compliance_threshold: str = "high",
    refresh: bool = False,
) -> tuple[dict, dict]:
    await _cleanup_cache_if_needed()
    cache_key = _build_cache_key(
        user,
        asset_group_ids=asset_group_ids,
        application_ids=application_ids,
        issue_technologies=issue_technologies,
        vulnerabilities=vulnerabilities,
        scan_types=scan_types,
        scan_statuses=scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        compliance_rule=compliance_rule,
        compliance_threshold=compliance_threshold,
    )
    if not refresh:
        cached = sqlite_store.get_analytics_snapshot(cache_key)
        if _is_snapshot_fresh(cached):
            payload = _hydrate_bundle_defaults(cached.get("payload"))
            if not _bundle_has_required_sections(cached.get("payload")):
                lock = _get_lock(cache_key)
                if not lock.locked():
                    asyncio.create_task(
                        _refresh_snapshot_background(
                            cache_key,
                            user,
                            asset_group_ids=asset_group_ids,
                            application_ids=application_ids,
                            issue_technologies=issue_technologies,
                            vulnerabilities=vulnerabilities,
                            scan_types=scan_types,
                            scan_statuses=scan_statuses,
                            application_name=application_name,
                            from_date=from_date,
                            to_date=to_date,
                            compliance_rule=compliance_rule,
                            compliance_threshold=compliance_threshold,
                        )
                    )
            freshness = _build_freshness(
                source="cache",
                generated_at=str(payload.get("generated_at") or "") or None,
                fetched_at=str(cached.get("fetched_at") or "") or None,
                expires_at=str(cached.get("expires_at") or "") or None,
            )
            if not _is_base_data_fresh():
                asyncio.create_task(_warm_base_data_background())
            return payload, freshness

        if cached:
            payload = _hydrate_bundle_defaults(cached.get("payload"))
            lock = _get_lock(cache_key)
            if not lock.locked():
                asyncio.create_task(
                    _refresh_snapshot_background(
                        cache_key,
                        user,
                        asset_group_ids=asset_group_ids,
                        application_ids=application_ids,
                        issue_technologies=issue_technologies,
                        vulnerabilities=vulnerabilities,
                        scan_types=scan_types,
                        scan_statuses=scan_statuses,
                        application_name=application_name,
                        from_date=from_date,
                        to_date=to_date,
                        compliance_rule=compliance_rule,
                        compliance_threshold=compliance_threshold,
                    )
                )
            freshness = _build_freshness(
                source="cache",
                generated_at=str(payload.get("generated_at") or "") or None,
                fetched_at=str(cached.get("fetched_at") or "") or None,
                expires_at=str(cached.get("expires_at") or "") or None,
            )
            if not _is_base_data_fresh():
                asyncio.create_task(_warm_base_data_background())
            return payload, freshness

        # Fast default-view fallback: serve latest known snapshot immediately
        # while rebuilding the current cache key in background.
        has_active_scope = bool(
            asset_group_ids
            or application_ids
            or issue_technologies
            or vulnerabilities
            or scan_types
            or scan_statuses
            or (application_name or "").strip()
            or from_date
            or to_date
        )
        if not has_active_scope:
            latest = sqlite_store.get_latest_analytics_snapshot()
            if latest and latest.get("payload"):
                payload = _hydrate_bundle_defaults(latest.get("payload"))
                lock = _get_lock(cache_key)
                if not lock.locked():
                    asyncio.create_task(
                        _refresh_snapshot_background(
                            cache_key,
                            user,
                            asset_group_ids=asset_group_ids,
                            application_ids=application_ids,
                            issue_technologies=issue_technologies,
                            vulnerabilities=vulnerabilities,
                            scan_types=scan_types,
                            scan_statuses=scan_statuses,
                            application_name=application_name,
                            from_date=from_date,
                            to_date=to_date,
                            compliance_rule=compliance_rule,
                            compliance_threshold=compliance_threshold,
                        )
                    )
                freshness = _build_freshness(
                    source="cache-fallback",
                    generated_at=str(payload.get("generated_at") or "") or None,
                    fetched_at=str(latest.get("fetched_at") or "") or None,
                    expires_at=str(latest.get("expires_at") or "") or None,
                )
                if not _is_base_data_fresh():
                    asyncio.create_task(_warm_base_data_background())
                return payload, freshness

    lock = _get_lock(cache_key)
    async with lock:
        if not refresh:
            cached = sqlite_store.get_analytics_snapshot(cache_key)
            if _is_snapshot_fresh(cached):
                payload = _hydrate_bundle_defaults(cached.get("payload"))
                freshness = _build_freshness(
                    source="cache",
                    generated_at=str(payload.get("generated_at") or "") or None,
                    fetched_at=str(cached.get("fetched_at") or "") or None,
                    expires_at=str(cached.get("expires_at") or "") or None,
                )
                return payload, freshness

        try:
            bundle = await _build_bundle(
                user,
                asset_group_ids=asset_group_ids,
                application_ids=application_ids,
                issue_technologies=issue_technologies,
                vulnerabilities=vulnerabilities,
                scan_types=scan_types,
                scan_statuses=scan_statuses,
                application_name=application_name,
                from_date=from_date,
                to_date=to_date,
                compliance_rule=compliance_rule,
                compliance_threshold=compliance_threshold,
                source_refresh=refresh,
            )
        except Exception:
            logger.exception("Analytics live build failed for key %s; serving last known snapshot if available", cache_key)
            cached = sqlite_store.get_analytics_snapshot(cache_key)
            if cached:
                payload = _hydrate_bundle_defaults(cached.get("payload"))
                freshness = _build_freshness(
                    source="cache-stale",
                    generated_at=str(payload.get("generated_at") or "") or None,
                    fetched_at=str(cached.get("fetched_at") or "") or None,
                    expires_at=str(cached.get("expires_at") or "") or None,
                )
                return payload, freshness
            raise
        fetched_at = _utc_now()
        # Cold-start guard: if the bundle has no issues (data not yet loaded from ASoC),
        # use a very short TTL so the hollow snapshot expires quickly and a proper build
        # is triggered on the next request rather than caching empty data for the full TTL.
        _bundle_total_issues = int(
            (bundle.get("portfolio_summary") or {}).get("total_issues") or 0
        )
        _effective_ttl = (
            30 if _bundle_total_issues == 0 else max(15, settings.analytics_cache_ttl_seconds)
        )
        expires_at = fetched_at + timedelta(seconds=_effective_ttl)
        sqlite_store.upsert_analytics_snapshot(
            cache_key=cache_key,
            payload=bundle,
            fetched_at=_to_iso(fetched_at),
            expires_at=_to_iso(expires_at),
        )
        freshness = _build_freshness(
            source="live",
            generated_at=str(bundle.get("generated_at") or "") or None,
            fetched_at=_to_iso(fetched_at),
            expires_at=_to_iso(expires_at),
        )
        return bundle, freshness


@router.get("/statistics")
async def statistics(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    payload = _hydrate_statistics_from_summary(bundle)
    payload["_freshness"] = freshness
    return payload


@router.get("/trend")
async def trend_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    refresh: bool = Query(default=False),
) -> list[dict]:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, _ = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    return bundle["trend_active"] if active_only else bundle["trend_all"]


@router.get("/kpi")
async def kpi_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> list[dict]:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, _ = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    return bundle["kpi"]


@router.get("/mttr")
async def mttr_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> list[dict]:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, _ = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    return bundle["mttr"]


@router.get("/portfolio-summary")
async def portfolio_summary(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    payload = dict(bundle["portfolio_summary"])
    payload["_freshness"] = freshness
    return payload


@router.get("/prioritization")
async def prioritization_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    payload = dict(bundle.get("prioritization") or {})
    payload["_freshness"] = freshness
    return payload


@router.get("/findings-series")
async def findings_series_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    period: str = Query(default="month"),
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    normalized_period = period.lower().strip()
    if normalized_period not in {"week", "month", "year"}:
        normalized_period = "month"

    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )

    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    series_bundle = bundle.get("findings_series") or {}
    return {
        "period": normalized_period,
        "items": list(series_bundle.get(normalized_period, [])),
        "_freshness": freshness,
    }


@router.get("/scan-series")
async def scan_series_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    period: str = Query(default="month"),
    severity_source: str = Query(default=""),
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    normalized_period = period.lower().strip()
    if normalized_period not in {"day", "week", "month"}:
        normalized_period = "month"
    normalized_source = _normalize_scan_severity_source(
        severity_source or settings.analytics_scan_severity_source
    )

    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )

    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    series_by_source = bundle.get("scan_series_by_source") or {}
    selected_bundle = series_by_source.get(normalized_source)
    if not isinstance(selected_bundle, dict):
        selected_bundle = bundle.get("scan_series") or {}
    return {
        "period": normalized_period,
        "severity_source": normalized_source,
        "items": list(selected_bundle.get(normalized_period, [])),
        "_freshness": freshness,
    }


@router.get("/bundle")
async def analytics_bundle(
    user: Annotated[UserContext, Depends(get_current_user)],
    findings_period: str = Query(default="month"),
    scan_period: str = Query(default="month"),
    severity_source: str = Query(default=""),
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    compliance_rule: str | None = Query(default=None),
    compliance_threshold: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)

    normalized_findings_period = findings_period.lower().strip()
    if normalized_findings_period not in {"week", "month", "year"}:
        normalized_findings_period = "month"

    normalized_scan_period = scan_period.lower().strip()
    if normalized_scan_period not in {"day", "week", "month"}:
        normalized_scan_period = "month"

    normalized_source = _normalize_scan_severity_source(
        severity_source or settings.analytics_scan_severity_source
    )
    normalized_compliance_rule = _normalize_compliance_rule(compliance_rule)
    normalized_compliance_threshold = _normalize_compliance_threshold(compliance_threshold)

    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )

    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        compliance_rule=normalized_compliance_rule,
        compliance_threshold=normalized_compliance_threshold,
        refresh=refresh,
    )

    statistics_payload = _hydrate_statistics_from_summary(bundle)
    portfolio_payload = dict(bundle.get("portfolio_summary") or {})
    prioritization_payload = dict(bundle.get("prioritization") or {})
    findings_bundle = bundle.get("findings_series") or {}
    scan_bundle_by_source = bundle.get("scan_series_by_source") or {}
    selected_scan_bundle = scan_bundle_by_source.get(normalized_source)
    if not isinstance(selected_scan_bundle, dict):
        selected_scan_bundle = bundle.get("scan_series") or {}

    workbench_payload = dict(bundle.get("workbench_trends") or {})
    workbench_payload["compliance_rule"] = normalized_compliance_rule
    workbench_payload["compliance_threshold"] = normalized_compliance_threshold

    return {
        "statistics": statistics_payload,
        "trend": list(bundle.get("trend_active") or []),
        "portfolio_summary": portfolio_payload,
        "prioritization": prioritization_payload,
        "findings_series": {
            "period": normalized_findings_period,
            "items": list(findings_bundle.get(normalized_findings_period, [])),
        },
        "scan_series": {
            "period": normalized_scan_period,
            "severity_source": normalized_source,
            "items": list(selected_scan_bundle.get(normalized_scan_period, [])),
        },
        "workbench_trends": workbench_payload,
        "_freshness": freshness,
    }


@router.get("/workbench-trends")
async def workbench_trends_chart(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    compliance_rule: str | None = Query(default=None),
    compliance_threshold: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    normalized_compliance_rule = _normalize_compliance_rule(compliance_rule)
    normalized_compliance_threshold = _normalize_compliance_threshold(compliance_threshold)
    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=selected_issue_technologies,
        vulnerabilities=selected_vulnerabilities,
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        compliance_rule=normalized_compliance_rule,
        compliance_threshold=normalized_compliance_threshold,
        refresh=refresh,
    )
    payload = dict(bundle.get("workbench_trends") or {})
    payload["compliance_rule"] = normalized_compliance_rule
    payload["compliance_threshold"] = normalized_compliance_threshold
    payload["_freshness"] = freshness
    return payload


@router.get("/filter-options")
async def analytics_filter_options(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    application_name: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    vulnerability_limit: int = Query(default=2000, ge=50, le=10000),
    refresh: bool = Query(default=False),
) -> dict:
    assert_action_allowed("view_analytics", user.role)
    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )
    bundle, freshness = await _get_bundle(
        user,
        asset_group_ids=selected_asset_groups,
        application_ids=selected_applications,
        issue_technologies=[],
        vulnerabilities=[],
        scan_types=selected_scan_types,
        scan_statuses=selected_scan_statuses,
        application_name=application_name,
        from_date=from_date,
        to_date=to_date,
        refresh=refresh,
    )
    options = dict(bundle.get("issue_filter_options") or {})
    vulnerabilities = list(options.get("vulnerabilities") or [])
    if vulnerability_limit > 0:
        vulnerabilities = vulnerabilities[:vulnerability_limit]
    return {
        "technologies": list(options.get("technologies") or []),
        "unclassified_count": int(options.get("unclassified_count") or 0),
        "vulnerabilities": vulnerabilities,
        "_freshness": freshness,
    }


@router.get("/issue-counts")
async def get_issue_counts(
    user: Annotated[UserContext, Depends(get_current_user)],
    asset_group_id: str | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    application_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
) -> dict:
    """Lightweight endpoint returning accurate issue counts from /Count API.

    Makes up to 10 parallel requests to AppScan /Count endpoints and returns
    exact integer counts for total, severity, status, and technology dimensions.
    Response time is typically < 2 seconds regardless of total issue volume.

    When dimension filters (issue_technologies, vulnerabilities, scan_types,
    scan_statuses, date range) are active, routes to bundle statistics which
    apply those filters in-memory against the full issue list.
    """
    assert_action_allowed("view_analytics", user.role)

    selected_asset_groups, selected_applications = _resolve_scope_filters(
        user,
        asset_group_id=asset_group_id,
        asset_group_ids=asset_group_ids,
        application_id=application_id,
        application_ids=application_ids,
    )
    selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
        issue_technology=issue_technology,
        issue_technologies=issue_technologies,
        vulnerability=vulnerability,
        vulnerabilities=vulnerabilities,
    )
    selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
        scan_type=scan_type,
        scan_types=scan_types,
        scan_status=scan_status,
        scan_statuses=scan_statuses,
    )

    # The /Count API only supports a single ApplicationId filter.  Route to the
    # bundle (which applies all filters in-memory) whenever:
    #   • dimension filters are active (Issues / Scans / Reports panels), OR
    #   • an asset-group scope is active (Count API cannot scope by asset group), OR
    #   • more than one application is selected (Count API can't multi-select apps).
    has_dimensional_filters = bool(
        selected_issue_technologies
        or selected_vulnerabilities
        or selected_scan_types
        or selected_scan_statuses
        or from_date
        or to_date
    )
    needs_bundle = bool(
        has_dimensional_filters
        or selected_asset_groups
        or len(selected_applications) > 1
    )

    counts: dict = {
        "total": 0, "active": 0, "resolved": 0,
        "critical": 0, "high": 0, "medium": 0, "low": 0,
        "sast": 0, "dast": 0, "sca": 0, "iast": 0,
    }

    if needs_bundle:
        # Bundle path — handles all filter dimensions accurately.
        try:
            bundle, _ = await _get_bundle(
                user,
                asset_group_ids=selected_asset_groups,
                application_ids=selected_applications,
                issue_technologies=selected_issue_technologies,
                vulnerabilities=selected_vulnerabilities,
                scan_types=selected_scan_types,
                scan_statuses=selected_scan_statuses,
                application_name=None,
                from_date=from_date,
                to_date=to_date,
            )
            stats = bundle.get("statistics") or {}
            counts = {
                "total": int(stats.get("total_issues", 0)),
                "active": int(stats.get("active_issues", 0)),
                "resolved": int(stats.get("resolved_issues", 0)),
                "critical": int(stats.get("critical_issues", 0)),
                "high": int(stats.get("high_issues", 0)),
                "medium": int(stats.get("medium_issues", 0)),
                "low": int(stats.get("low_issues", 0)),
                "sast": int(stats.get("sast_issues", 0)),
                "dast": int(stats.get("dast_issues", 0)),
                "sca": int(stats.get("sca_issues", 0)),
                "iast": int(stats.get("iast_issues", 0)),
                "count_source": "bundle",
            }
        except Exception as exc:
            logger.warning("get_issue_counts: bundle fetch failed: %s", exc)
    else:
        # No scope / dimensional filters active, single app or org-wide request.
        # Use the /Count API for fast accurate results.
        # Determine a single application_id for scoped /Count requests when exactly
        # one application is selected; otherwise use org-level counts.
        scoped_app_id: str | None = None
        if len(selected_applications) == 1:
            scoped_app_id = selected_applications[0]

        try:
            counts = await asyncio.wait_for(
                aggregate_issue_counts(application_id=scoped_app_id),
                timeout=settings.asoc_count_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("get_issue_counts: count fetch failed: %s", exc)
            counts = {
                "total": 0, "active": 0, "resolved": 0,
                "critical": 0, "high": 0, "medium": 0, "low": 0,
                "sast": 0, "dast": 0, "sca": 0, "iast": 0,
            }

        # When Count API is unavailable (all zeros), fall back to bundle statistics
        if all(counts.get(k, 0) == 0 for k in ("total", "sast", "dast", "sca", "iast")):
            try:
                bundle, _ = await _get_bundle(
                    user,
                    asset_group_ids=selected_asset_groups,
                    application_ids=selected_applications,
                    issue_technologies=[],
                    vulnerabilities=[],
                    scan_types=[],
                    scan_statuses=[],
                    application_name=None,
                    from_date=None,
                    to_date=None,
                )
                stats = bundle.get("statistics") or {}
                if stats.get("total_issues", 0):
                    counts = {
                        "total": int(stats.get("total_issues", 0)),
                        "active": int(stats.get("active_issues", 0)),
                        "resolved": int(stats.get("resolved_issues", 0)),
                        "critical": int(stats.get("critical_issues", 0)),
                        "high": int(stats.get("high_issues", 0)),
                        "medium": int(stats.get("medium_issues", 0)),
                        "low": int(stats.get("low_issues", 0)),
                        "sast": int(stats.get("sast_issues", 0)),
                        "dast": int(stats.get("dast_issues", 0)),
                        "sca": int(stats.get("sca_issues", 0)),
                        "iast": int(stats.get("iast_issues", 0)),
                        "count_source": "bundle_fallback",
                    }
            except Exception as _fb_exc:
                logger.warning("get_issue_counts: bundle fallback failed: %s", _fb_exc)

    now = _utc_now()
    return {
        **counts,
        "count_source": counts.get("count_source", "api_count"),
        "_freshness": _build_freshness(
            source="live",
            generated_at=_to_iso(now),
            fetched_at=_to_iso(now),
            expires_at=None,
        ),
    }


@router.get("/chart-data")
async def get_chart_data(
    user: Annotated[UserContext, Depends(get_current_user)],
    application_id: str | None = Query(default=None),
    asset_group_id: str | None = Query(default=None),
    application_ids: list[str] | None = Query(default=None),
    asset_group_ids: list[str] | None = Query(default=None),
    issue_technology: str | None = Query(default=None),
    issue_technologies: list[str] | None = Query(default=None),
    vulnerability: str | None = Query(default=None),
    vulnerabilities: list[str] | None = Query(default=None),
    scan_type: str | None = Query(default=None),
    scan_types: list[str] | None = Query(default=None),
    scan_status: str | None = Query(default=None),
    scan_statuses: list[str] | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> dict:
    """All chart data in one call for the dashboard.

    Reads pre-computed chart data (risk heatmap, status distribution, top apps)
    from the cached analytics bundle — derived from the full issue list, so no
    separate Count API calls are needed.  Accepts the same scope and dimension
    filters as /analytics/bundle so that sidebar filter selections are reflected
    in the Workbench chart cards.
    """
    assert_action_allowed("view_analytics", user.role)

    _empty = {
        "risk_heatmap": {"matrix": [], "totals": {}},
        "status_distribution": {"statuses": []},
        "top_apps": {"apps": []},
    }
    try:
        selected_asset_groups, selected_applications = _resolve_scope_filters(
            user,
            asset_group_id=asset_group_id,
            asset_group_ids=asset_group_ids,
            application_id=application_id,
            application_ids=application_ids,
        )
        selected_issue_technologies, selected_vulnerabilities = _resolve_issue_filters(
            issue_technology=issue_technology,
            issue_technologies=issue_technologies,
            vulnerability=vulnerability,
            vulnerabilities=vulnerabilities,
        )
        selected_scan_types, selected_scan_statuses = _resolve_scan_filters(
            scan_type=scan_type,
            scan_types=scan_types,
            scan_status=scan_status,
            scan_statuses=scan_statuses,
        )
        bundle, freshness = await _get_bundle(
            user,
            asset_group_ids=selected_asset_groups,
            application_ids=selected_applications,
            issue_technologies=selected_issue_technologies,
            vulnerabilities=selected_vulnerabilities,
            scan_types=selected_scan_types,
            scan_statuses=selected_scan_statuses,
            application_name=None,
            from_date=from_date,
            to_date=to_date,
            refresh=refresh,
        )
        result = bundle.get("chart_data") or _empty
    except Exception as exc:
        logger.warning("get_chart_data: bundle fetch failed: %s", exc)
        result = _empty
        freshness = {}

    now = _utc_now()
    result["_freshness"] = freshness or _build_freshness(
        source="live",
        generated_at=_to_iso(now),
        fetched_at=_to_iso(now),
        expires_at=None,
    )
    return result


@router.get("/risk-heatmap")
async def get_risk_heatmap(
    user: Annotated[UserContext, Depends(get_current_user)],
    application_id: str | None = Query(default=None),
    asset_group_id: str | None = Query(default=None),
) -> dict:
    """Severity × Technology risk heatmap matrix.

    Returns a 4×4 matrix of issue counts (Critical/High/Medium/Low ×
    SAST/DAST/SCA/IAST) built from 16 parallel /Count requests.
    """
    assert_action_allowed("view_analytics", user.role)

    try:
        result = await asyncio.wait_for(
            issue_count_service.get_risk_heatmap(
                application_id=application_id,
                asset_group_id=asset_group_id,
            ),
            timeout=settings.asoc_count_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("get_risk_heatmap: fetch failed: %s", exc)
        result = {"matrix": [], "totals": {}}

    now = _utc_now()
    result["_freshness"] = _build_freshness(
        source="live",
        generated_at=_to_iso(now),
        fetched_at=_to_iso(now),
        expires_at=None,
    )
    return result


@router.get("/top-apps")
async def get_top_apps(
    user: Annotated[UserContext, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=500),
    asset_group_id: str | None = Query(default=None),
) -> dict:
    """Top N applications by issue count.

    Returns the top *limit* applications ranked by total issue count, with
    per-app critical and high counts included for prioritization.
    """
    assert_action_allowed("view_analytics", user.role)

    try:
        result = await asyncio.wait_for(
            issue_count_service.get_top_apps_by_issues(
                limit=limit,
                asset_group_id=asset_group_id,
            ),
            timeout=settings.asoc_count_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("get_top_apps: fetch failed: %s", exc)
        result = {"apps": []}

    now = _utc_now()
    result["_freshness"] = _build_freshness(
        source="live",
        generated_at=_to_iso(now),
        fetched_at=_to_iso(now),
        expires_at=None,
    )
    return result


@router.get("/status-distribution")
async def get_status_distribution(
    user: Annotated[UserContext, Depends(get_current_user)],
    application_id: str | None = Query(default=None),
    asset_group_id: str | None = Query(default=None),
) -> dict:
    """Issue counts by status (Open / Fixed / InProgress / Noise).

    Makes 4 parallel /Count requests and returns exact integer counts per
    status value.
    """
    assert_action_allowed("view_analytics", user.role)

    try:
        result = await asyncio.wait_for(
            issue_count_service.get_status_distribution(
                application_id=application_id,
                asset_group_id=asset_group_id,
            ),
            timeout=settings.asoc_count_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("get_status_distribution: fetch failed: %s", exc)
        result = {"statuses": []}

    now = _utc_now()
    result["_freshness"] = _build_freshness(
        source="live",
        generated_at=_to_iso(now),
        fetched_at=_to_iso(now),
        expires_at=None,
    )
    return result


@router.get("/technology-breakdown")
async def get_technology_breakdown(
    user: Annotated[UserContext, Depends(get_current_user)],
    application_id: str | None = Query(default=None),
    asset_group_id: str | None = Query(default=None),
) -> dict:
    """Issue counts by technology (SAST / DAST / SCA / IAST).

    Reuses :func:`aggregate_issue_counts` and extracts the technology fields,
    returning a list suitable for pie/bar chart rendering.
    """
    assert_action_allowed("view_analytics", user.role)

    scoped_app_id: str | None = None
    if application_id:
        scoped_app_id = application_id

    try:
        counts = await asyncio.wait_for(
            aggregate_issue_counts(application_id=scoped_app_id),
            timeout=settings.asoc_count_timeout_seconds,
        )
    except Exception as exc:
        logger.warning("get_technology_breakdown: count fetch failed: %s", exc)
        counts = {"sast": 0, "dast": 0, "sca": 0, "iast": 0}

    technologies = [
        {"technology": "SAST", "count": int(counts.get("sast", 0))},
        {"technology": "DAST", "count": int(counts.get("dast", 0))},
        {"technology": "SCA",  "count": int(counts.get("sca", 0))},
        {"technology": "IAST", "count": int(counts.get("iast", 0))},
    ]
    now = _utc_now()
    return {
        "technologies": technologies,
        "total": sum(item["count"] for item in technologies),
        "_freshness": _build_freshness(
            source="live",
            generated_at=_to_iso(now),
            fetched_at=_to_iso(now),
            expires_at=None,
        ),
    }


@router.get("/severity-trend")
async def get_severity_trend(
    user: Annotated[UserContext, Depends(get_current_user)],
    application_id: str | None = Query(default=None),
    asset_group_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=7, le=365),
) -> dict:
    """Severity distribution trend over time (from cached analytics snapshots).

    Reads the most recent analytics snapshot from the postgres store and
    returns the findings_series data filtered to the requested time window.
    This endpoint does not make live API calls; it serves pre-computed data.
    """
    assert_action_allowed("view_analytics", user.role)

    latest = sqlite_store.get_latest_analytics_snapshot()
    if not latest or not latest.get("payload"):
        now = _utc_now()
        return {
            "days": days,
            "series": [],
            "_freshness": _build_freshness(
                source="none",
                generated_at=None,
                fetched_at=_to_iso(now),
                expires_at=None,
            ),
        }

    payload = _hydrate_bundle_defaults(latest.get("payload"))
    findings_bundle = payload.get("findings_series") or {}
    # Use monthly granularity as the canonical series for trend data.
    monthly_series: list[dict] = list(findings_bundle.get("month") or [])

    # Filter to the requested time window.
    cutoff = _utc_now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m")
    filtered = [
        row for row in monthly_series
        if str(row.get("period", "")) >= cutoff_str
    ]

    freshness = _build_freshness(
        source="cache",
        generated_at=str(payload.get("generated_at") or "") or None,
        fetched_at=str(latest.get("fetched_at") or "") or None,
        expires_at=str(latest.get("expires_at") or "") or None,
    )
    return {
        "days": days,
        "series": filtered,
        "_freshness": freshness,
    }
