"""Issue count service — builds chart payloads using /Count endpoints."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config.settings import settings
from app.services.multi_endpoint import (
    aggregate_risk_heatmap,
    aggregate_status_distribution,
    aggregate_top_apps,
)

logger = logging.getLogger(__name__)

_SEVERITIES = ("Critical", "High", "Medium", "Low")
_TECHNOLOGIES = ("SAST", "DAST", "SCA", "IAST")
_STATUSES = ("Open", "Fixed", "InProgress", "Noise")


async def get_risk_heatmap(
    *,
    application_id: str | None = None,
    asset_group_id: str | None = None,
) -> dict[str, Any]:
    """Build a severity × technology matrix using 16 parallel /Count calls.

    Returns::

        {
            "matrix": [
                {"severity": "Critical", "sast": 120, "dast": 45, "sca": 89, "iast": 12},
                {"severity": "High",     "sast": 340, "dast": 120, "sca": 200, "iast": 30},
                {"severity": "Medium",   "sast": 1200, "dast": 500, "sca": 800, "iast": 100},
                {"severity": "Low",      "sast": 5000, "dast": 2000, "sca": 3000, "iast": 500},
            ],
            "totals": {"sast": 6660, "dast": 2665, "sca": 4089, "iast": 642}
        }
    """
    return await aggregate_risk_heatmap(
        application_id=application_id,
        asset_group_id=asset_group_id,
    )


async def get_status_distribution(
    *,
    application_id: str | None = None,
    asset_group_id: str | None = None,
) -> dict[str, Any]:
    """Issue counts by status.

    Returns::

        {
            "statuses": [
                {"status": "Open",       "count": 80000},
                {"status": "Fixed",      "count": 60000},
                {"status": "InProgress", "count": 15000},
                {"status": "Noise",      "count": 5000},
            ]
        }
    """
    return await aggregate_status_distribution(
        application_id=application_id,
        asset_group_id=asset_group_id,
    )


async def get_top_apps_by_issues(
    *,
    limit: int | None = None,
    asset_group_id: str | None = None,
) -> dict[str, Any]:
    """Top N applications by issue count.

    Returns::

        {
            "apps": [
                {"app_id": "...", "app_name": "WebApp1", "total": 5000, "critical": 200, "high": 800},
                ...
            ]
        }
    """
    effective_limit = limit if limit is not None else settings.asoc_top_apps_chart_limit
    return await aggregate_top_apps(
        limit=effective_limit,
        asset_group_id=asset_group_id,
    )


async def get_chart_data_bundle(
    *,
    application_id: str | None = None,
    asset_group_id: str | None = None,
) -> dict[str, Any]:
    """All chart data in one call — for the dashboard to fetch everything at once.

    Runs risk heatmap, status distribution, and top apps in parallel.
    """
    heatmap_task = get_risk_heatmap(
        application_id=application_id,
        asset_group_id=asset_group_id,
    )
    status_task = get_status_distribution(
        application_id=application_id,
        asset_group_id=asset_group_id,
    )
    top_apps_task = get_top_apps_by_issues(
        asset_group_id=asset_group_id,
    )

    heatmap, status_dist, top_apps = await asyncio.gather(
        heatmap_task,
        status_task,
        top_apps_task,
        return_exceptions=True,
    )

    def _safe(result: Any, fallback: Any) -> Any:
        if isinstance(result, BaseException):
            logger.warning("get_chart_data_bundle: sub-call failed: %s", result)
            return fallback
        return result

    return {
        "risk_heatmap": _safe(heatmap, {"matrix": [], "totals": {}}),
        "status_distribution": _safe(status_dist, {"statuses": []}),
        "top_apps": _safe(top_apps, {"apps": []}),
    }
