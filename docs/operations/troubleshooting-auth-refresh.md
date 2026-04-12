# Troubleshooting: Auth Failure and Frozen Refresh

## Scope
Use this playbook when the UI shows:
- `Failed to authenticate or load dashboard data.`
- Refresh button appears stuck or charts never reload.

This issue was reproduced and fixed in local operations by standardizing backend startup, hardening frontend timeouts, and separating expensive diagnostics from normal dashboard flow.

## Known Root Causes
1. Backend running on a different port than frontend expects.
- Frontend is configured to call `http://localhost:8000/api/v1`.
- If backend runs on `8010`, auth and data load fail in UI.

2. Stale or broken uvicorn process on `8000`.
- A hung process can keep the port in a bad state where bind fails and requests time out.

3. Slow analytics path from heavy upstream reads.
- Local auth endpoint can be healthy while analytics endpoints block long enough to look like UI freeze.

4. Python environment mismatch.
- Running the backend with a Python env missing dependencies causes intermittent startup failures and inconsistent behavior.

## Permanent Code Safeguards Added
1. Frontend request timeout enabled (prevents infinite wait):
- `frontend/src/shared/services/api.ts`

2. Frontend initial list loading made resilient with fallbacks:
- `frontend/src/app/App.tsx`

3. DAST page-coverage enrichment moved to non-blocking background cache/hydration so dashboard refresh is not blocked:
- `backend/app/services/asoc_read_service.py`

4. DAST diagnostics isolated to a dedicated endpoint (for investigation only):
- `backend/app/api/v1/routes/scans.py`
- `GET /api/v1/scans/dast-page-coverage-diagnostics`

5. Applications filter clear behavior hardened to prevent blank-list confusion:
- `frontend/src/app/App.tsx`
- `frontend/src/styles.css`
- See also: `docs/operations/troubleshooting-application-filter-list.md`

## Standard Recovery Procedure
Run these from repository root.

1. Check backend listener status.
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
curl -sS -m 8 http://127.0.0.1:8000/api/v1/auth/mode || true
```

2. Stop stale uvicorn processes.
```bash
pkill -f "uvicorn app.main:app" || true
```

3. Start backend on the expected port (`8000`) using project env.
```bash
cd backend
if [ -x ../.venv/bin/python ]; then
  PYTHONPATH=$(pwd) ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
else
  PYTHONPATH=$(pwd) /usr/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
fi
```

4. Verify auth and protected route.
```bash
curl -sS -m 8 http://127.0.0.1:8000/api/v1/auth/mode
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"health.check","role":"SecurityManager","asset_group_ids":["ag-1"]}' \
  | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
curl -sS -m 20 "http://127.0.0.1:8000/api/v1/analytics/workbench-trends" \
  -H "Authorization: Bearer $TOKEN" | head -c 300
```

5. Reload frontend tab and click `Refresh Live`.

## Operational Guardrails
1. Always run backend on port `8000` for local UI.
2. Use one backend process only during local testing.
3. Do not attach expensive diagnostics to normal dashboard routes.
4. Keep diagnostics endpoints optional and bounded with timeouts.
5. If auth works but analytics times out, treat it as data-path latency, not auth failure.

## Regression Checklist (Before Merge)
1. Backend health:
- `GET /api/v1/auth/mode` responds in < 2 seconds.

2. Auth flow:
- `POST /api/v1/auth/login` returns token.

3. Dashboard critical endpoints:
- `GET /api/v1/analytics/statistics` responds with payload.
- `GET /api/v1/analytics/workbench-trends` responds with payload.

4. Frontend behavior:
- No persistent auth-failure banner after backend is healthy.
- Refresh does not freeze indefinitely.

## Notes on DAST Page Coverage
The trend pipeline now supports `page_count`, but if upstream AppScan payloads do not provide visited-page metrics, buckets will remain zero/non-distributed. Use diagnostics endpoint above to confirm source-field availability in tenant context.