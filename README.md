# AppScan Custom Dashboard

Documentation-first monorepo for a read-only HCL AppScan dashboard with multi-data-source aggregation.

## Core Principles
- Read-only integration for all external ASoC and AppScan 360 calls
- Multi-data-source support (endpoint registry with per-source SSL policy; UI toggle for self-signed cert environments)
- Role and asset-group scoped access controls on all data endpoints
- Cache-first analytics responses with refresh override paths
- Backend authorization and connector safety checks as non-negotiable guardrails

## Repository Layout
- `backend/` FastAPI backend, repositories, services, workers, Alembic migrations
- `frontend/` React + TypeScript dashboard UI
- `docs/` architecture, development, operations, continuity
- `scripts/` local setup helpers (including PostgreSQL bootstrap scripts)
- `infra/` deployment/runtime assets
- `data/` local export artifacts

## Backend Snapshot
- App entrypoint: `backend/app/main.py`
- API root: `/api/v1`
- Enabled route groups:
	- `/auth`, `/scans`, `/applications`, `/asset-groups`, `/issues`
	- `/analytics`, `/dashboards`, `/reports`, `/pipeline-bom`, `/audit`, `/endpoints`
- Startup jobs:
	- DB/table init + seed data
	- data source bootstrap from environment
	- optional scheduler and analytics prewarm workers
- Production static serving:
	- serves `frontend/dist` when built

## Persistence and Migrations
- Runtime DB: PostgreSQL (`DATABASE_URL`)
- Alembic migrations: `backend/migrations/versions/`
- Current migration chain:
	- `0001_initial_sqlite_schema.py`
	- `0002_schedule_retry_and_report_artifacts.py`
	- `0003_analytics_snapshots_cache.py`
	- `0004_data_sources.py`

## Local Development
1. Start local PostgreSQL:
	 - `scripts/postgres/install_local_postgres.sh`
	 - `scripts/postgres/start.sh`
2. Start backend:
	 - `cd backend`
	 - `python3 -m pip install -e '.[dev]'`
	 - `python3 -m uvicorn app.main:app --reload --port 8000`
3. Start frontend:
	 - `cd frontend`
	 - `npm install`
	 - `npm run dev`

## Installer
A pre-built source ZIP is available at the project parent directory:
- `AppScan-Custom-Dashboard-v0.1-source.zip` (38 MB) — includes all source files, migrations, and scripts required for a clean install

## Safety Guarantee
ASoC connector calls are read-only by policy and code guard. Mutating operations are blocked except token login (`POST /api/v4/Account/ApiKeyLogin`).

## Docker / Compose — One-Command Deployment

Files: Dockerfile + docker-compose.yml

Multi-stage build: Node 20 builds the React frontend → Python 3.12-slim runtime with gunicorn + non-root user + healthcheck.

Quick start:

cd infra/compose

# Create .env
cat > .env << 'EOF'
ASOC_API_URL=https://cloud.appscan.com
ASOC_API_KEY_ID=your-key-id
ASOC_API_KEY_SECRET=your-secret
JWT_SECRET=your-random-secret-minimum-32-chars
EOF

# Launch (PostgreSQL 16 + Dashboard)
docker compose up -d

# Access at http://localhost:8000


Stack: PostgreSQL 16-alpine (port 55432) + dashboard (port 8000) with persistent pgdata volume.

## Azure Bicep IaC — Production Cloud Deployment

File: main.bicep + main.parameters.json

Creates 5 Azure resources:

Resource	Purpose
App Service (B1, Linux/Docker)	Runs the dashboard container
PostgreSQL Flexible Server (B1ms, v16)	Application database
Key Vault (RBAC mode)	Stores JWT secret + DB password
Application Insights	Metrics & logging
Log Analytics Workspace	Centralized logs

Deploy:

az group create --name appscan-rg --location eastus

az deployment group create \
  --resource-group appscan-rg \
  --template-file infra/azure/main.bicep \
  --parameters infra/azure/main.parameters.json \
  --parameters dbAdminPassword="$(openssl rand -base64 24)" \
               jwtSecret="$(openssl rand -base64 32)"


App Service gets managed identity with Key Vault Secrets User role — no passwords in app settings.



## Related Docs
- `docs/development/coding-standards.md`
- `docs/development/test-strategy.md`
- `docs/development/api-compliance-checklist.md`
- `docs/operations/runbook.md`
