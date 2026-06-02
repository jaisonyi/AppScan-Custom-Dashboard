"""Shared pytest fixtures for the AppScan ASPM Dashboard backend test suite."""
from __future__ import annotations

import pytest

from app.core.config.settings import settings
from app.core.security.auth import create_access_token
from app.core.security.dependencies import UserContext


# ---------------------------------------------------------------------------
# User context fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user() -> UserContext:
    return UserContext(
        subject="admin@test.com",
        role="PlatformAdmin",
        asset_group_ids=["ag-1", "ag-2"],
    )


@pytest.fixture
def security_manager_user() -> UserContext:
    return UserContext(
        subject="sm@test.com",
        role="SecurityManager",
        asset_group_ids=["ag-1"],
    )


@pytest.fixture
def app_owner_user() -> UserContext:
    return UserContext(
        subject="owner@test.com",
        role="AppOwner",
        asset_group_ids=["ag-1"],
    )


@pytest.fixture
def developer_user() -> UserContext:
    return UserContext(
        subject="dev@test.com",
        role="Developer",
        asset_group_ids=["ag-1"],
    )


@pytest.fixture
def auditor_user() -> UserContext:
    return UserContext(
        subject="audit@test.com",
        role="Auditor",
        asset_group_ids=["ag-1"],
    )


# ---------------------------------------------------------------------------
# JWT token fixtures
# ---------------------------------------------------------------------------

_TEST_SECRET = "test-secret-32-chars-minimum-len!"


@pytest.fixture
def valid_local_jwt(monkeypatch) -> str:
    monkeypatch.setattr(settings, "jwt_secret", _TEST_SECRET)
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "access_token_expire_minutes", 60)
    return create_access_token("testuser", "SecurityManager", ["ag-1"])


@pytest.fixture
def expired_local_jwt(monkeypatch) -> str:
    monkeypatch.setattr(settings, "jwt_secret", _TEST_SECRET)
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    return create_access_token("testuser", "SecurityManager", ["ag-1"])


@pytest.fixture
def tampered_jwt(valid_local_jwt) -> str:
    parts = valid_local_jwt.split(".")
    sig = parts[2]
    parts[2] = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Settings override fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def local_auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "jwt_secret", _TEST_SECRET)


@pytest.fixture
def oidc_auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")


# ---------------------------------------------------------------------------
# Mock store / data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_dashboard() -> dict:
    return {
        "id": "d-test-1",
        "name": "Test Dashboard",
        "widgets": [{"type": "kpi_card", "title": "Issues"}],
        "blueprint": {"status": "draft", "visibility": "team"},
        "owner": "admin@test.com",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }


@pytest.fixture
def fake_audit_event() -> dict:
    return {
        "id": "ae-test-1",
        "actor": "admin@test.com",
        "action": "dashboard.create",
        "resource_type": "dashboard",
        "resource_id": "d-test-1",
        "details": {},
        "created_at": "2025-01-01T00:00:00+00:00",
    }


@pytest.fixture
def fake_scans() -> list[dict]:
    return [
        {
            "id": "s-1",
            "name": "SAST Scan",
            "status": "completed",
            "scan_type": "SAST",
            "asset_group_id": "ag-1",
            "application_id": "app-1",
            "created_at": "2025-01-15T00:00:00Z",
            "duration_seconds": 420,
            "page_coverage": 0,
            "native_severity": "high",
        },
        {
            "id": "s-2",
            "name": "DAST Scan",
            "status": "completed",
            "scan_type": "DAST",
            "asset_group_id": "ag-1",
            "application_id": "app-1",
            "created_at": "2025-02-10T00:00:00Z",
            "duration_seconds": 3600,
            "page_coverage": 420,
            "native_severity": "critical",
        },
        {
            "id": "s-3",
            "name": "SCA Scan",
            "status": "failed",
            "scan_type": "SCA",
            "asset_group_id": "ag-2",
            "application_id": "app-2",
            "created_at": "2025-03-05T00:00:00Z",
            "duration_seconds": 185,
            "page_coverage": 0,
            "native_severity": "unknown",
        },
    ]


@pytest.fixture
def fake_issues() -> list[dict]:
    return [
        {
            "id": "i-1",
            "severity": "critical",
            "status": "Open",
            "asset_group_id": "ag-1",
            "application_id": "app-1",
            "opened_at": "2025-01-10T00:00:00Z",
            "closed_at": "",
            "mttr_days": 0,
            "vulnerability": "SQL Injection",
        },
        {
            "id": "i-2",
            "severity": "high",
            "status": "Open",
            "asset_group_id": "ag-1",
            "application_id": "app-1",
            "opened_at": "2025-02-01T00:00:00Z",
            "closed_at": "",
            "mttr_days": 0,
            "vulnerability": "XSS",
        },
        {
            "id": "i-3",
            "severity": "medium",
            "status": "closed",
            "asset_group_id": "ag-2",
            "application_id": "app-2",
            "opened_at": "2025-01-20T00:00:00Z",
            "closed_at": "2025-02-20T00:00:00Z",
            "mttr_days": 31,
            "vulnerability": "CSRF",
        },
    ]


@pytest.fixture
def fake_applications() -> list[dict]:
    return [
        {
            "id": "app-1",
            "name": "Payments API",
            "asset_group_id": "ag-1",
            "created_at": "2025-01-01T00:00:00Z",
        },
        {
            "id": "app-2",
            "name": "Portal Web",
            "asset_group_id": "ag-2",
            "created_at": "2025-02-01T00:00:00Z",
        },
    ]


@pytest.fixture
def fake_asset_groups() -> list[dict]:
    return [
        {"id": "ag-1", "name": "Production"},
        {"id": "ag-2", "name": "Staging"},
    ]
