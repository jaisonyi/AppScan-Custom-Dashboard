# C4 Component

## Backend Components
- API Routers
- Authorization Guard (RBAC + asset-group filters)
- ASoC Connectors (API + MCP)
- Domain Services (issues, scans, KPIs, MTTR)
- Reporting Engine
- Dashboard Template Engine

## ASoC Connector Responsibilities
- Enforce read-only method and endpoint allow-list.
- Authenticate using Swagger v4-compatible API key login to bearer token.
- Fallback to `X-API-KEY` header format if bearer login is unavailable.
- Normalize OData page responses (`Items`, `Count`) to internal service models.
- Aggregate scoped issues (`Application` scope) into dashboard-ready issue views.

## Frontend Components
- Module-driven feature pages
- Shared charting widgets
- Role-aware route guards
