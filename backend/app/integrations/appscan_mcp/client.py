from __future__ import annotations

from typing import Any


class AsocMcpClient:
    """Stub client for AppScan-MCP read workflows.

    Replace internals with your MCP transport implementation while preserving
    read-only behavior.
    """

    async def list_scans(self) -> list[dict[str, Any]]:
        return []

    async def list_applications(self) -> list[dict[str, Any]]:
        return []

    async def list_asset_groups(self) -> list[dict[str, Any]]:
        return []

    async def list_issues(self) -> list[dict[str, Any]]:
        return []
