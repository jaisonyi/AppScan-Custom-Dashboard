from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = Path(__file__).resolve().parents[3]

_JWT_SECRET_DEFAULT = secrets.token_urlsafe(32)


class Settings(BaseSettings):
    app_env: str = "development"
    app_port: int = 8000
    frontend_origin: str = "http://localhost:5173"

    jwt_secret: str = _JWT_SECRET_DEFAULT
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    auth_mode: str = "local"
    oidc_issuer_url: str = ""
    oidc_jwks_url: str = ""
    oidc_audience: str = ""
    oidc_role_claim: str = "role"
    oidc_asset_groups_claim: str = "asset_group_ids"

    asoc_service_url: str = "https://cloud.appscan.com"
    asoc_api_key: str = ""
    asoc_api_secret: str = ""
    # JSON array of all configured endpoints (set by installer for multi-endpoint deployments).
    # Format: [{"url": "https://...", "key": "...", "secret": "...", "label": "...", "verify": true}]
    # If empty, falls back to the primary asoc_service_url / asoc_api_key / asoc_api_secret.
    asoc_endpoints_json: str = ""
    asoc_read_only: bool = True
    # Set to False ONLY for on-premises instances with self-signed / private-CA certificates.
    # WARNING: disabling SSL verification removes man-in-the-middle attack protection.
    # Per-endpoint override: add "verify": false to an entry in ASOC_ENDPOINTS_JSON.
    asoc_verify_ssl: bool = True
    asoc_page_size: int = 1000          # API maximum; 5× fewer requests than 200
    asoc_max_pages: int = 5000          # covers up to 5,000,000 items
    asoc_issue_max_pages_per_app: int = 1000  # covers 1,000,000 per app
    asoc_issue_app_concurrency: int = 8
    # Count-first strategy — uses /Count endpoints for accurate KPIs
    asoc_use_count_endpoints: bool = True   # set False to revert to pagination-derived counts
    asoc_count_concurrency: int = 9         # parallel /Count requests
    asoc_count_timeout_seconds: float = 10.0
    asoc_top_apps_chart_limit: int = 50     # top-N apps in bar chart
    analytics_scan_severity_source: str = "hybrid"
    analytics_cache_ttl_seconds: int = 3600
    analytics_cache_cleanup_interval_seconds: int = 600
    analytics_prewarm_enabled: bool = True
    analytics_prewarm_interval_seconds: int = 1800
    identity_probe_ttl_seconds: int = 86400

    report_scheduler_enabled: bool = True
    report_scheduler_interval_seconds: int = 30
    report_scheduler_max_retries: int = 5
    report_scheduler_backoff_base_seconds: int = 60
    report_scheduler_backoff_max_seconds: int = 3600
    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/aspm"

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def all_asoc_endpoints(self) -> list[dict[str, str]]:
        """Return all configured ASoC endpoints.

        Parses ``ASOC_ENDPOINTS_JSON`` when set; falls back to the single
        primary endpoint (``asoc_service_url`` / ``asoc_api_key`` /
        ``asoc_api_secret``) when the JSON field is absent or unparseable.

        Each entry is a dict with keys ``url``, ``key``, ``secret``, ``label``.
        """
        raw = (self.asoc_endpoints_json or "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    cleaned: list[dict[str, str]] = []
                    for item in parsed:
                        if isinstance(item, dict) and item.get("url") and item.get("key"):
                            # Per-entry verify: explicit bool overrides global default;
                            # absent / non-bool fields fall back to asoc_verify_ssl.
                            raw_verify = item.get("verify")
                            ep_verify: bool = (
                                bool(raw_verify)
                                if isinstance(raw_verify, bool)
                                else self.asoc_verify_ssl
                            )
                            cleaned.append(
                                {
                                    "url": str(item["url"]).rstrip("/"),
                                    "key": str(item["key"]),
                                    "secret": str(item.get("secret", "")),
                                    "label": str(item.get("label", item["url"])),
                                    "verify": ep_verify,
                                }
                            )
                    if cleaned:
                        return cleaned
            except (json.JSONDecodeError, TypeError):
                pass
        # Fallback: single primary endpoint
        if self.asoc_api_key:
            return [
                {
                    "url": self.asoc_service_url.rstrip("/"),
                    "key": self.asoc_api_key,
                    "secret": self.asoc_api_secret,
                    "label": "Primary",
                    "verify": self.asoc_verify_ssl,
                }
            ]
        return []


settings = Settings()

if not os.environ.get("JWT_SECRET"):
    logger.warning(
        "JWT_SECRET is not set in the environment. A random secret has been generated for this "
        "process startup. All existing tokens will be invalidated on restart. Set JWT_SECRET in "
        "your .env file or environment to use a stable secret."
    )
