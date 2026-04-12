# Multi-Team Validation Cadence

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
- Applications scope clear/apply behavior is validated end-to-end:
	- clearing Applications resets search text and selected IDs
	- list repopulates from scoped catalog (or explicit empty-state message is shown)
- Operations Workbench cards remain readable and arranged as two charts per row on desktop.
- Operations Workbench contract remains complete and visible in UI:
	- license consumption by technology
	- scan time bucket trends
	- SAST/SCA size buckets plus top10
	- DAST page coverage buckets plus top10
	- most frequently rescanned top10
- Workbench cards continue to render under empty/partial source datasets via fallback payload defaults.
- Freshness source behavior remains observable during normal and forced refresh paths for analytics/workbench responses.
- Current User pane continues to show `/api/v4/User` identity with tenant metadata enrichment.
- Linux and macOS installers are regenerated from latest baseline and pass smoke install checks.
- Windows installer is regenerated from latest baseline and passes smoke install checks.
- Installer conflict-first behavior is validated (ports/dependencies): notify and confirm before changes.
- Uninstall scripts are validated to remove only the target dashboard instance by default.
- HTTPS installer roadmap artifacts remain documented for the next installer cycle:
	- self-signed mode
	- CA-authorized certificate + domain mode
	- certificate path validation and HTTPS port conflict handling
