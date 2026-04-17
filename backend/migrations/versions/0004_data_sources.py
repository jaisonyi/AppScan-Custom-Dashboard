"""Add data_sources table for multi-data-source support.

Revision ID: 0004_data_sources
Revises: 0003_analytics_snapshots_cache
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op


revision = "0004_data_sources"
down_revision = "0003_analytics_snapshots_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_sources (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            api_secret TEXT NOT NULL,
            verify_ssl BOOLEAN NOT NULL DEFAULT TRUE,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_sources")
