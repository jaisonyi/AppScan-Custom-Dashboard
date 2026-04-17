"""Multi-endpoint support for ASoC read services.

Reads all configured ASoC data sources from the ``data_sources`` DB table
(with env-var fallback) and returns one ``AsocReadService`` instance per
enabled source.  Results from :func:`aggregate_list` are tagged with
``_data_source_id`` and ``_data_source_label`` so callers can distinguish
items from different ASoC instances.

Usage::

    from app.services.multi_endpoint import get_endpoint_services, aggregate_list

    services = get_endpoint_services()   # one service per data source
    all_scans = await aggregate_list("list_scans")   # merged + tagged
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config.settings import settings
from app.services.asoc_read_service import AsocReadService
from app.services import data_source_service

logger = logging.getLogger(__name__)


_MAX_DATA_SOURCE_IDS = 20


def _load_sources(
    *,
    data_source_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the list of enabled data sources (DB-first, env fallback).

    When *data_source_ids* is provided, only sources whose ``id`` is in that
    list are returned.  Invalid / unknown IDs are silently dropped.  The list
    is capped at :data:`_MAX_DATA_SOURCE_IDS` entries to prevent cache-key
    proliferation.
    """
    sources = data_source_service.list_all(include_disabled=False)
    if data_source_ids:
        valid_ids = {ds["id"] for ds in sources}
        allowed = set(data_source_ids[:_MAX_DATA_SOURCE_IDS]) & valid_ids
        sources = [ds for ds in sources if ds["id"] in allowed]
    return sources


def get_endpoint_services(
    *,
    data_source_ids: list[str] | None = None,
) -> list[AsocReadService]:
    """Return one :class:`AsocReadService` per enabled data source.

    Loads data sources from the DB (falls back to env if DB is empty).
    Returns an empty list when no data sources are configured.
    """
    sources = _load_sources(data_source_ids=data_source_ids)
    return [
        AsocReadService.for_endpoint(
            ds["url"], ds["api_key"], ds["api_secret"],
            verify=ds.get("verify_ssl", True),
        )
        for ds in sources
    ]


def get_endpoint_labels() -> list[dict[str, str]]:
    """Return label metadata for all enabled data sources.

    Useful for API responses that need to identify which data source a
    result came from without exposing credentials.

    Returns a list of dicts with keys ``id``, ``url``, and ``label``.
    """
    return [
        {"id": ds["id"], "url": ds["url"], "label": ds["label"]}
        for ds in _load_sources()
    ]


async def _fetch_one(svc: AsocReadService, method: str, /, *args: Any, **kwargs: Any) -> list[Any]:
    """Call ``method`` on a single service and normalise the result to a list."""
    result = await getattr(svc, method)(*args, **kwargs)
    return result if isinstance(result, list) else []


async def aggregate_list(
    method: str,
    /,
    *args: Any,
    data_source_ids: list[str] | None = None,
    **kwargs: Any,
) -> list[Any]:
    """Call ``method`` on every data source service and concatenate results.

    Each item in the merged list is tagged with ``_data_source_id`` and
    ``_data_source_label`` so callers can identify the origin.

    When *data_source_ids* is provided, only the specified data sources are
    queried — this avoids unnecessary ASoC API calls.

    Errors from individual endpoints are silently skipped so a single broken
    endpoint never blocks data from the others.  All errors are logged at
    WARNING level so operators can detect degraded endpoints.

    Example::

        scans = await aggregate_list("list_scans", use_mock_on_error=False)
        issues = await aggregate_list("list_issues_for_applications", app_ids)
    """
    sources = _load_sources(data_source_ids=data_source_ids)
    services = [
        AsocReadService.for_endpoint(
            ds["url"], ds["api_key"], ds["api_secret"],
            verify=ds.get("verify_ssl", True),
        )
        for ds in sources
    ]
    if not services:
        return []
    results = await asyncio.gather(
        *[_fetch_one(svc, method, *args, **kwargs) for svc in services],
        return_exceptions=True,
    )
    merged: list[Any] = []
    for idx, result in enumerate(results):
        ds = sources[idx] if idx < len(sources) else {}
        ds_id = ds.get("id", f"unknown-{idx}")
        ds_label = ds.get("label", f"endpoint[{idx}]")
        ds_url = ds.get("url", "unknown")
        if isinstance(result, BaseException):
            logger.warning(
                "aggregate_list('%s') failed for data source '%s' (%s): %s",
                method,
                ds_label,
                ds_url,
                result,
                exc_info=result,
            )
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    item["_data_source_id"] = ds_id
                    item["_data_source_label"] = ds_label
            merged.extend(result)
    return merged


