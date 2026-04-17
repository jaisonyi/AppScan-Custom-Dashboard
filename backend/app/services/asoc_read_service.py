from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config.settings import settings
from app.integrations.appscan_api.client import AsocApiClient
from app.services import mock_data


_DAST_PAGE_CACHE_LOCK = asyncio.Lock()
_DAST_PAGE_CACHE: dict[str, dict[str, Any]] = {}
_DAST_PAGE_REFRESH_TASK: Any = None
_DAST_PAGE_REFRESH_CURSOR = 0
# DAST page cache TTL must comfortably outlive the base-data cache (max(900, ttl×3))
# and the SQLite bundle cache (max(15, ttl))  so page_coverage remains populated through
# multiple bundle expiry cycles without disappearing between refreshes.
_DAST_PAGE_CACHE_TTL_SECONDS = max(3600, int(getattr(settings, "analytics_cache_ttl_seconds", 180) or 180) * 4)
_DAST_PAGE_ERROR_TTL_SECONDS = 120
_DAST_PAGE_REFRESH_LIMIT = 500
_DAST_PAGE_REFRESH_TIMEOUT_SECONDS = 20.0
_DAST_PAGE_FETCH_TIMEOUT_SECONDS = 4.0
_DAST_PAGE_REFRESH_CONCURRENCY = 6


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("Items", "items", "value", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def _first(item: dict[str, Any], keys: list[str], fallback: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return fallback


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _parse_duration_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed >= 0 else None

    raw = str(value).strip()
    if not raw:
        return None

    # HH:MM:SS(.mmm) or MM:SS
    if ":" in raw:
        parts = raw.split(":")
        try:
            if len(parts) == 3:
                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])
                return max(0.0, hours * 3600 + minutes * 60 + seconds)
            if len(parts) == 2:
                minutes = float(parts[0])
                seconds = float(parts[1])
                return max(0.0, minutes * 60 + seconds)
        except ValueError:
            return None

    try:
        parsed = float(raw)
        return parsed if parsed >= 0 else None
    except ValueError:
        return None


def _first_numeric(item: dict[str, Any], keys: list[str]) -> float | None:
    latest = item.get("LatestExecution") if isinstance(item, dict) else None
    for key in keys:
        if isinstance(latest, dict) and key in latest:
            parsed = _parse_duration_to_seconds(latest.get(key))
            if parsed is not None:
                return parsed
        if key in item:
            parsed = _parse_duration_to_seconds(item.get(key))
            if parsed is not None:
                return parsed

    # Some ASoC payloads nest execution counters deeper than the first level.
    key_set = {str(key).strip().lower() for key in keys if str(key).strip()}

    def _find_numeric_nested(value: Any, depth: int) -> float | None:
        if depth < 0 or value is None:
            return None
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if str(nested_key).strip().lower() in key_set:
                    parsed = _parse_duration_to_seconds(nested_value)
                    if parsed is not None:
                        return parsed
            for nested_value in value.values():
                parsed = _find_numeric_nested(nested_value, depth - 1)
                if parsed is not None:
                    return parsed
            return None
        if isinstance(value, list):
            for item_value in value:
                parsed = _find_numeric_nested(item_value, depth - 1)
                if parsed is not None:
                    return parsed
        return None

    if isinstance(latest, dict):
        nested = _find_numeric_nested(latest, 3)
        if nested is not None:
            return nested

    nested = _find_numeric_nested(item, 3)
    if nested is not None:
        return nested
    return None


def _extract_scan_duration_seconds(item: dict[str, Any]) -> float:
    # Phase 1 – fields whose values are already in seconds.
    value = _first_numeric(
        item,
        [
            "ExecutionDurationSec",       # ASoC actual field (in LatestExecution, flattened by _map_scan_item)
            "DurationSeconds",
            "durationSeconds",
            "ScanDurationSeconds",
            "ExecutionTimeSeconds",
            "ExecutionDurationSeconds",
            "TotalSeconds",
            "ElapsedSeconds",
        ],
    )
    if value is not None:
        return float(value or 0.0)

    # Phase 2 – fields whose values are in minutes; convert to seconds.
    minutes_value = _first_numeric(
        item,
        [
            "ExecutionMinutes",
            "DurationMinutes",
            "ScanDurationMinutes",
            "ExecutionTimeMinutes",
            "TotalMinutes",
            "ElapsedMinutes",
        ],
    )
    if minutes_value is not None:
        return float(minutes_value or 0.0) * 60.0

    # Phase 3 – ambiguous name; use the value as-is (treat as seconds).
    ambiguous = _first_numeric(
        item,
        [
            "Duration",
            "ExecutionDuration",
            "ScanDuration",
            "ExecutionTime",
            "ScanTime",
        ],
    )
    return float(ambiguous or 0.0)


def _extract_scan_page_coverage(item: dict[str, Any]) -> int:
    value = _first_numeric(
        item,
        [
            "NVisitedPages",
            "nVisitedPages",
            "PagesDiscovered",
            "pagesDiscovered",
            "PagesTested",
            "pagesTested",
            "PagesVisited",
            "pagesVisited",
            "VisitedPages",
            "visitedPages",
            "PagesCrawled",
            "pagesCrawled",
            "CrawledPages",
            "crawledPages",
            "PagesFound",
            "pagesFound",
            "PageCount",
            "pageCount",
            "NumPages",
            "numPages",
            "TotalPages",
            "totalPages",
            "UrlCount",
            "urlCount",
            "UrlsVisited",
            "urlsVisited",
            "VisitedUrls",
            "visitedUrls",
            "TotalUrls",
            "totalUrls",
        ],
    )
    return int(value or 0)


def _collect_page_like_key_hits(payload: Any, *, max_hits: int = 24) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    include_tokens = ("page", "url", "crawl", "discover", "visited", "tested")

    def _walk(value: Any, path: str, depth: int) -> None:
        if len(hits) >= max_hits or depth < 0:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                key_str = str(key)
                next_path = f"{path}.{key_str}" if path else key_str
                lower_key = key_str.lower()
                if any(token in lower_key for token in include_tokens):
                    entry: dict[str, Any] = {"path": next_path, "type": type(nested).__name__}
                    if isinstance(nested, (int, float, str, bool)) or nested is None:
                        entry["value"] = nested
                    hits.append(entry)
                    if len(hits) >= max_hits:
                        return
                _walk(nested, next_path, depth - 1)
                if len(hits) >= max_hits:
                    return
            return
        if isinstance(value, list):
            for index, nested in enumerate(value[:10]):
                next_path = f"{path}[{index}]" if path else f"[{index}]"
                _walk(nested, next_path, depth - 1)
                if len(hits) >= max_hits:
                    return

    _walk(payload, "", 4)
    return hits


def _extract_sast_size_profile(item: dict[str, Any]) -> int:
    value = _first_numeric(
        item,
        [
            # Explicit size fields (bytes / KB / MB – heuristic conversion applied later)
            "SourceSize",
            "sourceSize",
            "CodeSize",
            "codeSize",
            "TargetSize",
            "targetSize",
            # File-count fields (used when byte-granularity is unavailable)
            "FileCount",
            "fileCount",
            "nFiles",
            "NFiles",
            "NumFiles",
            "numFiles",
            "FilesAnalyzed",
            "filesAnalyzed",
            "ScannedFiles",
            "scannedFiles",
            "AnalyzedFiles",
            "analyzedFiles",
            "TotalFiles",
            "totalFiles",
            # Lines of code as last-resort proxy
            "LinesOfCode",
            "linesOfCode",
            "Loc",
        ],
    )
    return int(value or 0)


def _extract_sca_size_profile(item: dict[str, Any]) -> int:
    value = _first_numeric(
        item,
        [
            "NOpenSourcePackages",        # ASoC actual field (in LatestExecution, flattened by _map_scan_item)
            "DependencyCount",
            "dependencyCount",
            "PackageCount",
            "packageCount",
            "nPackages",
            "NPackages",
            "NumPackages",
            "numPackages",
            "LibraryCount",
            "libraryCount",
            "ModuleCount",
            "moduleCount",
            "ComponentCount",
            "componentCount",
            "DirectDependencies",
            "directDependencies",
            "TransitiveDependencies",
            "transitiveDependencies",
            "ArtifactSize",
            "artifactSize",
        ],
    )
    return int(value or 0)


def _iso_month(value: str | None) -> str | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m")


def _normalize_scan_type(item: dict[str, Any]) -> str:
    raw = _first(
        item,
        ["ScanType", "Type", "Technology", "scanType", "type", "ScanTechnology", "TestType"],
        "Unknown",
    )
    value = raw.strip().upper()
    if "DYNAMIC" in value or "DAST" in value:
        return "DAST"
    if "STATIC" in value or "SAST" in value:
        return "SAST"
    if "SCA" in value:
        return "SCA"
    if "IAST" in value:
        return "IAST"

    # Fallback for scan naming conventions where type is embedded in the name.
    name_hint = str(item.get("Name", "")).upper()
    if "DAST" in name_hint:
        return "DAST"
    if "SAST" in name_hint:
        return "SAST"
    if "SCA" in name_hint:
        return "SCA"
    if "IAST" in name_hint:
        return "IAST"

    for known in ("DAST", "SAST", "SCA", "IAST"):
        if known in value:
            return known
    return "OTHER"


def _normalize_scan_status(item: dict[str, Any]) -> str:
    latest = item.get("LatestExecution") if isinstance(item, dict) else None
    latest_status = ""
    if isinstance(latest, dict):
        latest_status = _first(latest, ["Status", "ExecutionStatusType", "StatusType", "State"], "")

    value = _first(item, ["Status", "status", "ExecutionStatus", "State"], latest_status or "Unknown").strip().lower()
    if value in {"completed", "complete", "finished", "done"}:
        return "completed"
    if value in {"ready", "finishedwithwarning", "readywithissues"}:
        return "completed"
    if value in {"failed", "error", "aborted", "canceled", "cancelled"}:
        return "failed"
    if value in {"running", "inprogress", "in progress"}:
        return "running"
    if value in {"pending", "queued", "scheduled"}:
        return "pending"
    return value or "unknown"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _extract_native_scan_severity(item: dict[str, Any]) -> str:
    latest = item.get("LatestExecution") if isinstance(item, dict) else None
    latest_severity = ""
    if isinstance(latest, dict):
        latest_severity = _first(
            latest,
            ["Severity", "RiskLevel", "Risk", "MaxSeverity", "HighestSeverity", "IssueSeverity"],
            "",
        )

    candidate = _first(
        item,
        ["Severity", "RiskLevel", "Risk", "MaxSeverity", "HighestSeverity", "IssueSeverity"],
        latest_severity,
    )
    return _normalize_severity(candidate)


def _is_active_issue(item: dict[str, Any]) -> bool:
    value = str(item.get("status", "")).strip().lower()
    return value not in {"closed", "fixed", "resolved"}


def _normalize_severity(value: str | None) -> str:
    level = str(value or "").strip().lower()
    if level in {"critical", "4", "sev4", "sev-4", "veryhigh"}:
        return "critical"
    if level in {"high", "3", "sev3", "sev-3"}:
        return "high"
    if level in {"medium", "moderate", "2", "sev2", "sev-2"}:
        return "medium"
    if level in {"low", "1", "sev1", "sev-1", "info", "informational", "0"}:
        return "low"
    return "unknown"


def _normalize_issue_technology(value: str | None) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return "UNKNOWN"
    if "DAST" in raw or "DYNAMIC" in raw:
        return "DAST"
    if "SAST" in raw or "STATIC" in raw:
        return "SAST"
    if "SCA" in raw:
        return "SCA"
    if "IAST" in raw:
        return "IAST"
    return "UNKNOWN"


def _resolve_issue_technology(
    issue: dict[str, Any],
    app_technology_map: dict[str, set[str]],
    app_primary_technology: dict[str, str],
) -> str:
    """Resolve one technology per issue to keep counts and filters deterministic."""
    explicit = _normalize_issue_technology(str(issue.get("issue_technology", "") or ""))
    if explicit != "UNKNOWN":
        return explicit

    app_id = str(issue.get("application_id", "") or "")
    app_tech = {t for t in app_technology_map.get(app_id, set()) if t in {"DAST", "SAST", "SCA", "IAST"}}
    if len(app_tech) == 1:
        return next(iter(app_tech))
    if app_id in app_primary_technology:
        return app_primary_technology[app_id]
    return "UNKNOWN"


