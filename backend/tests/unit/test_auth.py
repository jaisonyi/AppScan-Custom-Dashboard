"""Unit tests for app.core.security.auth — JWT creation, decoding, and OIDC."""
from __future__ import annotations

import asyncio
from time import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import JWTError, jwt

import app.core.security.auth as auth_module
from app.core.config.settings import settings
from app.core.security.auth import (
    _JWKS_TTL_SECONDS,
    create_access_token,
    decode_access_token,
    decode_access_token_async,
    oidc_is_configured,
    oidc_missing_fields,
)

_TEST_SECRET = "test-secret-32-chars-minimum-len!"
_TEST_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_local_settings(monkeypatch, expire_minutes: int = 60) -> None:
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "jwt_secret", _TEST_SECRET)
    monkeypatch.setattr(settings, "jwt_algorithm", _TEST_ALGORITHM)
    monkeypatch.setattr(settings, "access_token_expire_minutes", expire_minutes)


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


def test_create_access_token_returns_decodable_jwt(monkeypatch) -> None:
    """Token created with create_access_token() decodes to correct claims."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("alice", "PlatformAdmin", ["ag-1"])
    payload = jwt.decode(token, _TEST_SECRET, algorithms=[_TEST_ALGORITHM])
    assert payload["sub"] == "alice"


def test_create_access_token_contains_sub_role_asset_groups(monkeypatch) -> None:
    """Decoded payload has sub, role, asset_group_ids."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("bob", "SecurityManager", ["ag-1", "ag-2"])
    payload = jwt.decode(token, _TEST_SECRET, algorithms=[_TEST_ALGORITHM])
    assert payload["sub"] == "bob"
    assert payload["role"] == "SecurityManager"
    assert payload["asset_group_ids"] == ["ag-1", "ag-2"]


def test_create_access_token_expires_in_configured_minutes(monkeypatch) -> None:
    """`exp` claim is within expected window (now + configured minutes)."""
    _patch_local_settings(monkeypatch, expire_minutes=30)
    before = time()
    token = create_access_token("charlie", "Developer", [])
    after = time()
    payload = jwt.decode(token, _TEST_SECRET, algorithms=[_TEST_ALGORITHM])
    exp = payload["exp"]
    # exp should be approximately now + 30 minutes (1800 seconds)
    assert before + 1799 <= exp <= after + 1801


def test_create_access_token_with_empty_asset_groups(monkeypatch) -> None:
    """Token with empty asset_group_ids encodes correctly."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("dave", "Auditor", [])
    payload = jwt.decode(token, _TEST_SECRET, algorithms=[_TEST_ALGORITHM])
    assert payload["asset_group_ids"] == []


# ---------------------------------------------------------------------------
# decode_access_token (synchronous)
# ---------------------------------------------------------------------------


def test_decode_access_token_local_mode_valid(monkeypatch) -> None:
    """Valid local JWT decodes without error."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("eve", "AppOwner", ["ag-1"])
    payload = decode_access_token(token)
    assert payload["sub"] == "eve"
    assert payload["role"] == "AppOwner"


def test_decode_access_token_local_mode_expired_raises(monkeypatch) -> None:
    """Expired JWT raises JWTError."""
    _patch_local_settings(monkeypatch, expire_minutes=-1)
    token = create_access_token("frank", "Developer", [])
    with pytest.raises(JWTError):
        decode_access_token(token)


def test_decode_access_token_local_mode_tampered_raises(monkeypatch) -> None:
    """Tampered signature raises JWTError."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("grace", "Auditor", [])
    parts = token.split(".")
    sig = parts[2]
    parts[2] = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    tampered = ".".join(parts)
    with pytest.raises(JWTError):
        decode_access_token(tampered)


def test_decode_access_token_wrong_secret_raises(monkeypatch) -> None:
    """Token signed with a different secret raises JWTError on decode."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("henry", "Developer", [])
    # Now change the secret so decode fails
    monkeypatch.setattr(settings, "jwt_secret", "completely-different-secret-xyz!")
    with pytest.raises(JWTError):
        decode_access_token(token)


# ---------------------------------------------------------------------------
# decode_access_token_async (async local mode)
# ---------------------------------------------------------------------------


async def test_decode_access_token_async_local_mode(monkeypatch) -> None:
    """decode_access_token_async() in local mode returns same payload as sync."""
    _patch_local_settings(monkeypatch)
    token = create_access_token("iris", "SecurityManager", ["ag-1"])
    payload = await decode_access_token_async(token)
    assert payload["sub"] == "iris"
    assert payload["role"] == "SecurityManager"


