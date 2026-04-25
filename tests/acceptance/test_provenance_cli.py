"""Phase 2: standalone exercising of the provenance CLI subcommands.

Closes gap #6 from docs/TEST_COVERAGE.md:
  predict-structure finalize-results <dir>
  predict-structure aggregate-results --in a.json b.json -o out.json

These commands are exercised indirectly today (the Perl service script
calls finalize-results post-report; the multi-tool CWL workflow calls
aggregate-results). This test file calls them directly to catch
contract drift cheaply.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance.matrix import CRAMBIN_RESIDUES, PROTEIN_FASTA
from tests.acceptance.validators import assert_valid_results_json

pytestmark = [
    pytest.mark.phase2,
    pytest.mark.gpu,
    pytest.mark.container,
    pytest.mark.tier1,
]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"


def _make_canonical_output(container, tmp_path: Path, label: str) -> Path:
    """Run a real prediction so we have a normalized output dir to operate on."""
    out = tmp_path / label
    out.mkdir()
    result = container.predict(
        tool="esmfold",
        entity_args=["--protein", PROTEIN_FASTA],
        output_dir=Path("/output"),
        extra_args=["--fp16"],
        binds={
            str(TEST_DATA_HOST): "/data",
            str(out): "/output",
        },
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Setup prediction failed:\n{result.stderr[-1500:]}"
    )
    return out


class TestFinalizeResults:
    """`predict-structure finalize-results` regenerates results.json + RO-Crate."""

    def test_regenerates_results_json(self, container, tmp_path):
        out = _make_canonical_output(container, tmp_path, "out")
        # Sabotage results.json so we can detect the regen
        original = (out / "results.json").read_text()
        (out / "results.json").write_text(json.dumps({"stale": True}))

        result = container.exec(
            ["predict-structure", "finalize-results", "/output"],
            gpu=False,
            binds={str(out): "/output"},
            timeout=60,
        )
        assert result.returncode == 0, (
            f"finalize-results failed:\n{result.stderr[-1000:]}"
        )
        regenerated = json.loads((out / "results.json").read_text())
        assert regenerated.get("schema_version"), (
            f"finalize-results did not produce a valid manifest:\n{regenerated}"
        )
        # And it should still validate
        assert_valid_results_json(out)

    def test_no_emit_rocrate_flag(self, container, tmp_path):
        """--no-emit-rocrate skips ro-crate-metadata.json."""
        out = _make_canonical_output(container, tmp_path, "out")
        # Pre-clean any existing crate from the prediction step
        crate = out / "ro-crate-metadata.json"
        if crate.exists():
            crate.unlink()
        result = container.exec(
            ["predict-structure", "finalize-results", "/output", "--no-emit-rocrate"],
            gpu=False,
            binds={str(out): "/output"},
            timeout=60,
        )
        assert result.returncode == 0
        assert not crate.exists(), (
            "--no-emit-rocrate should skip ro-crate-metadata.json"
        )


class TestAggregateResults:
    """`predict-structure aggregate-results` combines per-tool manifests."""

    def test_aggregates_two_runs(self, container, tmp_path):
        out_a = _make_canonical_output(container, tmp_path, "a")
        out_b = _make_canonical_output(container, tmp_path, "b")

        # Run aggregate-results inside the container, binding both result dirs
        # plus a writable target dir.
        agg_dir = tmp_path / "agg"
        agg_dir.mkdir()
        result = container.exec(
            ["predict-structure", "aggregate-results",
             "--in", "/run_a/results.json",
             "--in", "/run_b/results.json",
             "-o", "/agg/results.json"],
            gpu=False,
            binds={
                str(out_a): "/run_a",
                str(out_b): "/run_b",
                str(agg_dir): "/agg",
            },
            timeout=30,
        )
        assert result.returncode == 0, (
            f"aggregate-results failed:\n{result.stderr[-1000:]}"
        )

        agg = json.loads((agg_dir / "results.json").read_text())
        assert agg["kind"] == "multi-tool"
        assert agg["schema_version"]
        assert "timestamp" in agg
        assert len(agg["runs"]) == 2
        for run in agg["runs"]:
            assert run["tool"] == "esmfold"
            assert run["metrics"]["num_residues"] == CRAMBIN_RESIDUES
