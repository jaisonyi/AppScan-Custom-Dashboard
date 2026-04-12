import pytest

from app.integrations.appscan_api.client import AsocApiClient, ReadOnlyViolationError


@pytest.mark.asyncio
async def test_read_only_policy_blocks_non_get() -> None:
    client = AsocApiClient()
    with pytest.raises(ReadOnlyViolationError):
        client._validate_request("POST", "/api/v4/Scans")


@pytest.mark.asyncio
async def test_read_only_policy_allows_api_key_login_post_only() -> None:
    client = AsocApiClient()
    # Swagger v4 auth flow requires this POST endpoint even in read-only mode.
    client._validate_request("POST", "/api/v4/Account/ApiKeyLogin")
