# Installation Guide

## Prerequisites
- Python 3.12+
- Node.js 20+
- PostgreSQL 16+

## Local Data Storage
- Dashboard and report persistence uses PostgreSQL.
- For local development, PostgreSQL can be installed and initialized under the project root at `.postgres/`.
- Persisted entities include dashboards, dashboard versions, report templates, report schedules, report history, and audit events.
- Analytics responses are cached in database snapshots for fast page loads.
- Generated report artifacts are stored under `data/exports` and can be downloaded via API.
- Schedule cadence parsing uses `croniter` for standard cron expressions.
- The repository layer (`postgres_store.py`) uses a module-level connection with thread-safe locking — connections are reused across requests rather than opened per-request. An `atexit` handler closes the connection cleanly on shutdown.

## Project-Local PostgreSQL Setup
1. From repository root, run:
	- `scripts/postgres/install_local_postgres.sh`
2. This installs PostgreSQL binaries (via Homebrew when missing), initializes `.postgres/data`, starts DB on port `55432`, and creates DB `aspm`.
3. Runtime DB URL:
	- `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/aspm`
4. Helper scripts:
	- `scripts/postgres/start.sh`
	- `scripts/postgres/stop.sh`
	- `scripts/postgres/status.sh`

## Migrations (Alembic)
1. Install backend dev dependencies (includes Alembic).
2. Apply migrations from `backend/`:
	- `alembic -c alembic.ini upgrade head`
3. Create future migrations:
	- `alembic -c alembic.ini revision -m "describe change"`

## Configure Environment
1. Copy `.env.example` to `.env`.
2. Set `ASOC_SERVICE_URL`, `ASOC_API_KEY`, and `ASOC_API_SECRET` for the **primary** data source.
	- US cloud base: `https://cloud.appscan.com`
	- EU cloud base: `https://eu.cloud.appscan.com`
	- AppScan 360 base: your custom URL
	- Effective v4 endpoint pattern is `<ASOC_SERVICE_URL>/api/v4/...`
	- Legacy value `https://cloud.appscan.com/eu` is normalized to `https://eu.cloud.appscan.com`.
3. Keep `ASOC_READ_ONLY=true`.
4. Set `JWT_SECRET` to a long random string for production deployments.
	- If `JWT_SECRET` is **not** set, a secure random value is auto-generated at startup (`secrets.token_urlsafe(32)`) and a warning is logged.
	- **Important**: an auto-generated secret means all issued tokens are invalidated on every restart. Always set `JWT_SECRET` explicitly in production.
5. Choose auth mode:
	- `AUTH_MODE=local` (default): uses bootstrap login endpoint for local development.
	- `AUTH_MODE=oidc` (optional): local login is disabled; provide enterprise bearer token.
5. Scheduler options (enabled by default):
	- `REPORT_SCHEDULER_ENABLED=true`
	- `REPORT_SCHEDULER_INTERVAL_SECONDS=30`
 	- `REPORT_SCHEDULER_MAX_RETRIES=5`
 	- `REPORT_SCHEDULER_BACKOFF_BASE_SECONDS=60`
 	- `REPORT_SCHEDULER_BACKOFF_MAX_SECONDS=3600`
6. Analytics cache tuning:
	- `ANALYTICS_CACHE_TTL_SECONDS=180`
	- `ANALYTICS_CACHE_CLEANUP_INTERVAL_SECONDS=600`
	- Use `?refresh=true` on analytics endpoints for a forced refresh when needed.
7. For OIDC mode, set:
	- `OIDC_ISSUER_URL`
	- `OIDC_JWKS_URL` (optional if issuer discovery is available)
	- `OIDC_AUDIENCE` (optional, tenant-specific)
	- `OIDC_ROLE_CLAIM`, `OIDC_ASSET_GROUPS_CLAIM` (optional overrides)

## Backend
1. Create virtual environment.
2. Install dependencies from `backend/pyproject.toml`.
3. Run API: `uvicorn app.main:app --reload --port 8000`.
4. Verify DB connectivity by calling `GET /health` and one protected endpoint after login.
5. Scheduler loop starts with backend startup and executes due report schedules automatically.
6. Optional schedule operations:
	- `GET /api/v1/reports/schedules/monitor` for monitor widget data
	- `POST /api/v1/reports/schedules/{schedule_id}/run-now` to trigger immediate execution

## Frontend
1. Install dependencies in `frontend/`.
2. Run web app: `npm run dev`.
3. Default local access is HTTP:
	- `http://localhost:5173`
	- `https://localhost:5173` is not enabled by default.

## HTTPS Deployment Note (Planned Installer Capability)
- Current local/developer default remains HTTP for simplicity.
- Next installer enhancement will provide an explicit HTTPS mode selection during install:
	1. Self-signed certificate mode
	2. CA-authorized certificate mode (domain + certificate chain)
- Planned installer prompts for HTTPS mode:
	- Enable HTTPS? (yes/no)
	- If self-signed: generate cert/key automatically
	- If CA mode: collect domain, cert path, key path, optional chain path
	- Select HTTPS port and validate conflict
- Planned runtime policy:
	- If HTTPS is enabled, installer will validate files/ports first and notify before applying changes.
	- If conflicts are detected (port in use, invalid cert path, permission issue), installer will stop and request confirmation instead of forcing changes.
