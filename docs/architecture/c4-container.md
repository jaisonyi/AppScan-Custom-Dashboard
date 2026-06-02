# C4 Container

## Containers
- React Web UI: dashboards, analytics, reports, **data source selection UI**
- FastAPI Backend: API, authorization, domain logic, **multi-data-source aggregation**
- PostgreSQL: normalized analytics data, **data source connection configurations (`data_sources` table)**
- Redis: cache and queue support
- Worker: scheduled ingestion and metrics recompute

## Data Source Management Layer
- `data_source_store.py`: PostgreSQL CRUD repository for data source configurations
- `endpoints.py` routes: list, create, update, delete, and probe data sources via `/api/v1/endpoints`
- `multi_endpoint.py` service: aggregates data from all enabled data sources with parallel fetch and per-source failure isolation
- `AsocReadService.for_endpoint()`: creates per-source API client instances with correct SSL verification settings

## CSV Export Layer (v1.5e)
- `exports.py` routes: four streaming CSV endpoints under `/api/v1/export` for PowerBI / Excel / Tableau integration
- Endpoints: `scans.csv`, `applications.csv`, `issues.csv`, `summary.csv`
- Reuses the same read-only aggregation pipeline (`aggregate_list()`, `filter_by_asset_group()`) as the dashboard UI
- Auth enforced on every endpoint; asset-group scoping applied

## Deployment Topology (v1.5e)
- **Docker**: Multi-stage `Dockerfile` produces a single container (Node build → Python 3.12-slim runtime)
- **Docker Compose**: Local stack with PostgreSQL 16-alpine + dashboard app container
- **Azure Bicep**: Production stack — App Service (Linux/Docker), PostgreSQL Flexible Server, Key Vault, Application Insights

## Security Boundary
ASoC integration is read-only and blocks mutating HTTP methods. This policy applies to **all configured data sources**.

## ASoC Connector Boundary Details
- Allowed read prefixes: `/api/v4/Scans`, `/api/v4/Apps`, `/api/v4/AssetGroups`, `/api/v4/Issues`, `/api/v4/Reports`
- Allowed non-read exception in read-only mode: `POST /api/v4/Account/ApiKeyLogin`
- Data-model note: issues are fetched via scoped endpoint (`/api/v4/Issues/{scope}/{scopeId}`), aggregated per application.
