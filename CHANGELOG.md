# Changelog

## [1.4.3] - 2026-04-17

### Added
- **PowerBI-friendly CSV export endpoints** (`/api/v1/export`): four streaming CSV endpoints for external BI tool integration
  - `GET /api/v1/export/scans.csv` — all scans with ID, name, type, technology, status, dates, duration, severity counts
  - `GET /api/v1/export/applications.csv` — all applications with ID, name, risk rating, asset group, issue counts
  - `GET /api/v1/export/issues.csv` — all issues with ID, application, severity, status, type, dates, CWE, location
  - `GET /api/v1/export/summary.csv` — KPI pivot table (Metric/Value) + top 20 applications breakdown
  - All endpoints support `data_source_ids` query parameter for source-scoped exports
  - Auth enforced: `get_current_user` + `assert_action_allowed` on each endpoint
  - Asset-group scoping applied via `filter_by_asset_group()`
  - Response uses `StreamingResponse` with `text/csv` content type and `Content-Disposition` filename
- **Docker containerization** (`infra/docker/Dockerfile`): multi-stage build image
  - Stage 1: Node 20-alpine builds React frontend (`npm ci && npm run build`)
  - Stage 2: Python 3.12-slim production image with gunicorn + uvicorn workers
  - Non-root `dashboard` user, healthcheck on `/health`, `libpq5` for psycopg
- **Docker Compose local stack** (`infra/compose/docker-compose.yml`): full-stack local deployment
  - PostgreSQL 16-alpine + dashboard app container
  - Port mapping: 55432 (DB) and 8000 (app)
  - Environment-driven configuration: `DATABASE_URL`, `JWT_SECRET`, `FRONTEND_ORIGIN`, ASoC credentials
- **Azure Bicep IaC template** (`infra/azure/main.bicep`): production Azure deployment
  - App Service (Linux/Docker) with system-assigned managed identity
  - PostgreSQL Flexible Server (B1ms, v16) with firewall rules
  - Key Vault (RBAC mode) for secrets management
  - Application Insights + Log Analytics for observability
  - Parameters file: `infra/azure/main.parameters.json`

### Changed
- `backend/app/api/v1/router.py` — added `exports` router (`prefix="/export"`, `tags=["export"]`); now 12 route groups (was 11)
- Route count: **63 total routes** registered (was ~59)

---

## [1.4.2] - 2026-04-16

### Added
- **SSL verification toggle in Add/Edit endpoint form**: New "Skip SSL verification" checkbox in the Data Sources Manage modal allows connecting to AppScan 360 instances with self-signed or internal CA certificates
  - `epForm` state extended with `verify_ssl: true` (default — SSL verification on)
  - Checkbox label: "Skip SSL verification (for self-signed / local TLS certs)"; inverted UX: checking the box sets `verify_ssl: false`
  - `verify_ssl` threaded through form state → `api.ts` payload types → existing backend support (`EndpointCreateRequest.verify_ssl`, `EndpointUpdateRequest.verify_ssl`)
  - Backend support was already present since v1.4.0; this release completes the frontend exposure so users no longer need API calls to configure SSL policy
- **Status bar**: 5-file sync status indicator in the top bar shows live backend data source synchronisation state

### Fixed
- **Manage button not appearing after fresh install**: `getCurrentUser()` now executes in its own `try/catch` block before `refreshData()`, preventing a `refreshData()` failure from leaving `currentUser` as `null` and hiding the Manage button for PlatformAdmin users

### Changed
- `frontend/src/shared/services/api.ts` — `createEndpoint()` and `updateEndpoint()` payload types extended with `verify_ssl?: boolean`
- `frontend/src/app/App.tsx` — `epForm` state, all three reset locations, edit-load init, and save handler updated to carry `verify_ssl`
- 0 TypeScript errors after all changes

### Installer
- Source ZIP rebuilt: `AppScan-Custom-Dashboard-v0.1-source.zip` (38 MB) at project parent directory, including all v1.4.2 changes

---

## [1.4.1] - 2026-04-13

### Fixed
- **Data source identity probe ("Unable to verify identity")**: `refresh_api_user_info()` now extracts the API key owner's name, email, and role from `TenantInfo.UserInfo` instead of relying on `UserId` from the `ApiKeyLogin` response (which only returns `{Token, Expire}`)
  - Primary path: `GET /api/v4/Account/TenantInfo` → `UserInfo.FirstName` / `LastName` / `Email` / `IsAdmin`
  - Fallback path: `GET /api/v4/User/{id}` (used only if `TenantInfo.UserInfo` is absent)
  - `IsAdmin` boolean mapped to role string: `true` → "Administrator", `false` → "User"
  - Username fallback: if `FirstName`/`LastName` are empty, falls back to `UserInfo.Username`
- **Auth header exception handling**: `_get_auth_header()` in `AsocApiClient` now catches all `Exception` types (was limited to `AsocAuthenticationError | AsocResponseFormatError | AsocRequestError`), ensuring bearer-to-X-API-KEY fallback works for unexpected error types

### Changed
- `data_source_service.refresh_api_user_info()`: rewritten to extract identity from `TenantInfo.UserInfo` as primary source
- `AsocApiClient._get_auth_header()`: broadened exception clause from 3 specific types to `Exception`

### Tests
- New `test_data_source_service.py`: 9 tests covering UserInfo extraction, IsAdmin mapping, Username fallback, User endpoint fallback, and error handling
- New `test_asoc_client_login.py`: 9 tests covering bearer login, expiry, fallback to X-API-KEY, and owner UserId capture
- Total unit test count: **577 tests** across **26 test files** (was 543 across 23)

