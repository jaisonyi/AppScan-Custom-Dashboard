# Test Strategy

## Test Pyramid
- Unit: domain logic and KPI formulas
- Integration: API routers, connectors, repositories
- End-to-end: core user journeys

## Current Unit Test Suite (v1.3.1)

### Running Tests
```bash
cd backend
pip install -e ".[dev]"
pytest tests/unit/ -v --cov=app --cov-report=term-missing
```

### Test File Inventory

| Test File | Tests | Module Under Test | Coverage |
|---|---|---|---|
| `tests/unit/test_policy.py` | 77 | `app/core/security/policy.py` | ~77% |
| `tests/unit/test_authorization.py` | 20 | `app/core/security/authorization.py` | ~100% |
| `tests/unit/test_auth.py` | 20 | `app/core/security/auth.py` | ~75% |
| `tests/unit/test_dependencies.py` | 12 | `app/core/security/dependencies.py` | ~100% |
| `tests/unit/test_settings.py` | 22 | `app/core/config/settings.py` | ~90% |
| `tests/unit/test_postgres_store.py` | 59 | `app/repositories/postgres_store.py` | ~89% |
| `tests/unit/test_asoc_read_service.py` | 119 | `app/services/asoc_read_service.py` | ~43% |
| `tests/unit/test_multi_endpoint.py` | 17 | `app/services/multi_endpoint.py` | ~80% |
| `tests/unit/test_report_artifacts.py` | 9 | `app/services/report_artifacts.py` | ~90% |
| `tests/unit/test_routes_auth.py` | 15 | `app/api/v1/routes/auth.py` | ~93% |
| `tests/unit/test_routes_dashboard.py` | 19 | `app/api/v1/routes/dashboard.py` | ~86% |
| `tests/unit/test_routes_audit.py` | 8 | `app/api/v1/routes/audit.py` | ~86% |
| `tests/unit/test_routes_analytics.py` | 24 | `app/api/v1/routes/analytics.py` | ~47% |
| `tests/unit/test_routes_reports.py` | 23 | `app/api/v1/routes/reports.py` | ~86% |
| `tests/unit/test_routes_pipeline_bom.py` | 6 | `app/api/v1/routes/pipeline_bom.py` | ~86% |
| `tests/unit/test_routes_applications.py` | 5 | `app/api/v1/routes/applications.py` | — |
| `tests/unit/test_routes_asset_groups.py` | 5 | `app/api/v1/routes/asset_groups.py` | — |
| `tests/unit/test_routes_issues.py` | 5 | `app/api/v1/routes/issues.py` | — |
| `tests/unit/test_routes_scans.py` | 9 | `app/api/v1/routes/scans.py` | — |
| `tests/unit/test_report_scheduler.py` | 11 | `app/workers/report_scheduler.py` | ~75% |
| `tests/unit/test_analytics_prewarm.py` | 6 | `app/workers/analytics_prewarm.py` | ~90% |
| `tests/unit/test_schedule_utils.py` | 16 | `app/workers/schedule_utils.py` | — |
| `tests/conftest.py` | 18 fixtures | Shared test fixtures | — |
| **Total** | **518** | **20 test files** | **~62% overall** |

### Coverage Targets

| Tier | Target | Current | Notes |
|---|---|---|---|
| Unit tests (overall) | 60% | ~62% | Threshold set in `backend/pyproject.toml` |
| Security modules | 80%+ | 75–100% | Policy, auth, authorization, dependencies |
| Repository layer | 80%+ | ~89% | `postgres_store.py` |
| Route handlers | 80%+ | 86–93% | Except `analytics.py` (47%) |
| `asoc_read_service.py` | 80%+ | ~43% | Requires integration tests (1343 statements) |
| `analytics.py` routes | 80%+ | ~47% | Requires integration tests (935 statements) |
| Integration tests | 80%+ | 0% | **Not yet implemented** |

### Mocking Strategy
- **HTTP calls**: `respx` for mocking `httpx.AsyncClient` requests to ASoC API
- **Database**: `pytest-mock` (`MagicMock`/`AsyncMock`) for `psycopg` connection and cursor objects
- **Time**: `freezegun` for deterministic datetime-dependent logic
- **FastAPI dependencies**: `app.dependency_overrides` to inject mock auth/DB dependencies
- **Async**: `pytest-asyncio` with `asyncio_mode = "auto"` for all async test functions
- **Fixtures**: 18 shared fixtures in `tests/conftest.py` (mock settings, mock DB, mock HTTP client, sample data payloads)

## Mandatory Checks
- Authorization matrix tests for role and asset-group access
- ASoC connector safety tests to block non-read-only calls
- Report generation and dashboard widget rendering tests
- Repository persistence tests for dashboard versions, report schedules, and audit events
- Migration smoke checks (`alembic upgrade head`) against a clean local database
- Analytics snapshot cache tests (first-call build, second-call cache hit, refresh override)
- Scheduler execution tests (due schedule processing, next run computation, retry/backoff)
- Report artifact tests (file creation, metadata persistence, download endpoint)
- Frontend mode persistence tests (local storage restore for dashboard view mode)
- Current User panel tests (identity from `/api/v4/User`, tenant metadata from `/api/v4/Account/TenantInfo`)
- Scope filter correctness tests for all sidebar dimensions:
	- applications
	- asset groups
	- issues technology/vulnerability
	- scans type/status
	- reports time window
