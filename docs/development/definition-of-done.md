# Definition of Done

- Feature implemented and peer reviewed
- Unit and integration tests added or updated
- Role and asset-group authorization validated
- Read-only ASoC safety not bypassed
- Docs updated: architecture, operations, continuity
- Swagger v4 compatibility validated against ASoC spec link
- Sequential validation complete and recorded: Step 1, Step 2, Step 3
- Persistent data changes include migration script updates
- Audit events emitted for dashboard/report mutation flows
- Dashboard mode preference persistence validated (General, Larger Chart, SOC Style)
- Analytics cache behavior validated (cache hit, cache miss, refresh path)
- Analytics startup responsiveness validated (default view serves cache/fallback quickly while refresh can continue in background)
- Scheduler flow validated (cron parsing, retry/backoff, run-now, next-run update)
- Report artifact generation and download endpoint validated
- Operations Workbench charts validated for business meaning and readability (two charts per row desktop layout)
- Operations Workbench five-card contract validated end-to-end:
	- license consumption by technology (model-aware)
	- scan time bucket trends with period control (week/month/year) and 8 time buckets (`<5m`, `5-10m`, `10-30m`, `30-60m`, `60-120m`, `120-240m`, `240-300m`, `>=300m`)
	- SAST/SCA size bucket distribution plus top10
	- DAST page coverage bucket distribution plus top10
	- DAST Page Coverage chart validated to render both `scan_count` (dashed blue) and `page_count` (solid teal) series with `<Legend>` so chart is never blank when enrichment cache is cold
	- DAST page-count cache TTL confirmed `>= 3600` seconds and `>= 4×` base cache TTL
	- most frequently rescanned top10
- Scan Time Bucket Trends chart validated to render SAST/SCA/DAST trend lines for the selected bucket and selected period.
- Scan Time duration extractor validated: `ExecutionMinutes` field multiplied by 60, not treated as seconds; extractor unit test passes for all minutes-named and seconds-named field variants.
- SAST/SCA size extractors validated: `nFiles`, `NumFiles`, `FilesAnalyzed`, `nPackages`, `LibraryCount` all produce non-zero bucket counts in test fixtures.
- Mock data normalization validated: `mock_data.scans()` items flow through same mapper as live ASoC data; `ScanType`/`ExecutionMinutes`/`NVisitedPages` correctly normalized before reaching analytics engine.
- License Consumption chart visualization validated to show `Applications Tested` and `Scans Executed` bars for DAST/SAST/SCA/IAST.
- Workbench cards render with safe fallback values when source data is empty or partial (no card disappearance)
- Freshness and refresh behavior validated for workbench analytics (`cache`, `cache-fallback`, `cache-stale`, `live`)
- Scope filters validated end-to-end (Applications, Asset Groups, Issues, Scans, Reports) and confirmed to change body statistics/charts
- Current User pane validated using ASoC v4 User identity plus TenantInfo metadata
- Linux installer package updated and verified from latest code baseline
- macOS installer package updated and verified from latest code baseline
- Installer prompts validated for service URL, API key, and API secret collection
- Installer archives verified to exclude secrets and local runtime artifacts
- Installer conflict handling validated (port/dependency conflicts notify first; no forced destructive action)
- Uninstall behavior validated as instance-only by default (shared dependencies preserved when other instances exist)
- HTTPS installer design note documented (self-signed and CA-authorized certificate mode) for next installer iteration

## v1.3.1 Test Coverage Status

| Module | Coverage | Notes |
|---|---|---|
| `app/core/security/policy.py` | ~77% | 77 unit tests |
| `app/core/security/auth.py` | ~75% | 20 unit tests |
| `app/core/security/authorization.py` | ~100% | 20 unit tests |
| `app/core/security/dependencies.py` | ~100% | 12 unit tests |
| `app/core/config/settings.py` | ~90% | 22 unit tests |
| `app/repositories/postgres_store.py` | ~89% | 59 unit tests |
| `app/api/v1/routes/auth.py` | ~93% | 15 unit tests |
| `app/api/v1/routes/dashboard.py` | ~86% | 19 unit tests |
| `app/api/v1/routes/audit.py` | ~86% | 8 unit tests |
| `app/api/v1/routes/analytics.py` | ~47% | 24 unit tests; full coverage requires integration tests |
| `app/api/v1/routes/reports.py` | ~86% | 23 unit tests |
| `app/api/v1/routes/pipeline_bom.py` | ~86% | 6 unit tests |
| `app/services/asoc_read_service.py` | ~43% | 119 unit tests; full coverage requires integration tests (1343 statements) |
| `app/services/multi_endpoint.py` | ~80% | 17 unit tests |
| `app/services/report_artifacts.py` | ~90% | 9 unit tests |
| `app/workers/report_scheduler.py` | ~75% | 11 unit tests |
| `app/workers/analytics_prewarm.py` | ~90% | 6 unit tests |
| **Overall** | **~62%** | 518 tests across 20 files; integration tests needed for full coverage |

- 518 unit tests now exist across 20 test files (all passing, ~6 seconds)
- `asoc_read_service.py` (1343 statements) and `analytics.py` routes (935 statements) require integration tests to reach 80%+ coverage — HTTP integration paths cannot be fully exercised with unit tests alone
- Coverage threshold set to 60% in `backend/pyproject.toml` until integration test suite is added

## v1.3 Security and Quality Audit Checklist
- Repository module confirmed as `postgres_store.py` (not `sqlite_store.py`); all imports updated
- `JWT_SECRET` explicitly set for production deployments (auto-generated random secret is not acceptable for persistent sessions)
- Login role validation confirmed: `POST /auth/login` rejects roles not present in `ROLE_ACTION_POLICY`
- Dashboard update and delete confirmed to use separate permission actions (`update_dashboard` and `delete_dashboard`)
- Stub endpoints confirmed to include `_stub: true` response field and `X-Stub-Data: true` response header
- Audit endpoint pagination validated: `offset`, `limit`, and `total` present in `GET /audit/events` response envelope
- Scheduler structured logging validated in log output: start/stop, execution, failures, retry/backoff entries present
- Multi-endpoint aggregator logging validated: endpoint failures logged at `WARNING` level in `aggregate_list` and `aggregate_tenant_info`
