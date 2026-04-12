from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.repositories.postgres_store import (
    append_audit_event,
    append_report_history,
    create_report_schedule as create_report_schedule_row,
    create_report_template as create_report_template_row,
    delete_report_schedule as delete_report_schedule_row,
    delete_report_template as delete_report_template_row,
    get_report_artifact,
    latest_schedule_execution_map,
    report_artifact_map,
    list_report_schedules as list_report_schedule_rows,
    list_report_history as list_report_history_rows,
    list_report_templates as list_report_template_rows,
    update_report_schedule as update_report_schedule_row,
)
from app.services.report_artifacts import create_report_artifact, resolve_artifact_path
from app.workers.schedule_utils import compute_next_run_iso, ensure_valid_cron

router = APIRouter()
REPORT_TEMPLATE_NOT_FOUND = "Report template not found"
REPORT_SCHEDULE_NOT_FOUND = "Report schedule not found"


class ReportRequest(BaseModel):
    name: str
    filters: dict[str, Any]
    format: str = "json"


class ReportTemplateCreateRequest(BaseModel):
    name: str
    filters: dict[str, Any]


class ReportScheduleCreateRequest(BaseModel):
    name: str
    template_id: Optional[str] = None
    cron: str
    format: str = "json"
    enabled: bool = True
    next_run_at: Optional[str] = None


class ReportScheduleUpdateRequest(BaseModel):
    name: Optional[str] = None
    template_id: Optional[str] = None
    cron: Optional[str] = None
    format: Optional[str] = None
    enabled: Optional[bool] = None
    next_run_at: Optional[str] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_stale(ts: str | None, threshold_minutes: int = 15) -> bool:
    if not ts:
        return True
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return True
    return (_utc_now() - dt) > timedelta(minutes=threshold_minutes)


@router.get("/templates")
def list_report_templates(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict]:
    assert_action_allowed("view_report_templates", user.role)
    return list_report_template_rows()


@router.post("/templates")
def create_report_template(
    payload: ReportTemplateCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("generate_report", user.role)
    template_id = f"rt-{uuid4().hex[:8]}"
    row = create_report_template_row(template_id, payload.name, payload.filters, user.subject)
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report_template.create",
        resource_type="report_template",
        resource_id=template_id,
        details={"name": payload.name},
    )
    return row


@router.delete("/templates/{template_id}", responses={404: {"description": REPORT_TEMPLATE_NOT_FOUND}})
def delete_report_template(
    template_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("generate_report", user.role)
    if not delete_report_template_row(template_id):
        raise HTTPException(status_code=404, detail=REPORT_TEMPLATE_NOT_FOUND)
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report_template.delete",
        resource_type="report_template",
        resource_id=template_id,
        details={},
    )
    return {"status": "deleted", "id": template_id}


@router.post("/generate")
def generate_report(
    payload: ReportRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("generate_report", user.role)
    report_id = f"r-{uuid4().hex[:8]}"
    row = append_report_history(
        report_id=report_id,
        report_name=payload.name,
        output_format=payload.format,
        status="queued",
        requested_by=user.subject,
        filters=payload.filters,
        message="Custom reporting capability scaffolded.",
    )
    artifact = create_report_artifact(
        report_id,
        {
            "report_id": report_id,
            "name": payload.name,
            "format": payload.format,
            "filters": payload.filters,
            "status": "queued",
            "generated_at": row["created_at"],
            "generated_by": user.subject,
        },
    )
    row["artifact"] = {
        "available": True,
        "download_path": f"/reports/history/{report_id}/download",
        "file_name": artifact["file_name"],
    }
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report.generate",
        resource_type="report",
        resource_id=row["id"],
        details={"name": payload.name, "format": payload.format},
    )
    return row


@router.get("/history")
def list_report_history(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict]:
    assert_action_allowed("view_report_templates", user.role)
    rows = list_report_history_rows(50)
    artifact_by_report = report_artifact_map([str(row["id"]) for row in rows])
    for row in rows:
        artifact = artifact_by_report.get(str(row["id"]))
        row["artifact"] = {
            "available": artifact is not None,
            "download_path": f"/reports/history/{row['id']}/download" if artifact else None,
            "file_name": artifact["file_name"] if artifact else None,
        }
    return rows


