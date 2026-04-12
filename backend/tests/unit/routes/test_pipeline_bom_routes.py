"""Unit tests for pipeline BOM stub route: GET /pipeline-bom."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.security.dependencies import UserContext, get_current_user
from app.main import app


# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------

def _admin() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1"])


def _developer() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_startup(monkeypatch):
    monkeypatch.setattr("app.repositories.postgres_store.init_db", MagicMock())
    monkeypatch.setattr("app.repositories.postgres_store.ensure_seed_data", MagicMock())


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline-bom
# ---------------------------------------------------------------------------

class TestListPipelineBom:
    def test_list_pipeline_bom_returns_200(self):
        app.dependency_overrides[get_current_user] = _admin
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/pipeline-bom")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_pipeline_bom_has_stub_header(self):
        app.dependency_overrides[get_current_user] = _admin
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/pipeline-bom")
        app.dependency_overrides.clear()

        assert resp.headers.get("x-stub-data") == "true"

    def test_list_pipeline_bom_items_have_stub_flag(self):
        app.dependency_overrides[get_current_user] = _admin
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/pipeline-bom")
        app.dependency_overrides.clear()

        data = resp.json()
        for item in data:
            assert item.get("_stub") is True

    def test_list_pipeline_bom_requires_auth(self):
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/pipeline-bom")
        assert resp.status_code in (401, 403)

    def test_list_pipeline_bom_allowed_for_developer(self):
        app.dependency_overrides[get_current_user] = _developer
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/pipeline-bom")
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_list_pipeline_bom_response_has_pipeline_field(self):
        app.dependency_overrides[get_current_user] = _admin
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/v1/pipeline-bom")
        app.dependency_overrides.clear()

        data = resp.json()
        assert "pipeline" in data[0]
        assert "stages" in data[0]
        assert "components" in data[0]
