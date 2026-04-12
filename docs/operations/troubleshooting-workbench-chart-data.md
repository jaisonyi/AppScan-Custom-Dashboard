# Troubleshooting: Workbench Trend Charts Show Empty Buckets

## Scope
Use this playbook when one or more Operations Workbench trend charts display no data or all-zero buckets:
- **Scan Time Bucket Trends** — all buckets show zero counts for SAST, SCA, or DAST
- **SAST/SCA Scan Target Size Trends** — file/package size buckets all show zero
- **DAST Page Coverage Trends** — chart appears empty or visited-page series is all zero

---

## Scan Time Bucket Trends — Empty or All `lt5`

### Symptoms
- All scan time buckets show 0 for DAST, SAST, and SCA.
- All scans fall in the `lt5` (< 5 min) bucket regardless of actual scan duration.

### Root Cause
ASoC returns scan duration as `ExecutionMinutes` (integer, minutes), not `DurationSeconds`.
If the extractor only reads seconds-named fields, every scan has `duration_seconds = 0` and is bucketed as `lt5`.

### Code Location
`backend/app/services/asoc_read_service.py` → `_extract_scan_duration_seconds`

### Expected Behavior
The extractor must use a 3-phase approach:
1. Seconds-named fields (`DurationSeconds`, `durationSeconds`, etc.): use as-is.
2. Minutes-named fields (`ExecutionMinutes`, `DurationMinutes`, `ScanDurationMinutes`, `ExecutionTimeMinutes`, `TotalMinutes`, `ElapsedMinutes`): multiply by 60.
3. Ambiguous fields: use as-is.

### Diagnostic Check
```bash
cd /Users/dongillee/asoc-aspm-dashboard/backend
TOKEN=$(../.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.core.security.auth import create_access_token
print(create_access_token('ops','PlatformAdmin',[]))
")
curl -sS -m 30 "http://127.0.0.1:8000/api/v1/analytics/bundle" \
  -H "Authorization: Bearer $TOKEN" \
  | /usr/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('scan_time_trend',{}).get('by_period',{}).get('month',[])
print('scan_time rows:', len(rows))
if rows: print('sample:', rows[0])
"
```

### Fix Confirmation
- `ExecutionMinutes:18` in raw scan data → `duration_seconds = 1080.0` after mapping.
- `ExecutionMinutes:45` → `duration_seconds = 2700.0`.
- Scans in those ranges appear in `m10_30` and `m30_60` buckets respectively.

---

## SAST/SCA Scan Target Size Trends — All-Zero Buckets

### Symptoms
- File size distribution shows no SAST or SCA scans in any bucket.
- Top-10 size list is empty.

### Root Cause
ASoC returns file counts under field names that vary by scan type and API version:
- SAST: `nFiles`, `NumFiles`, `FilesAnalyzed`, `ScannedFiles`, `AnalyzedFiles`, `TotalFiles`
- SCA: `nPackages`, `LibraryCount`, `ModuleCount`, `DirectDependencies`, `TransitiveDependencies`

If the extractor only reads a single field name, most scans return size 0.

### Code Location
`backend/app/services/asoc_read_service.py` → `_extract_sast_size_profile`, `_extract_sca_size_profile`

### Diagnostic Check
```bash
cd /Users/dongillee/asoc-aspm-dashboard/backend
TOKEN=$(../.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.core.security.auth import create_access_token
print(create_access_token('ops','PlatformAdmin',[]))
")
curl -sS -m 30 "http://127.0.0.1:8000/api/v1/analytics/bundle" \
  -H "Authorization: Bearer $TOKEN" \
  | /usr/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('file_size_profile',{}).get('by_period',{}).get('month',[])
print('size rows:', len(rows))
if rows:
    for r in rows[:3]: print(r)
"
```

### Note on Bucket Placement
`_size_to_mb` treats raw file counts as heuristic MB values. A SAST scan with `nFiles:340` is placed in the `lt1` bucket (< 1 MB / < ~1000 files). This is a known approximation until ASoC exposes byte-level size data.

---

## DAST Page Coverage — Chart Appears Empty or `page_count` All Zero

### Symptoms
- The DAST Page Coverage chart is blank.
- The visited-pages series (`page_count`) shows 0 for all periods but scan data is otherwise present.
- Chart was working recently and then stopped showing data after server restart.

