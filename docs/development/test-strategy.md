# Test Strategy

Last reviewed: 2026-04-15

## Test Pyramid
- Unit: core business logic, route behavior, repository/service guards
- Integration: connector and DB interaction flows
- End-to-end: critical dashboard user journeys

## Current Unit Suite Snapshot
- Unit test files: 26
- Collected unit tests: 577
- Coverage gate: 60% (`backend/pyproject.toml`)

## Standard Commands
```bash
cd backend
python3 -m pip install -e '.[dev]'

# Fast unit suite
python3 -m pytest tests/unit/ -q --tb=short

# Coverage run
python3 -m pytest tests/unit/ -q --cov=app --cov-report=term-missing

# Count collected tests (sanity check)
python3 -m pytest tests/unit --collect-only -q | grep -E "::test_" | wc -l
```

## Current Unit Areas
- Security/auth:
  - `test_policy.py`, `test_authorization.py`, `test_auth.py`, `test_dependencies.py`
- Settings and repositories:
  - `test_settings.py`, `test_postgres_store.py`
- Services/workers:
  - `test_asoc_read_service.py`, `test_multi_endpoint.py`, `test_data_source_service.py`
  - `test_report_scheduler.py`, `test_analytics_prewarm.py`, `test_schedule_utils.py`, `test_report_artifacts.py`
- Integrations and safety:
  - `test_asoc_client_login.py`, `test_read_only_policy.py`
- Routes:
  - `tests/unit/routes/test_*.py` covering auth, analytics, scans, applications, asset groups, issues, dashboard, reports, audit, pipeline BOM, and data-source filtering

## Mocking and Fixtures
- HTTP client calls: `respx` with `httpx.AsyncClient`
- DB interactions: `pytest-mock` (`MagicMock`/`AsyncMock`)
- Time-sensitive logic: `freezegun`
- FastAPI dependency overrides for auth and DB
- Async tests: `pytest-asyncio` with `asyncio_mode = auto`

## Mandatory Validation Areas
- Role and asset-group authorization behavior
- Read-only connector guard (no non-login mutating ASoC calls)
- Analytics cache paths (build, hit, refresh override)
- Multi-data-source aggregation and `data_source_ids` filtering rules
- Report schedule lifecycle (CRUD, run-now, retries/backoff)
- Report artifact creation and download paths
- Current-user identity enrichment behavior

## ASoC Compatibility Checks
- Use `/api/v4/*` endpoints only.
- Allow POST only for `/api/v4/Account/ApiKeyLogin` in read-only mode.
- Handle non-JSON/unauthorized upstream responses without retrying mutating patterns.

## Sequential Validation Flow
1. Connectivity and read-only smoke checks.
2. Role-matrix authorization checks.
3. Auth-mode checks (`local` and `oidc` behavior).

## CSV Export Test Areas (v1.5e)
- Unit: verify CSV column headers and row content for each export endpoint.
- Unit: verify auth enforcement (reject unauthenticated and unauthorized requests).
- Unit: verify asset-group scoping filters items correctly.
- Unit: verify `data_source_ids` parameter is forwarded to `aggregate_list()`.
- Unit: verify `summary.csv` KPI pivot structure (Metric/Value format).
- Integration: verify streaming response produces valid CSV parseable by standard CSV libraries.

## Containerization Test Areas (v1.5e)
- Docker build: `docker build -f infra/docker/Dockerfile .` completes without errors.
- Docker Compose: `docker compose up -d` starts both PostgreSQL and dashboard containers.
- Health endpoint: `curl http://localhost:8000/health` returns 200 from containerized app.
- Azure Bicep: `az bicep build --file infra/azure/main.bicep` validates without errors.

## Performance Validation
- Compare first analytics call vs cached follow-up latency.
- Validate refresh path does not trigger duplicate heavy fetches.
- Validate scoped filter requests reuse prefetched data where applicable.
- Validate dashboard remains responsive during refresh and cache rebuild paths.
