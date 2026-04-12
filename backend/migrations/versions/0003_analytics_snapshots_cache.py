"""Add analytics snapshots cache table.

Revision ID: 0003_analytics_snapshots_cache
Revises: 0002_schedule_retry_artifacts
Create Date: 2026-04-01
"""

from __future__ import annotations

from alembic import op


revision = "0003_analytics_snapshots_cache"
down_revision = "0002_schedule_retry_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_snapshots (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analytics_snapshots")
