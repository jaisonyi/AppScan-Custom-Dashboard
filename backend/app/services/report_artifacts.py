from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.repositories.postgres_store import EXPORTS_DIR, upsert_report_artifact


def create_report_artifact(report_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    file_name = f"{report_id}.json"
    file_path = EXPORTS_DIR / file_name
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return upsert_report_artifact(
        report_id=report_id,
        file_name=file_name,
        file_path=str(file_path),
        mime_type="application/json",
        size_bytes=file_path.stat().st_size,
    )


def resolve_artifact_path(path_str: str) -> Path:
    path = Path(path_str).resolve()
    exports_root = EXPORTS_DIR.resolve()
    if exports_root not in path.parents and path != exports_root:
        raise ValueError("Artifact path is outside exports directory")
    return path
