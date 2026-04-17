"""Unit tests for app.core.security.policy — RBAC policy enforcement."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.security.policy import ROLE_ACTION_POLICY, assert_action_allowed

# ---------------------------------------------------------------------------
# All known roles and actions
# ---------------------------------------------------------------------------

ALL_ROLES = {"PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"}
EXPECTED_ACTIONS = {
    "view_scans",
    "view_applications",
    "view_asset_groups",
    "view_issues",
    "view_analytics",
    "view_dashboards",
    "create_dashboard",
    "update_dashboard",
    "delete_dashboard",
    "view_widget_registry",
    "view_dashboard_templates",
    "manage_dashboard_templates",
    "view_report_templates",
    "generate_report",
    "manage_report_schedules",
    "view_audit_events",
    "view_pipeline_bom",
    "view_endpoints",
    "check_endpoint_status",
    "manage_endpoints",
}


# ---------------------------------------------------------------------------
# Policy structure tests
# ---------------------------------------------------------------------------


def test_all_17_actions_present() -> None:
    """ROLE_ACTION_POLICY must contain exactly the expected set of actions."""
    assert set(ROLE_ACTION_POLICY.keys()) == EXPECTED_ACTIONS


def test_all_5_roles_covered() -> None:
    """Every role must appear in at least one action's allowed set."""
    roles_seen: set[str] = set()
    for allowed in ROLE_ACTION_POLICY.values():
        roles_seen.update(allowed)
    assert ALL_ROLES.issubset(roles_seen)


def test_policy_values_are_sets() -> None:
    """Each policy value must be a set (not a list or other type)."""
    for action, roles in ROLE_ACTION_POLICY.items():
        assert isinstance(roles, set), f"Policy for '{action}' is not a set"


# ---------------------------------------------------------------------------
# assert_action_allowed — happy-path tests
# ---------------------------------------------------------------------------


def test_assert_action_allowed_passes_for_platform_admin() -> None:
    """PlatformAdmin is allowed for every action in the policy."""
    for action in ROLE_ACTION_POLICY:
        # Should not raise
        assert_action_allowed(action, "PlatformAdmin")


def test_auditor_can_view_audit_events() -> None:
    """Auditor calling view_audit_events raises no exception."""
    assert_action_allowed("view_audit_events", "Auditor")  # must not raise


def test_assert_action_allowed_passes_for_valid_role_parametrized(
    action: str = "view_scans",
) -> None:
    """All roles allowed for view_scans can call it without error."""
    for role in ROLE_ACTION_POLICY["view_scans"]:
        assert_action_allowed("view_scans", role)


@pytest.mark.parametrize(
    "action,role",
    [
        ("view_scans", "PlatformAdmin"),
        ("view_scans", "SecurityManager"),
        ("view_scans", "AppOwner"),
        ("view_scans", "Developer"),
        ("view_scans", "Auditor"),
        ("view_analytics", "Developer"),
        ("view_dashboards", "Auditor"),
        ("view_audit_events", "PlatformAdmin"),
        ("view_audit_events", "SecurityManager"),
        ("view_audit_events", "Auditor"),
        ("generate_report", "PlatformAdmin"),
        ("generate_report", "SecurityManager"),
        ("generate_report", "Auditor"),
        ("manage_report_schedules", "PlatformAdmin"),
        ("manage_report_schedules", "SecurityManager"),
        ("create_dashboard", "PlatformAdmin"),
        ("create_dashboard", "SecurityManager"),
        ("create_dashboard", "AppOwner"),
    ],
)
def test_assert_action_allowed_passes_for_valid_combos(action: str, role: str) -> None:
    """Parametrized: all allowed role/action combos pass without raising."""
    assert_action_allowed(action, role)  # must not raise


# ---------------------------------------------------------------------------
# assert_action_allowed — 403 tests
# ---------------------------------------------------------------------------


def test_assert_action_allowed_raises_403_for_wrong_role() -> None:
    """Developer calling generate_report raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("generate_report", "Developer")
    assert exc_info.value.status_code == 403


def test_assert_action_allowed_raises_403_for_auditor_on_manage_schedules() -> None:
    """Auditor calling manage_report_schedules raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("manage_report_schedules", "Auditor")
    assert exc_info.value.status_code == 403


def test_developer_cannot_create_dashboard() -> None:
    """Developer calling create_dashboard raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("create_dashboard", "Developer")
    assert exc_info.value.status_code == 403


def test_developer_cannot_delete_dashboard() -> None:
    """Developer calling delete_dashboard raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("delete_dashboard", "Developer")
    assert exc_info.value.status_code == 403


def test_auditor_cannot_manage_dashboard_templates() -> None:
    """Auditor calling manage_dashboard_templates raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("manage_dashboard_templates", "Auditor")
    assert exc_info.value.status_code == 403


def test_app_owner_cannot_manage_report_schedules() -> None:
    """AppOwner calling manage_report_schedules raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("manage_report_schedules", "AppOwner")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# assert_action_allowed — 500 for unknown action
# ---------------------------------------------------------------------------


def test_assert_action_allowed_raises_500_for_unknown_action() -> None:
    """Unknown action string raises HTTP 500 (missing policy)."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("nonexistent_action", "PlatformAdmin")
    assert exc_info.value.status_code == 500


def test_assert_action_allowed_raises_500_for_empty_action() -> None:
    """Empty action string raises HTTP 500."""
    with pytest.raises(HTTPException) as exc_info:
        assert_action_allowed("", "PlatformAdmin")
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Read-only actions — all roles can access
# ---------------------------------------------------------------------------

READ_ONLY_ACTIONS = [
    "view_scans",
    "view_applications",
    "view_asset_groups",
    "view_issues",
    "view_analytics",
    "view_dashboards",
    "view_widget_registry",
    "view_dashboard_templates",
    "view_pipeline_bom",
]


@pytest.mark.parametrize("action", READ_ONLY_ACTIONS)
@pytest.mark.parametrize("role", list(ALL_ROLES))
def test_read_only_roles_parametrized(action: str, role: str) -> None:
    """All read-only actions are accessible by every role."""
    assert_action_allowed(action, role)  # must not raise
