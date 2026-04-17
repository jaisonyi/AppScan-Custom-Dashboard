# Copilot Instructions — AppScan Custom Dashboard

## Project Overview

Monorepo for the **AppScan Custom Dashboard** (ASoC ASPM Dashboard) — a read-only integration dashboard for HCL AppScan on Cloud (ASoC). Provides role-scoped and asset-group-scoped visibility into application security posture.

**Core rule**: Read-only access to ASoC — all mutations are blocked at the API client layer.

---

## Tech Stack

- **Backend**: Python ≥3.9, FastAPI ≥0.116, PostgreSQL (SQLAlchemy 2.0+, psycopg ≥3.2), Alembic, httpx ≥0.28
- **Auth**: python-jose (JWT HS256), passlib (bcrypt); OIDC supported
- **Frontend**: React 18.3, TypeScript 5.6, Vite 5.4, Recharts, Axios
- **Testing**: pytest, pytest-asyncio, respx, freezegun | **Linter**: Ruff

---

## Repository Layout

```
backend/app/
  main.py, api/v1/routes/, core/config/, core/security/,
  domain/, schemas/, services/, repositories/, integrations/, workers/, plugins/
backend/tests/       # unit/, integration/, e2e/
frontend/src/
  app/, modules/, shared/ (charts, hooks, services/api.ts, types, ui)
docs/                # Architecture (C4, ADRs), development, operations
```

---

## Coding Standards

### Python
- `from __future__ import annotations` in every module
- Type hints on all params, returns, and local variables
- `snake_case` functions/variables, `PascalCase` classes, `_prefix` private, `UPPER_SNAKE` constants
- `logging.getLogger(__name__)` per module — never `print()`
- Ruff-clean: no unused imports, no bare `except`

### TypeScript / React
- Strict mode, ES2020, functional components with hooks only
- `PascalCase` components, `camelCase` functions/variables
- Feature modules in `src/modules/`, shared code in `src/shared/`

---

## Guardrails

- **Never mutate ASoC data** — no DELETE/PATCH/PUT to ASoC endpoints; raises `ReadOnlyViolationError`
- **Auth on every endpoint** — `Depends(get_current_user)` + `assert_action_allowed(action, user.role)`
- **Asset-group scoping on lists** — `filter_by_asset_group(items, user.asset_group_ids, user.role, key_names)`
- **Async I/O** — all HTTP/DB/file I/O via async/await
- **Follow adjacent patterns** — match existing code in the same directory before inventing new patterns
- **Roles**: `PlatformAdmin`, `SecurityManager`, `AppOwner`, `Developer`, `Auditor`

---

## Local Development

```bash
# PostgreSQL
scripts/postgres/install_local_postgres.sh && scripts/postgres/start.sh

# Backend
cd backend && python -m pip install -e '.[dev]' && python -m uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev

# Build frontend for production (served by FastAPI)
cd frontend && npm run build
```

---

## Specialist Context

Detailed conventions for architecture, implementation, security, and testing live in their respective agent/mode files under `.github/agents/` and `.github/copilot-chat-modes/`. See `AGENTS.md` for the full map.
