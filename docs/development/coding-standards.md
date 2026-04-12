# Coding Standards

## Backend
- Python 3.9+ runtime compatibility required (3.12 target supported)
- Type hints required for public functions
- Pydantic models for request and response boundaries
- Domain logic separated from API handlers
- For type annotations that may be evaluated at runtime, prefer `from __future__ import annotations`
- Database schema changes must include Alembic migration files

## Frontend
- React + TypeScript
- Feature-module folder structure
- Shared components in `shared/`
- Persist user interface preferences that affect landing experience (for example, dashboard view mode)
- Avoid duplicate analytics fetches after initial bundle load; do not issue redundant chart endpoint calls on the same state transition.
- Keep Operations Workbench readability-first layout: maximum two chart cards per row on desktop; single-column fallback on smaller screens.
- Keep filters server-driven for correctness (do not rely on frontend-only filtering for security-sensitive counts).

## Security
- Never log secrets
- Enforce backend authorization checks for every data endpoint
- ASoC connectors remain read-only by policy and by code guard
- Do not implement mutating ASoC operations in any service or helper

## ASoC Integration Rules
- Follow Swagger v4 schema and paths from `https://cloud.appscan.com/swagger/v4/swagger.json`.
- Use `POST /api/v4/Account/ApiKeyLogin` for bearer token retrieval.
- Use `X-API-KEY: <KeyId>:<KeySecret>` only as fallback.
- Do not use legacy `/api/v2/*` endpoints.
- Keep issue retrieval scoped (`/api/v4/Issues/{scope}/{scopeId}`) and aggregate in service layer.
- Duration extractor must use a 3-phase approach: (1) seconds-named fields used as-is, (2) minutes-named fields (`ExecutionMinutes`, `DurationMinutes`, `ScanDurationMinutes`, `ExecutionTimeMinutes`, `TotalMinutes`, `ElapsedMinutes`) multiplied by 60, (3) ambiguous-named fields used as-is. ASoC commonly returns `ExecutionMinutes` not `DurationSeconds`.
- SAST size extractor must cover all known ASoC file-count keys: `nFiles`, `NFiles`, `NumFiles`, `numFiles`, `FilesAnalyzed`, `filesAnalyzed`, `ScannedFiles`, `scannedFiles`, `AnalyzedFiles`, `analyzedFiles`, `TotalFiles`, `totalFiles`.
- SCA size extractor must cover all known ASoC package-count keys: `nPackages`, `NPackages`, `NumPackages`, `numPackages`, `LibraryCount`, `libraryCount`, `ModuleCount`, `moduleCount`, `DirectDependencies`, `directDependencies`, `TransitiveDependencies`, `transitiveDependencies`.
- Mock data items must use raw ASoC-style field names (e.g. `ScanType`, `ExecutionMinutes`, `NVisitedPages`) and flow through the same mapper as live data; never return raw mock dicts directly from service methods that downstream consumers expect normalized field names from.

## Data and Performance Rules
- Use analytics snapshot caching for expensive aggregate endpoints.
- Expose explicit refresh flags for cache bypass when current data is required.
- Keep scheduler retry/backoff deterministic and auditable.
- Prefer fast stale-cache return with background refresh for default dashboard views to keep first paint responsive.
- When cache key is cold, fallback to latest known snapshot for default view and rebuild target key asynchronously.
- For scoped analytics filters, avoid duplicate remote issue fetches per request; reuse pre-fetched issue datasets and apply in-memory application-id filtering when possible.
- For live refresh actions, avoid forcing rebuild on every analytics endpoint in parallel; force refresh once and read remaining sections from refreshed cache.
- Coalesce near-simultaneous forced base-data refresh requests to prevent repeated full remote sync cycles.
- Analytics UI loaders should degrade gracefully per endpoint (fallback to prior snapshot/state) instead of blanking the full dashboard when one request stalls or fails.
- Refresh-triggered heavy reads must be non-blocking for visible statistics: render cached data immediately and apply refreshed values asynchronously when available.
- Frontend API base URL and backend CORS origins must support both `localhost` and `127.0.0.1` host variants for local development to prevent silent browser-side data drops.

## Workbench Analytics Contract Rules
- Keep `/api/v1/analytics/workbench-trends` payload normalized and stable for frontend consumption.
- Maintain compatibility hydration for legacy shapes so old snapshots do not break rendering.
- Keep model-aware license consumption in technology rows (DAST, SAST, SCA, IAST) with explicit model metadata fields.
- License Consumption chart view must prioritize `consumed_apps` and `consumed_scans` as primary bars for DAST/SAST/SCA/IAST.
- Keep scan-time trend payload in normalized v2 shape with:
	- period options: `week`, `month`, `year`
	- bucket options: `<5m`, `5-10m`, `10-30m`, `30-60m`, `60-120m`, `120-240m`, `240-300m`, `>=300m`
	- per-period rows that include per-bucket counts for `sast`, `sca`, `dast`, and `total`
- Scan Time Bucket Trends chart should use line-trend rendering for selected bucket with controls for `Period` and `Time Bucket`.
- Keep size and coverage analytics split into distribution buckets and top10 lists.
- Frontend chart labels for top10 categories should use compact truncation rules to preserve readability on desktop and mobile.
- DAST page coverage chart must render both `page_count` (visited pages, solid line) and `scan_count` (scans in bucket, dashed line) so the chart remains visible even when the DAST page-count cache is cold; a `<Legend>` must accompany the chart to distinguish the two series.
- DAST page-count cache TTL must be set to `max(3600, base_cache_ttl * 4)` to ensure the enrichment cache does not expire before the base data cache; short TTL causes the `page_count` series to appear as all-zeros while `scan_count` remains populated.

## Installer Packaging Rules
- Maintain deploy scripts for Linux and macOS under `/Users/dongillee/deploy_appscan_aspm_dashboard/Linux` and `/Users/dongillee/deploy_appscan_aspm_dashboard/Mac`.
- Installer bundles must exclude `.env`, local database files, logs, and runtime process files.
- Installers must prompt for service URL choice (US cloud, EU cloud, custom AppScan360 URL), API key, and API secret.
- Installers must preserve read-only ASoC behavior by setting `ASOC_READ_ONLY=true` during bootstrap.
- Installer scripts should be idempotent for reinstall/upgrade flows and safe to rerun.
- Installers must apply conflict-first behavior: detect port/dependency conflicts, notify user, and require confirmation before any change.
- Uninstall scripts must default to instance-only removal and avoid deleting shared dependencies when other dashboard instances are detected.
- HTTPS installer support is planned for the next iteration and must include both:
	- self-signed certificate option
	- CA-authorized certificate + domain option
