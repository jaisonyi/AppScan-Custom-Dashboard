"""Unit tests for AsocApiClient._login_succeeded flag and fallback behaviour."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.appscan_api.client import (
    AsocApiClient,
    AsocAuthenticationError,
    AsocResponseFormatError,
)


@pytest.fixture
def client() -> AsocApiClient:
    return AsocApiClient.make(
        url="https://test.appscan.example",
        key="test-key",
        secret="test-secret",
        verify=False,
    )


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestLoginSucceededInitialState:
    def test_initial_state_is_none(self, client: AsocApiClient) -> None:
        assert client.login_succeeded is None

    def test_default_constructor_initial_state(self) -> None:
        with patch("app.integrations.appscan_api.client.settings") as mock_settings:
            mock_settings.asoc_service_url = "https://cloud.appscan.com"
            mock_settings.asoc_api_key = "k"
            mock_settings.asoc_api_secret = "s"
            mock_settings.asoc_read_only = True
            mock_settings.asoc_verify_ssl = True
            c = AsocApiClient()
        assert c.login_succeeded is None


# ---------------------------------------------------------------------------
# Successful login — test via _login_with_api_key / _get_auth_header
# ---------------------------------------------------------------------------


class TestLoginSucceededOnSuccess:
    @pytest.mark.asyncio
    async def test_login_sets_flag_true(self, client: AsocApiClient) -> None:
        async def _fake_login() -> str:
            client._access_token = "tok"
            client._owner_user_id = "u1"
            client._login_succeeded = True
            return "tok"

        with patch.object(client, "_login_with_api_key", side_effect=_fake_login):
            headers = await client._get_auth_header()

        assert client.login_succeeded is True
        assert "Bearer" in headers.get("Authorization", "")

    @pytest.mark.asyncio
    async def test_owner_user_id_populated_after_login(self, client: AsocApiClient) -> None:
        async def _fake_login() -> str:
            client._access_token = "tok"
            client._owner_user_id = "user-42"
            client._login_succeeded = True
            return "tok"

        with patch.object(client, "_login_with_api_key", side_effect=_fake_login):
            await client._get_auth_header()

        assert client.owner_user_id == "user-42"


# ---------------------------------------------------------------------------
# Failed login — X-API-KEY fallback
# ---------------------------------------------------------------------------


class TestLoginSucceededOnFailure:
    @pytest.mark.asyncio
    async def test_auth_error_sets_flag_false(self, client: AsocApiClient) -> None:
        with patch.object(
            client, "_login_with_api_key",
            side_effect=AsocAuthenticationError("rejected"),
        ):
            headers = await client._get_auth_header()

        assert client.login_succeeded is False
        assert "X-API-KEY" in headers

    @pytest.mark.asyncio
    async def test_format_error_sets_flag_false(self, client: AsocApiClient) -> None:
        with patch.object(
            client, "_login_with_api_key",
            side_effect=AsocResponseFormatError("non-JSON"),
        ):
            headers = await client._get_auth_header()

        assert client.login_succeeded is False
        assert "X-API-KEY" in headers

    @pytest.mark.asyncio
    async def test_fallback_logs_warning(
        self, client: AsocApiClient, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with patch.object(
            client, "_login_with_api_key",
            side_effect=AsocAuthenticationError("rejected"),
        ):
            with caplog.at_level(logging.WARNING, logger="app.integrations.appscan_api.client"):
                await client._get_auth_header()

        assert any("Bearer token login failed" in m for m in caplog.messages)

    @pytest.mark.asyncio
    async def test_fallback_returns_api_key_header(self, client: AsocApiClient) -> None:
        with patch.object(
            client, "_login_with_api_key",
            side_effect=AsocAuthenticationError("rejected"),
        ):
            headers = await client._get_auth_header()

        assert headers["X-API-KEY"] == "test-key:test-secret"
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_owner_user_id_remains_none_on_failure(
        self, client: AsocApiClient,
    ) -> None:
        with patch.object(
            client, "_login_with_api_key",
            side_effect=AsocAuthenticationError("rejected"),
        ):
            await client._get_auth_header()

        assert client.owner_user_id is None
