# Branching Strategy

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
- For analytics changes, PR must include cache behavior evidence (first call vs cached call)
- For Operations Workbench analytics changes, PR must include:
	- backend payload contract evidence for `/api/v1/analytics/workbench-trends`
	- frontend rendering evidence for all five workbench cards:
		- license consumption by technology
		- scan time bucket trends
		- SAST/SCA size buckets plus top10
		- DAST page coverage buckets plus top10
		- most frequently rescanned top10
	- refresh path evidence using `refresh=true` and corresponding freshness source changes (`live`, `cache`, `cache-fallback`, `cache-stale`)
- For dashboard UX changes, PR must include screenshots for all supported view modes and Operations Workbench layout (two charts per row on desktop).
- For scope-filter changes, PR must include proof that body statistics/charts react correctly to:
	- Applications
	- Asset Groups
	- Issues (technology/vulnerability)
	- Scans (type/status)
	- Reports (time window)
- For release packaging changes, PR must include:
	- Linux installer artifact update
	- macOS installer artifact update
	- Windows installer artifact update
	- install/readme instructions updated for both OS flows
	- conflict-first and instance-only uninstall behavior evidence