- Planned uninstall policy:
	- Remove only this dashboard instance by default.
	- Do not remove shared dependencies automatically when other instances are detected.

## First Login
- Use bootstrap login endpoint in local mode, then map role and accessible asset groups.

## Multi-Data-Source Configuration (v1.4.0+)
After initial setup, additional ASoC/AppScan 360 instances can be configured through the dashboard UI or API.

### Via Dashboard UI
1. Log in as PlatformAdmin or SecurityManager.
2. Open the Data Sources sidebar panel.
3. Click "Manage" to add, edit, or remove data source connections.
4. For each data source, provide: label, URL, API key, API secret, and SSL verification preference.
   - For AppScan 360 instances with self-signed or internal CA certificates, check **"Skip SSL verification (for self-signed / local TLS certs)"** in the Add/Edit form. This sets `verify_ssl: false` for that data source so the backend does not validate the TLS certificate chain.
   - Leave the checkbox unchecked (default) for standard ASoC cloud instances.
5. Use "Check Status" to verify connectivity before enabling.

### Via API
```bash
# Add a data source
curl -X POST http://127.0.0.1:8000/api/v1/endpoints \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"label": "EU Cloud", "url": "https://eu.cloud.appscan.com", "api_key": "...", "api_secret": "...", "verify_ssl": true}'

# Check connectivity
curl -X POST http://127.0.0.1:8000/api/v1/endpoints/<id>/check-status \
  -H "Authorization: Bearer <token>"

# List all data sources
curl http://127.0.0.1:8000/api/v1/endpoints \
  -H "Authorization: Bearer <token>"
```

### SSL Verification
- Set `verify_ssl: true` (default) for ASoC cloud instances with valid certificates.
- Set `verify_ssl: false` for AppScan 360 instances with self-signed or internal CA certificates.
- When disabled, the backend logs a warning per data source.

## OIDC Optional Flow
- Call `GET /api/v1/auth/mode` to verify backend mode and OIDC readiness.
- If mode is `oidc`, provide external bearer token from your IdP in the frontend token input.
- If OIDC settings are missing and mode is `oidc`, protected routes return `503` with missing fields.

## Docker Compose Deployment (v1.4.3+)

A single-command local stack is available via Docker Compose.

### Prerequisites
- Docker 24+ and Docker Compose v2

### Quick Start
```bash
cd infra/compose

# Start the full stack (PostgreSQL + dashboard)
docker compose up -d

# Verify
curl http://localhost:8000/health
```

### Environment Variables
Create `infra/compose/.env` or export these before running:
```bash
ASOC_SERVICE_URL=https://cloud.appscan.com
ASOC_API_KEY=<your-api-key>
ASOC_API_SECRET=<your-api-secret>
JWT_SECRET=<random-secret>
FRONTEND_ORIGIN=http://localhost:8000
```

### Ports
| Service | Host Port | Container Port |
|---|---|---|
| PostgreSQL | 55432 | 5432 |
| Dashboard App | 8000 | 8000 |

### Stopping
```bash
docker compose down        # stop containers
docker compose down -v     # stop + remove volumes (deletes DB data)
```

## Azure Deployment (v1.4.3+)

An Azure Bicep template deploys the production stack: App Service, PostgreSQL Flexible Server, Key Vault, and Application Insights.

### Prerequisites
- Azure CLI (`az`) authenticated
- A resource group created

### Deploy
```bash
az deployment group create \
  --resource-group <rg-name> \
  --template-file infra/azure/main.bicep \
  --parameters infra/azure/main.parameters.json \
  --parameters \
    baseName=aspm-dashboard \
    dbAdminPassword=<secure-password> \
    jwtSecret=<random-secret>
```

### Resources Created
| Resource | SKU | Purpose |
|---|---|---|
| App Service (Linux/Docker) | B1 (default) | Hosts dashboard container |
| PostgreSQL Flexible Server | B1ms, v16 | Application database |
| Key Vault | RBAC mode | Secrets management |
| Application Insights + Log Analytics | Default | Observability |

### Post-Deploy
1. Push Docker image to a container registry and configure App Service to pull it.
2. Set ASoC credentials in Key Vault secrets.
3. Verify `https://<webAppUrl>/health`.

## CSV Export for PowerBI / Excel (v1.4.3+)

Four streaming CSV endpoints are available for external BI tool integration.

### Endpoints
| Endpoint | Description |
|---|---|
| `GET /api/v1/export/scans.csv` | All scans with severity counts |
| `GET /api/v1/export/applications.csv` | All applications with risk rating and issue counts |
| `GET /api/v1/export/issues.csv` | All issues with CWE, location, dates |
| `GET /api/v1/export/summary.csv` | KPI pivot table + Top 20 apps |

### Usage
```bash
# Export scans to CSV
curl -o scans.csv http://127.0.0.1:8000/api/v1/export/scans.csv \
  -H "Authorization: Bearer <token>"

# Export with specific data sources
curl -o issues.csv "http://127.0.0.1:8000/api/v1/export/issues.csv?data_source_ids=<id1>&data_source_ids=<id2>" \
  -H "Authorization: Bearer <token>"
```

### PowerBI Integration
1. In PowerBI Desktop, use **Get Data → Web**.
2. Set URL to `http://<dashboard-host>:8000/api/v1/export/scans.csv`.
3. Under **Advanced**, add HTTP header: `Authorization: Bearer <token>`.
4. Set refresh schedule as needed.
