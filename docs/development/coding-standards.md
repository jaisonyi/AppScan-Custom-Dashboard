# Coding Standards

Last reviewed: 2026-04-15

## Backend Standards
- Python 3.9+ compatibility is required.
- Every new module must include `from __future__ import annotations`.
- Type hints are required for public function parameters and return values.
- Route handlers stay thin; business logic belongs in `services/` and persistence in `repositories/`.
- Every API route must enforce auth and authorization (`get_current_user` + `assert_action_allowed`).
- All DB schema changes must include Alembic migration files under `backend/migrations/versions/`.

## Frontend Standards
- React functional components + TypeScript only.
- Feature code stays in `frontend/src/modules/`; shared abstractions in `frontend/src/shared/`.
- Keep filters server-driven for security-sensitive counts.
- Keep dashboard interactions responsive by avoiding duplicate analytics fetches for the same transition.
- Preserve local UX preferences that affect initial landing state.

## Multi-Data-Source Conventions
- Data sources are persisted in the `data_sources` table and managed through `data_source_store` / `data_source_service`.
- Routes must retrieve active sources through `multi_endpoint._load_sources()` and never query the table directly.
- `data_source_ids` inputs must be validated against enabled sources and capped at 20 IDs.
- Source-level failures are warning-only and must not fail the full aggregate response.
- Aggregated list items must carry `_data_source_id` and `_data_source_label` tags.
- Per-source SSL policy must be forwarded via `verify_ssl` to connector creation.

## Security and Read-Only Rules
- Never log API keys, secrets, tokens, or raw credential payloads.
- ASoC integration remains read-only across all sources.
- Only `POST /api/v4/Account/ApiKeyLogin` is allowed as a POST call to ASoC; all other mutating operations are blocked.
- Avoid introducing any helper that can bypass read-only guards in the API client layer.

## Analytics and Performance Rules
- Expensive analytics endpoints must use snapshot cache paths.
- `refresh=true` paths should force rebuild once and reuse refreshed cache where possible.
- Default dashboard loads should prefer fast cached/fallback responses and refresh asynchronously.
- Maintain non-blocking UX behavior for analytics refresh operations.
- Keep localhost and 127.0.0.1 origin compatibility for local CORS and frontend API usage.

## CSV Export Conventions (v1.4.3+)
- Export routes live in `backend/app/api/v1/routes/exports.py` and are registered under `/api/v1/export`.
- Use `StreamingResponse` with `text/csv` content type — never buffer full datasets in memory.
- Column definitions are declared as `_*_COLUMNS` tuples of `(key, header)` at module level.
- Every export endpoint must enforce `get_current_user` + `assert_action_allowed` + `filter_by_asset_group`.
- Export file names include a UTC timestamp: `{name}_{YYYYMMDD_HHMMSS}.csv`.
- Null/missing values are written as empty strings, not `None` or `null`.

## Containerization Conventions (v1.4.3+)
- Dockerfile lives at `infra/docker/Dockerfile` and uses a multi-stage build (Node → Python).
- Docker Compose file lives at `infra/compose/docker-compose.yml`.
- Azure Bicep template lives at `infra/azure/main.bicep` with parameter file `main.parameters.json`.
- Container runs as non-root user `dashboard` (UID 10001).
- Use `gunicorn` with `uvicorn.workers.UvicornWorker` in production; `uvicorn --reload` for local dev only.

## ASoC Mapping Rules
- Follow Swagger v4 endpoints (`/api/v4/*`) only.
- Keep issue retrieval scoped through `/api/v4/Issues/{scope}/{scopeId}` and aggregate in service layer.
- Continue mapping variant source fields for duration, file size, and package size normalization.
- Mock-mode scan records must pass through the same normalization pipeline as live ASoC records.
