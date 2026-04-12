"""Unit tests for backend/app/services/report_artifacts.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.report_artifacts import create_report_artifact, resolve_artifact_path


# ---------------------------------------------------------------------------
# create_report_artifact
# ---------------------------------------------------------------------------


class TestCreateReportArtifact:
    def test_writes_json_file(self, tmp_path):
        """file_path.write_text() is called with the serialized payload."""
        payload = {"key": "value", "count": 42}
        report_id = "r-test-001"
        expected_file = tmp_path / f"{report_id}.json"

        mock_artifact = {
            "report_id": report_id,
            "file_name": f"{report_id}.json",
            "file_path": str(expected_file),
            "mime_type": "application/json",
            "size_bytes": 100,
        }

        with patch("app.services.report_artifacts.EXPORTS_DIR", tmp_path), \
             patch("app.services.report_artifacts.upsert_report_artifact", return_value=mock_artifact):
            result = create_report_artifact(report_id, payload)

        # File should have been written
        assert expected_file.exists()
        written = json.loads(expected_file.read_text(encoding="utf-8"))
        assert written == payload

    def test_calls_upsert_with_correct_args(self, tmp_path):
        """upsert_report_artifact() is called with correct keyword arguments."""
        payload = {"data": [1, 2, 3]}
        report_id = "r-upsert-test"

        mock_upsert = MagicMock(return_value={
            "report_id": report_id,
            "file_name": f"{report_id}.json",
            "mime_type": "application/json",
        })

        with patch("app.services.report_artifacts.EXPORTS_DIR", tmp_path), \
             patch("app.services.report_artifacts.upsert_report_artifact", mock_upsert):
            create_report_artifact(report_id, payload)

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["report_id"] == report_id
        assert call_kwargs["file_name"] == f"{report_id}.json"
        assert call_kwargs["mime_type"] == "application/json"
        assert "file_path" in call_kwargs
        assert "size_bytes" in call_kwargs

    def test_returns_artifact_dict(self, tmp_path):
        """Return value has report_id, file_name, mime_type."""
        report_id = "r-return-test"
        payload = {"result": "ok"}
        expected = {
            "report_id": report_id,
            "file_name": f"{report_id}.json",
            "mime_type": "application/json",
            "size_bytes": 20,
        }

        with patch("app.services.report_artifacts.EXPORTS_DIR", tmp_path), \
             patch("app.services.report_artifacts.upsert_report_artifact", return_value=expected):
            result = create_report_artifact(report_id, payload)

        assert result["report_id"] == report_id
        assert result["file_name"] == f"{report_id}.json"
        assert result["mime_type"] == "application/json"

    def test_file_name_uses_report_id(self, tmp_path):
        """The file name is always <report_id>.json."""
        report_id = "r-custom-id-xyz"
        payload = {}

        with patch("app.services.report_artifacts.EXPORTS_DIR", tmp_path), \
             patch("app.services.report_artifacts.upsert_report_artifact", return_value={}):
            create_report_artifact(report_id, payload)

        assert (tmp_path / f"{report_id}.json").exists()


# ---------------------------------------------------------------------------
# resolve_artifact_path
# ---------------------------------------------------------------------------


class TestResolveArtifactPath:
    def test_returns_path_inside_exports_dir(self, tmp_path):
        """Valid path inside exports dir returns a Path object."""
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()
        target = exports_dir / "r-abc123.json"
        target.touch()

        with patch("app.services.report_artifacts.EXPORTS_DIR", exports_dir):
            result = resolve_artifact_path(str(target))

        assert isinstance(result, Path)
        assert result == target.resolve()

    def test_raises_for_path_traversal(self, tmp_path):
        """../../etc/passwd raises ValueError."""
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()

        traversal = str(exports_dir / "../../etc/passwd")

        with patch("app.services.report_artifacts.EXPORTS_DIR", exports_dir):
            with pytest.raises(ValueError, match="outside exports directory"):
                resolve_artifact_path(traversal)

    def test_raises_for_absolute_path_outside_dir(self, tmp_path):
        """Absolute path outside exports raises ValueError."""
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()

        outside_path = "/tmp/evil.json"

        with patch("app.services.report_artifacts.EXPORTS_DIR", exports_dir):
            with pytest.raises(ValueError, match="outside exports directory"):
                resolve_artifact_path(outside_path)

    def test_raises_for_sibling_directory_traversal(self, tmp_path):
        """Path that resolves to a sibling directory raises ValueError."""
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()
        sibling_dir = tmp_path / "other"
        sibling_dir.mkdir()

        sibling_path = str(sibling_dir / "secret.json")

        with patch("app.services.report_artifacts.EXPORTS_DIR", exports_dir):
            with pytest.raises(ValueError, match="outside exports directory"):
                resolve_artifact_path(sibling_path)

    def test_accepts_nested_path_inside_exports(self, tmp_path):
        """A path nested inside exports dir is accepted."""
        exports_dir = tmp_path / "exports"
        sub_dir = exports_dir / "subdir"
        sub_dir.mkdir(parents=True)
        target = sub_dir / "report.json"
        target.touch()

        with patch("app.services.report_artifacts.EXPORTS_DIR", exports_dir):
            result = resolve_artifact_path(str(target))

        assert result == target.resolve()
