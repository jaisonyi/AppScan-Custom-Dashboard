"""Initial SQLite schema for ASPM local persistence.

Revision ID: 0001_initial_sqlite_schema
Revises:
Create Date: 2026-04-01
"""

from __future__ import annotations

from alembic import op


revision = "0001_initial_sqlite_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
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
    op.execute(
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
    op.execute(
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
    op.execute(
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_schedules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            template_id TEXT,
            cron TEXT NOT NULL,
            format TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            next_run_at TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP TABLE IF EXISTS report_schedules")
    op.execute("DROP TABLE IF EXISTS dashboard_versions")
    op.execute("DROP TABLE IF EXISTS report_history")
    op.execute("DROP TABLE IF EXISTS report_templates")
    op.execute("DROP TABLE IF EXISTS dashboards")