### Root Causes

#### Root Cause A: DAST page-count cache TTL too short
The `_DAST_PAGE_CACHE_TTL_SECONDS` constant was historically set to `max(300, ttl)` (5 minutes minimum).
The base data cache TTL is typically longer. When the DAST enrichment cache expires first, all subsequent
`page_count` reads return 0 while `scan_count` stays populated — the chart looks empty.

**Fix:** TTL must be `max(3600, base_cache_ttl * 4)` (1 hour minimum, 4× base cache).

#### Root Cause B: Chart only rendered `page_count` series
If the frontend chart only renders the `page_count` line, the chart appears blank whenever the DAST
enrichment cache is cold (e.g., after server restart), even though `scan_count` data is available.

**Fix:** The DAST Page Coverage chart must render both:
- `page_count` — total visited pages (solid teal line)
- `scan_count` — number of scans in the bucket (dashed blue line)

A `<Legend>` must accompany the chart to distinguish the two series.

### Expected Behavior After Fix
- After first request post-restart: `scan_count > 0`, `page_count = 0` (cache warming in background).
- After background refresh completes (~20 seconds): both `scan_count` and `page_count` populated.
- Chart is never blank — `scan_count` dashed line remains visible even when `page_count` is 0.

### Diagnostic Check
```bash
cd /Users/dongillee/asoc-aspm-dashboard/backend
TOKEN=$(../.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app.core.security.auth import create_access_token
print(create_access_token('ops','PlatformAdmin',[]))
")
curl -sS -m 30 "http://127.0.0.1:8000/api/v1/analytics/bundle" \
  -H "Authorization: Bearer $TOKEN" \
  | /usr/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d.get('dast_page_coverage',{}).get('by_period',{}).get('month',[])
print('dast rows:', len(rows))
for r in rows[-3:]: print(r)
"
```

---

## Mock Mode — All Charts Empty Despite Known Mock Scans

### Symptoms
- Running without ASoC credentials (demo/dev mode).
- All three workbench charts show empty data even though `mock_data.scans()` has 8 scans.

### Root Cause
`list_scans` returned `mock_data.scans()` directly (raw ASoC-style field names: `ScanType`, `DurationSeconds`, `NVisitedPages`), bypassing the normalizer mapper. Downstream analytics consumers read normalized names (`scan_type`, `duration_seconds`, `page_coverage`), so all extraction returned 0.

### Fix Applied
`list_scans` now uses a unified path where mock items flow through the same mapper as live ASoC data. The mapper converts `ScanType → scan_type`, `ExecutionMinutes → duration_seconds × 60`, `NVisitedPages → page_coverage`, etc.

### Verification
```bash
cd /Users/dongillee/asoc-aspm-dashboard/backend
../.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0,'.')
import asyncio
from app.services import asoc_read_service, mock_data

svc = asoc_read_service.ASoCReadService.__new__(asoc_read_service.ASoCReadService)
svc._api_url = ""; svc._headers = {}; svc._read_only = True; svc._mock_on_error = True

async def run():
    scans = await svc.list_scans()
    for s in scans:
        print(s['id'], s['scan_type'],
              'dur=', s.get('duration_seconds'),
              'pages=', s.get('page_coverage'),
              'sast=', s.get('sast_file_size'),
              'sca=', s.get('sca_package_count'))

asyncio.run(run())
EOF
```

Expected output for s-4: `duration_s=1080.0` (from `ExecutionMinutes:18` × 60), `sast=870`.

---

## Regression Checklist

After any change to `asoc_read_service.py` extractors or `mock_data.py`:

- [ ] `py_compile` clean on `asoc_read_service.py` and `mock_data.py`
- [ ] `npm run build` clean in `frontend/`
- [ ] Smoke test: `GET /api/v1/analytics/bundle` returns non-empty `scan_time_trend`, `file_size_profile`, `dast_page_coverage`
- [ ] Mock extractor unit test: `ExecutionMinutes:18 → duration_seconds=1080.0`, `nFiles:340 → sast_file_size=340`, `NVisitedPages:420 → page_coverage=420`
- [ ] DAST chart shows `scan_count` dashed blue line and `page_count` solid teal line with legend
- [ ] `_DAST_PAGE_CACHE_TTL_SECONDS` value confirms `>= 3600`
