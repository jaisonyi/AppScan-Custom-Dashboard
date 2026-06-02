---
description: "Write and modify code for the AppScan Custom Dashboard following project conventions. Use when: implementing features, fixing bugs, writing backend routes, creating React components, modifying services, updating schemas."
---
You are a developer working on the AppScan Custom Dashboard — a FastAPI + React 18 monorepo for read-only AppScan ASPM integration.

## Backend Development
- Python ≥3.9 with `from __future__ import annotations` in every module
- Type hints on all function parameters, return types, and local variables
- `logging.getLogger(__name__)` per module — never `print()`
- Ruff-compatible style; no unused imports, no bare `except`
- Routes in `backend/app/api/v1/routes/` — one file per domain
- Every endpoint: `Depends(get_current_user)` + `assert_action_allowed()` + `filter_by_asset_group()`
- Multi-endpoint data: use `aggregate_list()` from `services/multi_endpoint.py`
- Schemas in `backend/app/schemas/` — `*Request` suffix, `Field()` with constraints (`ge`, `le`, `default_factory`)
- Repository in `backend/app/repositories/postgres_store.py` — SQL with `?` placeholders (`_CompatConnection` translates to `%s`)
- Error handling: `HTTPException` with status codes and descriptive `detail` messages
- Custom exceptions: `AsocAuthenticationError`, `AsocAuthorizationError`, `ReadOnlyViolationError`

## Frontend Development
- React 18 + TypeScript (strict mode, ES2020)
- Functional components with hooks only
- Feature modules in `src/modules/`, shared code in `src/shared/`
- API calls via `src/shared/services/api.ts` (Axios, base URL from `window.location`, 15s timeout)
- Token storage: `sessionStorage` key `aspm_access_token`; `localStorage` fallback `aspm_external_bearer_token` (OIDC)
- Charts via Recharts (Area, Bar, Line, Donut, Heatmap, TopApps)
- `PascalCase` for components, `camelCase` for functions/variables

## Constraints
- Never write code that mutates ASoC data
- Follow existing patterns in adjacent files
- Include error handling with `HTTPException` and descriptive `detail` messages
- Use async/await for all I/O operations
