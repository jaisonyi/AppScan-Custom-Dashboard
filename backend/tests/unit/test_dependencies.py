"""Unit tests for app.core.security.dependencies — get_current_user FastAPI dependency."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError

import app.core.security.dependencies as deps_module
from app.core.config.settings import settings
from app.core.security.dependencies import UserContext, get_current_user

_TEST_SECRET = "test-secret-32-chars-minimum-len!"


def _make_credentials(token: str) -> HTTPAuthorizationCredentials:
    """Helper: build HTTPAuthorizationCredentials with the given token."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ---------------------------------------------------------------------------
# get_current_user — valid local token
# ---------------------------------------------------------------------------


async def test_get_current_user_returns_user_context_for_valid_token(monkeypatch) -> None:
    """Valid JWT returns UserContext with correct fields."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    mock_payload = {
        "sub": "alice@test.com",
        "role": "PlatformAdmin",
        "asset_group_ids": ["ag-1", "ag-2"],
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("fake-valid-token")
        user = await get_current_user(credentials=creds)

    assert isinstance(user, UserContext)
    assert user.subject == "alice@test.com"
    assert user.role == "PlatformAdmin"
    assert user.asset_group_ids == ["ag-1", "ag-2"]


async def test_get_current_user_raises_401_for_invalid_token(monkeypatch) -> None:
    """Malformed token raises HTTP 401."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    with patch.object(
        deps_module,
        "decode_access_token_async",
        new=AsyncMock(side_effect=JWTError("bad token")),
    ):
        creds = _make_credentials("malformed.token.here")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 401


async def test_get_current_user_raises_401_for_expired_token(monkeypatch) -> None:
    """Expired token raises HTTP 401."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    with patch.object(
        deps_module,
        "decode_access_token_async",
        new=AsyncMock(side_effect=JWTError("Signature has expired")),
    ):
        creds = _make_credentials("expired.token.here")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 401


async def test_get_current_user_raises_401_for_missing_sub(monkeypatch) -> None:
    """Token without `sub` raises HTTP 401."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    mock_payload = {
        # "sub" is intentionally missing
        "role": "Developer",
        "asset_group_ids": ["ag-1"],
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("token-without-sub")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 401


async def test_get_current_user_raises_401_for_missing_role(monkeypatch) -> None:
    """Token without `role` raises HTTP 401."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    mock_payload = {
        "sub": "bob@test.com",
        # "role" is intentionally missing
        "asset_group_ids": ["ag-1"],
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("token-without-role")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 401


async def test_get_current_user_raises_401_for_non_list_asset_groups(monkeypatch) -> None:
    """`asset_group_ids` not a list raises HTTP 401."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    mock_payload = {
        "sub": "carol@test.com",
        "role": "Developer",
        "asset_group_ids": "ag-1",  # string instead of list
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("token-bad-asset-groups")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user — OIDC 503 guard
# ---------------------------------------------------------------------------


async def test_get_current_user_raises_503_when_oidc_not_configured(monkeypatch) -> None:
    """`auth_mode=oidc` but no issuer URL raises HTTP 503."""
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    creds = _make_credentials("any-token")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 503


async def test_get_current_user_raises_503_when_oidc_issuer_whitespace(monkeypatch) -> None:
    """`auth_mode=oidc` with whitespace-only issuer URL raises HTTP 503."""
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer_url", "   ")

    creds = _make_credentials("any-token")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)

    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# get_current_user — asset group normalization
# ---------------------------------------------------------------------------


async def test_get_current_user_normalizes_asset_group_ids(monkeypatch) -> None:
    """Empty strings in list are stripped from result."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    mock_payload = {
        "sub": "dave@test.com",
        "role": "AppOwner",
        "asset_group_ids": ["ag-1", "", "ag-2", ""],
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("token-with-empty-groups")
        user = await get_current_user(credentials=creds)

    assert user.asset_group_ids == ["ag-1", "ag-2"]


async def test_get_current_user_normalizes_empty_asset_group_list(monkeypatch) -> None:
    """Empty asset_group_ids list is accepted and returned as empty list."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")

    mock_payload = {
        "sub": "eve@test.com",
        "role": "Auditor",
        "asset_group_ids": [],
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("token-empty-groups")
        user = await get_current_user(credentials=creds)

    assert user.asset_group_ids == []
    assert user.role == "Auditor"


# ---------------------------------------------------------------------------
# get_current_user — OIDC mode claim mapping
# ---------------------------------------------------------------------------


async def test_get_current_user_uses_oidc_claims_in_oidc_mode(monkeypatch) -> None:
    """OIDC mode uses oidc_role_claim and oidc_asset_groups_claim from settings."""
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
    monkeypatch.setattr(settings, "oidc_role_claim", "custom_role")
    monkeypatch.setattr(settings, "oidc_asset_groups_claim", "custom_groups")

    mock_payload = {
        "sub": "frank@corp.com",
        "custom_role": "SecurityManager",
        "custom_groups": ["ag-1", "ag-3"],
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("oidc-token")
        user = await get_current_user(credentials=creds)

    assert user.subject == "frank@corp.com"
    assert user.role == "SecurityManager"
    assert user.asset_group_ids == ["ag-1", "ag-3"]


async def test_get_current_user_local_mode_uses_standard_claims(monkeypatch) -> None:
    """Local mode uses 'role' and 'asset_group_ids' claim keys."""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "oidc_issuer_url", "")
    # Even if oidc claims are set, local mode should ignore them
    monkeypatch.setattr(settings, "oidc_role_claim", "custom_role")
    monkeypatch.setattr(settings, "oidc_asset_groups_claim", "custom_groups")

    mock_payload = {
        "sub": "grace@test.com",
        "role": "Developer",
        "asset_group_ids": ["ag-1"],
        "custom_role": "PlatformAdmin",  # should be ignored in local mode
    }

    with patch.object(deps_module, "decode_access_token_async", new=AsyncMock(return_value=mock_payload)):
        creds = _make_credentials("local-token")
        user = await get_current_user(credentials=creds)

    assert user.role == "Developer"  # uses standard "role" key, not custom_role
    assert user.asset_group_ids == ["ag-1"]
