# Dependency Inventory

## Runtime Dependencies
- FastAPI ≥0.116
- httpx ≥0.28
- pydantic-settings
- psycopg ≥3.2 (PostgreSQL driver — raw SQL, no ORM)
- python-jose (JWT HS256)
- passlib (bcrypt)
- React 18.3
- Vite 5.4
- Recharts
- Axios

## Internal Modules (v1.4.0+)
- `data_source_store.py` — CRUD for the `data_sources` PostgreSQL table
- `multi_endpoint.py` — parallel aggregation across configured data sources
- `asoc_read_service.py` — read-only ASoC/AppScan 360 connector with `verify_ssl` support

## Internal Modules (v1.4.3+)
- `exports.py` — streaming CSV export routes for scans, applications, issues, and summary

## Infrastructure Dependencies (v1.4.3+)
- Docker 24+ / Docker Compose v2 — local container stack (`infra/compose/`)
- gunicorn + uvicorn workers — production ASGI server inside container
- Node 20-alpine — frontend build stage in multi-stage Dockerfile
- Python 3.12-slim — production runtime in Dockerfile
- Azure Bicep CLI — infrastructure-as-code for Azure deployment (`infra/azure/`)
- Azure App Service (Linux/Docker) — production hosting
- Azure Database for PostgreSQL Flexible Server v16 — managed database
- Azure Key Vault (RBAC mode) — secrets management
- Azure Application Insights + Log Analytics — observability

## External Dependencies
- ASoC / AppScan 360 API service URL(s) — one or more instances
- ASoC API key and secret per data source
- PostgreSQL ≥14 (stores users, data sources, analytics snapshots)
- OIDC identity provider (optional)
