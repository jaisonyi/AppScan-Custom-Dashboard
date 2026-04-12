from __future__ import annotations

from fastapi import HTTPException


ROLE_ACTION_POLICY: dict[str, set[str]] = {
    "view_scans": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "view_applications": {
        "PlatformAdmin",
        "SecurityManager",
        "AppOwner",
        "Developer",
        "Auditor",
    },
    "view_asset_groups": {
        "PlatformAdmin",
        "SecurityManager",
        "AppOwner",
        "Developer",
        "Auditor",
    },
    "view_issues": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "view_analytics": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "view_dashboards": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "create_dashboard": {"PlatformAdmin", "SecurityManager", "AppOwner"},
    "update_dashboard": {"PlatformAdmin", "SecurityManager", "AppOwner"},
    "delete_dashboard": {"PlatformAdmin", "SecurityManager", "AppOwner"},
    "view_widget_registry": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "view_dashboard_templates": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "manage_dashboard_templates": {"PlatformAdmin", "SecurityManager", "AppOwner"},
    "view_report_templates": {"PlatformAdmin", "SecurityManager", "AppOwner", "Auditor"},
    "generate_report": {"PlatformAdmin", "SecurityManager", "Auditor"},
    "manage_report_schedules": {"PlatformAdmin", "SecurityManager"},
    "view_audit_events": {"PlatformAdmin", "SecurityManager", "Auditor"},
    "view_pipeline_bom": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "view_endpoints": {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"},
    "check_endpoint_status": {"PlatformAdmin", "SecurityManager"},
    "manage_endpoints": {"PlatformAdmin", "SecurityManager"},
}


def assert_action_allowed(action: str, user_role: str) -> None:
    allowed_roles = ROLE_ACTION_POLICY.get(action)
    if not allowed_roles:
        raise HTTPException(status_code=500, detail=f"Missing policy action: {action}")
    if user_role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient role for requested action")
