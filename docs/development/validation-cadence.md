# Multi-Team Validation Cadence

Last reviewed: 2026-04-15

## Review Teams
- Architecture Review Team
- Security and Compliance Team
- Data and Analytics Team
- QA and Operations Team

## Milestone Gate
A milestone is complete only when all four teams sign off against acceptance criteria.

## Required Validations
- RBAC and asset-group access checks
- Read-only ASoC API safety checks
- KPI and MTTR formula checks
- End-to-end dashboard and reporting checks
- Analytics cache freshness and performance checks
- Scheduler reliability checks (cron, retry/backoff, run-now path)
- Report artifact generation and download checks
- Data source management and multi-source aggregation checks

## Contract Validation Requirement
- Before feature validation starts, confirm connector compliance with:
	- `https://cloud.appscan.com/swagger/index.html`
	- `https://cloud.appscan.com/swagger/v4/swagger.json`

## Execution Order
1. Step 1: connectivity and read-only endpoint smoke tests.
2. Step 2: strict role matrix validation.
3. Step 3: OIDC mode and login-path validation.

## Ongoing Sprint Exit Checks
- Dashboard first-page view modes render correctly and preserve user preference.
- Cached analytics endpoint returns fast on repeated reads and refreshes correctly.
- Default dashboard view remains responsive after backend restart (no long blocking on cold key).
- No duplicate analytics request fan-out on a single UI refresh/apply flow.
- Scheduler and audit event flows remain observable in API responses.
- Sidebar scope filters update body metrics and charts consistently across all supported filter dimensions.
- Applications scope clear/apply behavior is validated end-to-end.
- Operations Workbench cards remain readable and arranged as two charts per row on desktop.
- Operations Workbench contract remains complete and visible in UI (license consumption, scan time bucket trends, SAST/SCA size profile, DAST coverage, rescanned top10).
- Workbench cards continue to render under empty/partial source datasets via fallback payload defaults.
- Freshness source behavior remains observable during normal and forced refresh paths for analytics/workbench responses.
- Current User pane continues to show `/api/v4/User` identity with tenant metadata enrichment.
- Endpoints management UX is validated for `/api/v1/endpoints`, `/api/v1/endpoints/manage`, `/api/v1/endpoints/status`, and identity refresh flows.

## CSV Export Validation (v1.4.3+)
- `GET /api/v1/export/scans.csv` returns 200 with valid CSV headers and rows.
- `GET /api/v1/export/applications.csv` returns 200 with valid CSV headers and rows.
- `GET /api/v1/export/issues.csv` returns 200 with valid CSV headers and rows.
- `GET /api/v1/export/summary.csv` returns KPI pivot table followed by Top 20 apps section.
- All export endpoints reject unauthenticated requests (401).
- All export endpoints enforce role-based access via `assert_action_allowed`.
- Asset-group scoping filters exported rows correctly per user scope.
- `data_source_ids` parameter scopes exports to selected sources.
- CSV output is parseable by PowerBI, Excel, and standard CSV libraries.

## Container and Deployment Validation (v1.4.3+)
- `docker build -f infra/docker/Dockerfile .` succeeds.
- `docker compose -f infra/compose/docker-compose.yml up -d` starts both containers.
- `curl http://localhost:8000/health` returns 200 from containerized app.
- `az bicep build --file infra/azure/main.bicep` validates without errors.
- Container runs as non-root user (verify with `docker exec ... whoami`).

## Multi-Data-Source Validation
- Data source management routes (`/api/v1/endpoints`) return correct CRUD responses
- Connection probe (`/api/v1/endpoints/status`) returns reachable/unreachable status accurately
- Multi-source aggregation returns merged items with `_data_source_id`/`_data_source_label` tags
- `data_source_ids` param filters sources correctly on list and analytics endpoints
- Invalid/disabled data source IDs are silently ignored (not error)
- Maximum 20 data source IDs enforced per request
- Analytics cache keys are scoped by `data_source_ids` (different selections produce separate snapshots)
- SSL verification disabled when `verify_ssl=false` in data source config (no `CERTIFICATE_VERIFY_FAILED`)
- Frontend sidebar reflects data source connection status in real-time
- Frontend checkbox selection triggers correct re-fetch with `data_source_ids` param
- Scope chip updates immediately on data source selection change
- Partial source failure degrades gracefully (remaining sources still respond)

## Validation Evidence Format
Each sprint-level validation report should include:
1. Commands executed (or test job links).
2. Endpoint list covered.
3. Role matrix covered.
4. Cache/refresh behavior summary.
5. Regressions found and mitigation status.
