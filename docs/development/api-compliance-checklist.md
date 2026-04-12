# API Compliance Checklist (ASoC Swagger v4)

## Scope
This checklist maps each implemented backend API endpoint to the exact AppScan on Cloud Swagger v4 operation(s) it uses.

Sources:
- https://cloud.appscan.com/swagger/index.html
- https://cloud.appscan.com/swagger/v4/swagger.json

## Compliance Status Legend
- PASS: Endpoint path and auth model match Swagger v4.
- N/A (Internal): Endpoint is dashboard-internal and does not call ASoC directly.

## Checklist
| Internal Endpoint | Method | Backend Handler | ASoC Swagger v4 Operation(s) | Status | Notes |
|---|---|---|---|---|---|
| /api/v1/scans | GET | routes/scans.list_scans | GET /api/v4/Scans (`Scans_Get`) | PASS | Uses read-only connector with allow-list protection. |
| /api/v1/applications | GET | routes/applications.list_applications | GET /api/v4/Apps (`Apps_Get`) | PASS | Uses OData pagination via `$top`. |
| /api/v1/asset-groups | GET | routes/asset_groups.list_asset_groups | GET /api/v4/AssetGroups (`AssetGroups_Get`) | PASS | Filtered by role and accessible asset groups. |
| /api/v1/issues | GET | routes/issues.list_issues | GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Implemented as application-scoped aggregation: `/api/v4/Issues/Application/{appId}`. |
| /api/v1/analytics/statistics | GET | routes/analytics.statistics | GET /api/v4/Scans (`Scans_Get`), GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Computed from read-only datasets. |
| /api/v1/analytics/trend | GET | routes/analytics.trend_chart | GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Derived metric; no write action. |
| /api/v1/analytics/kpi | GET | routes/analytics.kpi_chart | GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Derived metric; no write action. |
| /api/v1/analytics/mttr | GET | routes/analytics.mttr_chart | GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Derived metric; no write action. |
| /api/v1/analytics/workbench-trends | GET | routes/analytics.workbench_trends | GET /api/v4/Scans (`Scans_Get`), GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`), GET /api/v4/Apps (`Apps_Get`), GET /api/v4/Account/TenantInfo (`Account_TenantInfo`) | PASS | Serves normalized workbench trend datasets including model-aware license consumption, bucketed scan-time trends, SAST/SCA size buckets + top10, DAST page-coverage buckets + top10, and rescanned top10. |
| /api/v1/analytics/findings-series | GET | routes/analytics.findings_series | GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Period bucketed findings trend (week/month/year). |
| /api/v1/analytics/scan-series | GET | routes/analytics.scan_series | GET /api/v4/Scans (`Scans_Get`), GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Period bucketed scan trend (day/week/month) with severity-source modes (`derived`, `native`, `hybrid`). |
| /api/v1/analytics/filter-options | GET | routes/analytics.filter_options | GET /api/v4/Scans (`Scans_Get`), GET /api/v4/Issues/{scope}/{scopeId} (`Issues_Get`) | PASS | Provides issue technology and vulnerability catalogs for filter UI. |
| /api/v1/auth/login | POST | routes/auth.login | POST /api/v4/Account/ApiKeyLogin (`Account_ApiKeyLogin`) is used by ASoC connector, not by this local auth endpoint | N/A (Internal) | Local JWT/OIDC gateway endpoint; does not mutate ASoC. |
| /api/v1/auth/mode | GET | routes/auth.auth_mode | None | N/A (Internal) | Local auth mode introspection. |
| /api/v1/auth/current-user | GET | routes/auth.current_user | GET /api/v4/User (`User_Get`), GET /api/v4/Account/TenantInfo (`Account_TenantInfo`) | PASS | Identity sourced from `/api/v4/User`; tenant metadata from `/api/v4/Account/TenantInfo`. |
| /api/v1/dashboards | GET | routes/dashboard.list_dashboards | None | N/A (Internal) | Internal dashboard metadata scaffold. |
| /api/v1/dashboards | POST | routes/dashboard.create_dashboard | None | N/A (Internal) | Internal dashboard creation with persistent storage and audit. |
| /api/v1/dashboards/{dashboard_id}/versions | GET | routes/dashboard.list_dashboard_versions | None | N/A (Internal) | Version history from local persistence. |
| /api/v1/dashboards/{dashboard_id}/rollback/{version} | POST | routes/dashboard.rollback_dashboard | None | N/A (Internal) | Rollback via local version history and audit logging. |
| /api/v1/dashboards/widget-registry | GET | routes/dashboard.list_widget_registry | None | N/A (Internal) | Pluggable widget metadata registry. |
| /api/v1/dashboards/templates | GET/POST | routes/dashboard.list_templates/create_template | None | N/A (Internal) | Template persistence in local database. |
| /api/v1/dashboards/wizard/create | POST | routes/dashboard.create_dashboard_via_wizard | None | N/A (Internal) | Wizard composition endpoint for templates and widgets. |
| /api/v1/reports/templates | GET | routes/reports.list_report_templates | Optional future mapping: GET /api/v4/Reports (`Reports_Get`) | N/A (Internal) | Currently internal template scaffold. |
| /api/v1/reports/generate | POST | routes/reports.generate_report | Optional future mapping: POST /api/v4/Reports/Issues|Security|Regulation|License/Sbom | N/A (Internal) | Currently queue simulation only; no ASoC write. |
| /api/v1/reports/schedules | GET/POST | routes/reports.list_schedules/create_schedule | None | N/A (Internal) | Persistent schedule management with cron validation. |
| /api/v1/reports/schedules/{schedule_id} | PUT/DELETE | routes/reports.update_schedule/delete_schedule | None | N/A (Internal) | Persistent updates with audit logging. |
| /api/v1/reports/schedules/{schedule_id}/run-now | POST | routes/reports.run_schedule_now | None | N/A (Internal) | Manual execution with history and audit event. |
| /api/v1/reports/schedules/monitor | GET | routes/reports.schedule_monitor | None | N/A (Internal) | Health/status monitor for dashboard widget use. |
| /api/v1/reports/history/{report_id}/download | GET | routes/reports.download_report_artifact | None | N/A (Internal) | Downloads locally stored report artifact. |
| /api/v1/audit/events | GET | routes/audit.list_audit_events | None | N/A (Internal) | Internal audit trail retrieval endpoint. |
| /api/v1/pipeline-bom | GET | routes/pipeline_bom.list_pipeline_bom | None | N/A (Internal) | Pipeline BOM is currently internal/mock source. |

## Connector-Level Compliance Checks
- Authentication:
  - Uses `POST /api/v4/Account/ApiKeyLogin` with `ApiKey` payload (`KeyId`, `KeySecret`).
  - Accepts bearer token from `AccessTokenData.Token`.
  - Supports `X-API-KEY: <KeyId>:<KeySecret>` header shape from Swagger security scheme.
- Read-only safety:
  - Allowed methods in read-only mode: `GET`, and `POST` only for `/api/v4/Account/ApiKeyLogin`.
  - Non-read operations are blocked by guardrails.
- Endpoint allow-list in read-only mode:
  - `/api/v4/Scans`
  - `/api/v4/Apps`
  - `/api/v4/AssetGroups`
  - `/api/v4/Issues`
  - `/api/v4/Reports`
  - `/api/v4/User`
  - `/api/v4/Roles`
  - `/api/v4/Account/TenantInfo`

## Workbench Trend Payload Contract (Normalized v2)
- Endpoint: `/api/v1/analytics/workbench-trends`
- `license_consumption`:
  - `detected_model`, `detected_model_label`, `model_source`
  - `technologies[]` with `technology`, `consumed_units`, `consumed_scans`, `consumed_apps`, `peak_concurrent`
- `scan_time_trend`:
  - `sast_sca[]` monthly bucket rows (`lt5`, `m5_10`, `m10_30`, `m30_60`, `m60_120`, `gte120`, `total`)
  - `dast[]` monthly bucket rows (`lt30`, `m30_60`, `m60_120`, `m120_240`, `gte240`, `total`)
- `application_file_size_profile`:
  - `bins[]` for SAST/SCA distribution
  - `top10[]` for largest applications/files in MB-scale fields
- `top_dast_page_coverage`:
  - `bins[]` coverage distribution buckets
  - `top10[]` top applications by covered pages
- Backward compatibility:
  - Legacy payload shapes are hydrated into normalized v2 defaults before response.

## Gaps and Next Planned Alignment
1. Reporting endpoints are internal scaffolds and not yet wired to ASoC report job operations.
2. Pipeline BOM endpoint is not yet integrated with external CI/CD APIs.
3. OIDC is optional but not fully configured without provider issuer/JWKS/audience values.
4. Analytics endpoints use snapshot caching; cache invalidation policies should be tuned per production SLA.
5. Workbench trend cards rely on available source fields (scan duration, coverage, size-like attributes); expose data-quality indicators for production reporting.
6. Workbench responses may return cached or cache-fallback data while background refresh rebuilds current snapshots; consumers should display freshness source and allow refresh override.

## Review Date
- Last reviewed against Swagger v4: 2026-04-06
