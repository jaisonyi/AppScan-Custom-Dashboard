# C4 Context

## Actors
- Platform Admin
- Security Manager
- App Owner
- Developer
- Auditor

## External Systems
- HCL AppScan on Cloud API (Swagger v4) — **multiple instances supported** (US cloud, EU cloud, custom AppScan 360)
- AppScan-MCP
- Identity Provider (OIDC)
- CI/CD systems for Pipeline BOM

## Integration Contract Notes
- ASoC API base: `https://cloud.appscan.com` (default; each data source can have a different base URL)
- Swagger reference: `https://cloud.appscan.com/swagger/index.html`
- OpenAPI reference: `https://cloud.appscan.com/swagger/v4/swagger.json`
- Auth pattern: API key login to bearer token, with API key header fallback.
- Each data source authenticates independently with its own API key pair.
- SSL verification can be disabled per data source (`verify_ssl=false`) for self-signed certificates.

## External BI Tools (v1.5e)
- **PowerBI / Excel / Tableau**: consume CSV export endpoints (`/api/v1/export/*.csv`) for offline reporting and custom analytics
- Data refresh via PowerBI Web Data Source or scheduled import; auth via JWT bearer token

## Hosting Platforms (v1.5e)
- **Docker**: self-hosted containerized deployment (single multi-stage image)
- **Azure**: App Service (Linux/Docker) + PostgreSQL Flexible Server + Key Vault + Application Insights (Bicep IaC)

## Core System
- ASPM Dashboard platform (this repository)
