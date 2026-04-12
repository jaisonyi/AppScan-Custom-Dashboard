from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security.authorization import filter_by_asset_group
from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.services.multi_endpoint import aggregate_list

router = APIRouter()


@router.get("")
async def list_issues(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict]:
    assert_action_allowed("view_issues", user.role)
    items = await aggregate_list("list_issues")
    return filter_by_asset_group(items, user.asset_group_ids, user.role, ["asset_group_id"])
