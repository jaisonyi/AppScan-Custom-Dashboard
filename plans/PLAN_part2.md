| `test_run_analytics_prewarm_stops_on_stop_event` | `stop_event.set()` causes loop to exit cleanly |
| `test_run_analytics_prewarm_logs_exception_on_failure` | `prewarm_base_data_cache` raises; exception is logged, loop continues |

**Mocking strategy:** Patch `prewarm_base_data_cache` with `AsyncMock`. Patch `settings.analytics_prewarm_interval_seconds = 0`. Use `asyncio.Event` for `stop_event`.

---

### 2.13 Route Tests — `tests/unit/routes/`

All route tests use `httpx.AsyncClient` with FastAPI's `app` instance. The `get_current_user` dependency is **overridden** in every route test to inject a controlled `UserContext` without real JWT validation.

#### `test_route_auth.py`

**Module under test:** [`backend/app/api/v1/routes/auth.py`](backend/app/api/v1/routes/auth.py)

| Test function | Description |
|---|---|
| `test_login_returns_token_for_valid_role` | POST `/auth/login` with valid role returns 200 + `access_token` |
| `test_login_rejects_invalid_role` | POST `/auth/login` with unknown role returns 400 |
| `test_login_disabled_in_oidc_mode` | `auth_mode=oidc` returns 405 |
| `test_auth_mode_returns_local` | GET `/auth/mode` returns `{"auth_mode": "local", ...}` |
| `test_auth_mode_returns_oidc_when_configured` | `auth_mode=oidc` returns `{"auth_mode": "oidc", ...}` |
| `test_current_user_profile_returns_local_profile` | GET `/auth/current-user` returns profile with `source="local"` |
| `test_current_user_profile_requires_auth` | No token returns 403 |

**Mocking strategy:** Override `get_current_user` dependency. Patch `settings.auth_mode` via `monkeypatch`. Patch `AsocApiClient.get` with `AsyncMock` returning empty dicts.

---

#### `test_route_dashboard.py`

**Module under test:** [`backend/app/api/v1/routes/dashboard.py`](backend/app/api/v1/routes/dashboard.py)

| Test function | Description |
|---|---|
| `test_list_dashboards_returns_200` | GET `/dashboards` returns 200 + list |
| `test_list_dashboards_requires_auth` | No token returns 403 |
| `test_create_dashboard_returns_200` | POST `/dashboards` with valid body returns 200 + dashboard dict |
| `test_create_dashboard_forbidden_for_developer` | `Developer` role returns 403 |
| `test_create_dashboard_forbidden_for_auditor` | `Auditor` role returns 403 |
| `test_update_dashboard_returns_200` | PUT `/dashboards/{id}` returns 200 + updated dict |
| `test_update_dashboard_returns_404_when_not_found` | Non-existent ID returns 404 |
| `test_delete_dashboard_returns_200` | DELETE `/dashboards/{id}` returns 200 + `{"status": "deleted"}` |
| `test_delete_dashboard_returns_404_when_not_found` | Non-existent ID returns 404 |
| `test_delete_dashboard_forbidden_for_developer` | `Developer` role returns 403 |
| `test_list_dashboard_versions_returns_200` | GET `/dashboards/{id}/versions` returns 200 + list |
| `test_list_dashboard_versions_returns_404_for_unknown_dashboard` | Non-existent ID returns 404 |
| `test_rollback_dashboard_version_returns_200` | POST `/dashboards/{id}/rollback/{v}` returns 200 |
| `test_rollback_dashboard_version_returns_404_for_unknown_version` | Non-existent version returns 404 |
| `test_list_widget_registry_returns_200` | GET `/dashboards/widget-registry` returns 200 + `{items, count}` |
| `test_list_dashboard_templates_returns_200` | GET `/dashboards/templates` returns 200 + list |
| `test_create_dashboard_template_forbidden_for_developer` | `Developer` role returns 403 |
| `test_create_dashboard_via_wizard_returns_200` | POST `/dashboards/wizard/create` returns 200 |
| `test_create_dashboard_via_wizard_requires_valid_widgets` | No valid widgets returns 400 |

**Mocking strategy:** Patch all `postgres_store` functions with `MagicMock`. Override `get_current_user` dependency. Patch `get_widget_map` and `list_widgets` for widget registry tests.

