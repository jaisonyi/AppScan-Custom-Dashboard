from __future__ import annotations

from typing import Annotated, Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.plugins.widget_registry import get_widget_map, list_widgets
from app.repositories.postgres_store import (
    append_audit_event,
    append_dashboard_version,
    create_dashboard_template as create_dashboard_template_row,
    create_dashboard as create_dashboard_row,
    delete_dashboard as delete_dashboard_row,
    get_dashboard_template as get_dashboard_template_row,
    get_dashboard_version as get_dashboard_version_row,
    get_dashboard as get_dashboard_row,
    list_dashboard_templates as list_dashboard_template_rows,
    list_dashboard_versions as list_dashboard_version_rows,
    list_dashboards as list_dashboard_rows,
    update_dashboard as update_dashboard_row,
)

router = APIRouter()
DASHBOARD_NOT_FOUND = "Dashboard not found"


class DashboardCreateRequest(BaseModel):
    name: str
    widgets: list[dict[str, Any]]
    blueprint: Optional[dict[str, Any]] = None


class DashboardUpdateRequest(BaseModel):
    name: Optional[str] = None
    widgets: Optional[list[dict[str, Any]]] = None
    blueprint: Optional[dict[str, Any]] = None


class DashboardTemplateCreateRequest(BaseModel):
    name: str
    description: str
    scope: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)
    widgets: list[dict[str, Any]]
    visibility: str = "team"


class DashboardWizardCreateRequest(BaseModel):
    name: str
    template_id: Optional[str] = None
    selected_widget_types: list[str] = Field(default_factory=list)
    asset_group_ids: list[str] = Field(default_factory=list)
    visibility: str = "team"
    layout: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


def _normalize_widget_definitions(widget_types: list[str]) -> list[dict[str, Any]]:
    widget_map = get_widget_map()
    result: list[dict[str, Any]] = []
    for widget_type in widget_types:
        entry = widget_map.get(widget_type)
        if entry is None:
            continue
        result.append(
            {
                "type": entry["type"],
                "title": entry["title"],
                "category": entry["category"],
                "config": entry["default_config"],
            }
        )
    return result


@router.get("")
def list_dashboards(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict]:
    assert_action_allowed("view_dashboards", user.role)
    return list_dashboard_rows()


@router.get("/widget-registry")
def list_widget_registry(user: Annotated[UserContext, Depends(get_current_user)]) -> dict[str, Any]:
    assert_action_allowed("view_widget_registry", user.role)
    widgets = [
        widget
        for widget in list_widgets()
        if user.role in set(widget.get("allowed_roles", []))
    ]
    return {"items": widgets, "count": len(widgets)}


@router.get("/templates")
def list_dashboard_templates(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict[str, Any]]:
    assert_action_allowed("view_dashboard_templates", user.role)
    return list_dashboard_template_rows()


@router.post("/templates")
def create_dashboard_template(
    payload: DashboardTemplateCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    assert_action_allowed("manage_dashboard_templates", user.role)
    template_id = f"dt-{uuid4().hex[:10]}"
    row = create_dashboard_template_row(
        template_id=template_id,
        name=payload.name,
        description=payload.description,
        scope=payload.scope,
        layout=payload.layout,
        widgets=payload.widgets,
        visibility=payload.visibility,
        created_by=user.subject,
    )
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="dashboard_template.create",
        resource_type="dashboard_template",
        resource_id=template_id,
        details={"name": payload.name, "widget_count": len(payload.widgets)},
    )
    return row


