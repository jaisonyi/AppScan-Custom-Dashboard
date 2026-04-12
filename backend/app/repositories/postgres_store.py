from __future__ import annotations

import atexit
import json
import logging
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config.settings import REPO_ROOT, settings

logger = logging.getLogger(__name__)

DATA_DIR = REPO_ROOT / "data"
EXPORTS_DIR = DATA_DIR / "exports"


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.split("://", 1)[1]
    return url


DATABASE_URL = _normalize_database_url(settings.database_url)

# ---------------------------------------------------------------------------
# Module-level connection reuse
# ---------------------------------------------------------------------------
# A single reusable connection is kept alive across calls.  Before each use
# we verify the connection is still open; if not, a fresh one is created.
# This avoids the overhead of opening/closing a TCP connection on every DB
# operation while remaining simple and dependency-free.
# ---------------------------------------------------------------------------
_CONNECTION: psycopg.Connection[Any] | None = None
_CONNECTION_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_driver_sql(query: str) -> str:
    # psycopg uses %s placeholders; keep SQL text compatible with existing call sites.
    return query.replace("?", "%s")


class _CompatConnection:
    def __init__(self, conn: psycopg.Connection[Any]):
        self._conn = conn

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> Any:
        return self._conn.execute(_as_driver_sql(query), params or ())

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        # Do NOT close the underlying connection — it is reused.
        pass


def _get_connection() -> psycopg.Connection[Any]:
    """Return the module-level reusable connection, creating one if needed.

    Thread-safe: protected by ``_CONNECTION_LOCK``.
    """
    global _CONNECTION  # noqa: PLW0603
    with _CONNECTION_LOCK:
        if _CONNECTION is None or _CONNECTION.closed:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
                raise RuntimeError("DATABASE_URL must be a PostgreSQL URL.")
            logger.debug("Opening new PostgreSQL connection to %s", DATABASE_URL.split("@")[-1])
            _CONNECTION = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return _CONNECTION


def _connect() -> _CompatConnection:
    """Return a :class:`_CompatConnection` backed by the reusable connection."""
    return _CompatConnection(_get_connection())


def _close_connection() -> None:
    """Close the module-level connection on interpreter shutdown."""
    global _CONNECTION  # noqa: PLW0603
    with _CONNECTION_LOCK:
        if _CONNECTION is not None and not _CONNECTION.closed:
            try:
                _CONNECTION.close()
                logger.debug("PostgreSQL connection closed on module unload.")
            except Exception:  # noqa: BLE001
                pass
        _CONNECTION = None


atexit.register(_close_connection)


def _column_exists(conn: _CompatConnection, table_name: str, column_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (table_name, column_name),
    ).fetchone()
    return row is not None


