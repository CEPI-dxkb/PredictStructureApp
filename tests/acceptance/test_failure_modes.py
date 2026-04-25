"""Phase 2: failure-mode coverage.

Closes gap #8 from docs/TEST_COVERAGE.md. The existing tests are mostly
positive paths. This module fault-injects to exercise:

- `_finalize_output` raises (not silently swallows) on missing
  metadata.json / confidence.json after normalization.
- `predict-structure finalize-results <empty-dir>` exits non-zero with
  a clear error message.
- `aggregate-results --in <bogus.json>` rejects malformed input.

These tests don't require GPU; they manipulate a fixture directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.phase2,
    pytest.mark.container,
    pytest.mark.tier1,
]


class TestFinalizeFailureModes:
    """`predict-structure finalize-results` propagates errors loudly."""

    def test_empty_dir_rejected(self, container, tmp_path):
        """Missing metadata.json + confidence.json -> non-zero exit."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = container.exec(
            ["predict-structure", "finalize-results", "/empty"],
            gpu=False,
            binds={str(empty): "/empty"},
            timeout=30,
        )
        assert result.returncode != 0, (
            "finalize-results should fail on an empty directory"
        )
        # User-friendly error mentioning the missing file
        msg = (result.stdout + result.stderr).lower()
        assert "metadata.json" in msg or "confidence.json" in msg, (
            f"Error message should mention the missing file:\n{msg[:1500]}"
        )

    def test_corrupt_metadata_rejected(self, container, tmp_path):
        """Invalid JSON in metadata.json -> non-zero exit, clear error."""
        d = tmp_path / "corrupt"
        d.mkdir()
        (d / "metadata.json").write_text("{not json")
        (d / "confidence.json").write_text(json.dumps({
            "plddt_mean": 50.0, "ptm": None, "per_residue_plddt": [50.0],
        }))
        result = container.exec(
            ["predict-structure", "finalize-results", "/d"],
            gpu=False,
            binds={str(d): "/d"},
            timeout=30,
        )
        assert result.returncode != 0


class TestAggregateFailureModes:
    """`predict-structure aggregate-results` rejects bad input cleanly."""

    def test_missing_input_file(self, container, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        result = container.exec(
            ["predict-structure", "aggregate-results",
             "--in", "/nonexistent.json",
             "-o", "/out/agg.json"],
            gpu=False,
            binds={str(out_dir): "/out"},
            timeout=15,
        )
        assert result.returncode != 0

    def test_invalid_json_input(self, container, tmp_path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        (in_dir / "bad.json").write_text("not-valid-json")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        result = container.exec(
            ["predict-structure", "aggregate-results",
             "--in", "/in/bad.json",
             "-o", "/out/agg.json"],
            gpu=False,
            binds={str(in_dir): "/in", str(out_dir): "/out"},
            timeout=15,
        )
        assert result.returncode != 0
