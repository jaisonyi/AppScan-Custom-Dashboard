# C4 Component

## Backend Components
- API Routers
- Authorization Guard (RBAC + asset-group filters)
- ASoC Connectors (API + MCP)
- **Data Source Store** (`data_source_store.py`): PostgreSQL CRUD for multi-instance connection configs
- **Multi-Endpoint Service** (`multi_endpoint.py`): parallel aggregation across data sources with tagging and failure isolation
- **Endpoint Management Routes** (`endpoints.py`): data source CRUD + connection probe
- Domain Services (issues, scans, KPIs, MTTR)
- Reporting Engine
- Dashboard Template Engine

## ASoC Connector Responsibilities
- Enforce read-only method and endpoint allow-list.
- Authenticate using Swagger v4-compatible API key login to bearer token.
- Fallback to `X-API-KEY` header format if bearer login fails (catches all exception types for maximum resilience).
- Normalize OData page responses (`Items`, `Count`) to internal service models.
- Aggregate scoped issues (`Application` scope) into dashboard-ready issue views.
- Support per-instance SSL verification configuration (`verify_ssl` threaded from DB to `httpx`).
- Extract API key owner identity from `TenantInfo.UserInfo` (name, email, role) for per-data-source identity display.

## Multi-Data-Source Aggregation Flow
1. `_load_sources()` reads enabled sources from DB, optionally filtered by `data_source_ids` (max 20, validated).
2. `aggregate_list()` creates per-source `AsocReadService` instances, fetches in parallel, tags items with `_data_source_id` / `_data_source_label`.
3. Per-source failures logged at WARNING; partial results returned from healthy sources.
4. Analytics pipelines use `aggregate_base_data()` with same source filtering and cache key scoping.

## CSV Export Components (v1.5e)
- **Export Routes** (`exports.py`): four `GET` endpoints producing streaming CSV via `StreamingResponse`
- Column definitions: `_SCAN_COLUMNS`, `_APP_COLUMNS`, `_ISSUE_COLUMNS` with `(key, header)` tuples
- `summary.csv` returns a KPI pivot table (Metric/Value rows) + Top 20 Applications breakdown
- Reuses `aggregate_list()`, `aggregate_issue_counts()`, `aggregate_top_apps()` from existing domain services
- Auth: `get_current_user` + `assert_action_allowed()` per endpoint; `filter_by_asset_group()` on all list data

## Infrastructure Components (v1.5e)
- **Dockerfile** (`infra/docker/Dockerfile`): multi-stage build — Node 20-alpine (frontend) → Python 3.12-slim (runtime), gunicorn + uvicorn workers, non-root user
- **Docker Compose** (`infra/compose/docker-compose.yml`): PostgreSQL 16-alpine + dashboard app, environment-driven config
- **Azure Bicep** (`infra/azure/main.bicep`): App Service + PostgreSQL Flexible Server + Key Vault (RBAC) + Application Insights

## Frontend Components
- Module-driven feature pages
- Shared charting widgets
- Role-aware route guards
- **Data Source Sidebar**: interactive checkboxes with live connection status, scope chip, and list item badges
