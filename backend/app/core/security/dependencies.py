from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.core.config.settings import settings
from app.core.security.auth import decode_access_token_async, oidc_is_configured, oidc_missing_fields

bearer_scheme = HTTPBearer(auto_error=True)


@dataclass
class UserContext:
    subject: str
    role: str
    asset_group_ids: list[str]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> UserContext:
    if settings.auth_mode.lower() == "oidc" and not oidc_is_configured():
        missing = ", ".join(oidc_missing_fields()) or "OIDC configuration"
        raise HTTPException(
            status_code=503,
            detail=f"OIDC mode enabled but not configured. Missing: {missing}",
        )

    token = credentials.credentials
    try:
        payload = await decode_access_token_async(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    subject = str(payload.get("sub", ""))
    role_key = settings.oidc_role_claim if settings.auth_mode.lower() == "oidc" else "role"
    asset_groups_key = (
        settings.oidc_asset_groups_claim if settings.auth_mode.lower() == "oidc" else "asset_group_ids"
    )
    role = str(payload.get(role_key, ""))
    asset_group_ids = payload.get(asset_groups_key, [])

    if not subject or not role or not isinstance(asset_group_ids, list):
        raise HTTPException(status_code=401, detail="Invalid token claims")

    normalized_asset_groups = [str(item) for item in asset_group_ids if str(item)]
    return UserContext(subject=subject, role=role, asset_group_ids=normalized_asset_groups)
