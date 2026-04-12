from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config.settings import settings
from app.core.security.auth import create_access_token, oidc_is_configured, oidc_missing_fields
from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import ROLE_ACTION_POLICY
from app.integrations.appscan_api.client import AsocApiClient

router = APIRouter()

_ALLOWED_ROLES: frozenset[str] = frozenset(
    role for roles in ROLE_ACTION_POLICY.values() for role in roles
)


class LoginRequest(BaseModel):
    username: str
    role: str = "SecurityManager"
    asset_group_ids: list[str] = Field(default_factory=lambda: ["ag-1"])


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("Items", "items", "value", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        # Some tenants may return a single user object instead of an Items list.
        if any(field in payload for field in ("UserName", "Email", "Id", "RoleName", "RoleId")):
            return [payload]
    return []


def _pick_user(items: list[dict[str, Any]], subject: str) -> Optional[dict[str, Any]]:
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    subject_norm = subject.strip().lower()
    if subject_norm:
        for item in items:
            candidates = [
                str(item.get("UserName", "")).strip().lower(),
                str(item.get("Email", "")).strip().lower(),
                str(item.get("Name", "")).strip().lower(),
            ]
            if subject_norm in candidates:
                return item
    return None


def _display_name(item: dict[str, Any], subject: str) -> str:
    first_name = str(item.get("FirstName", "")).strip()
    last_name = str(item.get("LastName", "")).strip()
    joined = " ".join(part for part in [first_name, last_name] if part).strip()
    if joined:
        return joined
    for key in ("Name", "UserName", "Email"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return subject


async def _load_user_catalog(client: AsocApiClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    page_size = 200
    max_items = 5000

    for skip in range(0, max_items, page_size):
        payload = await client.get("/api/v4/User", params={"$top": page_size, "$skip": skip})
        page = _extract_items(payload)
        if not page:
            break

        for item in page:
            key = (
                str(item.get("Id", "")).strip()
                or str(item.get("UserName", "")).strip().lower()
                or str(item.get("Email", "")).strip().lower()
            )
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            items.append(item)

        if len(page) < page_size:
            break

    return items


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, str]:
    if settings.auth_mode.lower() == "oidc":
        raise HTTPException(
            status_code=405,
            detail="Local login is disabled. Use enterprise OIDC sign-in and pass bearer token.",
        )
    if payload.role not in _ALLOWED_ROLES:
        valid_roles = sorted(_ALLOWED_ROLES)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{payload.role}'. Valid roles are: {', '.join(valid_roles)}",
        )
    token = create_access_token(payload.username, payload.role, payload.asset_group_ids)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/mode")
def auth_mode() -> dict[str, object]:
    mode = settings.auth_mode.lower()
    return {
        "auth_mode": mode,
        "oidc_configured": oidc_is_configured(),
        "oidc_missing_fields": oidc_missing_fields() if mode == "oidc" else [],
    }


@router.get("/current-user")
async def current_user_profile(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "source": "local",
        "subject": user.subject,
        "display_name": user.subject,
        "first_name": "",
        "last_name": "",
        "username": user.subject,
        "email": "",
        "role": user.role,
        "role_id": "",
        "organization_name": "",
        "tenant_name": "",
        "tenant_id": "",
        "tenant_region": "",
        "asset_group_ids": user.asset_group_ids,
        "asoc_endpoint": "",
    }

    if not settings.asoc_api_key or not settings.asoc_api_secret:
        return profile

    client = AsocApiClient()
    try:
        try:
            tenant_payload = await client.get("/api/v4/Account/TenantInfo")
            if isinstance(tenant_payload, dict):
                org_name = str(
                    tenant_payload.get("TenantName")
                    or tenant_payload.get("Name")
                    or ""
                ).strip()
                profile.update(
                    {
                        "organization_name": org_name,
                        "tenant_name": org_name,
                        "tenant_id": str(
                            tenant_payload.get("TenantId")
                            or tenant_payload.get("Id")
                            or ""
                        ).strip(),
                        "tenant_region": str(
                            tenant_payload.get("Region")
                            or tenant_payload.get("Geo")
                            or ""
                        ).strip(),
                    }
                )
        except Exception:
            profile["tenant_info_error"] = "tenant_info_unavailable"

        # Fast path: use the API key owner's UserId from the login response
        # (populated after the implicit login inside AsocApiClient._get_auth_header).
        # We trigger authentication by calling TenantInfo above; owner_user_id will be
        # populated if the login response included a UserId field.
        picked: dict[str, Any] | None = None

        owner_id = client.owner_user_id
        if owner_id:
            try:
                user_payload = await client.get(f"/api/v4/User/{owner_id}")
                # Single-user response may be the dict itself or wrapped in Items
                if isinstance(user_payload, dict):
                    items_direct = _extract_items(user_payload)
                    picked = items_direct[0] if items_direct else (
                        user_payload if any(
                            f in user_payload for f in ("UserName", "Email", "FirstName", "LastName")
                        ) else None
                    )
            except Exception:
                pass  # Fall through to catalog lookup below

        if picked is None:
            # Slow path: paginate all users and match by username/email
            items = await _load_user_catalog(client)
            if not items:
                raw_payload = await client.get("/api/v4/User", params={"$top": 500})
                items = _extract_items(raw_payload)
            picked = _pick_user(items, user.subject)

        if picked:
            first_name = str(picked.get("FirstName", "")).strip()
            last_name = str(picked.get("LastName", "")).strip()
            profile.update(
                {
                    "source": "asoc",
                    "asoc_endpoint": "/api/v4/User,/api/v4/Account/TenantInfo",
                    "first_name": first_name,
                    "last_name": last_name,
                    "display_name": _display_name(picked, user.subject),
                    "username": str(picked.get("UserName", "")).strip() or user.subject,
                    "email": str(picked.get("Email", "")).strip(),
                    "role": str(picked.get("RoleName", "")).strip() or user.role,
                    "role_id": str(picked.get("RoleId", "")).strip(),
                    "asoc_user_id": str(picked.get("Id", "")).strip(),
                }
            )
    except Exception:
        # Keep dashboard functional even when ASoC profile lookup is unavailable.
        profile["asoc_profile_error"] = "profile_lookup_unavailable"

    return profile
