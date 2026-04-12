# ADR-0001: Enforce Read-Only ASoC Policy

## Status
Accepted

## Context
This platform consumes AppScan on Cloud data. The user requires zero mutation of ASoC data from this project.

## Decision
- Swagger contract baseline is pinned to ASoC v4:
	- `https://cloud.appscan.com/swagger/index.html`
	- `https://cloud.appscan.com/swagger/v4/swagger.json`
- Read-only exception for authentication is allowed:
	- `POST /api/v4/Account/ApiKeyLogin`
- Resource read endpoints currently used:
	- `/api/v4/Scans`
	- `/api/v4/Apps`
	- `/api/v4/AssetGroups`
	- `/api/v4/Issues/{scope}/{scopeId}`
	- `/api/v4/Reports`

- Some API operations requiring write permissions are intentionally unavailable.
