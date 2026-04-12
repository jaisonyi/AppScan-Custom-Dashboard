# Troubleshooting: Application Filter List Is Empty

## Scope
Use this playbook when the Applications scope panel is open, but no application rows are shown after clearing filters.

## Symptoms
- Clicking `Clear` under Applications does not repopulate the list.
- The panel appears blank even though backend `/applications` returns items.
- Users assume filters are reset, but a stale search term is still active.

## Root Causes
1. Stale search query:
- Application search text can hide all rows even when `applicationIds` is cleared.

2. Empty local applications cache:
- If the initial `/applications` request failed (transient network/runtime issue), local state may remain empty.
- Clearing filters updates analytics scope but does not always repopulate app catalog unless explicitly retried.

3. Scope narrowing by asset groups:
- Effective application options are constrained by selected asset groups.
- With narrow group scope, no apps may be eligible.

## Code Safeguards
1. Clearing Applications now resets search text:
- `frontend/src/app/App.tsx`
- `clearScopeSelection('applications')` resets `applicationSearch`.

2. Clearing Applications now re-fetches app catalog if state is empty:
- `frontend/src/app/App.tsx`
- On clear, frontend calls `/applications` when cached `applications.length === 0`.

3. Explicit empty-state guidance in panel:
- `frontend/src/app/App.tsx`
- `frontend/src/styles.css`
- Users see whether the empty list is caused by search or by scoped availability.

## Verification Steps
1. Open Applications panel and type a restrictive search string.
2. Click `Clear`.
3. Confirm:
- Search input is empty.
- `All applications in selected asset groups` is active.
- List rows are visible (or explicit scoped empty-state message is shown).

4. Backend sanity check:
```bash
curl -sS -m 20 http://127.0.0.1:8000/api/v1/applications \
  -H "Authorization: Bearer <token>" | /usr/bin/python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 'non-list')"
```

## Regression Checklist
- Clearing Applications removes search text and selected application IDs.
- Applying/Clearing Asset Group filters updates available application list correctly.
- Applications panel never renders as a blank box without explanatory text.
- Clearing Applications still refreshes analytics payloads without blocking UI.
