# System Overview

## Mission
Deliver an extensible ASPM dashboard for HCL AppScan on Cloud with role-aware and asset-group-aware visibility, custom dashboards, and custom reporting.

## Architectural Style
- Modular monolith with plugin boundaries
- API-first contracts (OpenAPI)
- Event hooks for extension points

## Non-Functional Requirements
- Strict read-only ASoC integration
- Horizontal scalability for analytics workloads
- Multi-team continuity via living documentation
- Auditability for access and report generation
- Fast first-page rendering with database-backed analytics snapshots

## ASoC API Contract Baseline
- Source of truth: https://cloud.appscan.com/swagger/index.html
- OpenAPI spec: https://cloud.appscan.com/swagger/v4/swagger.json
- Supported read entities in this dashboard: `Scans`, `Apps`, `AssetGroups`, `Issues`, `Reports`
- Authentication follows Swagger v4 contract:
	- `POST /api/v4/Account/ApiKeyLogin` for bearer token retrieval (returns `{Token, Expire}` — does not include `UserId`)
	- `X-API-KEY: <KeyId>:<KeySecret>` fallback header when bearer retrieval fails (any exception triggers fallback)

## Multi-Data-Source Architecture
- The dashboard supports connecting to **multiple ASoC/AppScan 360 instances** simultaneously.
- Connection configurations are stored in the `data_sources` PostgreSQL table, managed via `/api/v1/endpoints` CRUD routes.
- Each data source has: URL, API key, API secret, display label, enabled flag, and `verify_ssl` option.
- The `multi_endpoint.py` service layer aggregates data from all enabled sources:
  - `_load_sources()` reads enabled sources with optional `data_source_ids` filtering (validated, capped at 20).
  - `aggregate_list()` fetches from each source in parallel, tags items with `_data_source_id` and `_data_source_label`.
  - Per-source failures are logged at WARNING but do not block other sources (graceful degradation).
- List endpoints (`/applications`, `/scans`, `/issues`, `/asset-groups`) and all 14 analytics endpoints accept `data_source_ids` query parameter for scoped views.
- Analytics cache keys incorporate `data_source_ids` for separate snapshots per selection.
- SSL verification (`verify_ssl`) is threaded through: `data_source_store` → `multi_endpoint` → `AsocReadService.for_endpoint()` → `AsocApiClient` → `httpx`.
- See ADR-0002 for the full decision record.

## Data Source Identity Probing
- Each data source has a per-source identity probe that determines the API key owner's name, email, and role.
- Identity is extracted primarily from `GET /api/v4/Account/TenantInfo` → `UserInfo` object:
  - `UserInfo.FirstName` + `UserInfo.LastName` → `api_user_name` (fallback: `UserInfo.Username`)
  - `UserInfo.Email` → `api_user_email`
  - `UserInfo.IsAdmin` → `api_user_role` (`true` = "Administrator", `false` = "User")
- Fallback: if `TenantInfo.UserInfo` is absent, attempts `GET /api/v4/User/{id}` using the `owner_user_id` from `ApiKeyLogin` (note: `ApiKeyLogin` often returns only `{Token, Expire}` without a `UserId`).
- Identity refresh has two modes:
  - **Stale refresh** (`refresh_stale_identities`): re-probes only sources whose `last_probed_at` exceeds the TTL (`identity_probe_ttl_seconds`, default 86400s / 24 hours). Called automatically by `GET /endpoints/identities?auto_refresh_stale=true`.
  - **Force refresh** (`refresh_all_api_user_info`): re-probes all enabled sources regardless of TTL.
- Results are cached in the `data_sources` table: `api_user_name`, `api_user_role`, `api_user_email`, `tenant_name`, `last_probed_at`, `last_probe_ok`.
- The frontend sidebar displays identity info per data source, showing "Unable to verify identity" when `last_probe_ok` is false and name/role fields are empty.

## Read-Only Enforcement
- Mutating methods are blocked in connector read-only mode.
- The only permitted `POST` is `POST /api/v4/Account/ApiKeyLogin` for session token acquisition.
- All dashboard data APIs are implemented as read routes only.
- The read-only policy applies uniformly to **all configured data sources**.

## Authentication Modes
- Local mode (default): internal bootstrap login for development and testing.
- OIDC mode (optional): external bearer token validation via issuer/JWKS. The JWKS/OIDC configuration fetch is performed asynchronously (`httpx.AsyncClient`) to avoid blocking the event loop.
- OIDC readiness is exposed by `GET /api/v1/auth/mode`.
- If `AUTH_MODE=oidc` but required OIDC settings are missing, protected routes return `503` with missing setting names.
- **JWT secret**: if `JWT_SECRET` is not set in the environment, a secure random value is auto-generated at startup via `secrets.token_urlsafe(32)` and a warning is logged. Tokens will be invalidated on restart unless `JWT_SECRET` is explicitly configured.
- **Login role validation**: `POST /auth/login` validates the requested `role` field against the allowed roles defined in `ROLE_ACTION_POLICY`. Requests with an unrecognised role are rejected.

## Repository Layer
- The persistence repository module is `postgres_store.py` (located at `backend/app/repositories/postgres_store.py`). The file was previously named `sqlite_store.py` — that name was misleading as the store has always used PostgreSQL.
- The repository uses a module-level connection with thread-safe locking and `atexit` cleanup for connection reuse across requests (no per-request connection overhead).

