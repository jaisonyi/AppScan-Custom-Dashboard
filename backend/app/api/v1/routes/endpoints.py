"""Data-source management routes — list, CRUD, and health-check configured ASoC data sources.

GET    /api/v1/endpoints              — list all data sources (label + URL only, no credentials)
GET    /api/v1/endpoints/status       — live connectivity probe for each data source (admin-only)
GET    /api/v1/endpoints/manage       — admin-only full list with api_key (secret masked)
GET    /api/v1/endpoints/identities   — per-source API user info for the sidebar
POST   /api/v1/endpoints/refresh-identities — refresh cached API user info from ASoC
POST   /api/v1/endpoints              — add a new data source (admin-only)
PUT    /api/v1/endpoints/{ds_id}      — update a data source by ID (admin-only)
DELETE /api/v1/endpoints/{ds_id}      — remove a data source by ID (admin-only)
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.security.dependencies import UserContext, get_current_user
from app.core.security.policy import assert_action_allowed
from app.integrations.appscan_api.client import (
    AsocApiClient,
    AsocAuthenticationError,
    AsocAuthorizationError,
    AsocRequestError,
    AsocResponseFormatError,
)
from app.repositories import data_source_store
from app.services import data_source_service

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
    enabled: bool | None = None

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
# View helpers
# ---------------------------------------------------------------------------

def _managed_view(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a list safe for the management API — includes api_key, masks secret."""
    return [
        {
            "id": ds.get("id", ""),
            "url": ds.get("url", ""),
            "label": ds.get("label", ""),
            "api_key": ds.get("api_key", ""),
            "has_secret": bool(ds.get("api_secret")),
            "verify_ssl": ds.get("verify_ssl", True),
            "enabled": ds.get("enabled", True),
        }
        for ds in sources
    ]


# ---------------------------------------------------------------------------
# Probe helper
# ---------------------------------------------------------------------------

async def _probe_data_source(ds: dict[str, Any]) -> dict[str, Any]:
    """Attempt a lightweight API call to verify data source connectivity.

    Returns a dict with keys: id, url, label, ok, latency_ms, error.
    Credentials are never included in the response.
    """
    verify = ds.get("verify_ssl", True)
    client = AsocApiClient.make(ds["url"], ds["api_key"], ds["api_secret"], verify=verify)
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
        "id": ds.get("id", ""),
        "url": ds["url"],
        "label": ds.get("label", ""),
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
    """Return all configured ASoC data sources (label + URL only — no credentials)."""
    assert_action_allowed("view_endpoints", user.role)
    sources = data_source_service.list_all(include_disabled=False)
    return {
        "endpoints": [
            {"id": ds["id"], "url": ds["url"], "label": ds["label"]}
            for ds in sources
        ],
        "total": len(sources),
    }


@router.get("/manage")
async def manage_list_endpoints(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return all data sources with api_key visible for editing (secret is masked).

    Restricted to PlatformAdmin and SecurityManager.
    """
    assert_action_allowed("manage_endpoints", user.role)
    sources = data_source_service.list_all(include_disabled=True)
    return {
        "endpoints": _managed_view(sources),
        "total": len(sources),
    }


@router.get("/status")
async def endpoint_status(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Probe connectivity for every configured ASoC data source (admin-only)."""
    assert_action_allowed("check_endpoint_status", user.role)
    sources = data_source_service.list_all(include_disabled=False)
    if not sources:
        return {"results": [], "total": 0}

    probe_results = await asyncio.gather(
        *[_probe_data_source(ds) for ds in sources],
        return_exceptions=True,
    )

    results: list[dict[str, Any]] = []
    for idx, result in enumerate(probe_results):
        ds = sources[idx] if idx < len(sources) else {}
        if isinstance(result, BaseException):
            results.append(
                {
                    "id": ds.get("id", ""),
                    "url": ds.get("url", "unknown"),
                    "label": ds.get("label", f"source[{idx}]"),
                    "ok": False,
                    "latency_ms": None,
                    "error": str(result),
                }
            )
        else:
            results.append(result)

    return {"results": results, "total": len(results)}


@router.get("/identities")
async def list_identities(
    user: Annotated[UserContext, Depends(get_current_user)],
    auto_refresh_stale: bool = False,
) -> dict[str, Any]:
    """Return per-data-source API user info for the sidebar identity pane."""
    assert_action_allowed("view_endpoints", user.role)
    if auto_refresh_stale:
        await data_source_service.refresh_stale_identities()
    identities = data_source_service.get_identities()
    return {"identities": identities, "total": len(identities)}


@router.post("/refresh-identities")
async def refresh_identities(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Refresh cached API user info from ASoC for all enabled data sources."""
    assert_action_allowed("manage_endpoints", user.role)
    await data_source_service.refresh_all_api_user_info()
    identities = data_source_service.get_identities()
    return {"identities": identities, "total": len(identities)}


# ---------------------------------------------------------------------------
# Mutation routes
# ---------------------------------------------------------------------------

@router.post("")
async def create_endpoint(
    body: EndpointCreateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Add a new ASoC data source.  Changes take effect immediately (no restart required)."""
    assert_action_allowed("manage_endpoints", user.role)
    data_source_service.create(
        label=body.label,
        url=body.url,
        api_key=body.api_key,
        api_secret=body.api_secret,
        verify_ssl=body.verify_ssl,
    )
    sources = data_source_service.list_all(include_disabled=True)
    return {"endpoints": _managed_view(sources), "total": len(sources)}


@router.put("/{ds_id}")
async def update_endpoint(
    ds_id: str,
    body: EndpointUpdateRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Update an existing data source by ID.  Changes take effect immediately."""
    assert_action_allowed("manage_endpoints", user.role)
    existing = data_source_store.get_data_source(ds_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No data source with id {ds_id!r}")
    fields: dict[str, Any] = {}
    if body.url is not None:
        fields["url"] = body.url
    if body.label is not None:
        fields["label"] = body.label.strip()
    if body.api_key is not None:
        fields["api_key"] = body.api_key.strip()
    if body.api_secret is not None:
        fields["api_secret"] = body.api_secret
    if body.verify_ssl is not None:
        fields["verify_ssl"] = body.verify_ssl
    if body.enabled is not None:
        fields["enabled"] = body.enabled
    if fields:
        data_source_store.update_data_source(ds_id, **fields)
    sources = data_source_service.list_all(include_disabled=True)
    return {"endpoints": _managed_view(sources), "total": len(sources)}


@router.delete("/{ds_id}")
async def delete_endpoint(
    ds_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Remove a data source by ID.  Changes take effect immediately."""
    assert_action_allowed("manage_endpoints", user.role)
    existing = data_source_store.get_data_source(ds_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No data source with id {ds_id!r}")
    data_source_store.delete_data_source(ds_id)
    sources = data_source_service.list_all(include_disabled=True)
    return {"endpoints": _managed_view(sources), "total": len(sources)}