async def test_decode_access_token_async_expired_raises(monkeypatch) -> None:
    """Expired token raises JWTError in async path."""
    _patch_local_settings(monkeypatch, expire_minutes=-1)
    token = create_access_token("jack", "Developer", [])
    with pytest.raises(JWTError):
        await decode_access_token_async(token)


# ---------------------------------------------------------------------------
# oidc_is_configured / oidc_missing_fields
# ---------------------------------------------------------------------------


def test_oidc_is_configured_returns_false_when_empty(monkeypatch) -> None:
    """Empty oidc_issuer_url returns False."""
    monkeypatch.setattr(settings, "oidc_issuer_url", "")
    assert oidc_is_configured() is False


def test_oidc_is_configured_returns_false_when_whitespace_only(monkeypatch) -> None:
    """Whitespace-only oidc_issuer_url returns False."""
    monkeypatch.setattr(settings, "oidc_issuer_url", "   ")
    assert oidc_is_configured() is False


def test_oidc_is_configured_returns_true_when_set(monkeypatch) -> None:
    """Non-empty oidc_issuer_url returns True."""
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
    assert oidc_is_configured() is True


def test_oidc_missing_fields_returns_issuer_url_when_missing(monkeypatch) -> None:
    """Empty issuer returns ['OIDC_ISSUER_URL']."""
    monkeypatch.setattr(settings, "oidc_issuer_url", "")
    missing = oidc_missing_fields()
    assert "OIDC_ISSUER_URL" in missing


def test_oidc_missing_fields_returns_empty_when_configured(monkeypatch) -> None:
    """Configured issuer returns empty list."""
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
    missing = oidc_missing_fields()
    assert missing == []


# ---------------------------------------------------------------------------
# JWKS cache tests
# ---------------------------------------------------------------------------


async def test_get_jwks_keys_uses_cache_when_fresh(monkeypatch) -> None:
    """Second call within TTL does not make HTTP request."""
    fresh_keys = [{"kid": "key-1", "kty": "RSA"}]
    # Pre-populate cache with a fresh timestamp
    monkeypatch.setattr(
        auth_module,
        "_JWKS_CACHE",
        {"fetched_at": time(), "keys": fresh_keys},
    )
    # Reset the lock so it is created fresh in this event loop
    monkeypatch.setattr(auth_module, "_JWKS_LOCK", None)
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://idp.example.com/jwks")

    with patch("httpx.AsyncClient.get") as mock_get:
        result = await auth_module._get_jwks_keys()

    assert result == fresh_keys
    mock_get.assert_not_called()


async def test_get_jwks_keys_refreshes_when_stale(monkeypatch) -> None:
    """Stale cache triggers HTTP request to JWKS endpoint."""
    stale_time = time() - _JWKS_TTL_SECONDS - 10
    monkeypatch.setattr(
        auth_module,
        "_JWKS_CACHE",
        {"fetched_at": stale_time, "keys": []},
    )
    monkeypatch.setattr(auth_module, "_JWKS_LOCK", None)
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://idp.example.com/jwks")

    fresh_keys = [{"kid": "key-2", "kty": "RSA"}]
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"keys": fresh_keys}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        result = await auth_module._get_jwks_keys()

    assert result == fresh_keys


# ---------------------------------------------------------------------------
# _decode_oidc_token — error cases
# ---------------------------------------------------------------------------


async def test_decode_oidc_token_raises_when_kid_missing(monkeypatch) -> None:
    """Token without `kid` header raises JWTError."""
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://idp.example.com/jwks")
    monkeypatch.setattr(auth_module, "_JWKS_LOCK", None)

    # Build a token without a kid header (use HS256 for simplicity)
    _patch_local_settings(monkeypatch)
    token = create_access_token("test", "Developer", [])
    # token has no kid header — _decode_oidc_token should raise

    with pytest.raises(JWTError, match="kid"):
        await auth_module._decode_oidc_token(token)


async def test_decode_oidc_token_raises_when_no_matching_key(monkeypatch) -> None:
    """No matching JWK for kid raises JWTError."""
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://idp.example.com/jwks")
    monkeypatch.setattr(auth_module, "_JWKS_LOCK", None)

    # Provide a JWKS cache with a key that has a different kid
    monkeypatch.setattr(
        auth_module,
        "_JWKS_CACHE",
        {"fetched_at": time(), "keys": [{"kid": "other-kid", "kty": "RSA"}]},
    )

    # Build a token that has a kid header
    header = {"alg": "HS256", "kid": "my-kid"}
    payload = {"sub": "test", "role": "Developer", "asset_group_ids": []}
    token = jwt.encode(payload, "secret", algorithm="HS256", headers=header)

    with pytest.raises(JWTError, match="matching JWK"):
        await auth_module._decode_oidc_token(token)
