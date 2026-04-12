from __future__ import annotations

from typing import Any


_WIDGET_REGISTRY: list[dict[str, Any]] = [
    {
        "type": "kpi_card",
        "title": "KPI Card",
        "category": "kpi",
        "description": "Single-value KPI widget with threshold bands.",
        "default_config": {"metric": "total_issues", "time_range": "30d"},
        "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
    },
    {
        "type": "issue_trend_line",
        "title": "Issue Trend",
        "category": "trend",
        "description": "Monthly issue trend line by severity or status.",
        "default_config": {"group_by": "month", "metric": "issues", "time_range": "6m"},
        "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
    },
    {
        "type": "mttr_bar",
        "title": "MTTR Chart",
        "category": "mttr",
        "description": "Mean-time-to-remediate chart by month.",
        "default_config": {"group_by": "month", "unit": "days", "time_range": "6m"},
        "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
    },
    {
        "type": "severity_pie",
        "title": "Severity Mix",
        "category": "kpi",
        "description": "Issue distribution by severity.",
        "default_config": {"metric": "issue_count", "group_by": "severity", "time_range": "30d"},
        "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
    },
    {
        "type": "issue_aging_table",
        "title": "Issue Aging",
        "category": "risk",
        "description": "Aging bucket table for open issues.",
        "default_config": {"buckets": ["0-7", "8-30", "31-90", "90+"], "time_range": "90d"},
        "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
    },
    {
        "type": "pipeline_risk",
        "title": "Pipeline Risk",
        "category": "pipeline",
        "description": "Pipeline BOM risk score and stage breakdown.",
        "default_config": {"metric": "risk_score", "time_range": "30d"},
        "allowed_roles": ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"],
    },
]


def list_widgets() -> list[dict[str, Any]]:
    return [dict(widget) for widget in _WIDGET_REGISTRY]


def get_widget_map() -> dict[str, dict[str, Any]]:
    return {str(widget["type"]): dict(widget) for widget in _WIDGET_REGISTRY}
