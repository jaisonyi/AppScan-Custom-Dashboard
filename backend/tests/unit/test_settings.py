"""Unit tests for app.core.config.settings — Settings/Config module."""
from __future__ import annotations

import json

import pytest

from app.core.config.settings import Settings


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_settings_defaults_are_sane() -> None:
    """Default auth_mode is 'local' and asoc_read_only is True."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.auth_mode == "local"
    assert s.asoc_read_only is True


def test_settings_default_jwt_algorithm() -> None:
    """Default JWT algorithm is HS256."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.jwt_algorithm == "HS256"


def test_settings_default_app_port() -> None:
    """Default app port is 8000."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_port == 8000


def test_settings_default_access_token_expire_minutes() -> None:
    """Default access token expiry is 60 minutes."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.access_token_expire_minutes == 60


def test_settings_default_oidc_fields_are_empty() -> None:
    """Default OIDC fields are empty strings."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.oidc_issuer_url == ""
    assert s.oidc_jwks_url == ""
    assert s.oidc_audience == ""


def test_settings_default_asoc_service_url() -> None:
    """Default ASoC service URL points to cloud.appscan.com."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.asoc_service_url == "https://cloud.appscan.com"


def test_settings_jwt_secret_is_auto_generated() -> None:
    """JWT secret is auto-generated when not provided (non-empty string)."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert isinstance(s.jwt_secret, str)
    assert len(s.jwt_secret) > 0


def test_settings_jwt_secret_can_be_overridden(monkeypatch) -> None:
    """JWT secret can be set via environment variable."""
    monkeypatch.setenv("JWT_SECRET", "my-custom-secret-value")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.jwt_secret == "my-custom-secret-value"


def test_settings_auth_mode_can_be_set_to_oidc(monkeypatch) -> None:
    """auth_mode can be switched to 'oidc' via environment variable."""
    monkeypatch.setenv("AUTH_MODE", "oidc")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.auth_mode == "oidc"


def test_settings_env_var_overrides_default(monkeypatch) -> None:
    """Environment variable overrides default value for app_port."""
    monkeypatch.setenv("APP_PORT", "9090")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_port == 9090


# ---------------------------------------------------------------------------
# all_asoc_endpoints() — empty / no key
# ---------------------------------------------------------------------------


def test_all_asoc_endpoints_returns_empty_when_no_key() -> None:
    """No asoc_api_key returns empty list."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="",
        asoc_endpoints_json="",
    )
    assert s.all_asoc_endpoints() == []


def test_all_asoc_endpoints_returns_empty_when_no_key_and_no_json() -> None:
    """No key and no JSON both absent returns empty list."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="",
        asoc_api_secret="",
        asoc_endpoints_json="",
    )
    result = s.all_asoc_endpoints()
    assert result == []


# ---------------------------------------------------------------------------
# all_asoc_endpoints() — single primary endpoint
# ---------------------------------------------------------------------------


def test_all_asoc_endpoints_returns_primary_when_key_set() -> None:
    """asoc_api_key set returns single-item list with 'Primary' label."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="my-key",
        asoc_api_secret="my-secret",
        asoc_service_url="https://cloud.appscan.com",
        asoc_endpoints_json="",
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 1
    assert result[0]["key"] == "my-key"
    assert result[0]["secret"] == "my-secret"
    assert result[0]["label"] == "Primary"
    assert result[0]["url"] == "https://cloud.appscan.com"


def test_all_asoc_endpoints_primary_strips_trailing_slash() -> None:
    """Primary endpoint URL with trailing slash is stripped."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="my-key",
        asoc_service_url="https://cloud.appscan.com/",
        asoc_endpoints_json="",
    )
    result = s.all_asoc_endpoints()
    assert result[0]["url"] == "https://cloud.appscan.com"


# ---------------------------------------------------------------------------
# all_asoc_endpoints() — JSON array parsing
# ---------------------------------------------------------------------------


def test_all_asoc_endpoints_parses_json_array() -> None:
    """Valid asoc_endpoints_json returns list of endpoint dicts."""
    endpoints = [
        {"url": "https://ep1.example.com", "key": "key1", "secret": "sec1", "label": "EP1"},
        {"url": "https://ep2.example.com", "key": "key2", "secret": "sec2", "label": "EP2"},
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 2
    assert result[0]["url"] == "https://ep1.example.com"
    assert result[0]["key"] == "key1"
    assert result[0]["label"] == "EP1"
    assert result[1]["url"] == "https://ep2.example.com"
    assert result[1]["key"] == "key2"
    assert result[1]["label"] == "EP2"


def test_all_asoc_endpoints_falls_back_on_invalid_json() -> None:
    """Malformed JSON falls back to primary endpoint."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="fallback-key",
        asoc_api_secret="fallback-secret",
        asoc_service_url="https://cloud.appscan.com",
        asoc_endpoints_json="not-valid-json{{{",
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 1
    assert result[0]["key"] == "fallback-key"
    assert result[0]["label"] == "Primary"


def test_all_asoc_endpoints_falls_back_on_empty_json_array() -> None:
    """Empty JSON array falls back to primary endpoint."""
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="fallback-key",
        asoc_endpoints_json="[]",
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 1
    assert result[0]["key"] == "fallback-key"


def test_all_asoc_endpoints_skips_entries_without_url_or_key() -> None:
    """Entries missing 'url' or 'key' are excluded."""
    endpoints = [
        {"url": "https://ep1.example.com", "key": "key1"},  # valid
        {"url": "https://ep2.example.com"},  # missing key — excluded
        {"key": "key3"},  # missing url — excluded
        {"url": "", "key": "key4"},  # empty url — excluded
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 1
    assert result[0]["key"] == "key1"


def test_all_asoc_endpoints_strips_trailing_slash_from_url() -> None:
    """URL with trailing slash is stripped in output."""
    endpoints = [
        {"url": "https://ep1.example.com/", "key": "key1", "label": "EP1"},
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert result[0]["url"] == "https://ep1.example.com"


def test_all_asoc_endpoints_uses_url_as_label_when_label_missing() -> None:
    """No 'label' field uses URL as label."""
    endpoints = [
        {"url": "https://ep1.example.com", "key": "key1"},
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert result[0]["label"] == "https://ep1.example.com"


def test_all_asoc_endpoints_uses_empty_string_for_missing_secret() -> None:
    """Missing 'secret' field defaults to empty string."""
    endpoints = [
        {"url": "https://ep1.example.com", "key": "key1"},
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert result[0]["secret"] == ""


def test_all_asoc_endpoints_json_takes_priority_over_primary() -> None:
    """When valid JSON is set, it takes priority over primary key."""
    endpoints = [
        {"url": "https://json-ep.example.com", "key": "json-key", "label": "JSON"},
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="primary-key",
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 1
    assert result[0]["key"] == "json-key"
    assert result[0]["label"] == "JSON"


def test_all_asoc_endpoints_falls_back_when_all_entries_invalid() -> None:
    """When all JSON entries are invalid, falls back to primary."""
    endpoints = [
        {"url": "", "key": ""},  # both empty — excluded
        {"label": "no-url-or-key"},  # missing url and key — excluded
    ]
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
        asoc_api_key="primary-key",
        asoc_endpoints_json=json.dumps(endpoints),
    )
    result = s.all_asoc_endpoints()
    assert len(result) == 1
    assert result[0]["key"] == "primary-key"
    assert result[0]["label"] == "Primary"
