from __future__ import annotations

from fastapi import HTTPException


ADMIN_ROLES = {"PlatformAdmin", "SecurityManager"}


def assert_asset_group_access(requested_asset_group: str, permitted_asset_groups: list[str]) -> None:
    if requested_asset_group not in permitted_asset_groups:
        raise HTTPException(status_code=403, detail="Access denied for asset group")


def assert_role(required_roles: list[str], user_role: str) -> None:
    if user_role not in required_roles:
        raise HTTPException(status_code=403, detail="Insufficient role")


def has_asset_group_access(
    requested_asset_group: str | None,
    permitted_asset_groups: list[str],
    user_role: str,
) -> bool:
    if requested_asset_group is None:
        return True
    if user_role in ADMIN_ROLES:
        return True
    return requested_asset_group in permitted_asset_groups


def filter_by_asset_group(
    items: list[dict],
    permitted_asset_groups: list[str],
    user_role: str,
    key_names: list[str],
) -> list[dict]:
    if user_role in ADMIN_ROLES:
        return items

    allowed = set(permitted_asset_groups)
    filtered: list[dict] = []
    for item in items:
        values: list[str] = []
        for key in key_names:
            raw = item.get(key)
            if raw is None:
                continue
            if isinstance(raw, list):
                values.extend(str(v) for v in raw)
            else:
                values.append(str(raw))

        if any(value in allowed for value in values):
            filtered.append(item)
    return filtered
