from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.services.multi_endpoint import aggregate_list

router = APIRouter()


@router.get("")
async def list_asset_groups(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict]:
    assert_action_allowed("view_asset_groups", user.role)
    items = await aggregate_list("list_asset_groups")
    if user.role in {"PlatformAdmin", "SecurityManager"}:
        return items
    allowed = set(user.asset_group_ids)
    return [item for item in items if str(item.get("id", "")) in allowed]
