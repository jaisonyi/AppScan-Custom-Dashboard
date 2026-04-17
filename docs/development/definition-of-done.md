# Definition of Done

Last reviewed: 2026-04-15

## Core Completion Criteria
- Feature is implemented and peer-reviewed.
- Unit tests are added/updated for changed behavior.
- Integration tests are added when the change crosses service/repository or connector boundaries.
- Documentation updates are included in the same PR for behavior/contract changes.

## Security and Access Criteria
- Every affected route keeps `get_current_user` and `assert_action_allowed` protections.
- Role and asset-group scoping is validated for all impacted list/analytics endpoints.
- ASoC read-only guard is preserved (no non-login mutating calls).
- Sensitive values (keys/secrets/tokens) are not exposed in logs or API responses.

## Data and Persistence Criteria
- DB-affecting changes include migration updates in `backend/migrations/versions/`.
- Migration path is validated locally (`alembic upgrade head`).
- Audit/event flows are preserved for dashboard/report mutation paths.

## Analytics and Performance Criteria
- Cache behavior is validated for first load, cached load, and `refresh=true` paths.
- Scope filtering behavior is validated end-to-end.
- Dashboard remains responsive during refresh and fallback scenarios.
- Workbench trends payload remains contract-compatible with frontend consumers.

## Multi-Data-Source Criteria
- Endpoint CRUD/management paths remain authorization-protected.
- `_load_sources()` filtering and max-20 ID limits are preserved.
- Aggregated items preserve `_data_source_id` and `_data_source_label` origin tags.
- Partial upstream failures degrade gracefully without full endpoint failure.
- `verify_ssl` behavior is validated for per-source configuration.

## CSV Export Criteria (v1.4.3+)
- Export endpoints enforce auth (`get_current_user`) and authorization (`assert_action_allowed`).
- Export responses use `StreamingResponse` with `text/csv` content type.
- Asset-group scoping is applied via `filter_by_asset_group`.
- CSV headers match the `_*_COLUMNS` definitions in `exports.py`.
- Null values are written as empty strings.

## Containerization Criteria (v1.4.3+)
- Dockerfile builds successfully in CI.
- Container runs as non-root user.
- Health check endpoint (`/health`) returns 200.
- Azure Bicep template validates without errors (`az bicep build`).
- No secrets are baked into the Docker image.

## Release Criteria
- Unit suite passes (`tests/unit`, currently 577 collected tests).
- Coverage gate in `backend/pyproject.toml` remains satisfied.
- API compatibility checks against ASoC Swagger v4 are complete for touched connector paths.
- Runbook-impacting operational changes are reflected in `docs/operations`.
