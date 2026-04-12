# Credentials and API Safety Policy

## Required Inputs
- `ASOC_SERVICE_URL`
- `ASOC_API_KEY`
- `ASOC_API_SECRET`

These are user-provided and modifiable through environment configuration.

## Security Handling
- Never store real credentials in source control.
- Do not print credentials in logs.
- Rotate keys according to organizational policy.

## Change Protection
This project must not change ASoC data. Connector guards block non-read operations by default.
