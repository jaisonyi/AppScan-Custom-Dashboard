# API Compliance Checklist (ASoC Swagger v4)

This page maps implemented backend endpoints to the exact ASoC Swagger v4 operations they rely on.

Source of truth: https://cloud.appscan.com/swagger/index.html

## Integration Rules

- Base URL: `${ASOC_SERVICE_URL}`
- Auth operation: `POST /api/v4/Account/ApiKeyLogin`
- Read-only data operations only: `GET`
- Allowed read prefixes:
  - `/api/v4/Scans`
  - `/api/v4/Apps`
  - `/api/v4/AssetGroups`
  - `/api/v4/Issues`
  - `/api/v4/Reports`

## Endpoint Mapping

| Dashboard Backend Endpoint | Implemented? | ASoC Swagger v4 Operation(s) | Compliance Status | Notes |
|---|---|---|---|---|
| `GET /api/v1/scans` | Yes | `GET /api/v4/Scans` | Compliant | Uses read-only client and asset-group filtering. |
| `GET /api/v1/applications` | Yes | `GET /api/v4/Apps` | Compliant | Uses read-only client and asset-group filtering. |
| `GET /api/v1/asset-groups` | Yes | `GET /api/v4/AssetGroups` | Compliant | Uses read-only client and role-based scope. |
| `GET /api/v1/issues` | Yes | `GET /api/v4/Issues/Application/{scopeId}` (scope pattern) | Compliant | Uses scoped issue retrieval per app and bounded fan-out. |
| `GET /api/v1/analytics/statistics` | Yes | Derived from `GET /api/v4/Scans` + `GET /api/v4/Issues/Application/{scopeId}` | Compliant | Computed metric endpoint, read-only source data. |
| `GET /api/v1/analytics/trend` | Yes | Derived from `GET /api/v4/Issues/Application/{scopeId}` | Compliant | Computed metric endpoint, read-only source data. |
| `GET /api/v1/analytics/kpi` | Yes | Derived from `GET /api/v4/Issues/Application/{scopeId}` | Compliant | Computed metric endpoint, read-only source data. |
| `GET /api/v1/analytics/mttr` | Yes | Derived from `GET /api/v4/Issues/Application/{scopeId}` | Compliant | Computed metric endpoint, read-only source data. |
| `GET /api/v1/analytics/portfolio-summary` | Yes | Derived from `GET /api/v4/Scans` + `GET /api/v4/Apps` + `GET /api/v4/AssetGroups` + `GET /api/v4/Issues/Application/{scopeId}` | Compliant | Computed summary endpoint with scope and time filters. |
| `GET /api/v1/auth/mode` | Yes | N/A (local backend endpoint) | N/A | Internal auth mode introspection. |
| `POST /api/v1/auth/login` | Yes | N/A (local backend endpoint) | N/A | Local mode only; blocked in OIDC mode. |
| `PUT /api/v1/dashboards/{dashboard_id}` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `DELETE /api/v1/dashboards/{dashboard_id}` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `GET /api/v1/dashboards` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `POST /api/v1/dashboards` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `GET /api/v1/dashboards/widget-registry` | Yes | N/A (internal registry) | Pending Integration | Returns pluggable widget definitions by role access. |
| `GET /api/v1/dashboards/templates` | Yes | N/A (internal persistence) | Pending Integration | Lists stored dashboard templates for wizard composition. |
| `POST /api/v1/dashboards/templates` | Yes | N/A (internal persistence) | Pending Integration | Creates reusable dashboard templates with scope/layout/widgets. |
| `POST /api/v1/dashboards/wizard/create` | Yes | N/A (internal composition) | Pending Integration | Creates dashboard using selected template and widget registry entries. |
| `GET /api/v1/reports/templates` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `POST /api/v1/reports/templates` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `DELETE /api/v1/reports/templates/{template_id}` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `POST /api/v1/reports/generate` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `GET /api/v1/reports/history` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |
| `GET /api/v1/reports/history/{report_id}/download` | Yes | N/A (current scaffold) | Pending Integration | Downloads generated artifact from local storage (`data/exports`). |
| `GET /api/v1/dashboards/{dashboard_id}/versions` | Yes | N/A (internal persistence) | Pending Integration | Dashboard version history from local repository. |
| `POST /api/v1/dashboards/{dashboard_id}/rollback/{version}` | Yes | N/A (internal persistence) | Pending Integration | Restores dashboard state from stored version and appends audit/version entries. |
| `GET /api/v1/reports/schedules` | Yes | N/A (internal persistence) | Pending Integration | Schedule listing from local repository. |
| `POST /api/v1/reports/schedules` | Yes | N/A (internal persistence) | Pending Integration | Schedule creation with role policy and audit event. |
| `PUT /api/v1/reports/schedules/{schedule_id}` | Yes | N/A (internal persistence) | Pending Integration | Schedule update with role policy and audit event. |
| `DELETE /api/v1/reports/schedules/{schedule_id}` | Yes | N/A (internal persistence) | Pending Integration | Schedule deletion with role policy and audit event. |
| `GET /api/v1/reports/schedules/monitor` | Yes | N/A (internal persistence) | Pending Integration | Returns schedule health summary, latest execution timestamps, and runs in last 24h. |
| `POST /api/v1/reports/schedules/{schedule_id}/run-now` | Yes | N/A (internal persistence) | Pending Integration | Manual immediate execution with report history and audit event creation. |
| `GET /api/v1/audit/events` | Yes | N/A (internal persistence) | Pending Integration | Audit trail reader for authorized roles. |
| `GET /api/v1/pipeline-bom` | Yes | N/A (current scaffold) | Pending Integration | Internal scaffold endpoint, no direct ASoC call. |

## Local Worker Coverage

- Background scheduler worker: `backend/app/workers/report_scheduler.py`
- Cron utility: `backend/app/workers/schedule_utils.py`
- Analytics cache snapshots: `analytics_snapshots` table in `data/aspm.db`
- Runtime behavior:
  - polls enabled schedules with due `next_run_at`
  - appends report history entries
  - writes report artifacts to `data/exports`
  - validates cron with `croniter` and updates `next_run_at` with exact next execution time
  - applies exponential retry backoff on failures and auto-disables schedules at max retries
  - writes `report_schedule.execute` audit events
  - stores scope-aware analytics bundles with TTL for fast repeated requests
  - supports explicit analytics refresh via `?refresh=true`

## Verification Checklist

- [x] Uses Swagger v4 paths only
- [x] Uses API key login operation for bearer-token retrieval
- [x] Enforces read-only operation policy (no mutation operations)
- [x] Retries by switching auth mode on unauthorized/non-JSON responses
- [x] Applies role and asset-group scope controls on all protected API routes
- [x] Supports optional OIDC mode without breaking local mode