---

#### `test_route_audit.py`

**Module under test:** [`backend/app/api/v1/routes/audit.py`](backend/app/api/v1/routes/audit.py)

| Test function | Description |
|---|---|
| `test_list_audit_events_returns_paginated_envelope` | GET `/audit/events` returns `{items, offset, limit, total}` |
| `test_list_audit_events_default_pagination` | No params returns `limit=200`, `offset=0` |
| `test_list_audit_events_custom_pagination` | `?limit=10&offset=5` passes correct params to store |
| `test_list_audit_events_forbidden_for_developer` | `Developer` role returns 403 |
| `test_list_audit_events_forbidden_for_app_owner` | `AppOwner` role returns 403 |
| `test_list_audit_events_allowed_for_auditor` | `Auditor` role returns 200 |
| `test_list_audit_events_requires_auth` | No token returns 403 |

**Mocking strategy:** Patch `list_audit_event_rows` and `count_audit_events` with `MagicMock`. Override `get_current_user` dependency.

---

#### `test_route_analytics.py`

**Module under test:** [`backend/app/api/v1/routes/analytics.py`](backend/app/api/v1/routes/analytics.py)

| Test function | Description |
|---|---|
| `test_statistics_returns_200` | GET `/analytics/statistics` returns 200 + stats dict |
| `test_statistics_requires_auth` | No token returns 403 |
| `test_trend_returns_active_issues_by_default` | GET `/analytics/trend` returns `trend_active` list |
| `test_trend_returns_all_issues_when_active_only_false` | `?active_only=false` returns `trend_all` list |
| `test_kpi_returns_200` | GET `/analytics/kpi` returns list of KPI dicts |
| `test_mttr_returns_200` | GET `/analytics/mttr` returns list of MTTR dicts |
| `test_portfolio_summary_returns_200` | GET `/analytics/portfolio-summary` returns summary dict |
| `test_resolve_scope_filters_raises_403_for_unauthorized_asset_group` | Non-admin requesting unauthorized group returns 403 |
| `test_build_cache_key_is_deterministic` | Same params produce same cache key |
| `test_build_cache_key_differs_for_different_params` | Different params produce different cache key |
| `test_is_snapshot_fresh_returns_false_for_expired` | Expired `expires_at` returns `False` |
| `test_is_snapshot_fresh_returns_true_for_valid` | Future `expires_at` returns `True` |
| `test_normalize_scan_severity_source_defaults_to_hybrid` | Unknown value returns `"hybrid"` |
| `test_normalize_compliance_rule_defaults_to_critical_high` | Unknown value returns `"critical_high"` |
| `test_normalize_id_list_deduplicates` | Duplicate IDs return deduplicated list |
| `test_normalize_id_list_splits_comma_separated` | `"ag-1,ag-2"` returns `["ag-1", "ag-2"]` |
| `test_normalize_issue_technology_list_filters_invalid` | `"INVALID"` is excluded |
| `test_hydrate_bundle_defaults_fills_missing_sections` | Bundle missing `kpi` gets `kpi` defaulted to `[]` |

**Mocking strategy:** Patch `_get_bundle` with `AsyncMock` returning a pre-built bundle dict. Patch `sqlite_store` functions with `MagicMock`. Override `get_current_user` dependency.

---

#### `test_route_reports.py`

**Module under test:** [`backend/app/api/v1/routes/reports.py`](backend/app/api/v1/routes/reports.py)

