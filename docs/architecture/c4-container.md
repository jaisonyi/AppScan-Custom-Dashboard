# C4 Container

## Containers
- React Web UI: dashboards, analytics, reports
- FastAPI Backend: API, authorization, domain logic
- PostgreSQL: normalized analytics data
- Redis: cache and queue support
- Worker: scheduled ingestion and metrics recompute

## Security Boundary
ASoC integration is read-only and blocks mutating HTTP methods.

## ASoC Connector Boundary Details
- Allowed read prefixes: `/api/v4/Scans`, `/api/v4/Apps`, `/api/v4/AssetGroups`, `/api/v4/Issues`, `/api/v4/Reports`
- Allowed non-read exception in read-only mode: `POST /api/v4/Account/ApiKeyLogin`
- Data-model note: issues are fetched via scoped endpoint (`/api/v4/Issues/{scope}/{scopeId}`), aggregated per application.
