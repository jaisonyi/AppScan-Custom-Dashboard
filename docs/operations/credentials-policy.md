# Credentials and API Safety Policy

## Required Inputs
- `ASOC_SERVICE_URL`
- `ASOC_API_KEY`
- `ASOC_API_SECRET`

These are user-provided and modifiable through environment configuration.

## Multi-Data-Source Credentials (v1.5e)
- Additional data source credentials (URL, API key, API secret) are stored in the `data_sources` PostgreSQL table.
- Each data source has independent credentials for authentication against its ASoC/AppScan 360 instance.
- Credentials are managed via the `/api/v1/endpoints` CRUD routes (PlatformAdmin/SecurityManager role required).
- The `api_secret` field is **never returned** in API responses — it is write-only.
- The `verify_ssl` flag controls SSL certificate verification per data source.

## Security Handling
- Never store real credentials in source control.
- Do not print credentials in logs.
- Rotate keys according to organizational policy.
- Data source credentials follow the same rotation and protection policies as environment-level credentials.

## Change Protection
This project must not change ASoC data. Connector guards block non-read operations by default. This applies to **all configured data sources**.