| Test function | Description |
|---|---|
| `test_list_report_templates_returns_200` | GET `/reports/templates` returns 200 + list |
| `test_list_report_templates_forbidden_for_developer` | `Developer` role returns 403 |
| `test_create_report_template_returns_200` | POST `/reports/templates` returns 200 + template dict |
| `test_delete_report_template_returns_200` | DELETE `/reports/templates/{id}` returns 200 |
| `test_delete_report_template_returns_404` | Non-existent ID returns 404 |
| `test_generate_report_returns_200_with_artifact` | POST `/reports/generate` returns 200 + `artifact` key |
| `test_generate_report_forbidden_for_app_owner` | `AppOwner` role returns 403 |
| `test_list_report_history_returns_200` | GET `/reports/history` returns 200 + list with `artifact` key |
| `test_download_report_artifact_returns_file` | GET `/reports/history/{id}/download` returns `FileResponse` |
| `test_download_report_artifact_returns_404_when_missing` | No artifact returns 404 |
| `test_download_report_artifact_returns_400_for_path_traversal` | Invalid path returns 400 |
| `test_list_report_schedules_returns_200` | GET `/reports/schedules` returns 200 + list |
| `test_create_report_schedule_returns_200` | POST `/reports/schedules` returns 200 + schedule dict |
| `test_create_report_schedule_returns_422_for_invalid_cron` | Invalid cron returns 422 |
| `test_create_report_schedule_forbidden_for_auditor` | `Auditor` role returns 403 |
| `test_update_report_schedule_returns_200` | PUT `/reports/schedules/{id}` returns 200 |
| `test_update_report_schedule_returns_404` | Non-existent ID returns 404 |
| `test_delete_report_schedule_returns_200` | DELETE `/reports/schedules/{id}` returns 200 |
| `test_monitor_report_schedules_returns_health_summary` | GET `/reports/schedules/monitor` returns `{total, enabled, unhealthy, ...}` |
| `test_run_schedule_now_returns_200` | POST `/reports/schedules/{id}/run-now` returns 200 + `{schedule, history}` |
| `test_run_schedule_now_returns_404_for_unknown` | Non-existent ID returns 404 |
| `test_is_stale_returns_true_for_old_timestamp` | Timestamp older than 15 min returns `True` |
| `test_is_stale_returns_false_for_recent_timestamp` | Recent timestamp returns `False` |
| `test_is_stale_returns_true_for_none` | `None` returns `True` |

**Mocking strategy:** Patch all `postgres_store` functions with `MagicMock`. Patch `create_report_artifact` with `MagicMock`. Patch `resolve_artifact_path` and `Path.exists()` for download tests. Override `get_current_user` dependency.

---

#### `test_route_pipeline_bom.py`

**Module under test:** [`backend/app/api/v1/routes/pipeline_bom.py`](backend/app/api/v1/routes/pipeline_bom.py)

| Test function | Description |
|---|---|
| `test_list_pipeline_bom_returns_200` | GET `/pipeline-bom` returns 200 + list |
| `test_list_pipeline_bom_has_stub_header` | Response has `X-Stub-Data: true` header |
| `test_list_pipeline_bom_items_have_stub_flag` | Each item has `_stub: true` |
| `test_list_pipeline_bom_requires_auth` | No token returns 403 |

**Mocking strategy:** Override `get_current_user` dependency only.

---

#### `test_route_applications.py`

**Module under test:** [`backend/app/api/v1/routes/applications.py`](backend/app/api/v1/routes/applications.py)

| Test function | Description |
|---|---|
| `test_list_applications_returns_200` | GET `/applications` returns 200 + list |
| `test_list_applications_requires_auth` | No token returns 403 |
| `test_list_applications_filters_by_asset_group_for_non_admin` | Non-admin returns only permitted groups |
| `test_list_applications_returns_all_for_admin` | `PlatformAdmin` returns all items |

**Mocking strategy:** Patch `aggregate_list` with `AsyncMock`. Override `get_current_user` dependency.

---

#### `test_route_asset_groups.py`

**Module under test:** [`backend/app/api/v1/routes/asset_groups.py`](backend/app/api/v1/routes/asset_groups.py)

| Test function | Description |
|---|---|
| `test_list_asset_groups_returns_200` | GET `/asset-groups` returns 200 + list |
| `test_list_asset_groups_requires_auth` | No token returns 403 |
| `test_list_asset_groups_admin_returns_all` | `PlatformAdmin` returns all groups |
| `test_list_asset_groups_non_admin_filters_to_permitted` | Non-admin returns only permitted group IDs |

**Mocking strategy:** Patch `aggregate_list` with `AsyncMock`. Override `get_current_user` dependency.

---

#### `test_route_issues.py`

**Module under test:** [`backend/app/api/v1/routes/issues.py`](backend/app/api/v1/routes/issues.py)

