from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse, urlunparse

from datetime import datetime, timezone
import httpx

from app.core.config.settings import settings

_logger = logging.getLogger(__name__)

# Only allow read operations and API-key login for bearer token retrieval.
_ALLOWED_METHODS = {"GET", "POST"}
_READ_ONLY_GET_PATH_PREFIXES = (
    "/api/v4/Scans",
    "/api/v4/Apps",
    "/api/v4/AssetGroups",
    "/api/v4/Issues",
    "/api/v4/Reports",
    "/api/v4/Account",
    "/api/v4/User",
    "/api/v4/Roles",
)
_AUTH_LOGIN_PATH = "/api/v4/Account/ApiKeyLogin"
_MAX_429_RETRIES = 3
_BASE_429_BACKOFF_SECONDS = 0.5
_MAX_429_BACKOFF_SECONDS = 5.0


class AsocAuthenticationError(RuntimeError):
    pass


class AsocAuthorizationError(RuntimeError):
    pass


class AsocRequestError(RuntimeError):
    pass


def _parse_asoc_expiry(raw_value: Any) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _asoc_key_pair_header(key_id: str, key_secret: str) -> str:
    return f"{key_id}:{key_secret}"


def _is_expired(dt: datetime | None) -> bool:
    if dt is None:
        return True
    return dt <= datetime.now(timezone.utc)


