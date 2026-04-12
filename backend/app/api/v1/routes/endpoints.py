"""Endpoint management routes — list and health-check configured ASoC endpoints.

GET /api/v1/endpoints        — list all configured endpoints (label + URL only, no credentials)
GET /api/v1/endpoints/status — live connectivity probe for each endpoint (admin-only)
GET /api/v1/endpoints/manage — admin-only full list with api_key (secret masked)
POST /api/v1/endpoints       — add a new endpoint (admin-only)
PUT /api/v1/endpoints/{idx}  — update an endpoint by index (admin-only)
DELETE /api/v1/endpoints/{idx} — remove an endpoint by index (admin-only)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.config.settings import REPO_ROOT, settings
from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.integrations.appscan_api.client import (
    AsocApiClient,
    AsocAuthenticationError,
    AsocAuthorizationError,
    AsocRequestError,
    AsocResponseFormatError,
)

router = APIRouter()

# Lightweight read path used as connectivity probe — available on all ASoC instances.
_PROBE_PATH = "/api/v4/Account/TenantInfo"
# Timeout (seconds) for each connectivity probe.  Long enough for EU/on-prem latency.
_PROBE_TIMEOUT = 15.0

# Regex: must start with https:// followed by a valid hostname
_URL_RE = re.compile(r"^https://[a-zA-Z0-9.\-]+(:\d+)?(/.*)?$")


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class EndpointCreateRequest(BaseModel):
    url: str
    label: str
    api_key: str
    api_secret: str
    verify_ssl: bool = True

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not _URL_RE.match(v):
            raise ValueError("url must start with https:// and contain a valid hostname")
        return v

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label must not be blank")
        return v

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("api_key must not be blank")
        return v


class EndpointUpdateRequest(BaseModel):
    url: str | None = None
    label: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    verify_ssl: bool | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().rstrip("/")
        if not _URL_RE.match(v):
            raise ValueError("url must start with https:// and contain a valid hostname")
        return v


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _env_path() -> Path:
    """Return the primary .env file path (repo root)."""
    return REPO_ROOT / ".env"


def _save_endpoints(endpoints: list[dict[str, str]]) -> None:
    """Persist *endpoints* to ASOC_ENDPOINTS_JSON in .env and update in-memory settings.

    The in-memory update means changes take effect immediately without a restart.
    The .env write ensures the config survives a restart.
    """
    json_val = json.dumps(endpoints, separators=(",", ":"))
    env_file = _env_path()

    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.startswith("ASOC_ENDPOINTS_JSON=") or line.startswith("ASOC_ENDPOINTS_JSON ="):
            new_lines.append(f"ASOC_ENDPOINTS_JSON={json_val}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"ASOC_ENDPOINTS_JSON={json_val}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    # Hot-reload: update the live singleton so the change takes effect immediately.
    settings.asoc_endpoints_json = json_val


def _managed_view(eps: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Return a list safe for the management API — includes api_key, masks secret."""
    return [
        {
            "index": i,
            "url": ep["url"],
            "label": ep["label"],
            "api_key": ep.get("key", ""),
            "has_secret": bool(ep.get("secret")),
            "verify_ssl": ep.get("verify", True),
        }
        for i, ep in enumerate(eps)
    ]


# ---------------------------------------------------------------------------
# Probe helper
# ---------------------------------------------------------------------------