def _ensure_column(conn: _CompatConnection, table_name: str, column_name: str, definition: str) -> None:
    if _column_exists(conn, table_name, column_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db() -> None:
    with closing(_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                widgets_json TEXT NOT NULL,
                owner TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "dashboards", "blueprint_json", "TEXT NOT NULL DEFAULT '{}' ")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                layout_json TEXT NOT NULL,
                widgets_json TEXT NOT NULL,
                visibility TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_history (
                id TEXT PRIMARY KEY,
                report_name TEXT NOT NULL,
                format TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_versions (
                id TEXT PRIMARY KEY,
                dashboard_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                name TEXT NOT NULL,
                widgets_json TEXT NOT NULL,
                owner TEXT NOT NULL,
                change_note TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_schedules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                template_id TEXT,
                cron TEXT NOT NULL,
                format TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                next_run_at TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                last_attempt_at TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "report_schedules", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "report_schedules", "last_error", "TEXT")
        _ensure_column(conn, "report_schedules", "last_attempt_at", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_artifacts (
                report_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_snapshots (
                cache_key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def list_dashboards() -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, name, widgets_json, blueprint_json, owner, created_at, updated_at FROM dashboards ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "widgets": json.loads(row["widgets_json"]),
            "blueprint": json.loads(row["blueprint_json"] or "{}"),
            "owner": row["owner"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_dashboard(dashboard_id: str) -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, name, widgets_json, blueprint_json, owner, created_at, updated_at FROM dashboards WHERE id = ?",
            (dashboard_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "widgets": json.loads(row["widgets_json"]),
        "blueprint": json.loads(row["blueprint_json"] or "{}"),
        "owner": row["owner"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_dashboard(
    dashboard_id: str,
    name: str,
    widgets: list[dict[str, Any]],
    owner: str,
    blueprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    resolved_blueprint = blueprint or {}
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO dashboards (id, name, widgets_json, blueprint_json, owner, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (dashboard_id, name, json.dumps(widgets), json.dumps(resolved_blueprint), owner, now, now),
        )
        conn.commit()
    return {
        "id": dashboard_id,
        "name": name,
        "widgets": widgets,
        "blueprint": resolved_blueprint,
        "owner": owner,
        "created_at": now,
        "updated_at": now,
    }


def _next_dashboard_version(conn: _CompatConnection, dashboard_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS max_version FROM dashboard_versions WHERE dashboard_id = ?",
        (dashboard_id,),
    ).fetchone()
    max_version = int(row["max_version"]) if row and row["max_version"] is not None else 0
    return max_version + 1


def append_dashboard_version(
    version_id: str,
    dashboard_id: str,
    name: str,
    widgets: list[dict[str, Any]],
    owner: str,
    change_note: str,
) -> dict[str, Any]:
    created_at = _utc_now()
    with closing(_connect()) as conn:
        version = _next_dashboard_version(conn, dashboard_id)
        conn.execute(
            """
            INSERT INTO dashboard_versions (id, dashboard_id, version, name, widgets_json, owner, change_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (version_id, dashboard_id, version, name, json.dumps(widgets), owner, change_note, created_at),
        )
        conn.commit()
    return {
        "id": version_id,
        "dashboard_id": dashboard_id,
        "version": version,
        "name": name,
        "widgets": widgets,
        "owner": owner,
        "change_note": change_note,
        "created_at": created_at,
    }


def list_dashboard_versions(dashboard_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, dashboard_id, version, name, widgets_json, owner, change_note, created_at
            FROM dashboard_versions
            WHERE dashboard_id = ?
            ORDER BY version DESC
            LIMIT ?
            """,
            (dashboard_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "dashboard_id": row["dashboard_id"],
            "version": row["version"],
            "name": row["name"],
            "widgets": json.loads(row["widgets_json"]),
            "owner": row["owner"],
            "change_note": row["change_note"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_dashboard_version(dashboard_id: str, version: int) -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT id, dashboard_id, version, name, widgets_json, owner, change_note, created_at
            FROM dashboard_versions
            WHERE dashboard_id = ? AND version = ?
            """,
            (dashboard_id, version),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "dashboard_id": row["dashboard_id"],
        "version": row["version"],
        "name": row["name"],
        "widgets": json.loads(row["widgets_json"]),
        "owner": row["owner"],
        "change_note": row["change_note"],
        "created_at": row["created_at"],
    }


def update_dashboard(
    dashboard_id: str,
    name: str | None = None,
    widgets: list[dict[str, Any]] | None = None,
    blueprint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    existing = get_dashboard(dashboard_id)
    if existing is None:
        return None
    updated_name = name if name is not None else existing["name"]
    updated_widgets = widgets if widgets is not None else existing["widgets"]
    updated_blueprint = blueprint if blueprint is not None else existing.get("blueprint", {})
    updated_at = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            UPDATE dashboards
            SET name = ?, widgets_json = ?, blueprint_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (updated_name, json.dumps(updated_widgets), json.dumps(updated_blueprint), updated_at, dashboard_id),
        )
        conn.commit()
    existing["name"] = updated_name
    existing["widgets"] = updated_widgets
    existing["blueprint"] = updated_blueprint
    existing["updated_at"] = updated_at
    return existing


def list_dashboard_templates() -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, name, description, scope_json, layout_json, widgets_json, visibility, created_by, created_at, updated_at
            FROM dashboard_templates
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "scope": json.loads(row["scope_json"]),
            "layout": json.loads(row["layout_json"]),
            "widgets": json.loads(row["widgets_json"]),
            "visibility": row["visibility"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_dashboard_template(template_id: str) -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT id, name, description, scope_json, layout_json, widgets_json, visibility, created_by, created_at, updated_at
            FROM dashboard_templates
            WHERE id = ?
            """,
            (template_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "scope": json.loads(row["scope_json"]),
        "layout": json.loads(row["layout_json"]),
        "widgets": json.loads(row["widgets_json"]),
        "visibility": row["visibility"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_dashboard_template(
    template_id: str,
    name: str,
    description: str,
    scope: dict[str, Any],
    layout: dict[str, Any],
    widgets: list[dict[str, Any]],
    visibility: str,
    created_by: str,
) -> dict[str, Any]:
    now = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO dashboard_templates
            (id, name, description, scope_json, layout_json, widgets_json, visibility, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                name,
                description,
                json.dumps(scope),
                json.dumps(layout),
                json.dumps(widgets),
                visibility,
                created_by,
                now,
                now,
            ),
        )
        conn.commit()
    return {
        "id": template_id,
        "name": name,
        "description": description,
        "scope": scope,
        "layout": layout,
        "widgets": widgets,
        "visibility": visibility,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def delete_dashboard(dashboard_id: str) -> bool:
    with closing(_connect()) as conn:
        cur = conn.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))
        conn.commit()
    return cur.rowcount > 0


def list_report_templates() -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, name, filters_json, created_by, created_at FROM report_templates ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "filters": json.loads(row["filters_json"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def create_report_template(
    template_id: str,
    name: str,
    filters: dict[str, Any],
    created_by: str,
) -> dict[str, Any]:
    now = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO report_templates (id, name, filters_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (template_id, name, json.dumps(filters), created_by, now),
        )
        conn.commit()
    return {
        "id": template_id,
        "name": name,
        "filters": filters,
        "created_by": created_by,
        "created_at": now,
    }


def delete_report_template(template_id: str) -> bool:
    with closing(_connect()) as conn:
        cur = conn.execute("DELETE FROM report_templates WHERE id = ?", (template_id,))
        conn.commit()
    return cur.rowcount > 0


def append_report_history(
    report_id: str,
    report_name: str,
    output_format: str,
    status: str,
    requested_by: str,
    filters: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    created_at = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO report_history (id, report_name, format, status, requested_by, filters_json, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                report_name,
                output_format,
                status,
                requested_by,
                json.dumps(filters),
                message,
                created_at,
            ),
        )
        conn.commit()
    return {
        "id": report_id,
        "report_name": report_name,
        "format": output_format,
        "status": status,
        "requested_by": requested_by,
        "filters": filters,
        "message": message,
        "created_at": created_at,
    }


def list_report_history(limit: int = 50) -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, report_name, format, status, requested_by, filters_json, message, created_at
            FROM report_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "report_name": row["report_name"],
            "format": row["format"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "filters": json.loads(row["filters_json"]),
            "message": row["message"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_report_schedules() -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, name, template_id, cron, format, enabled, next_run_at, retry_count, last_error, last_attempt_at,
                   created_by, created_at, updated_at
            FROM report_schedules
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "template_id": row["template_id"],
            "cron": row["cron"],
            "format": row["format"],
            "enabled": bool(row["enabled"]),
            "next_run_at": row["next_run_at"],
            "retry_count": int(row["retry_count"] or 0),
            "last_error": row["last_error"] or "",
            "last_attempt_at": row["last_attempt_at"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def create_report_schedule(
    schedule_id: str,
    name: str,
    template_id: str | None,
    cron: str,
    output_format: str,
    enabled: bool,
    next_run_at: str | None,
    created_by: str,
) -> dict[str, Any]:
    now = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO report_schedules (id, name, template_id, cron, format, enabled, next_run_at, retry_count, last_error, last_attempt_at, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                schedule_id,
                name,
                template_id,
                cron,
                output_format,
                1 if enabled else 0,
                next_run_at,
                0,
                "",
                None,
                created_by,
                now,
                now,
            ),
        )
        conn.commit()
    return {
        "id": schedule_id,
        "name": name,
        "template_id": template_id,
        "cron": cron,
        "format": output_format,
        "enabled": enabled,
        "next_run_at": next_run_at,
        "retry_count": 0,
        "last_error": "",
        "last_attempt_at": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def update_report_schedule(
    schedule_id: str,
    name: str | None = None,
    template_id: str | None = None,
    cron: str | None = None,
    output_format: str | None = None,
    enabled: bool | None = None,
    next_run_at: str | None = None,
    retry_count: int | None = None,
    last_error: str | None = None,
    last_attempt_at: str | None = None,
) -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        existing = conn.execute(
            """
                 SELECT id, name, template_id, cron, format, enabled, next_run_at, retry_count, last_error, last_attempt_at,
                     created_by, created_at, updated_at
            FROM report_schedules
            WHERE id = ?
            """,
            (schedule_id,),
        ).fetchone()
        if existing is None:
            return None

        updated_name = name if name is not None else existing["name"]
        updated_template_id = template_id if template_id is not None else existing["template_id"]
        updated_cron = cron if cron is not None else existing["cron"]
        updated_format = output_format if output_format is not None else existing["format"]
        updated_enabled = enabled if enabled is not None else bool(existing["enabled"])
        updated_next_run_at = next_run_at if next_run_at is not None else existing["next_run_at"]
        updated_retry_count = retry_count if retry_count is not None else int(existing["retry_count"] or 0)
        updated_last_error = last_error if last_error is not None else (existing["last_error"] or "")
        updated_last_attempt_at = last_attempt_at if last_attempt_at is not None else existing["last_attempt_at"]
        updated_at = _utc_now()

        conn.execute(
            """
            UPDATE report_schedules
            SET name = ?, template_id = ?, cron = ?, format = ?, enabled = ?, next_run_at = ?, retry_count = ?,
                last_error = ?, last_attempt_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated_name,
                updated_template_id,
                updated_cron,
                updated_format,
                1 if updated_enabled else 0,
                updated_next_run_at,
                updated_retry_count,
                updated_last_error,
                updated_last_attempt_at,
                updated_at,
                schedule_id,
            ),
        )
        conn.commit()
    return {
        "id": existing["id"],
        "name": updated_name,
        "template_id": updated_template_id,
        "cron": updated_cron,
        "format": updated_format,
        "enabled": updated_enabled,
        "next_run_at": updated_next_run_at,
        "retry_count": updated_retry_count,
        "last_error": updated_last_error,
        "last_attempt_at": updated_last_attempt_at,
        "created_by": existing["created_by"],
        "created_at": existing["created_at"],
        "updated_at": updated_at,
    }


def delete_report_schedule(schedule_id: str) -> bool:
    with closing(_connect()) as conn:
        cur = conn.execute("DELETE FROM report_schedules WHERE id = ?", (schedule_id,))
        conn.commit()
    return cur.rowcount > 0


def list_due_report_schedules(now_iso: str) -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
                 SELECT id, name, template_id, cron, format, enabled, next_run_at, retry_count, last_error, last_attempt_at,
                     created_by, created_at, updated_at
            FROM report_schedules
            WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (now_iso,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "template_id": row["template_id"],
            "cron": row["cron"],
            "format": row["format"],
            "enabled": bool(row["enabled"]),
            "next_run_at": row["next_run_at"],
            "retry_count": int(row["retry_count"] or 0),
            "last_error": row["last_error"] or "",
            "last_attempt_at": row["last_attempt_at"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def upsert_report_artifact(
    report_id: str,
    file_name: str,
    file_path: str,
    mime_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    created_at = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO report_artifacts (report_id, file_name, file_path, mime_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id)
            DO UPDATE SET file_name = excluded.file_name,
                          file_path = excluded.file_path,
                          mime_type = excluded.mime_type,
                          size_bytes = excluded.size_bytes,
                          created_at = excluded.created_at
            """,
            (report_id, file_name, file_path, mime_type, size_bytes, created_at),
        )
        conn.commit()
    return {
        "report_id": report_id,
        "file_name": file_name,
        "file_path": file_path,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "created_at": created_at,
    }


def get_report_artifact(report_id: str) -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT report_id, file_name, file_path, mime_type, size_bytes, created_at
            FROM report_artifacts
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "report_id": row["report_id"],
        "file_name": row["file_name"],
        "file_path": row["file_path"],
        "mime_type": row["mime_type"],
        "size_bytes": int(row["size_bytes"]),
        "created_at": row["created_at"],
    }


def get_analytics_snapshot(cache_key: str) -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT cache_key, payload_json, fetched_at, expires_at
            FROM analytics_snapshots
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()
    if row is None:
        return None
    return {
        "cache_key": row["cache_key"],
        "payload": json.loads(row["payload_json"]),
        "fetched_at": row["fetched_at"],
        "expires_at": row["expires_at"],
    }


def get_latest_analytics_snapshot() -> dict[str, Any] | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT cache_key, payload_json, fetched_at, expires_at
            FROM analytics_snapshots
            ORDER BY fetched_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return {
        "cache_key": row["cache_key"],
        "payload": json.loads(row["payload_json"]),
        "fetched_at": row["fetched_at"],
        "expires_at": row["expires_at"],
    }


def upsert_analytics_snapshot(
    cache_key: str,
    payload: dict[str, Any],
    fetched_at: str,
    expires_at: str,
) -> dict[str, Any]:
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO analytics_snapshots (cache_key, payload_json, fetched_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key)
            DO UPDATE SET payload_json = excluded.payload_json,
                          fetched_at = excluded.fetched_at,
                          expires_at = excluded.expires_at
            """,
            (cache_key, json.dumps(payload), fetched_at, expires_at),
        )
        conn.commit()
    return {
        "cache_key": cache_key,
        "payload": payload,
        "fetched_at": fetched_at,
        "expires_at": expires_at,
    }


def purge_expired_analytics_snapshots(now_iso: str) -> int:
    with closing(_connect()) as conn:
        cur = conn.execute(
            "DELETE FROM analytics_snapshots WHERE expires_at <= ?",
            (now_iso,),
        )
        conn.commit()
    return int(cur.rowcount or 0)


def report_artifact_map(report_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not report_ids:
        return {}
    placeholders = ",".join("?" for _ in report_ids)
    query = (
        "SELECT report_id, file_name, file_path, mime_type, size_bytes, created_at "
        f"FROM report_artifacts WHERE report_id IN ({placeholders})"
    )
    with closing(_connect()) as conn:
        rows = conn.execute(query, tuple(report_ids)).fetchall()
    return {
        str(row["report_id"]): {
            "report_id": row["report_id"],
            "file_name": row["file_name"],
            "file_path": row["file_path"],
            "mime_type": row["mime_type"],
            "size_bytes": int(row["size_bytes"]),
            "created_at": row["created_at"],
        }
        for row in rows
    }


def append_audit_event(
    event_id: str,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    created_at = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO audit_events (id, actor, action, resource_type, resource_id, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, actor, action, resource_type, resource_id, json.dumps(details), created_at),
        )
        conn.commit()
    return {
        "id": event_id,
        "actor": actor,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details,
        "created_at": created_at,
    }


def count_audit_events() -> int:
    """Return the total number of audit events (for pagination metadata)."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()
    return int(row["c"]) if row else 0


def list_audit_events(limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, actor, action, resource_type, resource_id, details_json, created_at
            FROM audit_events
            ORDER BY created_at DESC
            LIMIT ?
            OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "actor": row["actor"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "details": json.loads(row["details_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def latest_schedule_execution_map() -> dict[str, str]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT resource_id, MAX(created_at) AS last_executed_at
            FROM audit_events
            WHERE action = 'report_schedule.execute' AND resource_type = 'report_schedule'
            GROUP BY resource_id
            """
        ).fetchall()
    return {
        str(row["resource_id"]): str(row["last_executed_at"])
        for row in rows
        if row["resource_id"] and row["last_executed_at"]
    }


def ensure_seed_data() -> None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM dashboards").fetchone()
        dashboard_count = int(row["c"]) if row else 0
        if dashboard_count == 0:
            now = _utc_now()
            seed_dashboard_id = "d-1"
            conn.execute(
                """
                INSERT INTO dashboards (id, name, widgets_json, blueprint_json, owner, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed_dashboard_id,
                    "Executive ASPM",
                    json.dumps(
                        [
                            {"type": "kpi_card", "title": "Open Issues", "config": {"metric": "total_issues"}},
                            {"type": "issue_trend_line", "title": "Issue Trend", "config": {"time_range": "6m"}},
                            {"type": "mttr_bar", "title": "MTTR", "config": {"time_range": "6m"}},
                        ]
                    ),
                    json.dumps(
                        {
                            "status": "published",
                            "visibility": "team",
                            "asset_group_ids": ["ag-1"],
                            "layout": {"columns": 12, "items": []},
                            "version": 1,
                        }
                    ),
                    "system",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO dashboard_versions (id, dashboard_id, version, name, widgets_json, owner, change_note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "dv-1",
                    seed_dashboard_id,
                    1,
                    "Executive ASPM",
                    json.dumps(
                        [
                            {"type": "kpi_card", "title": "Open Issues", "config": {"metric": "total_issues"}},
                            {"type": "issue_trend_line", "title": "Issue Trend", "config": {"time_range": "6m"}},
                            {"type": "mttr_bar", "title": "MTTR", "config": {"time_range": "6m"}},
                        ]
                    ),
                    "system",
                    "seed",
                    now,
                ),
            )

        row = conn.execute("SELECT COUNT(*) AS c FROM dashboard_templates").fetchone()
        template_count = int(row["c"]) if row else 0
        if template_count == 0:
            now = _utc_now()
            conn.execute(
                """
                INSERT INTO dashboard_templates
                (id, name, description, scope_json, layout_json, widgets_json, visibility, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "dt-1",
                    "Security Manager Starter",
                    "Starter template focused on KPI, trend, and MTTR.",
                    json.dumps({"asset_group_ids": ["ag-1", "ag-2"]}),
                    json.dumps({"columns": 12, "items": []}),
                    json.dumps(
                        [
                            {"type": "kpi_card", "title": "Open Issues", "config": {"metric": "total_issues"}},
                            {"type": "severity_pie", "title": "Severity Mix", "config": {"time_range": "30d"}},
                            {"type": "mttr_bar", "title": "MTTR", "config": {"time_range": "6m"}},
                        ]
                    ),
                    "team",
                    "system",
                    now,
                    now,
                ),
            )

        row = conn.execute("SELECT COUNT(*) AS c FROM report_templates").fetchone()
        template_count = int(row["c"]) if row else 0
        if template_count == 0:
            conn.execute(
                """
                INSERT INTO report_templates (id, name, filters_json, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "rt-1",
                    "Monthly Risk Summary",
                    json.dumps({"severity": ["high", "critical"]}),
                    "system",
                    _utc_now(),
                ),
            )
        conn.commit()