| Test function | Description |
|---|---|
| `test_list_issues_returns_200` | GET `/issues` returns 200 + list |
| `test_list_issues_requires_auth` | No token returns 403 |
| `test_list_issues_filters_by_asset_group_for_non_admin` | Non-admin returns filtered by permitted groups |
| `test_list_issues_returns_all_for_admin` | `PlatformAdmin` returns all items |

**Mocking strategy:** Patch `aggregate_list` with `AsyncMock`. Override `get_current_user` dependency.

---

#### `test_route_scans.py`

**Module under test:** [`backend/app/api/v1/routes/scans.py`](backend/app/api/v1/routes/scans.py)

| Test function | Description |
|---|---|
| `test_list_scans_returns_200` | GET `/scans` returns 200 + list |
| `test_list_scans_requires_auth` | No token returns 403 |
| `test_list_scans_filters_by_asset_group_for_non_admin` | Non-admin returns filtered items |
| `test_list_scans_returns_all_for_admin` | `PlatformAdmin` returns all items |
| `test_dast_page_coverage_diagnostics_returns_200` | GET `/scans/dast-page-coverage-diagnostics` returns 200 |
| `test_dast_page_coverage_diagnostics_filters_items_for_non_admin` | Non-admin items filtered by asset group |

**Mocking strategy:** Patch `aggregate_list` and `get_endpoint_services` with `AsyncMock`. Patch `AsocReadService.diagnose_dast_page_coverage` with `AsyncMock`. Override `get_current_user` dependency.

---

## 3. Shared Fixtures — `conftest.py`

**File:** [`backend/tests/conftest.py`](backend/tests/conftest.py)

### 3.1 User Context Fixtures

```python
@pytest.fixture
def admin_user() -> UserContext:
    return UserContext(subject="admin@test.com", role="PlatformAdmin", asset_group_ids=["ag-1", "ag-2"])

@pytest.fixture
def security_manager_user() -> UserContext:
    return UserContext(subject="sm@test.com", role="SecurityManager", asset_group_ids=["ag-1"])

@pytest.fixture
def app_owner_user() -> UserContext:
    return UserContext(subject="owner@test.com", role="AppOwner", asset_group_ids=["ag-1"])

@pytest.fixture
def developer_user() -> UserContext:
    return UserContext(subject="dev@test.com", role="Developer", asset_group_ids=["ag-1"])

@pytest.fixture
def auditor_user() -> UserContext:
    return UserContext(subject="audit@test.com", role="Auditor", asset_group_ids=["ag-1"])
```

### 3.2 JWT Token Fixtures

```python
@pytest.fixture
def valid_local_jwt(monkeypatch) -> str:
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-32-chars-minimum-len!")
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "access_token_expire_minutes", 60)
    return create_access_token("testuser", "SecurityManager", ["ag-1"])

@pytest.fixture
def expired_local_jwt(monkeypatch) -> str:
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-32-chars-minimum-len!")
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    return create_access_token("testuser", "SecurityManager", ["ag-1"])

@pytest.fixture
def tampered_jwt(valid_local_jwt) -> str:
    parts = valid_local_jwt.split(".")
    sig = parts[2]
    parts[2] = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    return ".".join(parts)
```

### 3.3 FastAPI TestClient Fixtures

```python
@pytest.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def make_authed_client(app):
    def _factory(user: UserContext):
        app.dependency_overrides[get_current_user] = lambda: user
        return AsyncClient(app=app, base_url="http://test")
    yield _factory
    app.dependency_overrides.clear()

@pytest.fixture
async def authed_client(admin_user) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_current_user] = lambda: admin_user
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
```

### 3.4 Mock Store Fixtures

```python
@pytest.fixture
def fake_dashboard() -> dict:
    return {
        "id": "d-test-1", "name": "Test Dashboard",
        "widgets": [{"type": "kpi_card", "title": "Issues"}],
        "blueprint": {"status": "draft", "visibility": "team"},
        "owner": "admin@test.com",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }

@pytest.fixture
def fake_audit_event() -> dict:
    return {
        "id": "ae-test-1", "actor": "admin@test.com",
        "action": "dashboard.create", "resource_type": "dashboard",
        "resource_id": "d-test-1", "details": {},
        "created_at": "2025-01-01T00:00:00+00:00",
    }
```

