from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from time import time
from typing import Any

import httpx
from jose import JWTError
from jose import jwt

from app.core.config.settings import settings

_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "keys": []}
_JWKS_TTL_SECONDS = 300
# Async lock prevents concurrent JWKS refreshes from racing each other.
_JWKS_LOCK: asyncio.Lock | None = None


def _get_jwks_lock() -> asyncio.Lock:
    """Return the module-level asyncio.Lock, creating it lazily.

    The lock must be created inside a running event loop, so we defer
    construction until first use rather than at import time.
    """
    global _JWKS_LOCK  # noqa: PLW0603
    if _JWKS_LOCK is None:
        _JWKS_LOCK = asyncio.Lock()
    return _JWKS_LOCK


def oidc_is_configured() -> bool:
    return bool(settings.oidc_issuer_url.strip())


def oidc_missing_fields() -> list[str]:
    missing: list[str] = []
    if not settings.oidc_issuer_url.strip():
        missing.append("OIDC_ISSUER_URL")
    # JWKS can be discovered from issuer, so it is optional.
    # Audience is deployment-specific and can be omitted if tokens do not enforce aud.
    return missing


def create_access_token(subject: str, role: str, asset_group_ids: list[str]) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "asset_group_ids": asset_group_ids,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _fetch_oidc_configuration() -> dict[str, Any]:
    """Fetch the OIDC discovery document asynchronously."""
    issuer = settings.oidc_issuer_url.rstrip("/")
    if not issuer:
        raise JWTError("OIDC issuer URL is not configured")
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        return resp.json()


async def _get_jwks_keys() -> list[dict[str, Any]]:
    """Return JWKS keys, using the cache when still fresh.

    Uses an :class:`asyncio.Lock` to prevent concurrent refreshes from
    issuing duplicate HTTP requests to the JWKS endpoint.
    """
    now = time()
    # Fast path: cache is still valid — no lock needed for a read.
    if _JWKS_CACHE["keys"] and (now - float(_JWKS_CACHE["fetched_at"])) < _JWKS_TTL_SECONDS:
        return _JWKS_CACHE["keys"]

    async with _get_jwks_lock():
        # Re-check inside the lock in case another coroutine already refreshed.
        now = time()
        if _JWKS_CACHE["keys"] and (now - float(_JWKS_CACHE["fetched_at"])) < _JWKS_TTL_SECONDS:
            return _JWKS_CACHE["keys"]

        jwks_url = settings.oidc_jwks_url.strip()
        if not jwks_url:
            oidc_config = await _fetch_oidc_configuration()
            jwks_url = str(oidc_config.get("jwks_uri", "")).strip()
        if not jwks_url:
            raise JWTError("OIDC JWKS URL is not configured")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            payload = resp.json()

        keys = payload.get("keys", []) if isinstance(payload, dict) else []
        if not isinstance(keys, list):
            raise JWTError("Invalid JWKS payload")

        _JWKS_CACHE["fetched_at"] = now
        _JWKS_CACHE["keys"] = keys
        return keys


async def _decode_oidc_token(token: str) -> dict[str, Any]:
    """Decode and verify an OIDC JWT, fetching JWKS asynchronously."""
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    if not kid:
        raise JWTError("OIDC token header missing kid")

    key = None
    for candidate in await _get_jwks_keys():
        if isinstance(candidate, dict) and candidate.get("kid") == kid:
            key = candidate
            break
    if key is None:
        raise JWTError("Unable to find matching JWK for token kid")

    options: dict[str, bool] = {"verify_aud": bool(settings.oidc_audience.strip())}
    audience = settings.oidc_audience.strip() or None
    issuer = settings.oidc_issuer_url.rstrip("/") or None

    return jwt.decode(
        token,
        key,
        algorithms=[alg],
        audience=audience,
        issuer=issuer,
        options=options,
    )


async def decode_access_token_async(token: str) -> dict[str, Any]:
    """Async variant of :func:`decode_access_token` for use in async request handlers."""
    if settings.auth_mode.lower() == "oidc":
        return await _decode_oidc_token(token)
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def decode_access_token(token: str) -> dict[str, Any]:
    """Synchronous token decode (non-OIDC path only).

    For OIDC mode, callers inside an async context should use
    :func:`decode_access_token_async` to avoid blocking the event loop.
    """
    if settings.auth_mode.lower() == "oidc":
        # Fall back to running the async path in a new event loop when called
        # from a synchronous context (e.g., tests, CLI tools).
        return asyncio.run(_decode_oidc_token(token))
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
