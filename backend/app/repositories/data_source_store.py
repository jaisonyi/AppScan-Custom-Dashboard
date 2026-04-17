"""Repository for the ``data_sources`` table.

All functions follow the same raw-SQL + psycopg pattern used in
``postgres_store.py``.  Credentials are stored as-is in the database;
encryption-at-rest should be handled at the PostgreSQL / volume level.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from app.repositories.postgres_store import _connect

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema bootstrap (called from init_db)
# ---------------------------------------------------------------------------

def ensure_table() -> None:
    """Create the ``data_sources`` table if it does not already exist."""
    with closing(_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS data_sources (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                api_secret TEXT NOT NULL,
                verify_ssl BOOLEAN NOT NULL DEFAULT TRUE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                tenant_name TEXT NOT NULL DEFAULT '',
                api_user_name TEXT NOT NULL DEFAULT '',
                api_user_role TEXT NOT NULL DEFAULT '',
                api_user_email TEXT NOT NULL DEFAULT '',
                last_probed_at TEXT,
                last_probe_ok BOOLEAN,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # -- tenant_name column migration (added v0.1.6) --
        conn.execute(
            """
            ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS tenant_name TEXT NOT NULL DEFAULT ''
            """
        )
        conn.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_data_sources(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    """Return all data sources, ordered by label.

    By default only enabled sources are returned.  Pass
    ``include_disabled=True`` to include disabled ones (admin view).
    """
    with closing(_connect()) as conn:
        if include_disabled:
            rows = conn.execute(
                "SELECT * FROM data_sources ORDER BY label"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM data_sources WHERE enabled = TRUE ORDER BY label"
            ).fetchall()
    return [dict(r) for r in rows]


def get_data_source(ds_id: str) -> dict[str, Any] | None:
    """Return a single data source by ID, or ``None``."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM data_sources WHERE id = ?", (ds_id,)
        ).fetchone()
    return dict(row) if row else None


def get_data_source_by_url_and_key(url: str, api_key: str) -> dict[str, Any] | None:
    """Find a data source matching the given URL and API key (for dedup)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM data_sources WHERE url = ? AND api_key = ?",
            (url, api_key),
        ).fetchone()
    return dict(row) if row else None


def create_data_source(
    *,
    label: str,
    url: str,
    api_key: str,
    api_secret: str,
    verify_ssl: bool = True,
    enabled: bool = True,
) -> dict[str, Any]:
    """Insert a new data source row and return it."""
    ds_id = _new_id()
    now = _utc_now()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO data_sources
                (id, label, url, api_key, api_secret, verify_ssl, enabled,
                 tenant_name, api_user_name, api_user_role, api_user_email,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '', '', '', '', ?, ?)
            """,
            (ds_id, label, url, api_key, api_secret, verify_ssl, enabled, now, now),
        )
        conn.commit()
    return {
        "id": ds_id,
        "label": label,
        "url": url,
        "api_key": api_key,
        "api_secret": api_secret,
        "verify_ssl": verify_ssl,
        "enabled": enabled,
        "tenant_name": "",
        "api_user_name": "",
        "api_user_role": "",
        "api_user_email": "",
        "last_probed_at": None,
        "last_probe_ok": None,
        "created_at": now,
        "updated_at": now,
    }


def update_data_source(ds_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update one or more fields on an existing data source.

    Accepts keyword arguments matching column names.  Only provided fields
    are updated; absent fields are left unchanged.

    Returns the updated row or ``None`` if the ID was not found.
    """
    allowed = {
        "label", "url", "api_key", "api_secret", "verify_ssl", "enabled",
        "tenant_name", "api_user_name", "api_user_role", "api_user_email",
        "last_probed_at", "last_probe_ok",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_data_source(ds_id)

    updates["updated_at"] = _utc_now()
    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [ds_id]

    with closing(_connect()) as conn:
        conn.execute(
            f"UPDATE data_sources SET {set_clause} WHERE id = ?",  # noqa: S608
            tuple(values),
        )
        conn.commit()
    return get_data_source(ds_id)


def delete_data_source(ds_id: str) -> bool:
    """Delete a data source by ID. Returns True if a row was removed."""
    with closing(_connect()) as conn:
        cur = conn.execute("DELETE FROM data_sources WHERE id = ?", (ds_id,))
        conn.commit()
        return cur.rowcount > 0


def count_data_sources() -> int:
    """Return the total number of data sources (including disabled)."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM data_sources").fetchone()
    return int(row["cnt"]) if row else 0
