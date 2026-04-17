"""Service layer for data source management.

Handles:
- Bootstrap: import data sources from ``ASOC_ENDPOINTS_JSON`` env var on first
  startup (Option C — env bootstrap, DB override).
- CRUD operations delegating to ``data_source_store``.
- API user info fetching and caching (per-data-source identity).
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config.settings import settings
from app.integrations.appscan_api.client import AsocApiClient
from app.repositories import data_source_store as store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap — import from ASOC_ENDPOINTS_JSON on first startup
# ---------------------------------------------------------------------------

def bootstrap_from_env() -> int:
    """Import endpoints from ``ASOC_ENDPOINTS_JSON`` into the DB if the
    ``data_sources`` table is empty.

    Returns the number of newly imported data sources.
    """
    if store.count_data_sources() > 0:
        logger.debug("data_sources table already populated — skipping env bootstrap.")
        return 0

    env_endpoints = settings.all_asoc_endpoints()
    if not env_endpoints:
        logger.info("No ASoC endpoints configured in env — data_sources table remains empty.")
        return 0

    imported = 0
    for ep in env_endpoints:
        url = str(ep.get("url", "")).rstrip("/")
        key = str(ep.get("key", ""))
        secret = str(ep.get("secret", ""))
        label = str(ep.get("label", url))
        verify = ep.get("verify", True)

        if not url or not key:
            logger.warning("Skipping env endpoint with missing url or key: %s", label)
            continue

        existing = store.get_data_source_by_url_and_key(url, key)
        if existing:
            logger.debug("Data source already exists for %s — skipping.", label)
            continue

        store.create_data_source(
            label=label,
            url=url,
            api_key=key,
            api_secret=secret,
            verify_ssl=bool(verify),
        )
        imported += 1
        logger.info("Imported data source from env: '%s' (%s)", label, url)

    logger.info("Bootstrap complete — imported %d data source(s) from env.", imported)
    return imported


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def list_all(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    """Return data sources from DB.  Falls back to env if DB is empty."""
    rows = store.list_data_sources(include_disabled=include_disabled)
    if rows:
        return rows

    # Fallback: env-based endpoints (Option C behaviour)
    env_endpoints = settings.all_asoc_endpoints()
    return [
        {
            "id": f"env-{idx}",
            "label": str(ep.get("label", ep.get("url", f"endpoint-{idx}"))),
            "url": str(ep.get("url", "")),
            "api_key": str(ep.get("key", "")),
            "api_secret": str(ep.get("secret", "")),
            "verify_ssl": ep.get("verify", True),
            "enabled": True,
            "api_user_name": "",
            "api_user_role": "",
            "api_user_email": "",
            "last_probed_at": None,
            "last_probe_ok": None,
            "created_at": None,
            "updated_at": None,
        }
        for idx, ep in enumerate(env_endpoints)
    ]


def get(ds_id: str) -> dict[str, Any] | None:
    return store.get_data_source(ds_id)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def create(
    *,
    label: str,
    url: str,
    api_key: str,
    api_secret: str,
    verify_ssl: bool = True,
) -> dict[str, Any]:
    return store.create_data_source(
        label=label,
        url=url.rstrip("/"),
        api_key=api_key,
        api_secret=api_secret,
        verify_ssl=verify_ssl,
    )


def update(ds_id: str, **fields: Any) -> dict[str, Any] | None:
    return store.update_data_source(ds_id, **fields)


def delete(ds_id: str) -> bool:
    return store.delete_data_source(ds_id)


# ---------------------------------------------------------------------------
# Per-data-source API user identity
# ---------------------------------------------------------------------------

async def refresh_api_user_info(ds_id: str) -> dict[str, Any] | None:
    """Fetch the API key owner's name and role from ASoC and cache it.

    Queries ``/api/v4/Account/TenantInfo`` and ``/api/v4/User`` on the
    data source's ASoC endpoint, then updates the cached fields in the DB.

    Returns the updated data source row, or ``None`` if the source was not found.
    """
    ds = store.get_data_source(ds_id)
    if not ds:
        return None

    client = AsocApiClient.make(
        ds["url"], ds["api_key"], ds["api_secret"],
        verify=ds.get("verify_ssl", True),
    )

    tenant_name = ""
    user_name = ""
    user_role = ""
    user_email = ""

    try:
        tenant_info = await client.get("/api/v4/Account/TenantInfo")
        if isinstance(tenant_info, dict):
            tenant_name = str(tenant_info.get("TenantName", "")).strip()

            # Extract user identity from TenantInfo.UserInfo (always present
            # for authenticated API keys).  This is more reliable than the
            # separate /api/v4/User/{id} call because ApiKeyLogin does not
            # return a UserId in its response.
            user_info = tenant_info.get("UserInfo")
            if isinstance(user_info, dict):
                first = str(user_info.get("FirstName", "")).strip()
                last = str(user_info.get("LastName", "")).strip()
                user_name = (
                    " ".join(p for p in [first, last] if p)
                    or str(user_info.get("Username", "")).strip()
                )
                user_email = str(user_info.get("Email", "")).strip()
                is_admin = user_info.get("IsAdmin")
                if is_admin is True:
                    user_role = "Administrator"
                elif is_admin is False:
                    user_role = "User"

        # Fallback: if TenantInfo didn't include UserInfo, try the direct
        # /api/v4/User/{id} endpoint (requires owner_user_id from login).
        if not user_name:
            owner_id = client.owner_user_id
            if owner_id:
                try:
                    user_payload = await client.get(f"/api/v4/User/{owner_id}")
                    if isinstance(user_payload, dict):
                        first = str(user_payload.get("FirstName", "")).strip()
                        last = str(user_payload.get("LastName", "")).strip()
                        user_name = " ".join(p for p in [first, last] if p) or str(
                            user_payload.get("UserName", "")
                        ).strip()
                        user_role = user_role or str(user_payload.get("RoleName", "")).strip()
                        user_email = user_email or str(user_payload.get("Email", "")).strip()
                except Exception:
                    logger.debug("Could not fetch user detail for owner_id=%s on ds=%s", owner_id, ds_id)
    except Exception as exc:
        logger.warning("refresh_api_user_info failed for ds=%s: %s", ds_id, exc)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    return store.update_data_source(
        ds_id,
        tenant_name=tenant_name,
        api_user_name=user_name,
        api_user_role=user_role,
        api_user_email=user_email,
        last_probed_at=now,
        last_probe_ok=bool(tenant_name or user_name or user_role),
    )


async def refresh_all_api_user_info() -> list[dict[str, Any]]:
    """Refresh API user info for all enabled data sources (parallel)."""
    import asyncio

    sources = store.list_data_sources(include_disabled=False)
    tasks = [refresh_api_user_info(ds["id"]) for ds in sources]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            results.append(item)
        elif isinstance(item, Exception):
            logger.warning("refresh_all_api_user_info: task failed: %s", item)
    return results


async def refresh_stale_identities(ttl_seconds: int | None = None) -> list[dict[str, Any]]:
    """Refresh only data sources whose identity probe is stale or missing."""
    import asyncio
    from datetime import datetime, timezone, timedelta

    if ttl_seconds is None:
        ttl_seconds = settings.identity_probe_ttl_seconds

    sources = store.list_data_sources(include_disabled=False)
    now = datetime.now(timezone.utc)
    stale_ids: list[str] = []
    for ds in sources:
        probed = ds.get("last_probed_at")
        if not probed:
            stale_ids.append(ds["id"])
            continue
        try:
            probed_dt = datetime.fromisoformat(probed)
            if probed_dt.tzinfo is None:
                probed_dt = probed_dt.replace(tzinfo=timezone.utc)
            if now - probed_dt > timedelta(seconds=ttl_seconds):
                stale_ids.append(ds["id"])
        except (ValueError, TypeError):
            stale_ids.append(ds["id"])

    if not stale_ids:
        return []

    tasks = [refresh_api_user_info(ds_id) for ds_id in stale_ids]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            results.append(item)
        elif isinstance(item, Exception):
            logger.warning("refresh_stale_identities: task failed: %s", item)
    return results


def get_identities() -> list[dict[str, Any]]:
    """Return per-data-source API identity info for the sidebar display.

    Returns a list of dicts with safe-to-display fields only (no credentials).
    """
    sources = store.list_data_sources(include_disabled=False)
    return [
        {
            "id": ds["id"],
            "label": ds["label"],
            "url": ds["url"],
            "tenant_name": ds.get("tenant_name") or None,
            "api_user_name": ds.get("api_user_name") or None,
            "api_user_role": ds.get("api_user_role") or None,
            "api_user_email": ds.get("api_user_email") or None,
            "enabled": ds.get("enabled", True),
            "last_probed_at": ds.get("last_probed_at"),
            "last_probe_ok": ds.get("last_probe_ok"),
        }
        for ds in sources
    ]
