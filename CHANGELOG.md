# Changelog

## [1.3.1] - 2026-04-09

### Security
- Removed hardcoded developer email from user profile selection logic
- JWT secret now auto-generates a secure random value at startup when not configured; logs a warning
- Login endpoint validates requested role against allowed roles from policy
- Dashboard update and delete now use separate permission actions (`update_dashboard`, `delete_dashboard`)

### Fixed
- Renamed misleading `sqlite_store.py` to `postgres_store.py` (uses PostgreSQL, not SQLite)
- Fixed unbounded `_CACHE_LOCKS` dict growth in analytics module (bounded to 500 entries)
- Pipeline BOM endpoint now clearly marked as stub with `_stub: true` response field
- JWKS/OIDC configuration fetch converted from synchronous to async (no longer blocks event loop)

### Added
- Connection reuse in repository layer (module-level connection with thread-safe locking)
- Audit events endpoint now supports pagination (`offset`, `limit`, `total` in response)
- Structured logging in report scheduler (start/stop, execution, failures, retry/backoff)
- Structured logging in multi-endpoint aggregator (endpoint failures logged at WARNING)
- Comprehensive backend unit test suite: 518 tests across 20 test files
  - Security module tests: policy (77), authorization (20), auth (20), dependencies (12)
  - Settings/config tests (22) and PostgreSQL repository tests (59)
  - Service tests: ASoC read service (119), multi-endpoint (17), report artifacts (9)
  - Route/API tests: auth (15), dashboard (19), audit (8), analytics (24), reports (23), pipeline-bom (6), applications (5), asset-groups (5), issues (5), scans (9)
  - Worker tests: report scheduler (11), analytics prewarm (6), schedule utils (16)
  - Shared test fixtures in conftest.py (18 fixtures)
- Test plan documentation at `plans/PLAN.md`
- pytest configuration with coverage reporting in `backend/pyproject.toml`

### Changed
- `get_current_user` dependency is now async
- Audit events response format changed from flat list to `{items, offset, limit, total}` envelope