### 3.5 Mock ASoC Data Fixtures

```python
@pytest.fixture
def fake_scans() -> list[dict]:
    return [
        {"id": "s-1", "name": "SAST Scan", "status": "completed", "scan_type": "SAST",
         "asset_group_id": "ag-1", "application_id": "app-1",
         "created_at": "2025-01-15T00:00:00Z", "duration_seconds": 420,
         "page_coverage": 0, "native_severity": "high"},
        {"id": "s-2", "name": "DAST Scan", "status": "completed", "scan_type": "DAST",
         "asset_group_id": "ag-1", "application_id": "app-1",
         "created_at": "2025-02-10T00:00:00Z", "duration_seconds": 3600,
         "page_coverage": 420, "native_severity": "critical"},
        {"id": "s-3", "name": "SCA Scan", "status": "failed", "scan_type": "SCA",
         "asset_group_id": "ag-2", "application_id": "app-2",
         "created_at": "2025-03-05T00:00:00Z", "duration_seconds": 185,
         "page_coverage": 0, "native_severity": "unknown"},
    ]

@pytest.fixture
def fake_issues() -> list[dict]:
    return [
        {"id": "i-1", "severity": "critical", "status": "Open",
         "asset_group_id": "ag-1", "application_id": "app-1",
         "opened_at": "2025-01-10T00:00:00Z", "closed_at": "",
         "mttr_days": 0, "vulnerability": "SQL Injection"},
        {"id": "i-2", "severity": "high", "status": "Open",
         "asset_group_id": "ag-1", "application_id": "app-1",
         "opened_at": "2025-02-01T00:00:00Z", "closed_at": "",
         "mttr_days": 0, "vulnerability": "XSS"},
        {"id": "i-3", "severity": "medium", "status": "closed",
         "asset_group_id": "ag-2", "application_id": "app-2",
         "opened_at": "2025-01-20T00:00:00Z",
         "closed_at": "2025-02-20T00:00:00Z", "mttr_days": 31, "vulnerability": "CSRF"},
    ]

@pytest.fixture
def fake_applications() -> list[dict]:
    return [
        {"id": "app-1", "name": "Payments API", "asset_group_id": "ag-1",
         "created_at": "2025-01-01T00:00:00Z"},
        {"id": "app-2", "name": "Portal Web", "asset_group_id": "ag-2",
         "created_at": "2025-02-01T00:00:00Z"},
    ]

@pytest.fixture
def fake_asset_groups() -> list[dict]:
    return [
        {"id": "ag-1", "name": "Production"},
        {"id": "ag-2", "name": "Staging"},
    ]
```

### 3.6 Settings Override Fixtures

```python
@pytest.fixture
def local_auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-32-chars-minimum-len!")

@pytest.fixture
def oidc_auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.example.com")
```

---

## 4. Dependency Requirements

Add the following to `[project.optional-dependencies] dev` in [`backend/pyproject.toml`](backend/pyproject.toml):

| Package | Version | Status |
|---|---|---|
| `pytest` | `>=8.3.0` | Already present |
| `pytest-asyncio` | `>=0.24.0` | Already present |
| `ruff` | `>=0.6.0` | Already present |
| `alembic` | `>=1.14.0` | Already present |
| `pytest-mock` | `>=3.14.0` | **NEW** |
| `pytest-cov` | `>=5.0.0` | **NEW** |
| `respx` | `>=0.21.0` | **NEW** |
| `freezegun` | `>=1.5.0` | **NEW** |

**Updated dev section:**

```toml
[project.optional-dependencies]
dev = [
  "alembic>=1.14.0",
  "pytest>=8.3.0",
  "pytest-asyncio>=0.24.0",
  "pytest-mock>=3.14.0",
  "pytest-cov>=5.0.0",
  "respx>=0.21.0",
  "freezegun>=1.5.0",
  "ruff>=0.6.0",
]
```

---

## 5. Mocking Strategy Reference

