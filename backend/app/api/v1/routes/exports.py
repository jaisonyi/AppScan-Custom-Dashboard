from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.security.authorization import filter_by_asset_group
from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.services.multi_endpoint import (
    aggregate_issue_counts,
    aggregate_list,
    aggregate_top_apps,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column definitions for each exportable dataset
# ---------------------------------------------------------------------------

_SCAN_COLUMNS: list[tuple[str, str]] = [
    ("id", "Scan ID"),
    ("name", "Scan Name"),
    ("scan_type", "Technology"),
    ("status", "Status"),
    ("application_id", "Application ID"),
    ("application_name", "Application Name"),
    ("asset_group_id", "Asset Group ID"),
    ("created_at", "Created At"),
    ("duration_seconds", "Duration (s)"),
    ("sast_size", "SAST LOC"),
    ("sca_size", "SCA Components"),
    ("page_coverage", "Pages Scanned"),
    ("_data_source_label", "Data Source"),
]

_APP_COLUMNS: list[tuple[str, str]] = [
    ("id", "Application ID"),
    ("name", "Application Name"),
    ("asset_group_id", "Asset Group ID"),
    ("asset_group_name", "Asset Group"),
    ("risk_rating", "Risk Rating"),
    ("business_impact", "Business Impact"),
    ("total_issues", "Total Issues"),
    ("critical_issues", "Critical"),
    ("high_issues", "High"),
    ("medium_issues", "Medium"),
    ("low_issues", "Low"),
    ("open_issues", "Open Issues"),
    ("total_scans", "Total Scans"),
    ("testing_status", "Testing Status"),
    ("last_updated", "Last Updated"),
    ("_data_source_label", "Data Source"),
]

_ISSUE_COLUMNS: list[tuple[str, str]] = [
    ("id", "Issue ID"),
    ("application_name", "Application"),
    ("issue_type", "Issue Type"),
    ("severity", "Severity"),
    ("status", "Status"),
    ("scanner_type", "Technology"),
    ("location", "Location"),
    ("api", "API"),
    ("date_created", "Date Created"),
    ("last_updated", "Last Updated"),
    ("fix_group_id", "Fix Group ID"),
    ("cve", "CVE"),
    ("cvss", "CVSS"),
    ("_data_source_label", "Data Source"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    """Return UTC timestamp string for file names (e.g. '20260417_153045')."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _rows_to_csv(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> str:
    """Convert list of dicts to CSV string using defined column mapping."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header row
    writer.writerow([header for _, header in columns])
    # Data rows
    for row in rows:
        writer.writerow([str(row.get(key, "")) for key, _ in columns])
    return buf.getvalue()


def _csv_response(content: str, filename: str) -> StreamingResponse:
    """Return a streaming CSV response with proper headers."""
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


# ---------------------------------------------------------------------------
# CSV Export Endpoints
# ---------------------------------------------------------------------------

@router.get("/scans.csv")
async def export_scans_csv(
    user: Annotated[UserContext, Depends(get_current_user)],
    data_source_ids: list[str] | None = Query(default=None),
) -> StreamingResponse:
    """Export all scans as CSV — PowerBI-ready format."""
    assert_action_allowed("view_scans", user.role)
    items = await aggregate_list("list_scans", data_source_ids=data_source_ids)
    items = filter_by_asset_group(items, user.asset_group_ids, user.role, ["asset_group_id"])
    csv_content = _rows_to_csv(items, _SCAN_COLUMNS)
    return _csv_response(csv_content, f"scans_{_timestamp()}.csv")


@router.get("/applications.csv")
async def export_applications_csv(
    user: Annotated[UserContext, Depends(get_current_user)],
    data_source_ids: list[str] | None = Query(default=None),
) -> StreamingResponse:
    """Export all applications as CSV — PowerBI-ready format."""
    assert_action_allowed("view_applications", user.role)
    items = await aggregate_list("list_applications", data_source_ids=data_source_ids)
    items = filter_by_asset_group(items, user.asset_group_ids, user.role, ["asset_group_id"])
    csv_content = _rows_to_csv(items, _APP_COLUMNS)
    return _csv_response(csv_content, f"applications_{_timestamp()}.csv")


@router.get("/issues.csv")
async def export_issues_csv(
    user: Annotated[UserContext, Depends(get_current_user)],
    data_source_ids: list[str] | None = Query(default=None),
) -> StreamingResponse:
    """Export all issues as CSV — PowerBI-ready format."""
    assert_action_allowed("view_issues", user.role)
    items = await aggregate_list("list_issues", data_source_ids=data_source_ids)
    items = filter_by_asset_group(items, user.asset_group_ids, user.role, ["asset_group_id"])
    csv_content = _rows_to_csv(items, _ISSUE_COLUMNS)
    return _csv_response(csv_content, f"issues_{_timestamp()}.csv")


@router.get("/summary.csv")
async def export_summary_csv(
    user: Annotated[UserContext, Depends(get_current_user)],
    data_source_ids: list[str] | None = Query(default=None),
) -> StreamingResponse:
    """Export KPI summary as CSV — single-row pivot table for PowerBI cards."""
    assert_action_allowed("view_analytics", user.role)

    counts = await aggregate_issue_counts(data_source_ids=data_source_ids)
    top_apps_data = await aggregate_top_apps(limit=20, data_source_ids=data_source_ids)
    apps_list = top_apps_data.get("apps", []) if isinstance(top_apps_data, dict) else []

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Section 1: Overall KPI summary (single row)
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total Issues", counts.get("total", 0)])
    writer.writerow(["Active Issues", counts.get("active", 0)])
    writer.writerow(["Resolved Issues", counts.get("resolved", 0)])
    writer.writerow(["Critical", counts.get("critical", 0)])
    writer.writerow(["High", counts.get("high", 0)])
    writer.writerow(["Medium", counts.get("medium", 0)])
    writer.writerow(["Low", counts.get("low", 0)])
    writer.writerow(["SAST Issues", counts.get("sast", 0)])
    writer.writerow(["DAST Issues", counts.get("dast", 0)])
    writer.writerow(["SCA Issues", counts.get("sca", 0)])
    writer.writerow(["IAST Issues", counts.get("iast", 0)])
    writer.writerow([])

    # Section 2: Top applications
    writer.writerow(["Application", "Critical", "High", "Medium", "Low", "Total"])
    for app in apps_list:
        c = int(app.get("critical", 0) or 0)
        h = int(app.get("high", 0) or 0)
        m = int(app.get("medium", 0) or 0)
        low = int(app.get("low", 0) or 0)
        writer.writerow([
            app.get("app_name", app.get("name", "")),
            c, h, m, low,
            c + h + m + low,
        ])

    return _csv_response(buf.getvalue(), f"summary_{_timestamp()}.csv")