async def aggregate_tenant_info(
    *,
    data_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return ``tenant_info`` from the first data source that responds successfully."""
    sources = _load_sources(data_source_ids=data_source_ids)
    for idx, ds in enumerate(sources):
        ds_label = ds.get("label", f"endpoint[{idx}]")
        ds_url = ds.get("url", "unknown")
        svc = AsocReadService.for_endpoint(
            ds["url"], ds["api_key"], ds["api_secret"],
            verify=ds.get("verify_ssl", True),
        )
        try:
            result = await svc.get_tenant_info(use_mock_on_error=True)
            if isinstance(result, dict):
                logger.debug(
                    "aggregate_tenant_info: using tenant info from data source '%s' (%s).",
                    ds_label,
                    ds_url,
                )
                return result
        except Exception as exc:
            logger.warning(
                "aggregate_tenant_info: data source '%s' (%s) failed: %s",
                ds_label,
                ds_url,
                exc,
            )
    return {}


async def aggregate_issue_counts(
    *,
    application_id: str | None = None,
    odata_filter: str | None = None,
    data_source_ids: list[str] | None = None,
) -> dict[str, int]:
    """Aggregate issue counts from ALL configured data sources using /Count endpoints.

    Sums integer counts across data sources (each source is a separate
    AppScan instance with its own issue namespace).

    Returns a dict with keys:
      total, active, resolved, critical, high, medium, low,
      sast, dast, sca, iast
    """
    _empty: dict[str, int] = {
        "total": 0, "active": 0, "resolved": 0,
        "critical": 0, "high": 0, "medium": 0, "low": 0,
        "sast": 0, "dast": 0, "sca": 0, "iast": 0,
    }
    services = get_endpoint_services(data_source_ids=data_source_ids)
    if not services:
        return dict(_empty)

    results = await asyncio.gather(
        *[
            svc.get_issue_counts(application_id=application_id, odata_filter=odata_filter)
            for svc in services
        ],
        return_exceptions=True,
    )

    merged: dict[str, int] = {}
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("aggregate_issue_counts failed for one data source: %s", result)
            continue
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            if isinstance(value, int):
                merged[key] = merged.get(key, 0) + value

    # Ensure all expected keys are present even if all data sources failed.
    for key, default in _empty.items():
        merged.setdefault(key, default)

    return merged


async def aggregate_risk_heatmap(
    *,
    application_id: str | None = None,
    asset_group_id: str | None = None,
    data_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate a severity × technology risk heatmap across ALL configured data sources.

    Makes 16 parallel /Count calls (4 severities × 4 technologies) per data source
    and sums the results.  Each cell that fails is silently treated as 0.

    Returns::

        {
            "matrix": [
                {"severity": "Critical", "sast": N, "dast": N, "sca": N, "iast": N},
                ...
            ],
            "totals": {"sast": N, "dast": N, "sca": N, "iast": N}
        }
    """
    _severities = ("Critical", "High", "Medium", "Low")
    _technologies = ("SAST", "DAST", "SCA", "IAST")

    services = get_endpoint_services(data_source_ids=data_source_ids)
    if not services:
        return {
            "matrix": [
                {"severity": sev, **{tech.lower(): 0 for tech in _technologies}}
                for sev in _severities
            ],
            "totals": {tech.lower(): 0 for tech in _technologies},
        }

    # Accumulate counts across all data sources.
    # cells[severity][technology] = total count
    cells: dict[str, dict[str, int]] = {
        sev: {tech.lower(): 0 for tech in _technologies}
        for sev in _severities
    }

    semaphore = asyncio.Semaphore(max(1, settings.asoc_count_concurrency))

    async def _one_cell(svc: AsocReadService, severity: str, technology: str) -> tuple[str, str, int]:
        async with semaphore:
            try:
                count = await svc.get_filtered_count(
                    severity=severity,
                    technology=technology,
                    application_id=application_id,
                )
            except Exception as exc:
                logger.warning(
                    "aggregate_risk_heatmap: cell (%s, %s) failed: %s",
                    severity,
                    technology,
                    exc,
                )
                count = 0
        return severity, technology, count

    tasks = [
        _one_cell(svc, sev, tech)
        for svc in services
        for sev in _severities
        for tech in _technologies
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, BaseException):
            logger.warning("aggregate_risk_heatmap: gather exception: %s", result)
            continue
        severity, technology, count = result
        cells[severity][technology.lower()] = cells[severity].get(technology.lower(), 0) + count

    matrix = [
        {"severity": sev, **cells[sev]}
        for sev in _severities
    ]
    totals = {
        tech.lower(): sum(cells[sev].get(tech.lower(), 0) for sev in _severities)
        for tech in _technologies
    }
    return {"matrix": matrix, "totals": totals}


async def aggregate_status_distribution(
    *,
    application_id: str | None = None,
    asset_group_id: str | None = None,
    data_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate issue counts by status across ALL configured data sources.

    Makes 4 parallel /Count calls per data source (Open, Fixed, InProgress, Noise)
    and sums the results.

    Returns::

        {
            "statuses": [
                {"status": "Open",       "count": N},
                {"status": "Fixed",      "count": N},
                {"status": "InProgress", "count": N},
                {"status": "Noise",      "count": N},
            ]
        }
    """
    _statuses = ("Open", "Fixed", "InProgress", "Noise")

    services = get_endpoint_services(data_source_ids=data_source_ids)
    if not services:
        return {"statuses": [{"status": s, "count": 0} for s in _statuses]}

    status_totals: dict[str, int] = {s: 0 for s in _statuses}

    semaphore = asyncio.Semaphore(max(1, settings.asoc_count_concurrency))

    async def _one_status(svc: AsocReadService, status: str) -> tuple[str, int]:
        async with semaphore:
            try:
                count = await svc.get_filtered_count(
                    status=status,
                    application_id=application_id,
                )
            except Exception as exc:
                logger.warning(
                    "aggregate_status_distribution: status '%s' failed: %s",
                    status,
                    exc,
                )
                count = 0
        return status, count

    tasks = [
        _one_status(svc, status)
        for svc in services
        for status in _statuses
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, BaseException):
            logger.warning("aggregate_status_distribution: gather exception: %s", result)
            continue
        status, count = result
        status_totals[status] = status_totals.get(status, 0) + count

    return {
        "statuses": [{"status": s, "count": status_totals[s]} for s in _statuses]
    }


async def aggregate_top_apps(
    *,
    limit: int = 20,
    asset_group_id: str | None = None,
    data_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate top N applications by issue count across ALL configured data sources.

    First fetches the application list from all data sources, then makes per-app
    /Count calls (total + critical + high) in parallel under a shared semaphore.

    Returns::

        {
            "apps": [
                {"app_id": "...", "app_name": "...", "total": N, "critical": N, "high": N},
                ...
            ]
        }
    """
    services = get_endpoint_services(data_source_ids=data_source_ids)
    if not services:
        return {"apps": []}

    # Collect all applications from all data sources.
    app_results = await asyncio.gather(
        *[svc.list_applications(use_mock_on_error=False) for svc in services],
        return_exceptions=True,
    )

    # Build a deduplicated map of app_id -> app_name.
    app_map: dict[str, str] = {}
    for result in app_results:
        if isinstance(result, BaseException):
            logger.warning("aggregate_top_apps: list_applications failed: %s", result)
            continue
        if not isinstance(result, list):
            continue
        for app in result:
            app_id = str(app.get("id", "") or "").strip()
            app_name = str(app.get("name", "") or app_id).strip()
            if app_id and app_id not in app_map:
                app_map[app_id] = app_name

    if not app_map:
        return {"apps": []}

    # For each app, gather total + critical + high counts across all data sources.
    semaphore = asyncio.Semaphore(max(1, settings.asoc_count_concurrency))

    async def _fetch_app_counts(svc: AsocReadService, app_id: str) -> dict[str, int]:
        async with semaphore:
            try:
                counts = await svc.get_issue_counts(application_id=app_id)
            except Exception as exc:
                logger.warning(
                    "aggregate_top_apps: get_issue_counts for app '%s' failed: %s",
                    app_id,
                    exc,
                )
                counts = {"total": 0, "critical": 0, "high": 0}
        return {"app_id": app_id, **counts}

    count_tasks = [
        _fetch_app_counts(svc, app_id)
        for svc in services
        for app_id in app_map
    ]
    count_results = await asyncio.gather(*count_tasks, return_exceptions=True)

    # Merge counts per app_id across data sources.
    merged: dict[str, dict[str, int]] = {}
    for result in count_results:
        if isinstance(result, BaseException):
            logger.warning("aggregate_top_apps: count gather exception: %s", result)
            continue
        if not isinstance(result, dict):
            continue
        app_id = str(result.get("app_id", "") or "")
        if not app_id:
            continue
        bucket = merged.setdefault(app_id, {"total": 0, "critical": 0, "high": 0})
        bucket["total"] += int(result.get("total", 0) or 0)
        bucket["critical"] += int(result.get("critical", 0) or 0)
        bucket["high"] += int(result.get("high", 0) or 0)

    # Sort by total descending and apply limit.
    sorted_apps = sorted(merged.items(), key=lambda item: item[1]["total"], reverse=True)
    top_apps = [
        {
            "app_id": app_id,
            "app_name": app_map.get(app_id, app_id),
            "total": counts["total"],
            "critical": counts["critical"],
            "high": counts["high"],
        }
        for app_id, counts in sorted_apps[:limit]
    ]
    return {"apps": top_apps}


async def aggregate_base_data(
    *,
    data_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch scans, issues, applications, asset_groups, and tenant_info from ALL
    configured data sources concurrently and merge the results into a single dict.

    DAST page coverage is hydrated per-data-source using each source's own
    client so that individual scan detail requests are routed correctly.

    Also computes ``app_based_statistics`` by summing per-app issue/scan counts
    directly from the /api/v4/Apps response — the most reliable statistics source
    since it requires no extra API calls and is not subject to pagination limits.

    Returns a dict with keys: ``scans``, ``issues``, ``applications``,
    ``asset_groups``, ``tenant_info``, ``app_based_statistics``.
    """
    services = get_endpoint_services(data_source_ids=data_source_ids)
    sources = _load_sources(data_source_ids=data_source_ids)
    if not services:
        return {
            "scans": [],
            "issues": [],
            "applications": [],
            "asset_groups": [],
            "tenant_info": {},
            "app_based_statistics": {},
        }

    async def _one(svc: AsocReadService) -> dict[str, Any]:
        scans_raw, issues, apps, groups, tenant = await asyncio.gather(
            svc.list_scans(use_mock_on_error=False),
            svc.list_issues(use_mock_on_error=False),
            svc.list_applications(use_mock_on_error=False),
            svc.list_asset_groups(use_mock_on_error=False),
            svc.get_tenant_info(use_mock_on_error=True),
        )
        scans = await svc.hydrate_dast_page_coverage(
            scans_raw if isinstance(scans_raw, list) else [],
            schedule_refresh=True,
        )
        apps_list = apps if isinstance(apps, list) else []
        scans_list = scans if isinstance(scans, list) else []
        # Compute app-based statistics for this endpoint
        app_stats = AsocReadService.calculate_statistics_from_apps(apps_list, scans_list)
        return {
            "scans": scans_list,
            "issues": issues if isinstance(issues, list) else [],
            "applications": apps_list,
            "asset_groups": groups if isinstance(groups, list) else [],
            "tenant_info": tenant if isinstance(tenant, dict) else {},
            "app_based_statistics": app_stats,
        }

    results = await asyncio.gather(
        *[_one(svc) for svc in services],
        return_exceptions=True,
    )

    merged: dict[str, Any] = {
        "scans": [],
        "issues": [],
        "applications": [],
        "asset_groups": [],
        "tenant_info": {},
        "app_based_statistics": {},
    }
    # Accumulate app_based_statistics by summing across data sources
    _tag_keys = ("scans", "issues", "applications", "asset_groups")
    merged_app_stats: dict[str, int] = {}
    for idx, result in enumerate(results):
        if isinstance(result, BaseException):
            continue
        ds = sources[idx] if idx < len(sources) else {}
        ds_id = ds.get("id", f"unknown-{idx}")
        ds_label = ds.get("label", f"endpoint[{idx}]")
        for key in _tag_keys:
            items = result.get(key) or []
            for item in items:
                if isinstance(item, dict):
                    item["_data_source_id"] = ds_id
                    item["_data_source_label"] = ds_label
            merged[key].extend(items)
        if not merged["tenant_info"]:
            merged["tenant_info"] = result["tenant_info"]
        # Sum numeric fields from app_based_statistics across endpoints
        ep_stats = result.get("app_based_statistics") or {}
        for key, value in ep_stats.items():
            if isinstance(value, int):
                merged_app_stats[key] = merged_app_stats.get(key, 0) + value

    if merged_app_stats:
        merged_app_stats["count_source"] = "app_aggregation"
        merged["app_based_statistics"] = merged_app_stats

    return merged
