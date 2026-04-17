# Branching Strategy

Last reviewed: 2026-04-15

- `main`: production-ready
- `develop`: integration branch
- `feature/<name>`: feature branches
- `hotfix/<name>`: urgent fixes

## Pull Request Rules
- At least one reviewer from Architecture or Security team
- Passing CI checks required
- Updated docs required when architecture or access rules change
- For ASoC integration changes, PR must include:
	- Swagger v4 contract check evidence
	- Read-only policy test evidence
	- Step 1/2/3 validation summary
- For persistence changes, PR must include migration file and migration smoke output
- For analytics changes, PR must include cache behavior evidence (first call vs cached call) and refresh path evidence (`refresh=true` behavior)
- For Operations Workbench analytics changes, PR must include:
	- backend payload contract evidence for `/api/v1/analytics/workbench-trends`
	- frontend rendering evidence for all five workbench cards
	- refresh path evidence with corresponding freshness source transitions (`live`, `cache`, `cache-fallback`, `cache-stale`)
- For dashboard UX changes, PR must include screenshots for all supported view modes and Operations Workbench layout (two charts per row on desktop).
- For scope-filter changes, PR must include proof that body statistics/charts react correctly to:
	- Applications
	- Asset Groups
	- Issues (technology/vulnerability)
	- Scans (type/status)
	- Reports (time window)
- For multi-data-source changes, PR must include proof for:
	- `/api/v1/endpoints` management paths
	- source status/identity behaviors
	- `data_source_ids` filtering and max-ID guard
- For CSV export changes, PR must include:
	- Sample CSV output for each affected endpoint
	- Auth enforcement evidence (401 for unauthenticated requests)
	- Asset-group scoping evidence
- For containerization/deployment changes, PR must include:
	- Successful `docker build` output
	- Health check evidence from running container
	- `az bicep build` validation for any Bicep changes
