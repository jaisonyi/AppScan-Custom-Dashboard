"""Unit tests for auth routes: POST /auth/login, GET /auth/mode, GET /auth/current-user."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config.settings import settings
from app.core.security.dependencies import UserContext, get_current_user
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin_user() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])


def _make_developer_user() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    """Prevent real DB init and scheduler startup during TestClient lifespan."""
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())
    monkeypatch.setattr("app.core.config.settings.settings", settings)


@pytest.fixture
def authed_client():
    """TestClient with admin user injected via dependency override."""
    app.dependency_overrides[get_current_user] = _make_admin_user
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_client():
    """TestClient with NO dependency override (no auth)."""
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------

class TestLoginEndpoint:
    def test_login_returns_token_for_valid_role(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "local")
        monkeypatch.setattr(settings, "jwt_secret", "test-secret-32-chars-minimum-len!")
        monkeypatch.setattr(settings, "access_token_expire_minutes", 60)
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "admin@test.com", "role": "PlatformAdmin", "asset_group_ids": ["ag-1"]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_rejects_invalid_role(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "local")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "user@test.com", "role": "InvalidRole", "asset_group_ids": []},
            )
        assert resp.status_code == 400
        assert "Invalid role" in resp.json()["detail"]

    def test_login_disabled_in_oidc_mode(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "oidc")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "user@test.com", "role": "PlatformAdmin", "asset_group_ids": []},
            )
        assert resp.status_code == 405
        assert "OIDC" in resp.json()["detail"]

    def test_login_missing_username_returns_422(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "local")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/login", json={"role": "PlatformAdmin"})
        assert resp.status_code == 422

    def test_login_all_valid_roles_accepted(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "local")
        monkeypatch.setattr(settings, "jwt_secret", "test-secret-32-chars-minimum-len!")
        monkeypatch.setattr(settings, "access_token_expire_minutes", 60)
        valid_roles = ["PlatformAdmin", "SecurityManager", "AppOwner", "Developer", "Auditor"]
        with TestClient(app, raise_server_exceptions=True) as client:
            for role in valid_roles:
                resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": f"{role}@test.com", "role": role, "asset_group_ids": ["ag-1"]},
                )
                assert resp.status_code == 200, f"Expected 200 for role {role}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# GET /api/v1/auth/mode
# ---------------------------------------------------------------------------

class TestAuthModeEndpoint:
    def test_auth_mode_returns_local(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "local")
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/auth/mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_mode"] == "local"
        assert "oidc_configured" in data
        assert "oidc_missing_fields" in data

    def test_auth_mode_returns_oidc_when_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "oidc")
        monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/auth/mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_mode"] == "oidc"

    def test_auth_mode_no_auth_required(self, unauthed_client):
        """GET /auth/mode is a public endpoint — no token needed."""
        resp = unauthed_client.get("/api/v1/auth/mode")
        assert resp.status_code == 200

    def test_auth_mode_oidc_missing_fields_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "auth_mode", "oidc")
        monkeypatch.setattr(settings, "oidc_issuer_url", "")
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/auth/mode")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["oidc_missing_fields"]) > 0


# ---------------------------------------------------------------------------
# GET /api/v1/auth/current-user
# ---------------------------------------------------------------------------

class TestCurrentUserEndpoint:
    def test_current_user_profile_returns_local_profile(self, authed_client, monkeypatch):
        monkeypatch.setattr(settings, "asoc_api_key", "")
        monkeypatch.setattr(settings, "asoc_api_secret", "")
        resp = authed_client.get("/api/v1/auth/current-user")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "local"
        assert data["subject"] == "admin@test.com"
        assert data["role"] == "PlatformAdmin"

    def test_current_user_profile_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/v1/auth/current-user")
        assert resp.status_code in (401, 403)

    def test_current_user_returns_asset_group_ids(self, authed_client, monkeypatch):
        monkeypatch.setattr(settings, "asoc_api_key", "")
        monkeypatch.setattr(settings, "asoc_api_secret", "")
        resp = authed_client.get("/api/v1/auth/current-user")
        assert resp.status_code == 200
        data = resp.json()
        assert "asset_group_ids" in data
        assert isinstance(data["asset_group_ids"], list)

    def test_current_user_with_asoc_credentials_calls_api(self, monkeypatch):
        """When ASoC credentials are set, the route attempts to enrich profile."""
        monkeypatch.setattr(settings, "asoc_api_key", "fake-key")
        monkeypatch.setattr(settings, "asoc_api_secret", "fake-secret")
        mock_get = AsyncMock(return_value={})
        with patch("app.integrations.appscan_api.client.AsocApiClient.get", mock_get):
            app.dependency_overrides[get_current_user] = _make_admin_user
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.get("/api/v1/auth/current-user")
            app.dependency_overrides.clear()
        # Even if ASoC returns empty, profile should still be returned
        assert resp.status_code == 200

    def test_current_user_developer_role_returns_profile(self):
        """Developer role can access /current-user."""
        app.dependency_overrides[get_current_user] = _make_developer_user
        with TestClient(app, raise_server_exceptions=True) as client:
            with patch("app.core.config.settings.settings") as mock_settings:
                mock_settings.asoc_api_key = ""
                mock_settings.asoc_api_secret = ""
                mock_settings.auth_mode = "local"
                resp = client.get("/api/v1/auth/current-user")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