## Dashboard and Reporting Extensibility
- Dashboard APIs support list/create/update/delete with role checks.
- **Dashboard update and delete use separate permission actions**: `update_dashboard` and `delete_dashboard` are distinct entries in `ROLE_ACTION_POLICY` (`policy.py`), enforced by the PUT and DELETE endpoints respectively.
- Dashboard blueprint metadata is now persisted per dashboard: status, visibility, asset-group scope, layout, source template, and version marker.
- Widget registry is exposed by API for pluggable widget composition without code changes.
- Dashboard templates are persisted and can be used as wizard starters.
- Dashboard wizard creation flow combines template widgets and selected registry widgets into a new dashboard blueprint.
- Dashboard version history is stored for layout and metadata change tracking.
- Reporting APIs support template list/create/delete, generation history, and report schedule CRUD.
- Schedule monitor and manual run APIs are available for operations visibility and control.
- Scheduler applies retry/backoff policy for failures and disables schedules after max retries.
- Report execution stores downloadable JSON artifacts under `data/exports` and exposes a secure download endpoint.
- Analytics endpoints use shared bundle snapshots stored in `analytics_snapshots` table to avoid repeated heavy ASoC pulls.
- Analytics cache supports TTL and explicit refresh (`?refresh=true`) to balance speed with data freshness.
- DAST page-count enrichment uses a separate in-memory cache (`_DAST_PAGE_CACHE`) with TTL set to `max(3600, base_cache_ttl * 4)` to ensure enrichment data outlives the base data cache; this prevents the page-count series from going all-zero while scan-count data remains populated.
- Scan duration normalization is 3-phase: seconds-named fields are used as-is; minutes-named fields (`ExecutionMinutes`, `DurationMinutes`, etc.) are multiplied by 60; ambiguous fields are used as-is. ASoC commonly returns `ExecutionMinutes` for scan duration.
- SAST and SCA size profiles are extracted from a wide set of ASoC field name variants (`nFiles`, `NumFiles`, `FilesAnalyzed`, `nPackages`, `LibraryCount`, etc.) to accommodate ASoC API response inconsistencies across scan types and versions.
- Mock data items use raw ASoC-style field names and flow through the same normalizer mapper as live data to ensure analytics consumers receive correctly normalized field names.
- Persistence is database-backed on PostgreSQL using repository boundaries and Alembic migrations.
- Audit events are recorded for dashboard and reporting mutations.
- **Pipeline BOM** (`GET /api/v1/pipeline-bom`): currently a stub endpoint. Responses include `"_stub": true` and `"_stub_message"` fields, and the `X-Stub-Data: true` response header, to clearly distinguish stub data from live data.
- **Audit pagination**: `GET /audit/events` supports an `offset` parameter and returns a `{items, offset, limit, total}` envelope.

## Observability
- **Report scheduler**: emits structured log entries for scheduler start/stop, each execution attempt, failures, and retry/backoff decisions.
- **Multi-endpoint aggregator**: `aggregate_list` and `aggregate_tenant_info` log individual endpoint failures at `WARNING` level, enabling per-source failure visibility without masking partial results.

## UX Persistence
- Dashboard first-page view mode (`General`, `Larger Chart`, `SOC Style`) is persisted in browser local storage.
- Users return to their preferred default view automatically on reload.

## CSV Export for External BI Tools (v1.4.3+)
- Four streaming CSV endpoints under `/api/v1/export` provide PowerBI / Excel / Tableau-friendly data extraction.
- Endpoints: `scans.csv`, `applications.csv`, `issues.csv`, `summary.csv`.
- Each endpoint reuses the same read-only aggregation (`aggregate_list()`, `aggregate_issue_counts()`, `aggregate_top_apps()`) and asset-group scoping (`filter_by_asset_group()`) as the dashboard UI.
- Auth enforced on every endpoint: `get_current_user` + `assert_action_allowed`.
- `data_source_ids` query parameter supported for source-scoped exports.
- Responses use `StreamingResponse` with `text/csv` content type and timestamped `Content-Disposition` filenames.
- `summary.csv` is a KPI pivot table (Metric/Value rows) followed by a Top 20 Applications breakdown.
- No new ASoC API calls introduced — export endpoints consume the same cached / aggregated data as the UI.

## Containerization and Cloud Deployment (v1.4.3+)
- **Docker**: Multi-stage `Dockerfile` at `infra/docker/Dockerfile`.
  - Stage 1: Node 20-alpine builds the React frontend (`npm ci && npm run build`).
  - Stage 2: Python 3.12-slim production image with gunicorn + uvicorn workers, non-root `dashboard` user, healthcheck on `/health`.
- **Docker Compose**: `infra/compose/docker-compose.yml` provides a full-stack local deployment (PostgreSQL 16-alpine + dashboard app) for testing and demos.
- **Azure Bicep**: `infra/azure/main.bicep` deploys the production stack:
  - App Service (Linux/Docker) with system-assigned managed identity.
  - PostgreSQL Flexible Server (B1ms, v16) with firewall rules.
  - Key Vault (RBAC mode) for secrets management.
  - Application Insights + Log Analytics for observability.
- All infrastructure files are parameterized for environment-specific configuration.
