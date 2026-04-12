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
	- `POST /api/v4/Account/ApiKeyLogin` for bearer token retrieval
	- `X-API-KEY: <KeyId>:<KeySecret>` fallback header when bearer retrieval fails

## Read-Only Enforcement
- Mutating methods are blocked in connector read-only mode.
- The only permitted `POST` is `POST /api/v4/Account/ApiKeyLogin` for session token acquisition.
- All dashboard data APIs are implemented as read routes only.

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