def _build_auth_headers(token: str | None, key_id: str, key_secret: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers
    headers["X-API-KEY"] = _asoc_key_pair_header(key_id, key_secret)
    return headers


def _is_json_response(content_type: str) -> bool:
    return "application/json" in (content_type or "").lower()


def _extract_token(payload: dict[str, Any]) -> str:
    token = payload.get("Token") or payload.get("token") or payload.get("access_token")
    if not token:
        raise AsocAuthenticationError("ASoC API key login succeeded but no access token was returned.")
    return str(token)


def _parse_retry_after_seconds(raw_value: str | None) -> float | None:
    if not raw_value:
        return None
    try:
        parsed = float(raw_value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return min(parsed, _MAX_429_BACKOFF_SECONDS)


class ReadOnlyViolationError(RuntimeError):
    pass


class AsocResponseFormatError(RuntimeError):
    pass


class AsocApiClient:
    def __init__(self) -> None:
        self.base_url = self._normalize_service_url(settings.asoc_service_url)
        self.api_key = settings.asoc_api_key
        self.api_secret = settings.asoc_api_secret
        self.read_only = settings.asoc_read_only
        self._verify: bool | str = settings.asoc_verify_ssl
        self._access_token: str | None = None
        self._access_token_expiry: datetime | None = None
        self._owner_user_id: str | None = None
        self._login_succeeded: bool | None = None
        if not self._verify:
            _logger.warning(
                "[ASoC] SSL certificate verification is DISABLED for %s. "
                "This removes protection against man-in-the-middle attacks.",
                self.base_url,
            )

    @classmethod
    def make(cls, url: str, key: str, secret: str, verify: bool | str = True) -> "AsocApiClient":
        """Construct a client with explicit credentials (multi-endpoint support).

        Unlike the default ``__init__`` which reads from global settings, this
        factory accepts explicit endpoint parameters so callers can build a
        client for any of the configured ASoC endpoints without mutating
        module-level state.
        """
        instance = cls.__new__(cls)
        instance.base_url = cls._normalize_service_url(url)
        instance.api_key = key
        instance.api_secret = secret
        instance.read_only = settings.asoc_read_only
        instance._verify = verify
        instance._access_token = None
        instance._access_token_expiry = None
        instance._owner_user_id = None
        instance._login_succeeded = None
        if not verify:
            _logger.warning(
                "[ASoC] SSL certificate verification is DISABLED for %s. "
                "This removes protection against man-in-the-middle attacks.",
                instance.base_url,
            )
        return instance

    @property
    def owner_user_id(self) -> str | None:
        """Return the ASoC UserId of the API key owner, populated after first login."""
        return self._owner_user_id

    @property
    def login_succeeded(self) -> bool | None:
        """Return whether the last bearer token login attempt succeeded."""
        return self._login_succeeded

    @staticmethod
    def _normalize_service_url(raw_url: str) -> str:
        """Normalize AppScan EU legacy URL to the effective host.

        Legacy input `https://cloud.appscan.com/eu` should resolve to
        `https://eu.cloud.appscan.com` so API paths become
        `https://eu.cloud.appscan.com/api/v4/...`.
        """
        candidate = str(raw_url or "").strip()
        if not candidate:
            return "https://cloud.appscan.com"

        parsed = urlparse(candidate)
        if not parsed.scheme:
            parsed = urlparse(f"https://{candidate}")

        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").strip("/").lower()
        if host == "cloud.appscan.com" and path == "eu":
            parsed = parsed._replace(netloc="eu.cloud.appscan.com", path="", params="", query="", fragment="")

        normalized = urlunparse(parsed).rstrip("/")
        return normalized or "https://cloud.appscan.com"

    def _validate_request(self, method: str, path: str) -> None:
        if not self.read_only:
            return
        method_upper = method.upper()
        if method_upper not in _ALLOWED_METHODS:
            raise ReadOnlyViolationError(f"Blocked method in read-only mode: {method_upper}")

        # Read-only mode allows auth token retrieval from API key login.
        if method_upper == "POST" and path == _AUTH_LOGIN_PATH:
            return

        if method_upper != "GET":
            raise ReadOnlyViolationError(f"Blocked non-read method: {method_upper}")

        if not path.startswith(_READ_ONLY_GET_PATH_PREFIXES):
            raise ReadOnlyViolationError(f"Blocked endpoint not in read allow-list: {path}")

    async def _login_with_api_key(self) -> str:
        self._validate_request("POST", _AUTH_LOGIN_PATH)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-KEY": _asoc_key_pair_header(self.api_key, self.api_secret),
        }
        body = {"KeyId": self.api_key, "KeySecret": self.api_secret}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20.0, verify=self._verify) as client:
            resp = await client.post(_AUTH_LOGIN_PATH, headers=headers, json=body)
            if resp.status_code in {401, 403}:
                raise AsocAuthenticationError("ASoC rejected API key login (401/403).")
            if resp.status_code >= 400:
                raise AsocRequestError(f"ASoC API key login failed with status {resp.status_code}.")
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type.lower():
                raise AsocResponseFormatError(
                    "ASoC API key login returned non-JSON response content."
                )
            payload = resp.json()
            if not isinstance(payload, dict):
                raise AsocResponseFormatError("ASoC API key login returned unexpected payload shape.")
            token = _extract_token(payload)
            self._access_token = token
            self._access_token_expiry = _parse_asoc_expiry(payload.get("Expire") or payload.get("expire"))
            # Capture the API key owner's UserId for direct user lookup
            raw_uid = payload.get("UserId") or payload.get("userId") or payload.get("user_id")
            if raw_uid:
                self._owner_user_id = str(raw_uid).strip()
            self._login_succeeded = True
            return token

    async def _get_auth_header(self) -> dict[str, str]:
        # Prefer bearer token flow from Swagger Account/ApiKeyLogin and fallback to X-API-KEY.
        token = self._access_token
        if token and not _is_expired(self._access_token_expiry):
            return _build_auth_headers(token, self.api_key, self.api_secret)
        try:
            token = await self._login_with_api_key()
            return _build_auth_headers(token, self.api_key, self.api_secret)
        except Exception as _login_exc:
            self._login_succeeded = False
            _logger.warning(
                "[ASoC] Bearer token login failed for %s (%s: %s) — falling back to X-API-KEY header",
                self.base_url,
                type(_login_exc).__name__,
                _login_exc,
            )
            return _build_auth_headers(None, self.api_key, self.api_secret)

    def _fallback_headers(self, current_headers: dict[str, str]) -> dict[str, str] | None:
        # Allow one auth-mode switch retry to maximize compatibility with v4 auth behavior.
        if current_headers.get("Authorization"):
            return _build_auth_headers(None, self.api_key, self.api_secret)
        return None

    async def _get_with_429_retry(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> httpx.Response:
        response = await client.get(path, params=params, headers=headers)
        retry_index = 0
        while response.status_code == 429 and retry_index < _MAX_429_RETRIES:
            retry_after = _parse_retry_after_seconds(response.headers.get("Retry-After"))
            delay_seconds = retry_after or min(
                _MAX_429_BACKOFF_SECONDS,
                _BASE_429_BACKOFF_SECONDS * (2 ** retry_index),
            )
            _logger.warning(
                "[ASoC] Rate limited (429) for path %s; retrying in %.2fs (%d/%d)",
                path,
                delay_seconds,
                retry_index + 1,
                _MAX_429_RETRIES,
            )
            await asyncio.sleep(delay_seconds)
            retry_index += 1
            response = await client.get(path, params=params, headers=headers)
        return response

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._validate_request("GET", path)
        headers = await self._get_auth_header()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20.0, verify=self._verify) as client:
            resp = await self._get_with_429_retry(client, path, params=params, headers=headers)

            # Retry once with a refreshed bearer token on auth failure.
            if resp.status_code in {401, 403} and not headers.get("Authorization"):
                self._access_token = None
                self._access_token_expiry = None
                headers = await self._get_auth_header()
                resp = await self._get_with_429_retry(client, path, params=params, headers=headers)

            # If response is unauthorized or non-JSON, retry once by switching auth mode.
            content_type = resp.headers.get("content-type", "")
            if resp.status_code in {401, 403} or not _is_json_response(content_type):
                fallback_headers = self._fallback_headers(headers)
                if fallback_headers is not None:
                    resp = await self._get_with_429_retry(client, path, params=params, headers=fallback_headers)
                    headers = fallback_headers
                    content_type = resp.headers.get("content-type", "")

            if resp.status_code in {401, 403}:
                raise AsocAuthorizationError(f"ASoC request unauthorized for path: {path}")
            resp.raise_for_status()
            if not _is_json_response(content_type):
                raise AsocResponseFormatError(
                    f"Expected JSON from ASoC, got content-type: {content_type or 'unknown'}"
                )
            payload = resp.json()
            if isinstance(payload, dict):
                return payload
            # Keep interface stable for callers expecting dict payloads.
            return {"Items": payload}

    async def get_count(self, path: str, *, params: dict[str, Any] | None = None) -> int:
        """Call a /Count endpoint and return the integer result.

        AppScan /Count endpoints return a bare integer (not a JSON object).
        This method handles both integer and dict responses and falls back to 0
        on any error.  Uses the same path validation as get() to respect
        read-only mode.
        """
        self._validate_request("GET", path)
        headers = await self._get_auth_header()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=settings.asoc_count_timeout_seconds, verify=self._verify) as client:
            resp = await self._get_with_429_retry(client, path, params=params, headers=headers)

            # Retry once with a refreshed bearer token on auth failure.
            if resp.status_code in {401, 403} and not headers.get("Authorization"):
                self._access_token = None
                self._access_token_expiry = None
                headers = await self._get_auth_header()
                resp = await self._get_with_429_retry(client, path, params=params, headers=headers)

            # Retry once by switching auth mode on persistent auth failure or non-JSON.
            content_type = resp.headers.get("content-type", "")
            if resp.status_code in {401, 403} or not (
                _is_json_response(content_type) or resp.text.strip().lstrip("-").isdigit()
            ):
                fallback_headers = self._fallback_headers(headers)
                if fallback_headers is not None:
                    resp = await self._get_with_429_retry(client, path, params=params, headers=fallback_headers)
                    content_type = resp.headers.get("content-type", "")

            if resp.status_code in {401, 403}:
                raise AsocAuthorizationError(f"ASoC request unauthorized for path: {path}")
            resp.raise_for_status()

            # /Count endpoints return a bare integer string or a JSON dict.
            body = resp.text.strip()
            try:
                return int(body)
            except ValueError:
                pass
            # Some endpoints wrap the count: {"Count": 12345}
            try:
                payload = resp.json()
            except Exception:
                return 0
            if isinstance(payload, dict):
                for key in ("Count", "count", "TotalCount", "totalCount", "total", "Total"):
                    if key in payload:
                        try:
                            return int(payload[key])
                        except (TypeError, ValueError):
                            pass
            return 0

    async def get_with_count(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], int | None]:
        """GET a paginated endpoint with $inlinecount=allpages.

        Returns (items, total_count).  total_count is None when the API does
        not return an inlinecount field.  Uses the same path validation and
        auth retry logic as get().
        """
        merged_params = dict(params or {})
        merged_params["$inlinecount"] = "allpages"
        payload = await self.get(path, params=merged_params)
        # Extract items using the same key priority as _extract_items() in the service layer.
        items: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            for key in ("Items", "items", "value", "data"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    items = [item for item in candidate if isinstance(item, dict)]
                    break
        elif isinstance(payload, list):
            items = [item for item in payload if isinstance(item, dict)]
        # Extract total count from the inlinecount field.
        total: int | None = None
        if isinstance(payload, dict):
            for key in ("Count", "count", "TotalCount", "totalCount"):
                if key in payload:
                    try:
                        total = int(payload[key])
                    except (TypeError, ValueError):
                        pass
                    break
        return items, total