def _build_app_technology_maps(scans: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, str]]:
    app_technology_map: dict[str, set[str]] = {}
    app_technology_counts: dict[str, dict[str, int]] = {}

    for scan in scans:
        app_id = str(scan.get("application_id", "") or "")
        if not app_id:
            continue
        scan_type = str(scan.get("scan_type", "") or "").upper()
        if scan_type not in {"DAST", "SAST", "SCA", "IAST"}:
            continue
        app_technology_map.setdefault(app_id, set()).add(scan_type)
        bucket = app_technology_counts.setdefault(app_id, {})
        bucket[scan_type] = bucket.get(scan_type, 0) + 1

    # Tie-breaker priority keeps assignment deterministic across runs.
    priority = {"DAST": 4, "SAST": 3, "SCA": 2, "IAST": 1}
    app_primary_technology: dict[str, str] = {}
    for app_id, counts in app_technology_counts.items():
        winner = sorted(counts.items(), key=lambda item: (-item[1], -priority.get(item[0], 0), item[0]))[0][0]
        app_primary_technology[app_id] = winner

    return app_technology_map, app_primary_technology


def _period_bucket(value: str | None, period: str) -> str | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    if period == "day":
        return parsed.strftime("%Y-%m-%d")
    if period == "year":
        return parsed.strftime("%Y")
    if period == "week":
        iso_year, iso_week, _ = parsed.isocalendar()
        return f"{iso_year}-W{int(iso_week):02d}"
    return parsed.strftime("%Y-%m")


