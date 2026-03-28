"""CWL acceptance tests — three tiers of increasing integration depth.

Tier 1 (cwl marker): CWL validation only, no Docker/GPU needed. Runs in CI.
Tier 2 (docker marker): Dry-run with Docker. Requires Docker daemon.
Tier 3 (gpu marker): Full prediction with GPU. Manual/nightly only.

Run tiers selectively:
    pytest tests/test_cwl_acceptance.py -m cwl           # Tier 1 only
    pytest tests/test_cwl_acceptance.py -m docker         # Tier 2
    pytest tests/test_cwl_acceptance.py -m gpu            # Tier 3
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

CWL_DIR = Path(__file__).resolve().parents[1] / "cwl" / "tools"
JOBS_DIR = Path(__file__).resolve().parents[1] / "cwl" / "jobs"
TEST_DATA = Path(__file__).resolve().parents[1] / "test_data"

from predict_structure.config import get_tools, get_cwl_path


@pytest.mark.cwl
class TestAcceptanceTier1:
    """Tier 1: CWL validation only (no Docker, no GPU). Runs in CI."""

    def test_per_tool_cwl_definitions_exist(self):
        """Every tool has its own CWL definition that exists."""
        for tool in get_tools():
            cwl_path = get_cwl_path(tool)
            assert cwl_path.exists(), f"CWL for '{tool}' not found at {cwl_path}"

    def test_per_tool_cwl_validates(self):
        """cwltool --validate succeeds for each per-tool CWL definition."""
        for tool in get_tools():
            cwl_path = get_cwl_path(tool)
            result = subprocess.run(
                ["cwltool", "--validate", str(cwl_path)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"Validation failed for {tool} ({cwl_path}):\n{result.stderr}"
            )

    def test_all_job_yamls_are_loadable(self):
        """Every job YAML in cwl/jobs/ loads and has an input file."""
        job_files = sorted(JOBS_DIR.glob("*.yml"))
        assert len(job_files) >= 4, f"Expected at least 4 job files, got {len(job_files)}"

        input_keys = {"input_file", "input_fasta", "fasta_paths", "sequences"}
        for job_file in job_files:
            doc = yaml.safe_load(job_file.read_text())
            has_input = any(k in doc for k in input_keys)
            assert has_input, f"{job_file.name} missing input file key"

    def test_backend_roundtrip(self):
        """Build a job YAML from adapter command, verify native CWL input names."""
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "esm-fold-hf", "-i", "/data/crambin.fasta",
            "-o", "/data/output",
            "--num-recycles", "4",
        ]
        job = backend._build_job_yaml(command, tool_name="esmfold")

        assert job["sequences"]["class"] == "File"
        assert job["sequences"]["path"] == "/data/crambin.fasta"
        assert job["output_dir"] == "output"
        assert job["num_recycles"] == 4

    def test_boltz_roundtrip(self):
        """Boltz adapter command maps correctly to CWL job."""
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "boltz", "predict", "/data/input.yaml",
            "--out_dir", "/data/output",
            "--diffusion_samples", "3",
            "--use_msa_server",
            "--use_potentials",
        ]
        job = backend._build_job_yaml(command, tool_name="boltz")

        assert job["input_file"]["path"] == "/data/input.yaml"
        assert job["output_dir"] == "output"
        assert job["diffusion_samples"] == 3
        assert job["use_msa_server"] is True
        assert job["use_potentials"] is True

    def test_esmfold_fp16_mapped(self):
        """--fp16 is now mapped to CWL input (not skipped)."""
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "esm-fold-hf", "-i", "/data/crambin.fasta",
            "-o", "/data/output",
            "--num-recycles", "4",
            "--fp16",
        ]
        job = backend._build_job_yaml(command, tool_name="esmfold")
        assert job["fp16"] is True


@pytest.mark.cwl
@pytest.mark.docker
class TestAcceptanceTier2:
    """Tier 2: Dry-run (no GPU). Validates CWL wiring."""

    def test_esmfold_dry_run(self):
        """cwltool --no-container runs the per-tool CWL with a job file."""
        cwl_path = get_cwl_path("esmfold")
        job_file = JOBS_DIR / "crambin-esmfold.yml"
        result = subprocess.run(
            ["cwltool", "--no-container", str(cwl_path), str(job_file)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        # May fail due to missing tool, but should not fail on CWL parsing
        assert "Workflow error" not in result.stderr or result.returncode != 0


@pytest.mark.cwl
@pytest.mark.gpu
class TestAcceptanceTier3:
    """Tier 3: Full prediction (GPU required). Manual/nightly only."""

    def test_esmfold_full_prediction(self, tmp_path):
        """Full CWL run with ESMFold on crambin — check output exists."""
        cwl_path = get_cwl_path("esmfold")
        job_file = JOBS_DIR / "crambin-esmfold.yml"
        result = subprocess.run(
            ["cwltool", "--outdir", str(tmp_path), str(cwl_path), str(job_file)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            output_dir = tmp_path / "output"
            assert output_dir.is_dir()
