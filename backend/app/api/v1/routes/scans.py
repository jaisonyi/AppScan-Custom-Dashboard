from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.security.authorization import filter_by_asset_group
from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.services.asoc_read_service import AsocReadService
from app.services.multi_endpoint import aggregate_list, get_endpoint_services

router = APIRouter()
# Kept for single-endpoint diagnostics; aggregated calls are used for list routes.
_default_service = AsocReadService()


@router.get("")
async def list_scans(
    user: Annotated[UserContext, Depends(get_current_user)],
    data_source_ids: Optional[List[str]] = Query(default=None),
) -> list[dict]:
    assert_action_allowed("view_scans", user.role)
    items = await aggregate_list("list_scans", data_source_ids=data_source_ids)
    return filter_by_asset_group(items, user.asset_group_ids, user.role, ["asset_group_id"])


@router.get("/dast-page-coverage-diagnostics")
async def dast_page_coverage_diagnostics(
    user: Annotated[UserContext, Depends(get_current_user)],
    max_scans: int = Query(default=6, ge=1, le=20),
    scan_ids: Optional[list[str]] = Query(default=None),
) -> dict:
    assert_action_allowed("view_scans", user.role)
    _svc = next(iter(get_endpoint_services()), _default_service)
    payload = await _svc.diagnose_dast_page_coverage(scan_ids=scan_ids, max_scans=max_scans)
    items = payload.get("items") if isinstance(payload, dict) else []
    if isinstance(items, list):
        allowed_ids = set(user.asset_group_ids)
        filtered_items = [
            item
            for item in items
            if user.role in {"PlatformAdmin", "SecurityManager"}
            or str(item.get("asset_group_id", "")) in allowed_ids
            or not str(item.get("asset_group_id", ""))
        ]
        payload["items"] = filtered_items
    return payload
