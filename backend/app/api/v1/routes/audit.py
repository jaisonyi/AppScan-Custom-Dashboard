from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.repositories.postgres_store import (
    count_audit_events,
    list_audit_events as list_audit_event_rows,
)

router = APIRouter()


@router.get("/events")
async def list_audit_events(
    user: Annotated[UserContext, Depends(get_current_user)],
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List audit events with offset/limit pagination.

    Returns a paginated envelope::

        {
            "items": [...],
            "offset": 0,
            "limit": 200,
            "total": 1234
        }
    """
    assert_action_allowed("view_audit_events", user.role)
    items = list_audit_event_rows(limit=limit, offset=offset)
    total = count_audit_events()
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "total": total,
    }
