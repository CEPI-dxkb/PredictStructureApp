"""Phase 2: end-to-end CWL workflow execution acceptance tests.

Closes gaps #2 and #5 from docs/TEST_COVERAGE.md. The existing
`tests/test_cwl_*.py` files validate CWL syntax + the `cwl` execution
backend on the host. This module runs `cwltool` end-to-end against
the SIF and asserts the produced output tree matches the unified
layout (model_1.*, confidence.json, metadata.json, results.json,
ro-crate-metadata.json, raw/).

Skipped if `cwltool` or the SIF is not available.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
TEST_DATA = REPO / "test_data"
CWL_DIR = REPO / "cwl"

pytestmark = [
    pytest.mark.phase2,
    pytest.mark.gpu,
    pytest.mark.container,
    pytest.mark.tier1,
    pytest.mark.slow,  # cwltool startup + ESMFold ≈ 1-3 min
]


def _have_cwltool() -> bool:
    return shutil.which("cwltool") is not None


def _have_sif() -> Path | None:
    sif = REPO / ".." / ".." / "scout" / "containers" / "folding_prod.sif"
    sif = Path("/scout/containers/folding_prod.sif")
    return sif if sif.is_file() else None


@pytest.fixture
def cwltool_env():
    if not _have_cwltool():
        pytest.skip("cwltool not on PATH")
    sif = _have_sif()
    if sif is None:
        pytest.skip("folding_prod.sif not found at /scout/containers/")
    return sif


def _write_job(tmp_path: Path, fasta: Path, output_dir_name: str) -> Path:
    """Write a minimal CWL job file for predict-structure.cwl."""
    job_path = tmp_path / "job.yml"
    job_path.write_text(textwrap.dedent(f"""\
        tool: esmfold
        protein:
          - class: File
            path: {fasta}
        output_dir: {output_dir_name}
        seed: 42
        device: gpu
        output_format: pdb
        fp16: true
    """))
    return job_path


class TestSingleToolWorkflow:
    """`cwltool predict-structure.cwl` produces the unified layout."""

    def test_esmfold_via_cwltool(self, cwltool_env, tmp_path):
        sif = cwltool_env
        cwl_tool = CWL_DIR / "tools" / "predict-structure.cwl"
        fasta = TEST_DATA / "simple_protein.fasta"
        out_dir = tmp_path / "cwl_out"
        out_dir.mkdir()

        job = _write_job(tmp_path, fasta, "predictions")

        # cwltool with --singularity uses the SIF declared in the CWL's
        # DockerRequirement.dockerImageId.
        result = subprocess.run(
            [
                "cwltool",
                "--singularity",
                "--outdir", str(out_dir),
                str(cwl_tool),
                str(job),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert result.returncode == 0, (
            f"cwltool execution failed (rc={result.returncode})\n"
            f"STDERR:\n{result.stderr[-2500:]}"
        )

        # The CWL `predictions` output is a Directory globbed from
        # $(inputs.output_dir) -- cwltool stages it into outdir.
        predictions = out_dir / "predictions"
        assert predictions.is_dir(), (
            f"predictions/ not produced; outdir contents: {list(out_dir.iterdir())}"
        )

        # The unified layout
        assert (predictions / "model_1.pdb").exists(), (
            f"model_1.pdb missing under {predictions}: {list(predictions.iterdir())}"
        )
        assert (predictions / "confidence.json").exists()
        assert (predictions / "metadata.json").exists()
        assert (predictions / "results.json").exists()
        assert (predictions / "raw").is_dir()

    def test_results_json_via_cwl_matches_schema(self, cwltool_env, tmp_path):
        """results.json from a CWL run validates against the schema."""
        from tests.acceptance.validators import assert_valid_results_json

        sif = cwltool_env
        cwl_tool = CWL_DIR / "tools" / "predict-structure.cwl"
        fasta = TEST_DATA / "simple_protein.fasta"
        out_dir = tmp_path / "cwl_out"
        out_dir.mkdir()
        job = _write_job(tmp_path, fasta, "predictions")

        result = subprocess.run(
            ["cwltool", "--singularity",
             "--outdir", str(out_dir),
             str(cwl_tool), str(job)],
            capture_output=True, text=True, timeout=600,
        )
        assert result.returncode == 0, result.stderr[-1500:]
        assert_valid_results_json(out_dir / "predictions")