async def _probe_endpoint(ep: dict[str, str]) -> dict[str, Any]:
    """Attempt a lightweight API call to verify endpoint connectivity.

    Returns a dict with keys: url, label, ok, latency_ms, error.
    Credentials are never included in the response.
    """
    verify = ep.get("verify", True)
    client = AsocApiClient.make(ep["url"], ep["key"], ep["secret"], verify=verify)
    start = time.monotonic()
    error: str | None = None
    ok = False
    try:
        async with httpx.AsyncClient(base_url=client.base_url, timeout=_PROBE_TIMEOUT, verify=verify) as http:
            headers = await client._get_auth_header()
            resp = await http.get(_PROBE_PATH, headers=headers)
            if resp.status_code < 300:
                ok = True
            elif resp.status_code in {401, 403}:
                error = f"Authentication rejected (HTTP {resp.status_code})"
            else:
                error = f"Unexpected HTTP {resp.status_code}"
    except (AsocAuthenticationError, AsocAuthorizationError) as exc:
        error = f"Auth error: {exc}"
    except (AsocRequestError, AsocResponseFormatError) as exc:
        error = f"API error: {exc}"
    except httpx.TimeoutException:
        error = f"Connection timed out after {int(_PROBE_TIMEOUT)}s"
    except httpx.ConnectError as exc:
        error = f"Cannot connect: {exc}"
    except Exception as exc:  # noqa: BLE001
        error = f"Probe failed: {exc}"

    elapsed_ms = round((time.monotonic() - start) * 1000)
    return {
        "url": ep["url"],
        "label": ep["label"],
        "ok": ok,
        "latency_ms": elapsed_ms if ok else None,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_endpoints(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return all configured ASoC endpoints (label + URL only — no credentials)."""
    assert_action_allowed("view_endpoints", user.role)
    raw_endpoints = settings.all_asoc_endpoints()
    return {
        "endpoints": [
            {"index": i, "url": ep["url"], "label": ep["label"]}
            for i, ep in enumerate(raw_endpoints)
        ],
        "total": len(raw_endpoints),
    }


@router.get("/manage")
async def manage_list_endpoints(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return all endpoints with api_key visible for editing (secret is masked).

    Restricted to PlatformAdmin and SecurityManager.
    """
    assert_action_allowed("manage_endpoints", user.role)
    raw_endpoints = settings.all_asoc_endpoints()
    return {
        "endpoints": _managed_view(raw_endpoints),
        "total": len(raw_endpoints),
    }


@router.get("/status")
async def endpoint_status(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Probe connectivity for every configured ASoC endpoint (admin-only)."""
    assert_action_allowed("check_endpoint_status", user.role)
    raw_endpoints = settings.all_asoc_endpoints()
    if not raw_endpoints:
        return {"results": [], "total": 0}

    probe_results = await asyncio.gather(
        *[_probe_endpoint(ep) for ep in raw_endpoints],
        return_exceptions=True,
    )

    results: list[dict[str, Any]] = []
    for idx, result in enumerate(probe_results):
        ep = raw_endpoints[idx] if idx < len(raw_endpoints) else {}
        if isinstance(result, BaseException):
            results.append(
                {
                    "url": ep.get("url", "unknown"),
                    "label": ep.get("label", f"endpoint[{idx}]"),
                    "ok": False,
                    "latency_ms": None,
                    "error": str(result),
                }
            )
        else:
            results.append(result)

    return {"results": results, "total": len(results)}


# ---------------------------------------------------------------------------
# Mutation routes
# ---------------------------------------------------------------------------

@router.post("")
async def create_endpoint(
    body: EndpointCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Add a new ASoC endpoint.  Changes take effect immediately (no restart required)."""
    assert_action_allowed("manage_endpoints", user.role)
    eps = list(settings.all_asoc_endpoints())
    eps.append(
        {
            "url": body.url,
            "key": body.api_key,
            "secret": body.api_secret,
            "label": body.label,
            "verify": body.verify_ssl,
        }
    )
    _save_endpoints(eps)
    return {"endpoints": _managed_view(eps), "total": len(eps)}


@router.put("/{idx}")
async def update_endpoint(
    idx: int,
    body: EndpointUpdateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Update an existing endpoint by index.  Changes take effect immediately."""
    assert_action_allowed("manage_endpoints", user.role)
    eps = list(settings.all_asoc_endpoints())
    if idx < 0 or idx >= len(eps):
        raise HTTPException(status_code=404, detail=f"No endpoint at index {idx}")
    ep = dict(eps[idx])
    if body.url is not None:
        ep["url"] = body.url
    if body.label is not None:
        ep["label"] = body.label.strip()
    if body.api_key is not None:
        ep["key"] = body.api_key.strip()
    if body.api_secret is not None:
        ep["secret"] = body.api_secret
    if body.verify_ssl is not None:
        ep["verify"] = body.verify_ssl
    eps[idx] = ep
    _save_endpoints(eps)
    return {"endpoints": _managed_view(eps), "total": len(eps)}


@router.delete("/{idx}")
async def delete_endpoint(
    idx: int,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Remove an endpoint by index.  Changes take effect immediately."""
    assert_action_allowed("manage_endpoints", user.role)
    eps = list(settings.all_asoc_endpoints())
    if idx < 0 or idx >= len(eps):
        raise HTTPException(status_code=404, detail=f"No endpoint at index {idx}")
    eps.pop(idx)
    _save_endpoints(eps)
    return {"endpoints": _managed_view(eps), "total": len(eps)}
