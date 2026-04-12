"""Add schedule retry fields and report artifact table.

Revision ID: 0002_schedule_retry_artifacts
Revises: 0001_initial_sqlite_schema
Create Date: 2026-04-01
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "0002_schedule_retry_artifacts"
down_revision = "0001_initial_sqlite_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        existing_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(report_schedules)")).fetchall()
        }
    else:
        existing_columns = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'report_schedules'
                    """
                )
            ).fetchall()
        }
    if "retry_count" not in existing_columns:
        op.execute("ALTER TABLE report_schedules ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
    if "last_error" not in existing_columns:
        op.execute("ALTER TABLE report_schedules ADD COLUMN last_error TEXT")
    if "last_attempt_at" not in existing_columns:
        op.execute("ALTER TABLE report_schedules ADD COLUMN last_attempt_at TEXT")
    op.execute(
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_artifacts")