def _filter_by_period(
    items: list[dict[str, Any]],
    key: str,
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> list[dict[str, Any]]:
    if not from_dt and not to_dt:
        return items
    result: list[dict[str, Any]] = []
    for item in items:
        when = _parse_dt(str(item.get(key, "")))
        if when is None:
            continue
        if from_dt and when < from_dt:
            continue
        if to_dt and when > to_dt:
            continue
        result.append(item)
    return result


class AsocReadService:
    def __init__(self) -> None:
        self._client = AsocApiClient()

    @classmethod
    def for_endpoint(
        cls, url: str, key: str, secret: str, *, verify: bool | str = True,
    ) -> "AsocReadService":
        """Return a service instance bound to a specific ASoC endpoint.

        Use this for multi-endpoint deployments where each configured endpoint
        should be queried independently.  The returned instance shares no
        in-memory cache state with other instances.
        """
        instance = cls.__new__(cls)
        instance._client = AsocApiClient.make(url, key, secret, verify=verify)
        return instance

    @staticmethod
    def _extract_dast_visited_pages(payload: Any) -> int:
        if not isinstance(payload, dict):
            return 0
        value = _first_numeric(
            payload,
            [
                "NVisitedPages",
                "nVisitedPages",
                "VisitedPages",
                "visitedPages",
                "NVisitedUrls",
                "nVisitedUrls",
                "VisitedUrls",
                "visitedUrls",
            ],
        )
        if value is not None:
            return _safe_int(value, 0)
        return _extract_scan_page_coverage(payload)

    async def _apply_cached_dast_coverage(self, scans: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc)
        async with _DAST_PAGE_CACHE_LOCK:
            for scan in scans:
                if str(scan.get("scan_type", "")).upper() != "DAST":
                    continue
                scan_id = str(scan.get("id", "")).strip()
                if not scan_id:
                    continue
                entry = _DAST_PAGE_CACHE.get(scan_id)
                if not isinstance(entry, dict):
                    continue
                expires_at = entry.get("expires_at")
                if not isinstance(expires_at, datetime) or expires_at <= now:
                    continue
                cached_pages = _safe_int(entry.get("visited_pages"), 0)
                if cached_pages > 0:
                    scan["page_coverage"] = max(_safe_int(scan.get("page_coverage"), 0), cached_pages)

    async def hydrate_dast_page_coverage(
        self,
        scans: list[dict[str, Any]],
        *,
        schedule_refresh: bool = True,
    ) -> list[dict[str, Any]]:
        if not isinstance(scans, list):
            return []

        hydrated: list[dict[str, Any]] = []
        for item in scans:
            if isinstance(item, dict):
                hydrated.append(dict(item))

        await self._apply_cached_dast_coverage(hydrated)
        if schedule_refresh:
            await self._schedule_dast_coverage_refresh(hydrated)
        return hydrated

    async def _schedule_dast_coverage_refresh(self, scans: list[dict[str, Any]]) -> None:
        global _DAST_PAGE_REFRESH_TASK
        global _DAST_PAGE_REFRESH_CURSOR

        now = datetime.now(timezone.utc)
        candidates: list[dict[str, Any]] = []

        def _created_at_sort_key(scan: dict[str, Any]) -> float:
            parsed = _parse_dt(str(scan.get("created_at", "")))
            return parsed.timestamp() if parsed else 0.0

        sorted_scans = sorted(scans, key=_created_at_sort_key, reverse=True)

        async with _DAST_PAGE_CACHE_LOCK:
            prepared: list[dict[str, Any]] = []
            for scan in sorted_scans:
                if str(scan.get("scan_type", "")).upper() != "DAST":
                    continue
                scan_id = str(scan.get("id", "")).strip()
                if not scan_id:
                    continue

                current_pages = _safe_int(scan.get("page_coverage"), 0)
                if current_pages > 0:
                    _DAST_PAGE_CACHE[scan_id] = {
                        "visited_pages": current_pages,
                        "collected_at": now,
                        "expires_at": now + timedelta(seconds=_DAST_PAGE_CACHE_TTL_SECONDS),
                        "source": "scan_list",
                    }
                    continue

                entry = _DAST_PAGE_CACHE.get(scan_id)
                expires_at = entry.get("expires_at") if isinstance(entry, dict) else None
                if isinstance(expires_at, datetime) and expires_at > now:
                    continue

                prepared.append(
                    {
                        "id": scan_id,
                        "created_at": str(scan.get("created_at", "") or ""),
                        "exec_id": str(scan.get("_latest_exec_id", "") or ""),
                    }
                )

            if prepared:
                window_size = min(_DAST_PAGE_REFRESH_LIMIT, len(prepared))
                recent_priority = min(20, window_size)

                selected_ids: set[str] = set()
                for scan in prepared[:recent_priority]:
                    scan_id = str(scan.get("id") or "").strip()
                    if not scan_id or scan_id in selected_ids:
                        continue
                    candidates.append(scan)
                    selected_ids.add(scan_id)

                start = _DAST_PAGE_REFRESH_CURSOR % len(prepared)
                _DAST_PAGE_REFRESH_CURSOR = (start + window_size) % len(prepared)
                idx = start
                visited = 0
                while len(candidates) < window_size and visited < len(prepared):
                    scan = prepared[idx]
                    scan_id = str(scan.get("id") or "").strip()
                    if scan_id and scan_id not in selected_ids:
                        candidates.append(scan)
                        selected_ids.add(scan_id)
                    idx = (idx + 1) % len(prepared)
                    visited += 1

        if not candidates:
            return

        if _DAST_PAGE_REFRESH_TASK is not None and not _DAST_PAGE_REFRESH_TASK.done():
            return

        _DAST_PAGE_REFRESH_TASK = asyncio.create_task(self._refresh_dast_coverage_cache(candidates))

    async def _refresh_dast_coverage_cache(self, scans: list[dict[str, Any]]) -> None:
        global _DAST_PAGE_REFRESH_TASK

        semaphore = asyncio.Semaphore(max(2, _DAST_PAGE_REFRESH_CONCURRENCY))

        async def _fetch(scan: dict[str, Any]) -> tuple[str, int, str]:
            scan_id = str(scan.get("id", "")).strip()
            if not scan_id:
                return "", 0, "invalid"

            # Use DastExecution/{exec_id} which is the only ASoC Cloud endpoint
            # that returns NVisitedPages. Fall back to the legacy scan-detail
            # endpoint if exec_id was not recorded.
            exec_id = str(scan.get("exec_id", "")).strip()
            endpoint = (
                f"/api/v4/Scans/DastExecution/{exec_id}"
                if exec_id
                else f"/api/v4/Scans/Dast/{scan_id}"
            )
            async with semaphore:
                try:
                    payload = await asyncio.wait_for(
                        self._client.get(endpoint),
                        timeout=_DAST_PAGE_FETCH_TIMEOUT_SECONDS,
                    )
                    pages = self._extract_dast_visited_pages(payload)
                    return scan_id, _safe_int(pages, 0), "dast_execution_detail"
                except Exception:
                    return scan_id, 0, "error"

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_fetch(scan) for scan in scans], return_exceptions=True),
                timeout=_DAST_PAGE_REFRESH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return
        finally:
            if _DAST_PAGE_REFRESH_TASK is not None and _DAST_PAGE_REFRESH_TASK.done():
                _DAST_PAGE_REFRESH_TASK = None

        now = datetime.now(timezone.utc)
        async with _DAST_PAGE_CACHE_LOCK:
            for item in results:
                if isinstance(item, Exception):
                    continue
                scan_id, pages, source = item
                if not scan_id:
                    continue
                ttl = _DAST_PAGE_CACHE_TTL_SECONDS if pages > 0 else _DAST_PAGE_ERROR_TTL_SECONDS
                _DAST_PAGE_CACHE[scan_id] = {
                    "visited_pages": _safe_int(pages, 0),
                    "collected_at": now,
                    "expires_at": now + timedelta(seconds=ttl),
                    "source": source,
                }

        _DAST_PAGE_REFRESH_TASK = None

    @staticmethod
    def _extract_page_coverage_from_payload(payload: Any) -> int:
        candidates: list[dict[str, Any]] = []

        if isinstance(payload, dict):
            candidates.append(payload)
            latest = payload.get("LatestExecution")
            if isinstance(latest, dict):
                candidates.append(latest)

        for item in _extract_items(payload):
            candidates.append(item)
            latest = item.get("LatestExecution")
            if isinstance(latest, dict):
                candidates.append(latest)

        best = 0
        for candidate in candidates:
            best = max(best, _extract_scan_page_coverage(candidate))
        return best

    async def _enrich_dast_page_coverage(self, scans: list[dict[str, Any]]) -> None:
        dast_scans = [
            scan
            for scan in scans
            if str(scan.get("scan_type", "")).upper() == "DAST"
        ]
        if not dast_scans:
            return

        # Keep normal requests fast; enrich only when source list has no DAST coverage values at all.
        if any(_safe_int(scan.get("page_coverage"), 0) > 0 for scan in dast_scans):
            return

        candidates = [
            scan
            for scan in dast_scans
            if str(scan.get("id", "")).strip()
        ]
        if not candidates:
            return

        def _created_at_sort_key(scan: dict[str, Any]) -> float:
            parsed = _parse_dt(str(scan.get("created_at", "")))
            return parsed.timestamp() if parsed else 0.0

        candidates.sort(key=_created_at_sort_key, reverse=True)
        max_candidates = 50
        candidates = candidates[:max_candidates]

        semaphore = asyncio.Semaphore(max(2, min(12, settings.asoc_issue_app_concurrency)))

        async def _fetch_coverage(scan: dict[str, Any]) -> int:
            scan_id = str(scan.get("id", "")).strip()
            if not scan_id:
                return 0

            endpoints: list[tuple[str, dict[str, Any] | None]] = [
                (f"/api/v4/Scans/{scan_id}", None),
                (f"/api/v4/Scans/{scan_id}/LatestExecution", None),
                (f"/api/v4/Scans/{scan_id}/Statistics", None),
                (f"/api/v4/Scans/{scan_id}/Executions", {"$top": 5, "$skip": 0}),
            ]

            async with semaphore:
                best = 0
                execution_ids: list[str] = []
                for path, params in endpoints:
                    try:
                        payload = await asyncio.wait_for(self._client.get(path, params=params), timeout=3.0)
                    except Exception:
                        continue
                    best = max(best, self._extract_page_coverage_from_payload(payload))
                    if best > 0:
                        return best

                    if path.endswith("/Executions"):
                        for item in _extract_items(payload):
                            execution_id = _first(item, ["Id", "id", "ExecutionId", "executionId"], "")
                            if execution_id:
                                execution_ids.append(execution_id)

                for execution_id in execution_ids[:2]:
                    try:
                        payload = await asyncio.wait_for(
                            self._client.get(f"/api/v4/Scans/{scan_id}/Executions/{execution_id}"),
                            timeout=3.0,
                        )
                    except Exception:
                        continue
                    best = max(best, self._extract_page_coverage_from_payload(payload))
                    if best > 0:
                        return best
                return best

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[_fetch_coverage(scan) for scan in candidates],
                    return_exceptions=True,
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            return

        for scan, pages in zip(candidates, results):
            if isinstance(pages, Exception):
                continue
            if _safe_int(pages, 0) > 0:
                scan["page_coverage"] = _safe_int(pages, 0)

    async def diagnose_dast_page_coverage(
        self,
        *,
        scan_ids: list[str] | None = None,
        max_scans: int = 6,
    ) -> dict[str, Any]:
        if not self.has_credentials:
            return {
                "status": "no_credentials",
                "message": "ASoC credentials are not configured; diagnostics unavailable.",
                "items": [],
            }

        requested_ids = [str(item).strip() for item in (scan_ids or []) if str(item).strip()]
        target_scans: list[dict[str, Any]] = []

        if requested_ids:
            for scan_id in requested_ids[: max(1, min(max_scans, 20))]:
                target_scans.append({"id": scan_id, "name": scan_id, "created_at": ""})
        else:
            # Sample recent DAST scans from the list endpoint.
            try:
                raw_scans = await asyncio.wait_for(
                    self._fetch_all_pages(
                        "/api/v4/Scans",
                        base_params={"$top": 40, "$skip": 0},
                        max_pages=1,
                    ),
                    timeout=8.0,
                )
            except Exception as exc:
                return {
                    "status": "timeout",
                    "message": "Unable to fetch scan sample quickly for diagnostics.",
                    "error": type(exc).__name__,
                    "items": [],
                }
            mapped = [
                {
                    "id": _first(item, ["Id", "id", "ScanId"]),
                    "name": _first(item, ["Name", "name", "ScanName"], "Unnamed Scan"),
                    "scan_type": _normalize_scan_type(item),
                    "asset_group_id": _first(
                        item,
                        ["AssetGroupId", "AssetGroupID", "assetGroupId", "asset_group_id"],
                        "",
                    ),
                    "created_at": _first(item, ["CreatedAt", "createdAt", "DateCreated", "LastModified"], ""),
                    "mapped_page_coverage": _extract_scan_page_coverage(item),
                }
                for item in raw_scans
            ]
            mapped = [item for item in mapped if str(item.get("scan_type", "")) == "DAST" and str(item.get("id", ""))]

            def _sort_key(item: dict[str, Any]) -> float:
                parsed = _parse_dt(str(item.get("created_at", "")))
                return parsed.timestamp() if parsed else 0.0

            mapped.sort(key=_sort_key, reverse=True)
            target_scans = mapped[: max(1, min(max_scans, 20))]

        semaphore = asyncio.Semaphore(4)

        async def _probe_scan(scan: dict[str, Any]) -> dict[str, Any]:
            scan_id = str(scan.get("id", "")).strip()
            result: dict[str, Any] = {
                "scan_id": scan_id,
                "scan_name": str(scan.get("name", "") or scan_id),
                "created_at": str(scan.get("created_at", "") or ""),
                "asset_group_id": str(scan.get("asset_group_id", "") or ""),
                "mapped_page_coverage": _safe_int(scan.get("mapped_page_coverage"), 0),
                "endpoint_results": [],
            }

            if not scan_id:
                return result

            endpoints: list[tuple[str, dict[str, Any] | None]] = [
                (f"/api/v4/Scans/Dast/{scan_id}", None),
                (f"/api/v4/Scans/{scan_id}", None),
                (f"/api/v4/Scans/{scan_id}/LatestExecution", None),
                (f"/api/v4/Scans/{scan_id}/Executions", {"$top": 1, "$skip": 0}),
            ]

            execution_ids: list[str] = []
            async with semaphore:
                for endpoint, params in endpoints:
                    try:
                        payload = await asyncio.wait_for(self._client.get(endpoint, params=params), timeout=3.0)
                        extracted = self._extract_page_coverage_from_payload(payload)
                        key_hits = _collect_page_like_key_hits(payload)
                        top_level_keys: list[str] = []
                        first_item_keys: list[str] = []
                        if isinstance(payload, dict):
                            top_level_keys = sorted([str(key) for key in payload.keys()])[:80]
                            items = _extract_items(payload)
                            if items and isinstance(items[0], dict):
                                first_item_keys = sorted([str(key) for key in items[0].keys()])[:80]
                        result["endpoint_results"].append(
                            {
                                "endpoint": endpoint,
                                "ok": True,
                                "extracted_page_coverage": extracted,
                                "key_hits": key_hits,
                                "top_level_keys": top_level_keys,
                                "first_item_keys": first_item_keys,
                            }
                        )
                        if endpoint.endswith("/Executions"):
                            for row in _extract_items(payload):
                                execution_id = _first(row, ["Id", "id", "ExecutionId", "executionId"], "")
                                if execution_id:
                                    execution_ids.append(execution_id)
                    except Exception as exc:
                        result["endpoint_results"].append(
                            {
                                "endpoint": endpoint,
                                "ok": False,
                                "error": type(exc).__name__,
                            }
                        )

                for execution_id in execution_ids[:2]:
                    endpoint = f"/api/v4/Scans/{scan_id}/Executions/{execution_id}"
                    try:
                        payload = await asyncio.wait_for(self._client.get(endpoint), timeout=3.0)
                        extracted = self._extract_page_coverage_from_payload(payload)
                        key_hits = _collect_page_like_key_hits(payload)
                        top_level_keys: list[str] = []
                        first_item_keys: list[str] = []
                        if isinstance(payload, dict):
                            top_level_keys = sorted([str(key) for key in payload.keys()])[:80]
                            items = _extract_items(payload)
                            if items and isinstance(items[0], dict):
                                first_item_keys = sorted([str(key) for key in items[0].keys()])[:80]
                        result["endpoint_results"].append(
                            {
                                "endpoint": endpoint,
                                "ok": True,
                                "extracted_page_coverage": extracted,
                                "key_hits": key_hits,
                                "top_level_keys": top_level_keys,
                                "first_item_keys": first_item_keys,
                            }
                        )
                    except Exception as exc:
                        result["endpoint_results"].append(
                            {
                                "endpoint": endpoint,
                                "ok": False,
                                "error": type(exc).__name__,
                            }
                        )

            positives = [
                _safe_int(item.get("extracted_page_coverage"), 0)
                for item in result["endpoint_results"]
                if isinstance(item, dict)
            ]
            result["best_extracted_page_coverage"] = max(positives) if positives else 0
            return result

        try:
            probed = await asyncio.wait_for(
                asyncio.gather(*[_probe_scan(scan) for scan in target_scans], return_exceptions=True),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "message": "Diagnostics probe exceeded time budget.",
                "sample_size": 0,
                "items": [],
            }
        items: list[dict[str, Any]] = []
        for item in probed:
            if isinstance(item, Exception):
                continue
            items.append(item)

        return {
            "status": "ok",
            "sample_size": len(items),
            "items": items,
        }

    async def _fetch_all_pages(
        self,
        path: str,
        *,
        base_params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        params = dict(base_params or {})
        top = int(params.get("$top") or settings.asoc_page_size)
        page_limit = max_pages if max_pages is not None else settings.asoc_max_pages
        skip = int(params.get("$skip") or 0)
        results: list[dict[str, Any]] = []

        for _ in range(page_limit):
            page_params = dict(params)
            page_params["$top"] = top
            page_params["$skip"] = skip
            payload = await self._client.get(path, params=page_params)
            items = _extract_items(payload)
            if not items:
                break
            results.extend(items)
            if len(items) < top:
                break
            skip += top
        return results

    async def get_issue_counts(
        self,
        *,
        application_id: str | None = None,
        odata_filter: str | None = None,
    ) -> dict[str, int]:
        """Fetch accurate issue counts using /Count endpoints.

        Makes up to 10 parallel requests:
          - total
          - active (Status eq 'Open')
          - critical / high / medium / low (by Severity)
          - SAST / DAST / SCA / IAST (by Technology)

        Returns a dict with keys:
          total, active, resolved, critical, high, medium, low,
          sast, dast, sca, iast

        Falls back to zeros on any error so callers always get a usable dict.
        """
        if not self.has_credentials:
            return {
                "total": 0, "active": 0, "resolved": 0,
                "critical": 0, "high": 0, "medium": 0, "low": 0,
                "sast": 0, "dast": 0, "sca": 0, "iast": 0,
            }

        base_path = (
            f"/api/v4/Issues/Application/{application_id}/Count"
            if application_id
            else "/api/v4/Issues/Count"
        )

        def _build_filter(*parts: str) -> str | None:
            filters = [p for p in parts if p]
            if odata_filter:
                filters.append(odata_filter)
            return " and ".join(filters) if filters else None

        async def _count(extra_filter: str | None = None) -> int:
            params: dict[str, Any] = {}
            f = _build_filter(extra_filter or "")
            if f:
                params["$filter"] = f
            try:
                return await self._client.get_count(base_path, params=params or None)
            except Exception:
                return 0

        (
            total,
            active,
            fixed,
            critical,
            high,
            medium,
            low,
            sast,
            dast,
            sca,
            iast,
        ) = await asyncio.gather(
            _count(),
            _count("Status eq 'Open'"),
            _count("Status eq 'Fixed'"),
            _count("Severity eq 'Critical'"),
            _count("Severity eq 'High'"),
            _count("Severity eq 'Medium'"),
            _count("Severity eq 'Low'"),
            _count("Technology eq 'SAST'"),
            _count("Technology eq 'DAST'"),
            _count("Technology eq 'SCA'"),
            _count("Technology eq 'IAST'"),
        )

        return {
            "total": total,
            "active": active,
            # Use an explicit Fixed-status count rather than (total - active) which
            # would incorrectly classify InProgress, New and Noise as "resolved".
            "resolved": fixed,
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": max(total - critical - high - medium, 0) if low == 0 else low,
            "sast": sast,
            "dast": dast,
            "sca": sca,
            "iast": iast,
        }

    async def get_filtered_count(
        self,
        *,
        severity: str | None = None,
        technology: str | None = None,
        status: str | None = None,
        application_id: str | None = None,
    ) -> int:
        """Get a single filtered count using compound OData filter.

        Builds a compound ``$filter`` from the provided dimensions and calls
        the appropriate /Count endpoint.  Returns 0 on any error so callers
        always receive a usable integer.
        """
        if not self.has_credentials:
            return 0

        filters: list[str] = []
        if severity:
            filters.append(f"Severity eq '{severity}'")
        if technology:
            filters.append(f"Technology eq '{technology}'")
        if status:
            filters.append(f"Status eq '{status}'")

        base_path = (
            f"/api/v4/Issues/Application/{application_id}/Count"
            if application_id
            else "/api/v4/Issues/Count"
        )

        params: dict[str, Any] = {}
        if filters:
            params["$filter"] = " and ".join(filters)

        try:
            return await self._client.get_count(base_path, params=params or None)
        except Exception:
            return 0

    async def get_issue_counts_per_app(
        self,
        app_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Get issue counts for multiple applications in parallel.

        For each ``app_id`` in *app_ids*, calls :meth:`get_issue_counts` with
        ``application_id=app_id`` under a shared :class:`asyncio.Semaphore`
        bounded by ``settings.asoc_count_concurrency``.

        Returns a list of dicts, each containing the ``app_id`` key plus all
        keys returned by :meth:`get_issue_counts`.
        """
        if not self.has_credentials or not app_ids:
            return []

        ids = [str(app_id).strip() for app_id in app_ids if str(app_id).strip()]
        if not ids:
            return []

        semaphore = asyncio.Semaphore(max(1, settings.asoc_count_concurrency))

        async def _fetch_one(app_id: str) -> dict[str, Any]:
            async with semaphore:
                try:
                    counts = await self.get_issue_counts(application_id=app_id)
                except Exception:
                    counts = {
                        "total": 0, "active": 0, "resolved": 0,
                        "critical": 0, "high": 0, "medium": 0, "low": 0,
                        "sast": 0, "dast": 0, "sca": 0, "iast": 0,
                    }
                return {"app_id": app_id, **counts}

        results = await asyncio.gather(
            *[_fetch_one(app_id) for app_id in ids],
            return_exceptions=True,
        )
        output: list[dict[str, Any]] = []
        for app_id, result in zip(ids, results):
            if isinstance(result, BaseException):
                output.append({
                    "app_id": app_id,
                    "total": 0, "active": 0, "resolved": 0,
                    "critical": 0, "high": 0, "medium": 0, "low": 0,
                    "sast": 0, "dast": 0, "sca": 0, "iast": 0,
                })
            else:
                output.append(result)
        return output

    @property
    def has_credentials(self) -> bool:
        return bool(self._client.api_key and self._client.api_secret and self._client.base_url)

    async def get_tenant_info(self, *, use_mock_on_error: bool = True) -> dict[str, Any]:
        if not self.has_credentials:
            return {}
        try:
            payload = await self._client.get("/api/v4/Account/TenantInfo")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            if use_mock_on_error:
                return {}
            raise

    @staticmethod
    def _map_scan_item(item: dict[str, Any]) -> dict[str, Any]:
        """Map a raw ASoC scan API item to the internal scan dict shape."""
        # Flatten LatestExecution sub-fields so metric extractors can find them at top level.
        # LatestExecution contains ExecutionDurationSec, NOpenSourcePackages, etc.
        # item wins on any key conflict to preserve top-level field primacy.
        _le: dict[str, Any] = item.get("LatestExecution") or {}
        _merged: dict[str, Any] = {**_le, **item}
        return {
            "id": _first(item, ["Id", "id", "ScanId"]),
            "name": _first(item, ["Name", "name", "ScanName"], "Unnamed Scan"),
            "status": _normalize_scan_status(item),
            "scan_type": _normalize_scan_type(item),
            "asset_group_id": _first(
                item,
                ["AssetGroupId", "AssetGroupID", "assetGroupId", "asset_group_id"],
                "",
            ),
            "application_id": _first(item, ["ApplicationId", "applicationId", "AppId", "AppID"], ""),
            "application_name": _first(item, ["ApplicationName", "AppName", "applicationName"], ""),
            "native_severity": _extract_native_scan_severity(item),
            "created_at": _first(item, ["CreatedAt", "createdAt", "DateCreated", "LastModified"], ""),
            "duration_seconds": _extract_scan_duration_seconds(_merged),
            "page_coverage": _extract_scan_page_coverage(_merged),
            "sast_size": _extract_sast_size_profile(_merged),
            "sca_size": _extract_sca_size_profile(_merged),
            "target_name": _first(item, ["Target", "TargetName", "FileName", "Path", "EntryPoint"], ""),
            "_latest_exec_id": _first(_le, ["Id", "id", "ExecutionId"], ""),
        }

    async def list_scans_via_apps(self, *, use_mock_on_error: bool = True) -> list[dict[str, Any]]:
        """Attempt to fetch scans per-application using ``GET /api/v4/Apps/{appId}/Scans``.

        NOTE: This endpoint returns 404 on AppScan on Cloud (cloud.appscan.com).
        It is preserved here for on-premises ASoC deployments that may support it.
        The caller (:meth:`list_scans`) will fall back to the org-level endpoint
        when this method returns an empty list.

        Uses a single-app probe to detect endpoint availability before attempting
        to fetch all apps — avoids flooding logs with 404 errors.
        """
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        apps = await self.list_applications(use_mock_on_error=use_mock_on_error)
        app_ids = [str(a.get("id", "")) for a in apps if a.get("id")]

        if not app_ids:
            _logger.debug("list_scans_via_apps: no applications found")
            return []

        # Probe a single app to detect whether the per-app scan endpoint is supported.
        # If the probe raises (e.g. 404), skip the entire per-app approach immediately.
        probe_id = app_ids[0]
        try:
            probe_result = await self._fetch_all_pages(
                f"/api/v4/Apps/{probe_id}/Scans",
                max_pages=1,
            )
        except Exception as exc:
            _logger.debug(
                "list_scans_via_apps: per-app scan endpoint not supported "
                "(probe for app %s raised %s: %s) — skipping",
                probe_id,
                type(exc).__name__,
                exc,
            )
            # Return empty list so list_scans() falls back to org-level immediately.
            return []

        # Endpoint is supported — fetch remaining apps.
        sem = asyncio.Semaphore(max(1, settings.asoc_issue_app_concurrency))
        all_scans: list[dict[str, Any]] = list(probe_result)
        seen_ids: set[str] = {
            str(item.get("Id") or item.get("id") or item.get("ScanId") or "")
            for item in probe_result
            if item.get("Id") or item.get("id") or item.get("ScanId")
        }

        async def _fetch_app_scans(app_id: str) -> list[dict[str, Any]]:
            async with sem:
                try:
                    return await self._fetch_all_pages(
                        f"/api/v4/Apps/{app_id}/Scans",
                        max_pages=10000,
                    )
                except Exception as exc:
                    _logger.debug("list_scans_via_apps: app %s: %s", app_id, exc)
                    return []

        if len(app_ids) > 1:
            results = await asyncio.gather(*[_fetch_app_scans(aid) for aid in app_ids[1:]])
            for scan_list in results:
                for raw_item in scan_list:
                    scan_id = str(raw_item.get("Id") or raw_item.get("id") or raw_item.get("ScanId") or "")
                    if scan_id and scan_id not in seen_ids:
                        seen_ids.add(scan_id)
                        all_scans.append(raw_item)

        _logger.info(
            "list_scans_via_apps: fetched %d unique scans across %d apps",
            len(all_scans),
            len(app_ids),
        )
        return all_scans

    async def list_scans(self, *, use_mock_on_error: bool = True) -> list[dict[str, Any]]:
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        if not self.has_credentials:
            items: list[dict[str, Any]] = mock_data.scans()
        else:
            # PRIMARY: per-app scan fetching — guaranteed complete because per-app
            # scan counts are small and never hit pagination caps.
            # Falls back silently to org-level when the per-app endpoint is not supported.
            try:
                raw_items = await self.list_scans_via_apps(use_mock_on_error=False)
                if raw_items:
                    mapped_scans = [self._map_scan_item(item) for item in raw_items]
                    _logger.info("list_scans: per-app approach returned %d scans", len(mapped_scans))
                    return await self.hydrate_dast_page_coverage(mapped_scans, schedule_refresh=True)
                _logger.info("list_scans: per-app endpoint not available; using org-level GET /api/v4/Scans")
            except Exception as exc:
                _logger.warning("list_scans: per-app approach failed (%s); using org-level endpoint", exc)

            # FALLBACK / PRIMARY for cloud.appscan.com: org-level scan listing.
            # Note: this endpoint may be capped at 2000 results on some tenants.
            # ASoC rejects $top=1000 for Scans with HTTP 400 — cap at 500.
            try:
                items = await self._fetch_all_pages("/api/v4/Scans", base_params={"$top": 500})
                _logger.info("list_scans: org-level endpoint returned %d scans", len(items))
            except Exception:
                if use_mock_on_error:
                    items = mock_data.scans()
                else:
                    raise

        mapped_scans = [self._map_scan_item(item) for item in items]
        return await self.hydrate_dast_page_coverage(mapped_scans, schedule_refresh=True)

    async def list_applications(self, *, use_mock_on_error: bool = True) -> list[dict[str, Any]]:
        if not self.has_credentials:
            return mock_data.applications()
        try:
            items = await self._fetch_all_pages("/api/v4/Apps")
        except Exception:
            if use_mock_on_error:
                return mock_data.applications()
            raise
        return [
            {
                "id": _first(item, ["Id", "id", "ApplicationId"]),
                "name": _first(item, ["Name", "name", "ApplicationName"], "Unnamed Application"),
                "asset_group_id": _first(
                    item,
                    ["AssetGroupId", "AssetGroupID", "assetGroupId", "asset_group_id"],
                    "",
                ),
                "asset_group_name": _first(item, ["AssetGroupName", "assetGroupName", "asset_group_name"], ""),
                "created_at": _first(item, ["CreatedAt", "createdAt", "DateCreated", "OnboardedAt", "created_at"], ""),
                "last_updated": _first(item, ["LastUpdated", "lastUpdated", "UpdatedAt", "updatedAt", "last_updated"], ""),
                # Issue counts — directly from the /api/v4/Apps response
                "critical_issues": _safe_int(item.get("critical_issues") or item.get("CriticalIssues") or item.get("criticalIssues"), 0),
                "high_issues": _safe_int(item.get("high_issues") or item.get("HighIssues") or item.get("highIssues"), 0),
                "medium_issues": _safe_int(item.get("medium_issues") or item.get("MediumIssues") or item.get("mediumIssues"), 0),
                "low_issues": _safe_int(item.get("low_issues") or item.get("LowIssues") or item.get("lowIssues"), 0),
                "informational_issues": _safe_int(item.get("informational_issues") or item.get("InformationalIssues") or item.get("informationalIssues"), 0),
                "total_issues": _safe_int(item.get("total_issues") or item.get("TotalIssues") or item.get("totalIssues"), 0),
                "open_issues": _safe_int(item.get("open_issues") or item.get("OpenIssues") or item.get("openIssues"), 0),
                "new_issues": _safe_int(item.get("new_issues") or item.get("NewIssues") or item.get("newIssues"), 0),
                "issues_in_progress": _safe_int(item.get("issues_in_progress") or item.get("IssuesInProgress") or item.get("issuesInProgress"), 0),
                # Scan counts
                "total_scans": _safe_int(item.get("total_scans") or item.get("TotalScans") or item.get("totalScans"), 0),
                "n_scan_executions": _safe_int(item.get("n_scan_executions") or item.get("NScanExecutions") or item.get("nScanExecutions"), 0),
                # Risk / status metadata
                "risk_rating": _first(item, ["RiskRating", "riskRating", "risk_rating"], "Unknown"),
                "max_severity": _first(item, ["MaxSeverity", "maxSeverity", "max_severity"], "Undetermined"),
                "business_impact": _first(item, ["BusinessImpact", "businessImpact", "business_impact"], "Unspecified"),
                "testing_status": _first(item, ["TestingStatus", "testingStatus", "testing_status"], "NotStarted"),
                "scan_technologies": _first(item, ["ScanTechnologies", "scanTechnologies", "scan_technologies"], "NONE"),
                "overall_compliance": bool(item.get("overall_compliance", item.get("OverallCompliance", True))),
            }
            for item in items
        ]

    @staticmethod
    def calculate_statistics_from_apps(
        apps: list[dict[str, Any]],
        scans: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Calculate accurate statistics by summing per-app counts from /api/v4/Apps response.

        This is the MOST RELIABLE approach — the issue/scan counts are embedded directly
        in each application object returned by GET /api/v4/Apps, so no extra API calls
        are needed and there are no pagination truncation issues.
        """
        total_issues = sum(int(a.get("total_issues") or a.get("TotalIssues") or 0) for a in apps)
        critical = sum(int(a.get("critical_issues") or a.get("CriticalIssues") or 0) for a in apps)
        high = sum(int(a.get("high_issues") or a.get("HighIssues") or 0) for a in apps)
        medium = sum(int(a.get("medium_issues") or a.get("MediumIssues") or 0) for a in apps)
        low = sum(int(a.get("low_issues") or a.get("LowIssues") or 0) for a in apps)
        informational = sum(int(a.get("informational_issues") or a.get("InformationalIssues") or 0) for a in apps)
        open_issues = sum(int(a.get("open_issues") or a.get("OpenIssues") or 0) for a in apps)
        new_issues = sum(int(a.get("new_issues") or a.get("NewIssues") or 0) for a in apps)
        in_progress = sum(int(a.get("issues_in_progress") or a.get("IssuesInProgress") or 0) for a in apps)
        total_scans = sum(int(a.get("total_scans") or a.get("TotalScans") or 0) for a in apps)

        active = open_issues + new_issues + in_progress
        resolved = max(0, total_issues - active)

        # Scan-related stats from the scans list if provided
        scan_count = total_scans if total_scans > 0 else (len(scans) if scans else 0)
        running_scans = 0
        failed_scans = 0
        if scans:
            for s in scans:
                status = str(s.get("status") or s.get("Status") or "").lower()
                if status in ("running", "inqueue", "pending", "starting"):
                    running_scans += 1
                elif status in ("failed", "error"):
                    failed_scans += 1

        return {
            "total_issues": total_issues,
            "critical_issues": critical,
            "high_issues": high,
            "medium_issues": medium,
            "low_issues": low,
            "informational_issues": informational,
            "active_issues": active,
            "open_issues": open_issues,
            "new_issues": new_issues,
            "in_progress_issues": in_progress,
            "fixed_issues": resolved,
            "resolved_issues": resolved,
            "total_scans": scan_count,
            "running_scans": running_scans,
            "failed_scans": failed_scans,
            "total_applications": len(apps),
            "count_source": "app_aggregation",
        }

    async def list_asset_groups(self, *, use_mock_on_error: bool = True) -> list[dict[str, Any]]:
        if not self.has_credentials:
            return mock_data.asset_groups()
        try:
            items = await self._fetch_all_pages("/api/v4/AssetGroups")
        except Exception:
            if use_mock_on_error:
                return mock_data.asset_groups()
            raise
        return [
            {
                "id": _first(item, ["Id", "id", "AssetGroupId"]),
                "name": _first(item, ["Name", "name", "AssetGroupName"], "Unnamed Asset Group"),
            }
            for item in items
        ]

    async def list_issues(self, *, use_mock_on_error: bool = True) -> list[dict[str, Any]]:
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        if not self.has_credentials:
            return mock_data.issues()

        # PRIMARY: per-application issue fetching — guaranteed complete because
        # per-app issue counts are bounded and never hit org-level pagination caps.
        # Even the largest app won't have more than ~50,000 issues per page window.
        try:
            apps = await self.list_applications(use_mock_on_error=use_mock_on_error)
            app_ids = [str(app.get("id", "")) for app in apps if str(app.get("id", ""))]
            if app_ids:
                aggregated = await self.list_issues_for_applications(app_ids, use_mock_on_error=False)
                if aggregated:
                    _logger.info(
                        "list_issues: per-app approach fetched %d issues across %d apps",
                        len(aggregated),
                        len(app_ids),
                    )
                    return aggregated
                _logger.warning(
                    "list_issues: per-app approach returned 0 issues for %d apps; falling back to org-level endpoint",
                    len(app_ids),
                )
            else:
                _logger.warning("list_issues: no applications found; falling back to org-level endpoint")
        except Exception as exc:
            _logger.warning("list_issues: per-app approach failed (%s: %s); falling back to org-level endpoint", type(exc).__name__, exc)

        # FALLBACK: org-level issue listing (may be truncated by pagination caps).
        try:
            org_items = await self._fetch_all_pages("/api/v4/Issues")
            org_mapped = self._map_issue_items(org_items)
            if org_mapped:
                _logger.info("list_issues: org-level fallback returned %d issues", len(org_mapped))
                return org_mapped
        except Exception as exc:
            _logger.warning("list_issues: org-level fallback also failed: %s: %s", type(exc).__name__, exc)

        if use_mock_on_error:
            return mock_data.issues()
        raise RuntimeError("Unable to retrieve issues from ASoC API.")

    @staticmethod
    def _map_issue_items(payload_items: list[dict[str, Any]], default_app_id: str = "") -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        for item in payload_items:
            severity = _normalize_severity(_first(item, ["Severity", "severity"], "Unknown"))
            fix_group_id = _first(
                item,
                ["FixGroupId", "fixGroupId", "FixGroup", "GroupId", "IssueGroupId"],
                "",
            )
            fix_group_name = _first(
                item,
                ["FixGroupName", "fixGroupName", "FixGroup", "GroupName", "IssueGroupName"],
                fix_group_id or "Unassigned",
            )
            correlation_key = _first(
                item,
                [
                    "CorrelationId",
                    "CorrelationKey",
                    "IssueType",
                    "IssueTypeName",
                    "VulnerabilityType",
                    "VulnerabilityName",
                    "IssueName",
                ],
                fix_group_name,
            )
            mapped.append(
                {
                    "id": _first(item, ["Id", "id", "IssueId"]),
                    "severity": severity,
                    "status": _first(item, ["Status", "status"], "Open"),
                    "asset_group_id": _first(
                        item,
                        ["AssetGroupId", "AssetGroupID", "assetGroupId", "asset_group_id"],
                        "",
                    ),
                    "application_id": _first(item, ["ApplicationId", "applicationId", "AppId"], default_app_id),
                    "application_name": _first(item, ["ApplicationName", "AppName", "applicationName"], ""),
                    "opened_at": _first(
                        item,
                        [
                            "DateCreated",
                            "CreatedAt",
                            "createdAt",
                            "OpenDate",
                            "LastFound",
                            "FirstFound",
                        ],
                        "",
                    ),
                    "closed_at": _first(
                        item,
                        [
                            "ClosedAt",
                            "closedAt",
                            "ResolvedDate",
                            "DateClosed",
                            "ClosedDate",
                        ],
                        "",
                    ),
                    "mttr_days": item.get("MttrDays", item.get("mttr_days", 0)) or 0,
                    "fix_group_id": fix_group_id,
                    "fix_group_name": fix_group_name,
                    "correlation_key": correlation_key,
                    "vulnerability": _first(
                        item,
                        [
                            "IssueTypeName",
                            "IssueType",
                            "VulnerabilityType",
                            "VulnerabilityName",
                            "IssueName",
                        ],
                        correlation_key,
                    ),
                    "issue_technology": _first(
                        item,
                        [
                            "Technology",
                            "ScanType",
                            "TestType",
                            "Analyzer",
                            "Engine",
                        ],
                        "",
                    ),
                }
            )

            if not mapped[-1]["closed_at"] and str(mapped[-1]["status"]).strip().lower() in {
                "closed",
                "fixed",
                "resolved",
            }:
                mapped[-1]["closed_at"] = _first(item, ["LastUpdated", "UpdatedAt", "updatedAt"], "")
        return mapped

    async def list_issues_for_applications(
        self,
        app_ids: list[str],
        *,
        use_mock_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        if not self.has_credentials:
            return mock_data.issues() if use_mock_on_error else []

        ids = [str(app_id).strip() for app_id in app_ids if str(app_id).strip()]
        if not ids:
            return []

        semaphore = asyncio.Semaphore(max(1, settings.asoc_issue_app_concurrency))

        async def _fetch_for_app(app_id: str) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    payload_items = await self._fetch_all_pages(
                        f"/api/v4/Issues/Application/{app_id}",
                        # Use effectively unlimited pages per app — even the largest app
                        # won't have more than ~50,000 issues, so 10000 pages × 1000 per page
                        # is more than sufficient and guarantees no truncation.
                        max_pages=10000,
                    )
                    if payload_items:
                        _logger.debug(
                            "list_issues_for_applications: app %s returned %d issues",
                            app_id,
                            len(payload_items),
                        )
                except Exception as exc:
                    _logger.warning(
                            "list_issues_for_applications: failed to fetch issues for app %s: %s: %s",
                            app_id,
                            type(exc).__name__,
                            exc,
                    )
                    return []
                return self._map_issue_items(payload_items, default_app_id=app_id)

        results = await asyncio.gather(*[_fetch_for_app(app_id) for app_id in ids], return_exceptions=True)
        aggregated: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, list):
                aggregated.extend(result)

        _logger.info(
            "list_issues_for_applications: fetched %d total issues across %d apps",
            len(aggregated),
            len(ids),
        )

        if not aggregated and use_mock_on_error:
            return mock_data.issues()
        return aggregated

    @staticmethod
    def apply_filters(
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        *,
        asset_group_id: str | None = None,
        asset_group_ids: list[str] | None = None,
        application_id: str | None = None,
        application_ids: list[str] | None = None,
        application_name: str | None = None,
        issue_technologies: list[str] | None = None,
        vulnerabilities: list[str] | None = None,
        scan_types: list[str] | None = None,
        scan_statuses: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        from_dt = _parse_dt(from_date)
        to_dt = _parse_dt(to_date)
        asset_group_set = set(asset_group_ids or ([] if not asset_group_id else [asset_group_id]))
        application_set = set(application_ids or ([] if not application_id else [application_id]))
        app_name_needle = application_name.lower() if application_name else ""
        issue_technology_set = {
            _normalize_issue_technology(value)
            for value in (issue_technologies or [])
            if _normalize_issue_technology(value) != "UNKNOWN"
        }
        scan_type_set = {
            str(value or "").strip().upper()
            for value in (scan_types or [])
            if str(value or "").strip().upper() in {"DAST", "SAST", "SCA", "IAST", "OTHER"}
        }
        scan_status_set = {
            str(value or "").strip().lower()
            for value in (scan_statuses or [])
            if str(value or "").strip().lower()
        }
        vulnerability_set = {
            str(value or "").strip().lower()
            for value in (vulnerabilities or [])
            if str(value or "").strip()
        }

        app_technology_map, app_primary_technology = _build_app_technology_maps(scans)

        def scan_match(item: dict[str, Any]) -> bool:
            if asset_group_set:
                item_group = str(item.get("asset_group_id", ""))
                if item_group:
                    if item_group not in asset_group_set:
                        return False
                elif not application_set:
                    # When group id is missing, only allow matching by explicit application scope.
                    return False
            if application_set and str(item.get("application_id", "")) not in application_set:
                return False
            if app_name_needle and app_name_needle not in str(item.get("application_name", "")).lower():
                return False
            if issue_technology_set:
                scan_type = str(item.get("scan_type", "") or "").upper()
                if scan_type not in issue_technology_set:
                    return False
            if scan_type_set:
                scan_type = str(item.get("scan_type", "") or "").upper()
                if scan_type not in scan_type_set:
                    return False
            if scan_status_set:
                status = str(item.get("status", "") or "").lower()
                if status not in scan_status_set:
                    return False
            return True

        filtered_scans = [item for item in scans if scan_match(item)]
        scan_filter_active = bool(scan_type_set or scan_status_set)
        scoped_scan_app_ids = {
            str(item.get("application_id", ""))
            for item in filtered_scans
            if str(item.get("application_id", ""))
        }

        def issue_match(item: dict[str, Any]) -> bool:
            if asset_group_set:
                item_group = str(item.get("asset_group_id", ""))
                if item_group:
                    if item_group not in asset_group_set:
                        return False
                elif not application_set:
                    # When group id is missing, only allow matching by explicit application scope.
                    return False
            if application_set and str(item.get("application_id", "")) not in application_set:
                return False
            if app_name_needle and app_name_needle not in str(item.get("application_name", "")).lower():
                return False
            if issue_technology_set:
                technology = _resolve_issue_technology(item, app_technology_map, app_primary_technology)
                if technology == "UNKNOWN" or technology not in issue_technology_set:
                    return False
            if vulnerability_set:
                vuln = str(item.get("vulnerability", "") or item.get("correlation_key", "")).strip().lower()
                if vuln not in vulnerability_set:
                    return False

            if scan_filter_active:
                issue_app_id = str(item.get("application_id", ""))
                if not issue_app_id or issue_app_id not in scoped_scan_app_ids:
                    return False
            return True

        filtered_issues = [item for item in issues if issue_match(item)]

        filtered_scans = _filter_by_period(filtered_scans, "created_at", from_dt, to_dt)
        filtered_issues = _filter_by_period(filtered_issues, "opened_at", from_dt, to_dt)
        return filtered_scans, filtered_issues

    @staticmethod
    def filter_issues_by_dimensions(
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        *,
        issue_technologies: list[str] | None = None,
        vulnerabilities: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        issue_technology_set = {
            _normalize_issue_technology(value)
            for value in (issue_technologies or [])
            if _normalize_issue_technology(value) != "UNKNOWN"
        }
        vulnerability_set = {
            str(value or "").strip().lower()
            for value in (vulnerabilities or [])
            if str(value or "").strip()
        }

        if not issue_technology_set and not vulnerability_set:
            return list(issues)

        app_technology_map, app_primary_technology = _build_app_technology_maps(scans)
        filtered: list[dict[str, Any]] = []
        for item in issues:
            if issue_technology_set:
                technology = _resolve_issue_technology(item, app_technology_map, app_primary_technology)
                if technology == "UNKNOWN" or technology not in issue_technology_set:
                    continue

            if vulnerability_set:
                vuln = str(item.get("vulnerability", "") or item.get("correlation_key", "")).strip().lower()
                if vuln not in vulnerability_set:
                    continue

            filtered.append(item)

        return filtered

    @staticmethod
    def build_issue_filter_options(
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        *,
        vulnerability_limit: int = 2000,
    ) -> dict[str, Any]:
        app_technology_map, app_primary_technology = _build_app_technology_maps(scans)

        tech_counts: dict[str, int] = {"DAST": 0, "SAST": 0, "SCA": 0, "IAST": 0}
        unknown_count = 0
        vuln_counts: dict[str, int] = {}
        vuln_labels: dict[str, str] = {}

        for issue in issues:
            technology = _resolve_issue_technology(issue, app_technology_map, app_primary_technology)
            if technology in tech_counts:
                tech_counts[technology] += 1
            else:
                unknown_count += 1

            label = str(issue.get("vulnerability", "") or issue.get("correlation_key", "")).strip()
            if not label:
                continue
            key = label.lower()
            vuln_counts[key] = vuln_counts.get(key, 0) + 1
            vuln_labels.setdefault(key, label)

        technology_items = [
            {"value": technology, "label": technology, "count": int(tech_counts.get(technology, 0))}
            for technology in ("DAST", "SAST", "SCA", "IAST")
        ]

        vulnerability_items = sorted(
            (
                {
                    "value": key,
                    "label": vuln_labels.get(key, key),
                    "count": count,
                }
                for key, count in vuln_counts.items()
            ),
            key=lambda item: (-int(item["count"]), str(item["label"]).lower()),
        )
        if vulnerability_limit > 0:
            vulnerability_items = vulnerability_items[:vulnerability_limit]

        return {
            "technologies": technology_items,
            "unclassified_count": int(unknown_count),
            "vulnerabilities": vulnerability_items,
        }

    @staticmethod
    def _counts_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in items:
            value = str(item.get(key, "") or "unknown")
            out[value] = out.get(value, 0) + 1
        return out

    @staticmethod
    def _scans_grouped_by_application(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for scan in scans:
            app_id = str(scan.get("application_id", "") or "unknown")
            app_name = str(scan.get("application_name", "") or app_id)
            bucket = grouped.setdefault(
                app_id,
                {"application_id": app_id, "application_name": app_name, "count": 0},
            )
            bucket["count"] += 1
        return sorted(grouped.values(), key=lambda item: item["count"], reverse=True)

    def build_portfolio_summary(
        self,
        *,
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        applications: list[dict[str, Any]],
        asset_groups: list[dict[str, Any]],
        count_overrides: dict[str, int] | None = None,
        app_based_statistics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active_issues = [issue for issue in issues if _is_active_issue(issue)]
        failed_scans = [scan for scan in scans if str(scan.get("status", "")).lower() == "failed"]
        running_or_pending = [
            scan for scan in scans if str(scan.get("status", "")).lower() in {"running", "pending"}
        ]

        # Priority: 1) app-based aggregation, 2) count_overrides, 3) len(issues)
        app_stats = app_based_statistics or {}
        overrides = count_overrides or {}

        if app_stats.get("count_source") == "app_aggregation":
            total_issues = int(app_stats.get("total_issues", 0))
            active_issue_count = int(app_stats.get("active_issues", len(active_issues)))
            scan_count = int(app_stats.get("total_scans", len(scans)))
        elif overrides:
            total_issues = overrides.get("total", len(issues))
            active_issue_count = overrides.get("active", len(active_issues))
            scan_count = len(scans)
        else:
            total_issues = len(issues)
            active_issue_count = len(active_issues)
            scan_count = len(scans)

        return {
            "asset_group_count": len(asset_groups),
            "application_count": len(applications),
            "scan_count": scan_count,
            "scan_count_by_type": self._counts_by(scans, "scan_type"),
            "scan_count_by_status": self._counts_by(scans, "status"),
            "failed_scans_by_application": self._scans_grouped_by_application(failed_scans),
            "running_or_pending_scans_by_application": self._scans_grouped_by_application(running_or_pending),
            "total_issues": total_issues,
            "active_issues": active_issue_count,
            "active_issue_trend": self.calculate_trend(active_issues),
            "mttr_trend": self.calculate_mttr(issues),
        }

    @staticmethod
    def calculate_statistics(
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        *,
        count_overrides: dict[str, int] | None = None,
    ) -> dict[str, int]:
        """Calculate statistics.

        When count_overrides is provided (from /Count endpoints), those values
        take precedence over len(issues) for total/severity/active counts.
        The issues list is still used for open_scans and scan-derived metrics.
        """
        overrides = count_overrides or {}

        open_scans = sum(
            1
            for scan in scans
            if str(scan.get("status", "")).lower() in {"running", "pending", "queued", "scheduled"}
        )

        if overrides:
            total_issues = overrides.get("total", len(issues))
            active_issues = overrides.get("active", sum(1 for issue in issues if _is_active_issue(issue)))
            resolved_issues = overrides.get("resolved", max(total_issues - active_issues, 0))
            critical_count = overrides.get("critical", 0)
            high_count = overrides.get("high", 0)
            medium_count = overrides.get("medium", 0)
            low_count = overrides.get("low", max(total_issues - critical_count - high_count - medium_count, 0))
            sast_issues = overrides.get("sast", 0)
            dast_issues = overrides.get("dast", 0)
            sca_issues = overrides.get("sca", 0)
            iast_issues = overrides.get("iast", 0)
            count_source = "api_count"
        else:
            critical_count = sum(1 for issue in issues if _normalize_severity(issue.get("severity")) == "critical")
            high_count = sum(1 for issue in issues if _normalize_severity(issue.get("severity")) == "high")
            medium_count = sum(1 for issue in issues if _normalize_severity(issue.get("severity")) == "medium")
            low_count = max(len(issues) - critical_count - high_count - medium_count, 0)
            active_issues = sum(1 for issue in issues if _is_active_issue(issue))
            resolved_issues = max(len(issues) - active_issues, 0)
            total_issues = len(issues)
            _app_tech_map, _app_primary_tech = _build_app_technology_maps(scans)
            sast_issues = sum(1 for issue in issues if _resolve_issue_technology(issue, _app_tech_map, _app_primary_tech) == "SAST")
            dast_issues = sum(1 for issue in issues if _resolve_issue_technology(issue, _app_tech_map, _app_primary_tech) == "DAST")
            sca_issues = sum(1 for issue in issues if _resolve_issue_technology(issue, _app_tech_map, _app_primary_tech) == "SCA")
            iast_issues = sum(1 for issue in issues if _resolve_issue_technology(issue, _app_tech_map, _app_primary_tech) == "IAST")
            count_source = "pagination"

        return {
            "total_issues": total_issues,
            "active_issues": active_issues,
            "resolved_issues": resolved_issues,
            "critical_issues": critical_count,
            "high_issues": high_count,
            "medium_issues": medium_count,
            "low_issues": low_count,
            "open_scans": open_scans,
            "sast_issues": sast_issues,
            "dast_issues": dast_issues,
            "sca_issues": sca_issues,
            "iast_issues": iast_issues,
            "count_source": count_source,
        }

    @staticmethod
    def calculate_trend(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, int] = {}
        for issue in issues:
            month = _iso_month(str(issue.get("opened_at", "")))
            if not month:
                continue
            buckets[month] = buckets.get(month, 0) + 1

        if not buckets:
            now = datetime.now(timezone.utc)
            return [{"month": now.strftime("%Y-%m"), "issues": len(issues)}]
        return [{"month": month, "issues": buckets[month]} for month in sorted(buckets.keys())]

    @staticmethod
    def calculate_mttr(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, list[int]] = {}
        for issue in issues:
            month = _iso_month(str(issue.get("closed_at", "")))
            mttr_raw = issue.get("mttr_days", 0)
            try:
                mttr_days = int(mttr_raw)
            except (TypeError, ValueError):
                mttr_days = 0
            if not month:
                continue
            buckets.setdefault(month, []).append(mttr_days)

        if not buckets:
            return [{"month": datetime.now(timezone.utc).strftime("%Y-%m"), "days": 0}]

        result: list[dict[str, Any]] = []
        for month in sorted(buckets.keys()):
            values = buckets[month]
            avg_days = round(sum(values) / len(values), 2) if values else 0
            result.append({"month": month, "days": avg_days})
        return result

    @staticmethod
    def calculate_kpi(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        total = len(issues) or 1
        critical = sum(1 for issue in issues if _normalize_severity(issue.get("severity")) == "critical")
        high = sum(1 for issue in issues if _normalize_severity(issue.get("severity")) == "high")
        closed = sum(1 for issue in issues if str(issue.get("status", "")).lower() in {"fixed", "closed"})
        return [
            {"kpi": "Critical Exposure", "value": round((critical / total) * 100, 2)},
            {"kpi": "High Exposure", "value": round((high / total) * 100, 2)},
            {"kpi": "Remediation Closure", "value": round((closed / total) * 100, 2)},
        ]

    @staticmethod
    def calculate_prioritization(issues: list[dict[str, Any]]) -> dict[str, Any]:
        severity_keys = ("critical", "high", "medium", "low", "unknown")

        def empty_counts() -> dict[str, int]:
            return {key: 0 for key in severity_keys}

        raw_counts = empty_counts()
        fix_groups: dict[str, dict[str, Any]] = {}
        app_hotspots: dict[str, dict[str, Any]] = {}
        correlations: dict[str, dict[str, Any]] = {}

        for issue in issues:
            sev = _normalize_severity(issue.get("severity"))
            raw_counts[sev] += 1

            app_id = str(issue.get("application_id") or "unknown")
            app_name = str(issue.get("application_name") or app_id)
            app_bucket = app_hotspots.setdefault(
                app_id,
                {"application_id": app_id, "application_name": app_name, "total": 0, **empty_counts()},
            )
            app_bucket["total"] += 1
            app_bucket[sev] += 1

            fg_id = str(issue.get("fix_group_id") or "unassigned")
            fg_name = str(issue.get("fix_group_name") or "Unassigned")
            fg_key = f"{fg_id}:{fg_name}"
            fg_bucket = fix_groups.setdefault(
                fg_key,
                {
                    "fix_group_id": fg_id,
                    "fix_group_name": fg_name,
                    "total": 0,
                    "applications": set(),
                    **empty_counts(),
                },
            )
            fg_bucket["total"] += 1
            fg_bucket[sev] += 1
            fg_bucket["applications"].add(app_name)

            corr_key = str(issue.get("correlation_key") or fg_name or "uncorrelated")
            corr_bucket = correlations.setdefault(
                corr_key,
                {
                    "correlation_key": corr_key,
                    "total": 0,
                    "applications": set(),
                    **empty_counts(),
                },
            )
            corr_bucket["total"] += 1
            corr_bucket[sev] += 1
            corr_bucket["applications"].add(app_name)

        def weighted_score(item: dict[str, Any]) -> int:
            return (
                int(item.get("critical", 0)) * 5
                + int(item.get("high", 0)) * 3
                + int(item.get("medium", 0)) * 2
                + int(item.get("low", 0))
            )

        def dominant_severity(item: dict[str, Any]) -> str:
            for key in ("critical", "high", "medium", "low"):
                if int(item.get(key, 0)) > 0:
                    return key
            return "unknown"

        top_fix_groups = sorted(fix_groups.values(), key=weighted_score, reverse=True)[:25]
        top_critical = sorted(app_hotspots.values(), key=weighted_score, reverse=True)[:25]
        top_correlated = [
            item
            for item in sorted(correlations.values(), key=weighted_score, reverse=True)
            if int(item.get("total", 0)) >= 2
        ][:25]

        for bucket in top_fix_groups:
            bucket["applications"] = sorted(bucket["applications"])
            bucket["application_count"] = len(bucket["applications"])
            bucket["score"] = weighted_score(bucket)
        for bucket in top_critical:
            bucket["score"] = weighted_score(bucket)
        for bucket in top_correlated:
            bucket["applications"] = sorted(bucket["applications"])
            bucket["application_count"] = len(bucket["applications"])
            bucket["score"] = weighted_score(bucket)

        # Group-level totals: each fix group contributes once using its dominant severity.
        fix_group_totals = {key: 0 for key in severity_keys}
        for item in fix_groups.values():
            fix_group_totals[dominant_severity(item)] += 1
        fix_group_totals["total"] = len(fix_groups)

        # Keep finding-level totals for detailed drill-down and validation.
        fix_group_finding_totals = {
            key: sum(int(item.get(key, 0)) for item in fix_groups.values()) for key in severity_keys
        }
        fix_group_finding_totals["total"] = sum(int(item.get("total", 0)) for item in fix_groups.values())

        raw_findings = {**raw_counts, "total": sum(raw_counts.values())}
        critical_total = sum(int(item.get("critical", 0)) for item in top_critical)
        correlation_total = sum(int(item.get("critical", 0)) + int(item.get("high", 0)) for item in top_correlated)

        return {
            "raw_findings": raw_findings,
            "fix_groups": {
                "total_groups": len(fix_groups),
                "totals": fix_group_totals,
                "finding_totals": fix_group_finding_totals,
                "top_groups": top_fix_groups,
            },
            "most_critical": top_critical,
            "correlated_findings": top_correlated,
            "highlights": {
                "critical_hotspot_total": critical_total,
                "correlated_high_risk_total": correlation_total,
            },
        }

    @staticmethod
    def calculate_findings_series(issues: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
        granularity = period if period in {"week", "month", "year"} else "month"
        buckets: dict[str, dict[str, int]] = {}

        for issue in issues:
            bucket = _period_bucket(str(issue.get("opened_at", "")), granularity)
            if not bucket:
                continue
            row = buckets.setdefault(
                bucket,
                {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0},
            )
            sev = _normalize_severity(issue.get("severity"))
            row[sev] += 1
            row["total"] += 1

        if not buckets:
            now = datetime.now(timezone.utc)
            key = now.strftime("%Y") if granularity == "year" else now.strftime("%Y-%m")
            if granularity == "week":
                iso_year, iso_week, _ = now.isocalendar()
                key = f"{iso_year}-W{int(iso_week):02d}"
            return [
                {
                    "period": key,
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "unknown": 0,
                    "total": 0,
                }
            ]

        return [{"period": key, **buckets[key]} for key in sorted(buckets.keys())]

    @staticmethod
    def calculate_scan_series(
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        period: str,
        severity_source: str = "hybrid",
    ) -> list[dict[str, Any]]:
        granularity = period if period in {"day", "week", "month"} else "month"
        severity_mode = severity_source.strip().lower()
        if severity_mode not in {"derived", "native", "hybrid"}:
            severity_mode = "hybrid"
        severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
        app_severity: dict[str, str] = {}

        # Derive scan severity from the highest active issue severity in the same application.
        for issue in issues:
            if not _is_active_issue(issue):
                continue
            app_id = str(issue.get("application_id", "") or "")
            if not app_id:
                continue
            sev = _normalize_severity(issue.get("severity"))
            current = app_severity.get(app_id, "unknown")
            if severity_rank.get(sev, 0) > severity_rank.get(current, 0):
                app_severity[app_id] = sev

        buckets: dict[str, dict[str, int]] = {}
        for scan in scans:
            bucket = _period_bucket(str(scan.get("created_at", "")), granularity)
            if not bucket:
                continue

            app_id = str(scan.get("application_id", "") or "")
            derived_severity = app_severity.get(app_id, "unknown")
            native_severity = _normalize_severity(scan.get("native_severity"))

            if severity_mode == "derived":
                sev = derived_severity
            elif severity_mode == "native":
                sev = native_severity
            else:
                sev = native_severity if native_severity != "unknown" else derived_severity

            row = buckets.setdefault(
                bucket,
                {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": 0},
            )
            row[sev] += 1
            row["total"] += 1

        if not buckets:
            now = datetime.now(timezone.utc)
            if granularity == "day":
                key = now.strftime("%Y-%m-%d")
            elif granularity == "week":
                iso_year, iso_week, _ = now.isocalendar()
                key = f"{iso_year}-W{int(iso_week):02d}"
            else:
                key = now.strftime("%Y-%m")
            return [
                {
                    "period": key,
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "unknown": 0,
                    "total": 0,
                }
            ]

        return [{"period": key, **buckets[key]} for key in sorted(buckets.keys())]

    @staticmethod
    def calculate_workbench_trends(
        scans: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        applications: list[dict[str, Any]],
        compliance_rule: str = "critical_high",
        compliance_threshold: str = "high",
        tenant_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Base monthly severity trend for vulnerabilities.
        criticality_series = AsocReadService.calculate_findings_series(issues, "month")
        if not criticality_series:
            now_key = datetime.now(timezone.utc).strftime("%Y-%m")
            criticality_series = [
                {
                    "period": now_key,
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "unknown": 0,
                    "total": 0,
                }
            ]

        # Cumulative vulnerabilities trend from monthly identified findings.
        cumulative_total = 0
        cumulative_series: list[dict[str, Any]] = []
        for row in criticality_series:
            total = int(row.get("total", 0) or 0)
            cumulative_total += total
            cumulative_series.append(
                {
                    "period": str(row.get("period", "")),
                    "monthly_total": total,
                    "cumulative_total": cumulative_total,
                }
            )

        # Application compliance trend:
        # - critical_high: non-compliant when month has critical/high findings
        # - any_open: non-compliant when month has any severity finding
        # - custom: non-compliant when month has severity at/above selected threshold
        normalized_rule = str(compliance_rule or "").strip().lower()
        if normalized_rule not in {"critical_high", "any_open", "custom"}:
            normalized_rule = "critical_high"

        normalized_threshold = str(compliance_threshold or "").strip().lower()
        if normalized_threshold not in {"critical", "high", "medium", "low"}:
            normalized_threshold = "high"

        severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
        threshold_rank = severity_rank.get(normalized_threshold, 3)

        months_from_scans = {
            month
            for month in (_iso_month(str(scan.get("created_at", ""))) for scan in scans)
            if month
        }
        months_from_issues = {
            month
            for month in (_iso_month(str(issue.get("opened_at", ""))) for issue in issues)
            if month
        }
        all_months = sorted(months_from_scans.union(months_from_issues))
        if not all_months:
            all_months = [datetime.now(timezone.utc).strftime("%Y-%m")]

        total_apps = len({str(app.get("id", "")) for app in applications if str(app.get("id", ""))})
        high_risk_by_month: dict[str, set[str]] = {month: set() for month in all_months}
        for issue in issues:
            month = _iso_month(str(issue.get("opened_at", "")))
            if not month or month not in high_risk_by_month:
                continue
            severity = _normalize_severity(issue.get("severity"))
            if normalized_rule == "critical_high":
                if severity not in {"critical", "high"}:
                    continue
            elif normalized_rule == "any_open":
                if severity == "unknown":
                    continue
            else:
                if severity_rank.get(severity, 0) < threshold_rank:
                    continue
            app_id = str(issue.get("application_id", "") or "")
            if not app_id:
                continue
            high_risk_by_month[month].add(app_id)

        compliance_series: list[dict[str, Any]] = []
        for month in all_months:
            non_compliant = len(high_risk_by_month.get(month, set()))
            compliant = max(total_apps - non_compliant, 0)
            compliance_rate = round((compliant / total_apps) * 100, 2) if total_apps > 0 else 0.0
            compliance_series.append(
                {
                    "period": month,
                    "total_apps": total_apps,
                    "compliant": compliant,
                    "non_compliant": non_compliant,
                    "compliance_rate": compliance_rate,
                }
            )

        # Application onboarded trend by month.
        # One application should contribute to exactly one onboarding month.
        # Prefer app created_at; if missing, fall back to earliest scan created_at for that app.
        app_identity_month: dict[str, str] = {}

        earliest_scan_month_by_app: dict[str, str] = {}
        for scan in scans:
            app_id = str(scan.get("application_id", "") or "").strip()
            if not app_id:
                continue
            month = _iso_month(str(scan.get("created_at", "")))
            if not month:
                continue
            current = earliest_scan_month_by_app.get(app_id)
            if current is None or month < current:
                earliest_scan_month_by_app[app_id] = month

        for app in applications:
            app_id = str(app.get("id", "") or app.get("name", "") or "").strip()
            if not app_id:
                continue
            month = _iso_month(str(app.get("created_at", "")))
            if not month:
                month = earliest_scan_month_by_app.get(app_id)
            if not month:
                continue
            app_identity_month[app_id] = month

        onboarded_buckets: dict[str, int] = {}
        for month in app_identity_month.values():
            onboarded_buckets[month] = onboarded_buckets.get(month, 0) + 1

        if not onboarded_buckets:
            fallback_month = all_months[-1] if all_months else datetime.now(timezone.utc).strftime("%Y-%m")
            onboarded_buckets[fallback_month] = len(applications)

        onboarded_series: list[dict[str, Any]] = []
        onboarded_running = 0
        for month in sorted(onboarded_buckets.keys()):
            count = _safe_int(onboarded_buckets.get(month), 0)
            onboarded_running += count
            onboarded_series.append(
                {
                    "period": month,
                    "onboarded_count": count,
                    "cumulative_onboarded": onboarded_running,
                }
            )

        # Average days to resolve findings trend by closed month.
        resolved_buckets: dict[str, dict[str, float]] = {}
        for issue in issues:
            closed = _parse_dt(str(issue.get("closed_at", "")))
            opened = _parse_dt(str(issue.get("opened_at", "")))
            if not closed:
                continue
            month = closed.strftime("%Y-%m")
            mttr_days = issue.get("mttr_days", 0)
            days = float(mttr_days or 0)
            if days <= 0 and opened:
                delta = (closed - opened).total_seconds() / 86400.0
                days = delta if delta > 0 else 0.0
            bucket = resolved_buckets.setdefault(month, {"sum_days": 0.0, "fixed_count": 0})
            bucket["sum_days"] += days
            bucket["fixed_count"] += 1

        avg_resolve_series: list[dict[str, Any]] = []
        for month in sorted(resolved_buckets.keys()):
            fixed_count = _safe_int(resolved_buckets[month].get("fixed_count"), 0)
            sum_days = float(resolved_buckets[month].get("sum_days", 0.0) or 0.0)
            avg_days = round(sum_days / fixed_count, 2) if fixed_count > 0 else 0.0
            avg_resolve_series.append(
                {
                    "period": month,
                    "average_days": avg_days,
                    "fixed_count": fixed_count,
                }
            )

        if not avg_resolve_series:
            avg_resolve_series.append(
                {
                    "period": all_months[-1],
                    "average_days": 0.0,
                    "fixed_count": 0,
                }
            )

        def _increment_bucket(row: dict[str, int], value: float, edges: list[tuple[str, float]]) -> None:
            for key, upper in edges:
                if value < upper:
                    row[key] = row.get(key, 0) + 1
                    row["total"] = row.get("total", 0) + 1
                    return
            row["total"] = row.get("total", 0) + 1

        # License consumption with model detection.
        technologies = ("DAST", "SAST", "SCA", "IAST")
        scans_by_tech: dict[str, list[dict[str, Any]]] = {
            tech: [scan for scan in scans if str(scan.get("scan_type", "")).upper() == tech]
            for tech in technologies
        }

        def _peak_concurrent(scans_for_tech: list[dict[str, Any]]) -> int:
            # Best-effort proxy: max scans started on the same UTC day.
            day_counts: dict[str, int] = {}
            for scan in scans_for_tech:
                day_key = _period_bucket(str(scan.get("created_at", "")), "day")
                if not day_key:
                    continue
                day_counts[day_key] = day_counts.get(day_key, 0) + 1
            return max(day_counts.values()) if day_counts else 0

        def _detect_license_model(info: dict[str, Any] | None) -> tuple[str, str]:
            if not info:
                return "unknown", "unknown"

            model_candidates: list[str] = []

            def _walk(obj: Any) -> None:
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        key_str = str(key).lower()
                        if "license" in key_str or "consumption" in key_str or "model" in key_str:
                            model_candidates.append(str(value))
                        _walk(value)
                elif isinstance(obj, list):
                    for item in obj:
                        _walk(item)

            _walk(info)
            blob = " | ".join(model_candidates).lower()
            if any(token in blob for token in ("per scan", "scan-based", "perscan", "scan model")):
                return "per_scan", "tenant_info"
            if any(token in blob for token in ("per app", "per application", "application-based", "perapplication")):
                return "per_application", "tenant_info"
            if "concurrent" in blob:
                return "per_concurrent", "tenant_info"
            return "unknown", "unknown"

        detected_model, model_source = _detect_license_model(tenant_info)

        if detected_model == "unknown":
            # Heuristic fallback to avoid empty identification when tenant metadata is sparse.
            total_scans = sum(len(items) for items in scans_by_tech.values())
            total_apps = len({str(item.get("application_id", "")) for item in scans if str(item.get("application_id", ""))})
            if total_scans > 0 and total_apps > 0:
                detected_model = "per_scan" if total_scans >= total_apps * 4 else "per_application"
                model_source = "heuristic"

        model_label_map = {
            "per_scan": "Per Scan",
            "per_application": "Per Application",
            "per_concurrent": "Per Concurrent",
            "unknown": "Unknown",
        }

        license_rows: list[dict[str, Any]] = []
        for tech in technologies:
            tech_scans = scans_by_tech.get(tech, [])
            consumed_scans = len(tech_scans)
            consumed_apps = len(
                {
                    str(scan.get("application_id", ""))
                    for scan in tech_scans
                    if str(scan.get("application_id", ""))
                }
            )
            peak_concurrent = _peak_concurrent(tech_scans)
            if detected_model == "per_application":
                consumed_units = consumed_apps
            elif detected_model == "per_concurrent":
                consumed_units = peak_concurrent
            else:
                consumed_units = consumed_scans

            license_rows.append(
                {
                    "technology": tech,
                    "consumed_units": consumed_units,
                    "consumed_scans": consumed_scans,
                    "consumed_apps": consumed_apps,
                    "peak_concurrent": peak_concurrent,
                }
            )

        license_consumption = {
            "detected_model": detected_model,
            "detected_model_label": model_label_map.get(detected_model, "Unknown"),
            "model_source": model_source,
            "technologies": license_rows,
            "summary": {
                "total_scans": sum(row["consumed_scans"] for row in license_rows),
                "total_apps": len({str(item.get("id", "")) for item in applications if str(item.get("id", ""))}),
            },
        }

        # Scan duration bucket trend by period (week/month/year) and technology.
        scan_time_bucket_specs = [
            ("lt5", "<5m", 5.0),
            ("m5_10", "5-10m", 10.0),
            ("m10_30", "10-30m", 30.0),
            ("m30_60", "30-60m", 60.0),
            ("m60_120", "60-120m", 120.0),
            ("m120_240", "120-240m", 240.0),
            ("m240_300", "240-300m", 300.0),
            ("gte300", ">=300m", float("inf")),
        ]
        scan_time_bucket_keys = [key for key, _, _ in scan_time_bucket_specs]
        scan_time_bucket_labels = [
            {"key": key, "label": label}
            for key, label, _ in scan_time_bucket_specs
        ]

        def _duration_bucket_key(duration_minutes: float) -> str:
            for key, _, upper in scan_time_bucket_specs:
                if duration_minutes < upper:
                    return key
            return "gte300"

        def _empty_scan_time_row() -> dict[str, dict[str, int]]:
            return {
                key: {"sast": 0, "sca": 0, "dast": 0, "total": 0}
                for key in scan_time_bucket_keys
            }

        scan_time_by_period_key: dict[str, dict[str, dict[str, dict[str, int]]]] = {
            "week": {},
            "month": {},
            "year": {},
        }

        for scan in scans:
            scan_type = str(scan.get("scan_type", "") or "").upper()
            if scan_type not in {"SAST", "SCA", "DAST"}:
                continue

            created_at = str(scan.get("created_at", ""))
            duration_minutes = float(scan.get("duration_seconds", 0.0) or 0.0) / 60.0
            bucket_key = _duration_bucket_key(duration_minutes)
            tech_key = scan_type.lower()

            for period_name in ("week", "month", "year"):
                period_value = _period_bucket(created_at, period_name)
                if not period_value:
                    continue
                period_rows = scan_time_by_period_key[period_name]
                row = period_rows.setdefault(period_value, _empty_scan_time_row())
                row[bucket_key][tech_key] += 1
                row[bucket_key]["total"] += 1

        now = datetime.now(timezone.utc)
        period_fallback = {
            "week": now.strftime("%G-W%V"),
            "month": now.strftime("%Y-%m"),
            "year": now.strftime("%Y"),
        }

        scan_time_series_by_period: dict[str, list[dict[str, Any]]] = {}
        for period_name in ("week", "month", "year"):
            period_rows = scan_time_by_period_key[period_name]
            if not period_rows:
                period_rows[period_fallback[period_name]] = _empty_scan_time_row()

            series_rows: list[dict[str, Any]] = []
            for period_key in sorted(period_rows.keys()):
                row_payload: dict[str, Any] = {"period": period_key}
                for bucket_key in scan_time_bucket_keys:
                    row_payload[bucket_key] = dict(period_rows[period_key][bucket_key])
                series_rows.append(row_payload)
            scan_time_series_by_period[period_name] = series_rows

        scan_time_series = {
            "default_period": "month",
            "default_bucket": "lt5",
            "period_options": ["week", "month", "year"],
            "bucket_options": scan_time_bucket_labels,
            "by_period": scan_time_series_by_period,
        }

        # Application/File Size profile for SAST and SCA with size buckets + top 10.
        size_bucket_specs = [
            ("lt1", "<1MB", "#b91c1c", 1.0),
            ("m1_5", "1-5MB", "#dc2626", 5.0),
            ("m5_10", "5-10MB", "#ea580c", 10.0),
            ("m10_20", "10-20MB", "#d97706", 20.0),
            ("m20_100", "20-100MB", "#ca8a04", 100.0),
            ("m100_500", "100-500MB", "#65a30d", 500.0),
            ("m500_1g", "500MB-1GB", "#0f766e", 1024.0),
            ("gt1g", ">1GB", "#1d4ed8", float("inf")),
        ]
        size_edges = [(key, upper) for key, _, _, upper in size_bucket_specs]
        size_bucket_keys = [key for key, _, _, _ in size_bucket_specs]
        size_bucket_options = [
            {"key": key, "label": label, "color": color}
            for key, label, color, _ in size_bucket_specs
        ]

        def _size_to_mb(raw: Any) -> float:
            try:
                value = float(raw or 0.0)
            except (TypeError, ValueError):
                return 0.0
            if value <= 0:
                return 0.0
            if value >= 5_000_000:
                return round(value / (1024.0 * 1024.0), 3)
            if value >= 5_000:
                return round(value / 1024.0, 3)
            return round(value, 3)

        def _size_bucket_key(size_mb: float) -> str:
            for key, upper in size_edges:
                if size_mb < upper:
                    return key
            return "gt1g"

        def _empty_size_row() -> dict[str, dict[str, int]]:
            return {
                key: {"sast": 0, "sca": 0, "total": 0}
                for key in size_bucket_keys
            }

        size_buckets = {
            "sast": {key: 0 for key, _ in size_edges},
            "sca": {key: 0 for key, _ in size_edges},
        }
        size_profile_map: dict[str, dict[str, Any]] = {}
        size_by_period_key: dict[str, dict[str, dict[str, dict[str, int]]]] = {
            "week": {},
            "month": {},
            "year": {},
        }

        for scan in scans:
            scan_type = str(scan.get("scan_type", "") or "").upper()
            if scan_type not in {"SAST", "SCA"}:
                continue

            tech_key = scan_type.lower()
            raw_size = scan.get("sast_size") if scan_type == "SAST" else scan.get("sca_size")
            size_mb = _size_to_mb(raw_size)
            bucket_key = _size_bucket_key(size_mb)
            _increment_bucket(size_buckets[tech_key], size_mb, size_edges)

            created_at = str(scan.get("created_at", ""))
            for period_name in ("week", "month", "year"):
                period_value = _period_bucket(created_at, period_name)
                if not period_value:
                    continue
                period_rows = size_by_period_key[period_name]
                row = period_rows.setdefault(period_value, _empty_size_row())
                row[bucket_key][tech_key] += 1
                row[bucket_key]["total"] += 1

            app_id = str(scan.get("application_id", "") or "")
            if not app_id:
                continue

            app_name = str(scan.get("application_name", "") or app_id)
            entry = size_profile_map.setdefault(
                app_id,
                {
                    "application_id": app_id,
                    "application_name": app_name,
                    "sast_size_mb": 0.0,
                    "sca_size_mb": 0.0,
                },
            )

            if scan_type == "SAST":
                entry["sast_size_mb"] = max(float(entry.get("sast_size_mb", 0.0) or 0.0), size_mb)
            else:
                entry["sca_size_mb"] = max(float(entry.get("sca_size_mb", 0.0) or 0.0), size_mb)

        size_series_by_period: dict[str, list[dict[str, Any]]] = {}
        for period_name in ("week", "month", "year"):
            period_rows = size_by_period_key[period_name]
            if not period_rows:
                period_rows[period_fallback[period_name]] = _empty_size_row()

            series_rows: list[dict[str, Any]] = []
            for period_key in sorted(period_rows.keys()):
                row_payload: dict[str, Any] = {"period": period_key}
                for bucket_key in size_bucket_keys:
                    row_payload[bucket_key] = dict(period_rows[period_key][bucket_key])
                series_rows.append(row_payload)
            size_series_by_period[period_name] = series_rows

        size_bins = [
            {
                "bucket": label,
                "key": key,
                "sast": size_buckets["sast"][key],
                "sca": size_buckets["sca"][key],
            }
            for key, label, _, _ in size_bucket_specs
        ]

        size_profile_top10 = sorted(
            [
                {
                    **item,
                    "dominant_size_mb": max(float(item.get("sast_size_mb", 0.0) or 0.0), float(item.get("sca_size_mb", 0.0) or 0.0)),
                }
                for item in size_profile_map.values()
            ],
            key=lambda item: float(item.get("dominant_size_mb", 0.0) or 0.0),
            reverse=True,
        )[:25]

        size_profile = {
            "bins": size_bins,
            "top10": size_profile_top10,
            "default_period": "month",
            "default_bucket": "lt1",
            "period_options": ["week", "month", "year"],
            "bucket_options": size_bucket_options,
            "by_period": size_series_by_period,
        }

        # Top applications by DAST page coverage with page-size buckets + period trend.
        page_bucket_specs = [
            ("lt10", "<10", "#b91c1c", 10.0),
            ("m10_50", "10-50", "#dc2626", 50.0),
            ("m50_100", "50-100", "#ea580c", 100.0),
            ("m100_500", "100-500", "#d97706", 500.0),
            ("m500_1000", "500-1000", "#65a30d", 1000.0),
            ("gte1000", ">=1000", "#0f766e", float("inf")),
        ]
        page_edges = [(key, upper) for key, _, _, upper in page_bucket_specs]
        page_bucket_keys = [key for key, _, _, _ in page_bucket_specs]
        page_bucket_options = [
            {"key": key, "label": label, "color": color}
            for key, label, color, _ in page_bucket_specs
        ]

        def _page_bucket_key(pages: float) -> str:
            for key, upper in page_edges:
                if pages < upper:
                    return key
            return "gte1000"

        def _empty_page_row() -> dict[str, dict[str, int]]:
            return {
                key: {"scan_count": 0, "page_count": 0}
                for key in page_bucket_keys
            }

        page_bucket_counts: dict[str, dict[str, int]] = {
            key: {"scan_count": 0, "page_count": 0}
            for key in page_bucket_keys
        }
        page_bucket_counts["total"] = {"scan_count": 0, "page_count": 0}
        page_by_period_key: dict[str, dict[str, dict[str, dict[str, int]]]] = {
            "week": {},
            "month": {},
            "year": {},
        }

        dast_coverage_map: dict[str, dict[str, Any]] = {}
        for scan in scans:
            if str(scan.get("scan_type", "")).upper() != "DAST":
                continue

            created_at = str(scan.get("created_at", ""))
            coverage = float(_safe_int(scan.get("page_coverage"), 0))
            bucket_key = _page_bucket_key(coverage)
            page_bucket_counts[bucket_key]["scan_count"] = _safe_int(page_bucket_counts[bucket_key].get("scan_count"), 0) + 1
            page_bucket_counts[bucket_key]["page_count"] = _safe_int(page_bucket_counts[bucket_key].get("page_count"), 0) + _safe_int(coverage, 0)
            page_bucket_counts["total"]["scan_count"] = _safe_int(page_bucket_counts["total"].get("scan_count"), 0) + 1
            page_bucket_counts["total"]["page_count"] = _safe_int(page_bucket_counts["total"].get("page_count"), 0) + _safe_int(coverage, 0)

            for period_name in ("week", "month", "year"):
                period_value = _period_bucket(created_at, period_name)
                if not period_value:
                    continue
                period_rows = page_by_period_key[period_name]
                row = period_rows.setdefault(period_value, _empty_page_row())
                row[bucket_key]["scan_count"] += 1
                row[bucket_key]["page_count"] += _safe_int(coverage, 0)

            app_id = str(scan.get("application_id", "") or "")
            if not app_id:
                continue
            app_name = str(scan.get("application_name", "") or app_id)
            bucket = dast_coverage_map.setdefault(
                app_id,
                {
                    "application_id": app_id,
                    "application_name": app_name,
                    "pages": 0,
                },
            )
            bucket["pages"] = max(_safe_int(bucket.get("pages"), 0), _safe_int(coverage, 0))

        page_series_by_period: dict[str, list[dict[str, Any]]] = {}
        for period_name in ("week", "month", "year"):
            period_rows = page_by_period_key[period_name]
            if not period_rows:
                period_rows[period_fallback[period_name]] = _empty_page_row()

            series_rows: list[dict[str, Any]] = []
            for period_key in sorted(period_rows.keys()):
                row_payload: dict[str, Any] = {"period": period_key}
                for bucket_key in page_bucket_keys:
                    row_payload[bucket_key] = dict(period_rows[period_key][bucket_key])
                series_rows.append(row_payload)
            page_series_by_period[period_name] = series_rows

        top_dast_page_coverage = {
            "bins": [
                {
                    "bucket": label,
                    "key": key,
                    "count": page_bucket_counts[key]["scan_count"],
                    "scan_count": page_bucket_counts[key]["scan_count"],
                    "page_count": page_bucket_counts[key]["page_count"],
                }
                for key, label, _, _ in page_bucket_specs
            ],
            "top10": sorted(
                dast_coverage_map.values(),
                key=lambda item: _safe_int(item.get("pages"), 0),
                reverse=True,
            )[:25],
            "default_period": "month",
            "default_bucket": "lt10",
            "period_options": ["week", "month", "year"],
            "bucket_options": page_bucket_options,
            "by_period": page_series_by_period,
        }

        # Most frequently rescanned applications/files.
        rescan_map: dict[str, dict[str, Any]] = {}
        for scan in scans:
            app_id = str(scan.get("application_id", "") or "unknown")
            app_name = str(scan.get("application_name", "") or app_id)
            target_name = str(scan.get("target_name", "") or "")
            bucket = rescan_map.setdefault(
                app_id,
                {
                    "application_id": app_id,
                    "application_name": app_name,
                    "target_name": target_name,
                    "scan_count": 0,
                },
            )
            bucket["scan_count"] = _safe_int(bucket.get("scan_count"), 0) + 1
            if not bucket.get("target_name") and target_name:
                bucket["target_name"] = target_name

        most_rescanned = sorted(
            rescan_map.values(),
            key=lambda item: _safe_int(item.get("scan_count"), 0),
            reverse=True,
        )[:25]

        return {
            "cumulative_vulnerabilities": cumulative_series,
            "application_compliance": compliance_series,
            "vulnerabilities_criticality": criticality_series,
            "application_onboarded": onboarded_series,
            "average_days_to_resolve": avg_resolve_series,
            "license_consumption": license_consumption,
            "scan_time_trend": scan_time_series,
            "application_file_size_profile": size_profile,
            "top_dast_page_coverage": top_dast_page_coverage,
            "most_frequently_rescanned": most_rescanned,
            "compliance_meta": {
                "rule": normalized_rule,
                "threshold": normalized_threshold,
            },
        }