- Workbench trend dataset tests:
	- cumulative vulnerabilities
	- application compliance
	- vulnerabilities criticality
	- application onboarded
	- average days to resolve
	- license consumption by technology with model metadata
	- scan time trend payload v2:
		- period options (`week`, `month`, `year`)
		- bucket options (`<5m`, `5-10m`, `10-30m`, `30-60m`, `60-120m`, `120-240m`, `240-300m`, `>=300m`)
		- per-bucket technology counts (`sast`, `sca`, `dast`, `total`)
	- SAST/SCA app/file size bucket distribution and top10
	- DAST page coverage bucket distribution and top10
	- most frequently rescanned top10
	- legacy snapshot shape hydration into normalized workbench v2 response
	- frontend mapping check: License Consumption renders `Applications Tested` from `consumed_apps` and `Scans Executed` from `consumed_scans` for DAST/SAST/SCA/IAST
	- frontend mapping check: Scan Time Bucket Trends renders 3 trend lines (SAST/SCA/DAST) for selected bucket and selected period
	- extractor unit tests for duration field-name variants: `DurationSeconds` (as-is), `ExecutionMinutes` × 60, `DurationMinutes` × 60 — verify each produces correct `duration_seconds` float
	- extractor unit tests for SAST size field-name variants: `nFiles`, `NumFiles`, `FilesAnalyzed` — verify each populates `file_size_profile` buckets
	- extractor unit tests for SCA size field-name variants: `nPackages`, `LibraryCount`, `ModuleCount` — verify each populates `file_size_profile` buckets
	- DAST chart rendering test: `scan_count` Line visible when `page_count` is 0 (cache cold) and both lines visible when both are populated
	- mock mode normalization test: items from `mock_data.scans()` must pass through the same field-name mapper as live ASoC data; raw `ScanType`/`ExecutionMinutes`/`NVisitedPages` fields must map to normalized `scan_type`/`duration_seconds`/`page_coverage` before reaching analytics consumers
	- DAST page-count cache TTL test: verify `_DAST_PAGE_CACHE_TTL_SECONDS >= 3600` and that enrichment cache outlives base data cache TTL

## ASoC Compatibility Checks
- Verify connector uses `/api/v4/*` endpoints only.
- Verify `POST /api/v4/Account/ApiKeyLogin` is the only allowed POST in read-only mode.
- Verify non-JSON and unauthorized responses are handled without mutating retries.

## Sequential Validation Flow
1. Step 1: run read-only connectivity smoke tests on list and analytics endpoints.
2. Step 2: run centralized role-matrix allow/deny checks.
3. Step 3: run auth-mode checks (`local` and `oidc`) including local-login lockout in OIDC mode.

## Performance Validation
- Capture elapsed time for first analytics summary call and second cached call.
- Keep periodic checks to ensure cache TTL and refresh paths still produce current data.
- Validate no duplicate analytics fetch fan-out on a single dashboard refresh/apply action.
- Validate default-view cold key fallback returns quickly from latest known snapshot.
- Validate `/api/v1/analytics/workbench-trends?refresh=true` returns rebuilt payload and freshness source transitions as expected.
- Validate scoped filter apply path does not perform duplicate per-application issue fetches inside a single analytics bundle build.
- Validate refresh action triggers a single forced analytics rebuild path and reuses refreshed cache for remaining sections.
- Validate statistics tiles remain populated after refresh completes (no empty-state regression caused by refresh contention).
- Validate Refresh Live keeps statistics visible while refresh is in progress (non-blocking UI behavior).
- Validate local dev host compatibility: dashboard works from both `http://localhost:5173` and `http://127.0.0.1:5173` with successful analytics GET responses.

## Installer Validation
- Linux installer smoke test:
	- dependency checks
	- package extraction
	- `.env` bootstrap prompt flow
	- port conflict prompt flow (API/web/database)
	- backend/frontend start checks
- macOS installer smoke test:
	- dependency checks
	- package extraction
	- `.env` bootstrap prompt flow
	- port conflict prompt flow (API/web/database)
	- backend/frontend start checks
- Windows installer smoke test:
	- dependency checks
	- package extraction
	- `.env` bootstrap prompt flow
	- port conflict prompt flow (API/web/database)
	- backend/frontend start checks
- Uninstall safety checks:
	- instance-only uninstall by default
	- dependency removal is skipped or confirmed when other dashboard instances are detected
- Planned HTTPS installer coverage (next iteration):
	- self-signed certificate generation and startup validation
	- CA certificate path validation (domain/cert/key/chain)
	- HTTPS port conflict detection and confirm-before-apply behavior
- Verify installer output archives do not include:
	- `.env`
	- local DB files
	- logs
	- runtime pid/socket artifacts