@router.post("/wizard/create")
def create_dashboard_via_wizard(
    payload: DashboardWizardCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    assert_action_allowed("create_dashboard", user.role)

    template_widgets: list[dict[str, Any]] = []
    template_layout: dict[str, Any] = {}
    if payload.template_id:
        template = get_dashboard_template_row(payload.template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Dashboard template not found")
        template_widgets = list(template.get("widgets", []))
        template_layout = dict(template.get("layout", {}))

    selected_widgets = _normalize_widget_definitions(payload.selected_widget_types)
    final_widgets = template_widgets + [widget for widget in selected_widgets if widget not in template_widgets]
    if not final_widgets:
        raise HTTPException(status_code=400, detail="At least one valid widget is required")

    blueprint = {
        "status": payload.status,
        "visibility": payload.visibility,
        "asset_group_ids": payload.asset_group_ids,
        "layout": payload.layout or template_layout,
        "source_template_id": payload.template_id,
        "version": 1,
    }

    dashboard_id = f"d-{uuid4().hex[:8]}"
    row = create_dashboard_row(dashboard_id, payload.name, final_widgets, user.subject, blueprint)
    append_dashboard_version(
        version_id=f"dv-{uuid4().hex[:10]}",
        dashboard_id=dashboard_id,
        name=payload.name,
        widgets=final_widgets,
        owner=user.subject,
        change_note="created via wizard",
    )
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="dashboard.wizard_create",
        resource_type="dashboard",
        resource_id=dashboard_id,
        details={"template_id": payload.template_id, "widget_count": len(final_widgets)},
    )
    return row


@router.post("")
def create_dashboard(
    payload: DashboardCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("create_dashboard", user.role)
    dashboard_id = f"d-{uuid4().hex[:8]}"
    resolved_blueprint = payload.blueprint or {
        "status": "draft",
        "visibility": "team",
        "asset_group_ids": user.asset_group_ids,
        "layout": {"columns": 12, "items": []},
        "version": 1,
    }
    row = create_dashboard_row(dashboard_id, payload.name, payload.widgets, user.subject, resolved_blueprint)
    append_dashboard_version(
        version_id=f"dv-{uuid4().hex[:10]}",
        dashboard_id=dashboard_id,
        name=payload.name,
        widgets=payload.widgets,
        owner=user.subject,
        change_note="initial creation",
    )
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="dashboard.create",
        resource_type="dashboard",
        resource_id=dashboard_id,
        details={"name": payload.name, "widget_count": len(payload.widgets)},
    )
    return row


@router.put("/{dashboard_id}", responses={404: {"description": DASHBOARD_NOT_FOUND}})
def update_dashboard(
    dashboard_id: str,
    payload: DashboardUpdateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("update_dashboard", user.role)
    before = get_dashboard_row(dashboard_id)
    existing = update_dashboard_row(dashboard_id, payload.name, payload.widgets, payload.blueprint)
    if not existing:
        raise HTTPException(status_code=404, detail=DASHBOARD_NOT_FOUND)
    append_dashboard_version(
        version_id=f"dv-{uuid4().hex[:10]}",
        dashboard_id=dashboard_id,
        name=existing["name"],
        widgets=existing["widgets"],
        owner=existing["owner"],
        change_note="metadata/layout update",
    )
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="dashboard.update",
        resource_type="dashboard",
        resource_id=dashboard_id,
        details={
            "before_name": before["name"] if before else None,
            "after_name": existing["name"],
            "widget_count": len(existing["widgets"]),
        },
    )
    return existing


@router.delete("/{dashboard_id}", responses={404: {"description": DASHBOARD_NOT_FOUND}})
def delete_dashboard(
    dashboard_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("delete_dashboard", user.role)
    if not delete_dashboard_row(dashboard_id):
        raise HTTPException(status_code=404, detail=DASHBOARD_NOT_FOUND)
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="dashboard.delete",
        resource_type="dashboard",
        resource_id=dashboard_id,
        details={},
    )
    return {"status": "deleted", "id": dashboard_id}


@router.get("/{dashboard_id}/versions", responses={404: {"description": DASHBOARD_NOT_FOUND}})
def list_dashboard_versions(
    dashboard_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> list[dict]:
    assert_action_allowed("view_dashboards", user.role)
    if get_dashboard_row(dashboard_id) is None:
        raise HTTPException(status_code=404, detail=DASHBOARD_NOT_FOUND)
    return list_dashboard_version_rows(dashboard_id, 30)


@router.post("/{dashboard_id}/rollback/{version}", responses={404: {"description": DASHBOARD_NOT_FOUND}})
def rollback_dashboard_version(
    dashboard_id: str,
    version: int,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("create_dashboard", user.role)
    existing = get_dashboard_row(dashboard_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=DASHBOARD_NOT_FOUND)

    target = get_dashboard_version_row(dashboard_id, version)
    if target is None:
        raise HTTPException(status_code=404, detail="Dashboard version not found")

    updated = update_dashboard_row(dashboard_id, target["name"], target["widgets"])
    if updated is None:
        raise HTTPException(status_code=404, detail=DASHBOARD_NOT_FOUND)

    append_dashboard_version(
        version_id=f"dv-{uuid4().hex[:10]}",
        dashboard_id=dashboard_id,
        name=updated["name"],
        widgets=updated["widgets"],
        owner=updated["owner"],
        change_note=f"rollback to v{version}",
    )
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="dashboard.rollback",
        resource_type="dashboard",
        resource_id=dashboard_id,
        details={"from_version": version},
    )
    return updated