| What to mock | How | Where used |
|---|---|---|
| `get_current_user` FastAPI dependency | `app.dependency_overrides[get_current_user] = lambda: user` | All route tests |
| `postgres_store` functions | `monkeypatch.setattr("app.repositories.postgres_store.list_dashboards", mock)` | Route + scheduler tests |
| `AsocApiClient.get` | `mocker.patch.object(AsocApiClient, "get", new_callable=AsyncMock)` | Service + route tests |
| `httpx.AsyncClient.get` | `respx.mock` context manager | `test_auth.py` JWKS tests |
| `settings.*` fields | `monkeypatch.setattr(settings, "auth_mode", "oidc")` | Auth + dependency tests |
| `asyncio.create_task` | `mocker.patch("asyncio.create_task")` | Analytics background task tests |
| `Path.write_text` / `Path.exists` | `mocker.patch.object(Path, "write_text")` | Report artifact tests |
| `_JWKS_CACHE` module global | `monkeypatch.setattr("app.core.security.auth._JWKS_CACHE", {...})` | JWKS cache tests |
| `_DAST_PAGE_CACHE` module global | `monkeypatch.setattr("app.services.asoc_read_service._DAST_PAGE_CACHE", {})` | DAST cache tests |
| `datetime.now()` / `time.time()` | `freezegun.freeze_time("2025-06-01T00:00:00Z")` | TTL / expiry tests |

**Key principle:** Never mock what you are testing. Mock only the **boundary** (DB, HTTP, filesystem, time).

---

## 6. Priority Order

Implement test files in this order, based on risk and coverage impact:

| Priority | File | Rationale |
|---|---|---|
| **P1** | `tests/conftest.py` | Unblocks all other tests |
| **P1** | `tests/unit/test_policy.py` | Security-critical; pure logic; fast to write |
| **P1** | `tests/unit/test_authorization.py` | Security-critical; pure logic |
| **P1** | `tests/unit/test_auth.py` | JWT creation/validation is the auth boundary |
| **P1** | `tests/unit/test_dependencies.py` | `get_current_user` is called on every protected route |
| **P2** | `tests/unit/test_settings.py` | `all_asoc_endpoints()` has complex branching logic |
| **P2** | `tests/unit/test_schedule_utils.py` | Pure logic; unblocks scheduler tests |
| **P2** | `tests/unit/test_postgres_store.py` | Repository layer; high coverage impact |
| **P2** | `tests/unit/test_report_artifacts.py` | Path traversal security check |
| **P3** | `tests/unit/test_asoc_read_service.py` | Largest module; highest coverage gain |
| **P3** | `tests/unit/test_multi_endpoint.py` | Aggregation logic; error resilience |
| **P3** | `tests/unit/test_report_scheduler.py` | Retry/backoff logic |
| **P3** | `tests/unit/test_analytics_prewarm.py` | Worker lifecycle |
| **P4** | `tests/unit/routes/test_route_auth.py` | Auth routes |
| **P4** | `tests/unit/routes/test_route_dashboard.py` | Most complex route; CRUD + versions |
| **P4** | `tests/unit/routes/test_route_audit.py` | Pagination contract |
| **P4** | `tests/unit/routes/test_route_reports.py` | Schedule + artifact download |
| **P4** | `tests/unit/routes/test_route_analytics.py` | Cache key + filter normalization |
| **P5** | `tests/unit/routes/test_route_applications.py` | Simple proxy route |
| **P5** | `tests/unit/routes/test_route_asset_groups.py` | Simple proxy route |
| **P5** | `tests/unit/routes/test_route_issues.py` | Simple proxy route |
| **P5** | `tests/unit/routes/test_route_scans.py` | Diagnostics endpoint |
| **P5** | `tests/unit/routes/test_route_pipeline_bom.py` | Stub endpoint; minimal logic |

---

## 7. Coverage Targets

| Module group | Target | Rationale |
|---|---|---|
| `app/core/security/` | **>= 90%** | Auth boundary — highest risk |
| `app/repositories/postgres_store.py` | **>= 85%** | All CRUD paths must be exercised |
| `app/services/asoc_read_service.py` | **>= 80%** | Complex normalization logic |
| `app/services/multi_endpoint.py` | **>= 85%** | Error resilience paths |
| `app/services/report_artifacts.py` | **>= 90%** | Path traversal security |
| `app/workers/` | **>= 80%** | Retry/backoff logic |
| `app/api/v1/routes/` | **>= 75%** | Route-level RBAC enforcement |
| `app/core/config/settings.py` | **