---

## [1.4.0] - 2026-04-12

### Added
- **Multi-data-source architecture**: Dashboard can now connect to multiple ASoC/AppScan 360 instances simultaneously
  - New `data_sources` PostgreSQL table and `data_source_store.py` repository for CRUD management
  - New `endpoints.py` route module: list, add, update, delete, and probe data sources
  - Enhanced `multi_endpoint.py` service: `_load_sources()`, `aggregate_list()`, `aggregate_tenant_info()`, `aggregate_base_data()` with per-source tagging
  - Items returned from list endpoints are tagged with `_data_source_id` and `_data_source_label` for origin tracking
  - Alembic migration for `data_sources` table with `verify_ssl` column
- **Data source filtering (Phase 2)**: Users can select which data sources to include in dashboard views
  - `data_source_ids` query parameter on all list routes (`/applications`, `/scans`, `/issues`, `/asset-groups`) and all 14 analytics endpoints
  - `_load_sources()` pre-filters by requested IDs before aggregation
  - Analytics cache key (`_build_cache_key` v18) incorporates `data_source_ids` for scoped snapshots
  - Frontend: interactive checkbox sidebar for data source selection with live connection status indicators
  - Frontend: "Sources: ..." scope chip showing active data source selection
  - Frontend: `_data_source_label` badges on application and asset group list items
  - `buildListPath()` and `buildAnalyticsPath()` helper functions for consistent query parameter construction
- New unit tests for multi-data-source features: 25 tests added across 6 test files
  - `test_multi_endpoint.py`: 27 tests total (was 17) — source filtering, tagging, security validation
  - `test_applications_routes.py`: 8 tests total (was 5) — data_source_ids forwarding
  - `test_scans_routes.py`: 11 tests total (was 9) — data_source_ids forwarding
  - `test_issues_routes.py`: 7 tests total (was 5) — data_source_ids forwarding
  - `test_asset_groups_routes.py`: 7 tests total (was 5) — data_source_ids forwarding
  - `test_analytics_routes.py`: 29 tests total (was 24) — cache key with data_source_ids
- New `test_read_only_policy.py` with 2 read-only enforcement tests
- Total unit test count: **543 tests** across **23 test files** (was 518 across 20)

### Security
- Data source ID validation: `_load_sources()` validates requested IDs against enabled data sources (prevents probing disabled/nonexistent sources)
- Maximum 20 data source IDs per request to prevent abuse
- SSL certificate verification (`verify_ssl`) properly threaded through the full service chain:
  - `AsocReadService.for_endpoint()` now accepts `verify` keyword argument
  - All 3 call sites in `multi_endpoint.py` pass `ds.get("verify_ssl", True)` to the service
  - Previously, `verify_ssl=false` in the database was honored by the "Check Status" probe but not by data-fetching operations

### Fixed
- SSL `CERTIFICATE_VERIFY_FAILED` error when fetching data from AppScan 360 instances with self-signed certificates — `verify_ssl` was stored in DB but not passed to the `AsocReadService` during data aggregation

### Changed
- `AsocReadService.for_endpoint()` signature: added `*, verify: bool | str = True` keyword argument
- `multi_endpoint.py` call sites now pass `verify=ds.get("verify_ssl", True)` to `AsocReadService.for_endpoint()`
- Frontend `App.tsx`: added `selectedDataSourceIds` state, sidebar checkbox interactions, scope chip, and list item badges

### Architecture
- New ADR: `ADR-0002-multi-data-source-architecture.md` — decision record for multi-instance aggregation pattern

---

## [1.3.1] - 2026-04-09

### Security
- Removed hardcoded developer email from user profile selection logic
- JWT secret now auto-generates a secure random value at startup when not configured; logs a warning
- Login endpoint validates requested role against allowed roles from policy
- Dashboard update and delete now use separate permission actions (`update_dashboard`, `delete_dashboard`)

### Fixed
- Renamed misleading `sqlite_store.py` to `postgres_store.py` (uses PostgreSQL, not SQLite)
- Fixed unbounded `_CACHE_LOCKS` dict growth in analytics module (bounded to 500 entries)
- Pipeline BOM endpoint now clearly marked as stub with `_stub: true` response field
- JWKS/OIDC configuration fetch converted from synchronous to async (no longer blocks event loop)

### Added
- Connection reuse in repository layer (module-level connection with thread-safe locking)
- Audit events endpoint now supports pagination (`offset`, `limit`, `total` in response)
- Structured logging in report scheduler (start/stop, execution, failures, retry/backoff)
- Structured logging in multi-endpoint aggregator (endpoint failures logged at WARNING)
- Comprehensive backend unit test suite: 518 tests across 20 test files
  - Security module tests: policy (77), authorization (20), auth (20), dependencies (12)
  - Settings/config tests (22) and PostgreSQL repository tests (59)
  - Service tests: ASoC read service (119), multi-endpoint (17), report artifacts (9)
  - Route/API tests: auth (15), dashboard (19), audit (8), analytics (24), reports (23), pipeline-bom (6), applications (5), asset-groups (5), issues (5), scans (9)
  - Worker tests: report scheduler (11), analytics prewarm (6), schedule utils (16)
  - Shared test fixtures in conftest.py (18 fixtures)
- Test plan documentation at `plans/PLAN.md`
- pytest configuration with coverage reporting in `backend/pyproject.toml`

### Changed
- `get_current_user` dependency is now async
- Audit events response format changed from flat list to `{items, offset, limit, total}` envelope
