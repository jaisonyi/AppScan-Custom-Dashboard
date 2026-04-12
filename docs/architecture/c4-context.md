# C4 Context

## Actors
- Platform Admin
- Security Manager
- App Owner
- Developer
- Auditor

## External Systems
- HCL AppScan on Cloud API (Swagger v4)
- AppScan-MCP
- Identity Provider (OIDC)
- CI/CD systems for Pipeline BOM

## Integration Contract Notes
- ASoC API base: `https://cloud.appscan.com`
- Swagger reference: `https://cloud.appscan.com/swagger/index.html`
- OpenAPI reference: `https://cloud.appscan.com/swagger/v4/swagger.json`
- Auth pattern: API key login to bearer token, with API key header fallback.

## Core System
- ASPM Dashboard platform (this repository)
