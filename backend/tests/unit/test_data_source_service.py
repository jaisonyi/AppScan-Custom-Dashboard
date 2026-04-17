"""Unit tests for data_source_service.refresh_api_user_info identity extraction."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import data_source_service


_DS_ROW: dict = {
    "id": "ds-1",
    "label": "Test",
    "url": "https://cloud.appscan.com",
    "api_key": "key",
    "api_secret": "secret",
    "verify_ssl": True,
    "enabled": True,
}


def _make_client_mock(
    *,
    owner_user_id: str | None = None,
    tenant_info: dict | None = None,
    user_payload: dict | None = None,
    login_succeeded: bool | None = True,
) -> MagicMock:
    """Create a mock AsocApiClient with configurable get() behaviour."""
    client = MagicMock()
    client.owner_user_id = owner_user_id
    client.login_succeeded = login_succeeded

    async def _get(path: str) -> dict:
        if "TenantInfo" in path:
            return tenant_info or {}
        if owner_user_id and owner_user_id in path:
            return user_payload or {}
        return {}

    client.get = AsyncMock(side_effect=_get)
    return client


class TestRefreshLastProbeOk:
    """Verify the relaxed last_probe_ok formula: bool(tenant_name or user_name or user_role)."""

    @pytest.mark.asyncio
    async def test_tenant_name_only_is_ok(self) -> None:
        """last_probe_ok=True when TenantInfo succeeds but no UserInfo block."""
        client = _make_client_mock(
            owner_user_id=None,
            tenant_info={"TenantName": "Innovation Hub"},
        )
        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw) as update,
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["last_probe_ok"] is True
        assert result["tenant_name"] == "Innovation Hub"

    @pytest.mark.asyncio
    async def test_extracts_user_info_from_tenant_info(self) -> None:
        """UserInfo block in TenantInfo is extracted for name, email, and role."""
        client = _make_client_mock(
            owner_user_id=None,
            tenant_info={
                "TenantName": "Innovation Hub",
                "UserInfo": {
                    "Username": "dongil.lee@hcl.com",
                    "FirstName": "Dong il",
                    "LastName": "Lee",
                    "IsAdmin": True,
                    "Email": "dongil.lee@hcl.com",
                },
            },
        )
        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["last_probe_ok"] is True
        assert result["tenant_name"] == "Innovation Hub"
        assert result["api_user_name"] == "Dong il Lee"
        assert result["api_user_email"] == "dongil.lee@hcl.com"
        assert result["api_user_role"] == "Administrator"

    @pytest.mark.asyncio
    async def test_is_admin_false_maps_to_user_role(self) -> None:
        """IsAdmin=False maps to 'User' role string."""
        client = _make_client_mock(
            tenant_info={
                "TenantName": "Acme",
                "UserInfo": {"FirstName": "Jane", "LastName": "Doe", "IsAdmin": False, "Email": "jane@acme.com"},
            },
        )
        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["api_user_role"] == "User"
        assert result["api_user_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_username_fallback_when_no_first_last(self) -> None:
        """Falls back to Username if FirstName/LastName are empty."""
        client = _make_client_mock(
            tenant_info={
                "TenantName": "Org",
                "UserInfo": {"Username": "svc-account@corp.com", "FirstName": "", "LastName": ""},
            },
        )
        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["api_user_name"] == "svc-account@corp.com"

    @pytest.mark.asyncio
    async def test_fallback_to_user_endpoint_when_no_user_info(self) -> None:
        """Falls back to /api/v4/User/{id} when TenantInfo has no UserInfo."""
        client = _make_client_mock(
            owner_user_id="u1",
            tenant_info={"TenantName": "Acme"},
            user_payload={"FirstName": "Bob", "LastName": "Y", "RoleName": "Admin", "Email": "bob@acme.com"},
        )
        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["last_probe_ok"] is True
        assert result["tenant_name"] == "Acme"
        assert result["api_user_name"] == "Bob Y"
        assert result["api_user_role"] == "Admin"

    @pytest.mark.asyncio
    async def test_nothing_returned_is_not_ok(self) -> None:
        """last_probe_ok=False when no identity info is available at all."""
        client = _make_client_mock(
            owner_user_id=None,
            tenant_info={},
        )
        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["last_probe_ok"] is False

    @pytest.mark.asyncio
    async def test_ds_not_found_returns_none(self) -> None:
        with patch.object(data_source_service.store, "get_data_source", return_value=None):
            result = await data_source_service.refresh_api_user_info("missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_tenant_info_exception_sets_false(self) -> None:
        """last_probe_ok=False when TenantInfo call itself throws."""
        client = MagicMock()
        client.owner_user_id = None
        client.get = AsyncMock(side_effect=RuntimeError("connection refused"))

        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["last_probe_ok"] is False

    @pytest.mark.asyncio
    async def test_user_endpoint_failure_still_ok_if_tenant(self) -> None:
        """Probe is OK when user endpoint fails but tenant name was retrieved."""
        call_count = 0

        async def _get(path: str) -> dict:
            nonlocal call_count
            call_count += 1
            if "TenantInfo" in path:
                return {"TenantName": "OrgX"}
            raise RuntimeError("user endpoint down")

        client = MagicMock()
        client.owner_user_id = "u1"
        client.get = AsyncMock(side_effect=_get)

        with (
            patch.object(data_source_service.store, "get_data_source", return_value=_DS_ROW),
            patch.object(data_source_service, "AsocApiClient") as cls_mock,
            patch.object(data_source_service.store, "update_data_source", side_effect=lambda ds_id, **kw: kw),
        ):
            cls_mock.make.return_value = client
            result = await data_source_service.refresh_api_user_info("ds-1")

        assert result["last_probe_ok"] is True
        assert result["tenant_name"] == "OrgX"
        assert result["api_user_name"] == ""