@router.get("/history/{report_id}/download", responses={404: {"description": "Report artifact not found"}})
def download_report_artifact(
    report_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> FileResponse:
    assert_action_allowed("view_report_templates", user.role)
    artifact = get_report_artifact(report_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    try:
        file_path = resolve_artifact_path(str(artifact["file_path"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact path") from exc
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report artifact not found")
    return FileResponse(
        path=str(file_path),
        media_type=str(artifact["mime_type"]),
        filename=str(artifact["file_name"]),
    )


@router.get("/schedules")
def list_report_schedules(user: Annotated[UserContext, Depends(get_current_user)]) -> list[dict]:
    assert_action_allowed("view_report_templates", user.role)
    return list_report_schedule_rows()


@router.post("/schedules", responses={422: {"description": "Invalid cron expression"}})
def create_report_schedule(
    payload: ReportScheduleCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("manage_report_schedules", user.role)
    try:
        ensure_valid_cron(payload.cron)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid cron expression") from exc
    schedule_id = f"rs-{uuid4().hex[:8]}"
    next_run_at = payload.next_run_at or compute_next_run_iso(payload.cron)
    row = create_report_schedule_row(
        schedule_id=schedule_id,
        name=payload.name,
        template_id=payload.template_id,
        cron=payload.cron,
        output_format=payload.format,
        enabled=payload.enabled,
        next_run_at=next_run_at,
        created_by=user.subject,
    )
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report_schedule.create",
        resource_type="report_schedule",
        resource_id=schedule_id,
        details={"name": payload.name, "cron": payload.cron},
    )
    return row


@router.put(
    "/schedules/{schedule_id}",
    responses={
        404: {"description": REPORT_SCHEDULE_NOT_FOUND},
        422: {"description": "Invalid cron expression"},
    },
)
def update_report_schedule(
    schedule_id: str,
    payload: ReportScheduleUpdateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("manage_report_schedules", user.role)
    if payload.cron is not None:
        try:
            ensure_valid_cron(payload.cron)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid cron expression") from exc
    resolved_next_run = payload.next_run_at
    if payload.cron is not None and payload.next_run_at is None:
        resolved_next_run = compute_next_run_iso(payload.cron)
    row = update_report_schedule_row(
        schedule_id=schedule_id,
        name=payload.name,
        template_id=payload.template_id,
        cron=payload.cron,
        output_format=payload.format,
        enabled=payload.enabled,
        next_run_at=resolved_next_run,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=REPORT_SCHEDULE_NOT_FOUND)
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report_schedule.update",
        resource_type="report_schedule",
        resource_id=schedule_id,
        details={
            "cron": row["cron"],
            "enabled": row["enabled"],
        },
    )
    return row


@router.delete("/schedules/{schedule_id}", responses={404: {"description": REPORT_SCHEDULE_NOT_FOUND}})
def delete_report_schedule(
    schedule_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("manage_report_schedules", user.role)
    if not delete_report_schedule_row(schedule_id):
        raise HTTPException(status_code=404, detail=REPORT_SCHEDULE_NOT_FOUND)
    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report_schedule.delete",
        resource_type="report_schedule",
        resource_id=schedule_id,
        details={},
    )
    return {"status": "deleted", "id": schedule_id}


@router.get("/schedules/monitor")
def monitor_report_schedules(user: Annotated[UserContext, Depends(get_current_user)]) -> dict:
    assert_action_allowed("view_report_templates", user.role)
    schedules = list_report_schedule_rows()
    execution_map = latest_schedule_execution_map()
    history = list_report_history_rows(200)
    now = _utc_now()
    scheduler_runs_last_24h = sum(
        1
        for row in history
        if row.get("requested_by") == "scheduler"
        and (
            now
            - datetime.fromisoformat(str(row.get("created_at", now.isoformat())).replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        )
        <= timedelta(hours=24)
    )

    monitor_rows = []
    unhealthy = 0
    for schedule in schedules:
        last_executed_at = execution_map.get(schedule["id"])
        enabled = bool(schedule.get("enabled"))
        last_error = str(schedule.get("last_error") or "")
        stale = _is_stale(last_executed_at) if enabled else False
        if not enabled:
            health = "disabled"
        elif last_error:
            health = "failed"
        elif stale:
            health = "stale"
        else:
            health = "ok"
        if health in {"failed", "stale"}:
            unhealthy += 1
        monitor_rows.append(
            {
                "id": schedule["id"],
                "name": schedule["name"],
                "cron": schedule["cron"],
                "enabled": enabled,
                "next_run_at": schedule.get("next_run_at"),
                "last_executed_at": last_executed_at,
                "retry_count": int(schedule.get("retry_count") or 0),
                "last_error": last_error,
                "last_attempt_at": schedule.get("last_attempt_at"),
                "health": health,
            }
        )

    health_counts = {
        "ok": sum(1 for item in monitor_rows if item["health"] == "ok"),
        "stale": sum(1 for item in monitor_rows if item["health"] == "stale"),
        "failed": sum(1 for item in monitor_rows if item["health"] == "failed"),
        "disabled": sum(1 for item in monitor_rows if item["health"] == "disabled"),
    }

    return {
        "total": len(schedules),
        "enabled": sum(1 for s in schedules if s.get("enabled")),
        "unhealthy": unhealthy,
        "scheduler_runs_last_24h": scheduler_runs_last_24h,
        "health_counts": health_counts,
        "items": monitor_rows,
    }


@router.post("/schedules/{schedule_id}/run-now", responses={404: {"description": REPORT_SCHEDULE_NOT_FOUND}})
def run_schedule_now(
    schedule_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    assert_action_allowed("manage_report_schedules", user.role)
    schedules = list_report_schedule_rows()
    schedule = next((s for s in schedules if s["id"] == schedule_id), None)
    if schedule is None:
        raise HTTPException(status_code=404, detail=REPORT_SCHEDULE_NOT_FOUND)

    history = append_report_history(
        report_id=f"r-{uuid4().hex[:8]}",
        report_name=schedule["name"],
        output_format=schedule["format"],
        status="completed",
        requested_by=user.subject,
        filters={"schedule_id": schedule_id, "template_id": schedule.get("template_id")},
        message="Manual run-now execution.",
    )
    artifact = create_report_artifact(
        history["id"],
        {
            "report_id": history["id"],
            "name": history["report_name"],
            "format": history["format"],
            "filters": history["filters"],
            "status": history["status"],
            "generated_at": history["created_at"],
            "generated_by": user.subject,
        },
    )
    history["artifact"] = {
        "available": True,
        "download_path": f"/reports/history/{history['id']}/download",
        "file_name": artifact["file_name"],
    }
    next_run = compute_next_run_iso(schedule["cron"])
    updated = update_report_schedule_row(
        schedule_id=schedule_id,
        next_run_at=next_run,
        retry_count=0,
        last_error="",
        last_attempt_at=_utc_now().isoformat(),
    )

    append_audit_event(
        event_id=f"ae-{uuid4().hex[:10]}",
        actor=user.subject,
        action="report_schedule.run_now",
        resource_type="report_schedule",
        resource_id=schedule_id,
        details={"report_id": history["id"], "next_run_at": next_run},
    )

    return {
        "schedule": updated,
        "history": history,
    }
