"""Unit tests for app.core.security.authorization — authorization helpers."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.security.authorization import (
    ADMIN_ROLES,
    assert_asset_group_access,
    assert_role,
    filter_by_asset_group,
    has_asset_group_access,
)


# ---------------------------------------------------------------------------
# assert_asset_group_access
# ---------------------------------------------------------------------------


def test_assert_asset_group_access_raises_403_when_not_permitted() -> None:
    """Group not in permitted list raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_asset_group_access("ag-99", ["ag-1", "ag-2"])
    assert exc_info.value.status_code == 403


def test_assert_asset_group_access_passes_when_permitted() -> None:
    """Group in permitted list raises no exception."""
    assert_asset_group_access("ag-1", ["ag-1", "ag-2"])  # must not raise


def test_assert_asset_group_access_raises_403_for_empty_permitted_list() -> None:
    """Empty permitted list always raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_asset_group_access("ag-1", [])
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# assert_role
# ---------------------------------------------------------------------------


def test_assert_role_raises_403_for_wrong_role() -> None:
    """Role not in required list raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_role(["PlatformAdmin", "SecurityManager"], "Developer")
    assert exc_info.value.status_code == 403


def test_assert_role_passes_for_correct_role() -> None:
    """Role in required list raises no exception."""
    assert_role(["PlatformAdmin", "SecurityManager"], "PlatformAdmin")  # must not raise


def test_assert_role_passes_for_any_matching_role() -> None:
    """Any matching role in the list passes."""
    assert_role(["AppOwner", "Developer", "Auditor"], "Developer")  # must not raise


def test_assert_role_raises_403_for_empty_required_list() -> None:
    """Empty required list always raises HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        assert_role([], "PlatformAdmin")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# has_asset_group_access
# ---------------------------------------------------------------------------


def test_has_asset_group_access_returns_true_for_none_group() -> None:
    """`requested_asset_group=None` always returns True regardless of role."""
    assert has_asset_group_access(None, [], "Developer") is True
    assert has_asset_group_access(None, ["ag-1"], "AppOwner") is True


def test_has_asset_group_access_admin_bypasses_check() -> None:
    """`PlatformAdmin` with any group returns True."""
    assert has_asset_group_access("ag-99", [], "PlatformAdmin") is True
    assert has_asset_group_access("ag-99", ["ag-1"], "PlatformAdmin") is True


def test_has_asset_group_access_security_manager_bypasses_check() -> None:
    """`SecurityManager` with any group returns True."""
    assert has_asset_group_access("ag-99", [], "SecurityManager") is True
    assert has_asset_group_access("ag-99", ["ag-1"], "SecurityManager") is True


def test_has_asset_group_access_non_admin_checks_list_true() -> None:
    """Non-admin with group in permitted list returns True."""
    assert has_asset_group_access("ag-1", ["ag-1", "ag-2"], "Developer") is True


def test_has_asset_group_access_non_admin_checks_list_false() -> None:
    """Non-admin with group not in permitted list returns False."""
    assert has_asset_group_access("ag-99", ["ag-1", "ag-2"], "Developer") is False


def test_has_asset_group_access_non_admin_empty_permitted_returns_false() -> None:
    """Non-admin with empty permitted list returns False."""
    assert has_asset_group_access("ag-1", [], "AppOwner") is False


# ---------------------------------------------------------------------------
# filter_by_asset_group
# ---------------------------------------------------------------------------


def test_filter_by_asset_group_admin_returns_all(fake_issues) -> None:
    """Admin role returns all items unchanged."""
    result = filter_by_asset_group(fake_issues, ["ag-1"], "PlatformAdmin", ["asset_group_id"])
    assert result == fake_issues


def test_filter_by_asset_group_security_manager_returns_all(fake_issues) -> None:
    """SecurityManager role returns all items unchanged."""
    result = filter_by_asset_group(fake_issues, ["ag-1"], "SecurityManager", ["asset_group_id"])
    assert result == fake_issues


def test_filter_by_asset_group_non_admin_filters_correctly(fake_issues) -> None:
    """Non-admin returns only items with matching group IDs."""
    result = filter_by_asset_group(fake_issues, ["ag-1"], "Developer", ["asset_group_id"])
    assert len(result) == 2
    assert all(item["asset_group_id"] == "ag-1" for item in result)


def test_filter_by_asset_group_non_admin_no_match_returns_empty(fake_issues) -> None:
    """Non-admin with no matching groups returns empty list."""
    result = filter_by_asset_group(fake_issues, ["ag-99"], "AppOwner", ["asset_group_id"])
    assert result == []


def test_filter_by_asset_group_handles_list_values() -> None:
    """Item with `asset_group_id` as list is correctly matched."""
    items = [
        {"id": "x-1", "asset_group_id": ["ag-1", "ag-3"]},
        {"id": "x-2", "asset_group_id": ["ag-2"]},
    ]
    result = filter_by_asset_group(items, ["ag-1"], "Developer", ["asset_group_id"])
    assert len(result) == 1
    assert result[0]["id"] == "x-1"


def test_filter_by_asset_group_empty_list() -> None:
    """Empty items list returns empty result."""
    result = filter_by_asset_group([], ["ag-1"], "Developer", ["asset_group_id"])
    assert result == []


def test_filter_by_asset_group_multiple_key_names() -> None:
    """Items matched by any of the provided key names."""
    items = [
        {"id": "a-1", "primary_group": "ag-1", "secondary_group": "ag-3"},
        {"id": "a-2", "primary_group": "ag-2", "secondary_group": "ag-1"},
        {"id": "a-3", "primary_group": "ag-3", "secondary_group": "ag-3"},
    ]
    result = filter_by_asset_group(
        items, ["ag-1"], "Developer", ["primary_group", "secondary_group"]
    )
    assert len(result) == 2
    assert {item["id"] for item in result} == {"a-1", "a-2"}


def test_filter_by_asset_group_item_missing_key_is_excluded() -> None:
    """Items without any of the key names are excluded for non-admin."""
    items = [
        {"id": "b-1", "other_field": "ag-1"},
        {"id": "b-2", "asset_group_id": "ag-1"},
    ]
    result = filter_by_asset_group(items, ["ag-1"], "Developer", ["asset_group_id"])
    assert len(result) == 1
    assert result[0]["id"] == "b-2"


# ---------------------------------------------------------------------------
# ADMIN_ROLES constant
# ---------------------------------------------------------------------------


def test_admin_roles_contains_expected_roles() -> None:
    """ADMIN_ROLES must contain PlatformAdmin and SecurityManager."""
    assert "PlatformAdmin" in ADMIN_ROLES
    assert "SecurityManager" in ADMIN_ROLES


def test_admin_roles_does_not_contain_non_admin_roles() -> None:
    """ADMIN_ROLES must not contain Developer, AppOwner, or Auditor."""
    assert "Developer" not in ADMIN_ROLES
    assert "AppOwner" not in ADMIN_ROLES
    assert "Auditor" not in ADMIN_ROLES
