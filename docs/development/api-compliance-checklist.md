# API Compliance Checklist (ASoC Swagger v4)

Last reviewed: 2026-04-15

## Scope
This checklist maps current backend routes to external ASoC Swagger v4 operations.

References:
- https://cloud.appscan.com/swagger/index.html
- https://cloud.appscan.com/swagger/v4/swagger.json

## Status Legend
- PASS: Route behavior aligns with v4 read patterns.
- INTERNAL: Route is dashboard-local and does not call ASoC.

## Route Compliance Snapshot
| Internal Endpoint | Method | ASoC Mapping | Status | Notes |
|---|---|---|---|---|
| `/api/v1/scans` | GET | `GET /api/v4/Scans` | PASS | Read-only scan listing. |
| `/api/v1/scans/dast-page-coverage-diagnostics` | GET | `GET /api/v4/Scans` (+ issue/coverage enrichment) | PASS | Debug/diagnostic read path only. |
| `/api/v1/applications` | GET | `GET /api/v4/Apps` | PASS | Supports data-source scoped aggregation. |
| `/api/v1/asset-groups` | GET | `GET /api/v4/AssetGroups` | PASS | Role and asset-group filtered. |
| `/api/v1/issues` | GET | `GET /api/v4/Issues/{scope}/{scopeId}` | PASS | Uses application-scoped issue aggregation. |
| `/api/v1/analytics/*` | GET | `GET /api/v4/Scans`, `GET /api/v4/Apps`, `GET /api/v4/Issues/{scope}/{scopeId}`, `GET /api/v4/Account/TenantInfo` | PASS | Includes statistics, trend/kpi/mttr, bundle, workbench, filter-options, issue-counts, chart-data, risk heatmap, top-apps, status distribution, technology breakdown, severity trend, findings/scan series. |
| `/api/v1/auth/current-user` | GET | `GET /api/v4/User`, `GET /api/v4/Account/TenantInfo` | PASS | Identity enrichment path stays read-only. |
| `/api/v1/endpoints/status` | GET | `POST /api/v4/Account/ApiKeyLogin` + read checks | PASS | Connectivity probe only; no data mutation. |
| `/api/v1/endpoints/identities` | GET | `GET /api/v4/User`, `GET /api/v4/Account/TenantInfo` | PASS | Multi-source identity cache/read path. |
| `/api/v1/endpoints/refresh-identities` | POST | Same read operations as identities path | PASS | Internal refresh trigger; still read-only against ASoC. |
| `/api/v1/auth/login`, `/api/v1/auth/mode` | POST/GET | None (local auth gateway) | INTERNAL | Local JWT/OIDC mode control. |
| `/api/v1/dashboards/*` | GET/POST/PUT/DELETE | None | INTERNAL | Stored in local DB with audit trail. |
| `/api/v1/reports/*` | GET/POST/PUT/DELETE | None currently | INTERNAL | Local schedule/history/artifact flows. |
| `/api/v1/audit/events` | GET | None | INTERNAL | Local audit retrieval. |
| `/api/v1/pipeline-bom` | GET | None | INTERNAL | Dashboard-local source. |
| `/api/v1/export/scans.csv` | GET | `GET /api/v4/Scans` via `aggregate_list()` | PASS | Streaming CSV; auth + asset-group scoped. No new ASoC calls. |
| `/api/v1/export/applications.csv` | GET | `GET /api/v4/Apps` via `aggregate_list()` | PASS | Streaming CSV; auth + asset-group scoped. No new ASoC calls. |
| `/api/v1/export/issues.csv` | GET | `GET /api/v4/Issues/{scope}/{scopeId}` via `aggregate_list()` | PASS | Streaming CSV; auth + asset-group scoped. No new ASoC calls. |
| `/api/v1/export/summary.csv` | GET | Multiple read endpoints (scans, apps, issues) | PASS | KPI pivot table + Top 20 apps. Auth + asset-group scoped. |

## Connector Guardrails
- Auth token retrieval uses `POST /api/v4/Account/ApiKeyLogin`.
- Read-only mode allows `GET`, and allows `POST` only for ApiKeyLogin.
- Any other mutating call pattern is blocked.
- Allowed endpoint families in read-only mode include:
  - `/api/v4/Scans`
  - `/api/v4/Apps`
  - `/api/v4/AssetGroups`
  - `/api/v4/Issues`
  - `/api/v4/Reports`
  - `/api/v4/User`
  - `/api/v4/Roles`
  - `/api/v4/Account/TenantInfo`

## Multi-Source Compliance Rules
- `data_source_ids` query parameter is optional on list and analytics routes.
- Source selection is validated against enabled records and limited to 20 IDs.
- Source-level SSL policy (`verify_ssl`) must be propagated into httpx calls.
- Aggregate routes must degrade gracefully on partial source failures.

## Known Internal-Only Areas
1. Report routes are local orchestration and artifact flows, not remote ASoC report job execution.
2. Pipeline BOM is currently dashboard-internal.
3. OIDC behavior depends on environment-provided issuer/JWKS/audience values.
