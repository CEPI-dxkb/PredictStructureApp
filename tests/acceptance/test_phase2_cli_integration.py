"""Phase 2: predict-structure CLI integration tests inside the container.

Tests the unified CLI dispatching, --debug mode, entity flag combinations,
--job batch mode, and MSA file handling. All execution via
apptainer exec --nv <sif> predict-structure ... --backend subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance.matrix import (
    ALL_TIERS,
    CRAMBIN_RESIDUES,
    DNA_FASTA,
    MSA_FILE,
    PARAM_VARIATIONS,
    PROTEIN_FASTA,
    RNA_FASTA,
    TOOLS_WITH_TIERS,
    TOOL_INPUT_MATRIX,
    Tier,
    ToolTestCase,
    msa_args_for,
    parametrize_matrix,
    tier_entity_args,
    tier_supported_for_tool,
)
from tests.acceptance.timing import check_timing
from tests.acceptance.validators import assert_valid_output

pytestmark = [pytest.mark.phase2, pytest.mark.gpu, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"

TOOLS = ["boltz", "openfold", "chai", "alphafold", "esmfold"]


def _default_binds(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Create standard bind mounts and output dir."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    binds = {
        str(TEST_DATA_HOST): "/data",
        str(output_dir): "/output",
    }
    return binds, output_dir


class TestSubcommandExecution:
    """Each tool subcommand produces valid output inside the container."""

    @pytest.mark.parametrize("tool", ["esmfold"])
    def test_subcommand_quick(self, container, tool, tmp_path):
        """Quick: ESMFold only (fastest tool, ~30s)."""
        binds, output_dir = _default_binds(tmp_path)
        result = container.predict(
            tool=tool,
            entity_args=["--protein", PROTEIN_FASTA],
            output_dir=Path("/output"),
            extra_args=["--fp16"],
            binds=binds,
            timeout=120,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
        assert_valid_output(output_dir, tool=tool, expected_residues=CRAMBIN_RESIDUES)

    @pytest.mark.slow
    @pytest.mark.parametrize("tool,extra", [
        ("boltz", []),
        ("openfold", []),
        ("chai", []),
        ("alphafold", ["--af2-data-dir", "/local_databases/alphafold/databases"]),
    ])
    def test_subcommand_full(self, container, tool, extra, tmp_path):
        """Full: all GPU tools with protein input."""
        binds, output_dir = _default_binds(tmp_path)
        result = container.predict(
            tool=tool,
            entity_args=["--protein", PROTEIN_FASTA],
            output_dir=Path("/output"),
            extra_args=extra,
            binds=binds,
            timeout=3600,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
        assert_valid_output(output_dir, tool=tool, expected_residues=CRAMBIN_RESIDUES)


class TestDebugMode:
    """--debug prints the command without executing."""

    @pytest.mark.parametrize("tool", TOOLS)
    def test_debug_prints_command(self, container, tool, tmp_path):
        """--debug should print the native command and exit 0."""
        binds, output_dir = _default_binds(tmp_path)
        extra = []
        if tool == "alphafold":
            extra = ["--af2-data-dir", "/local_databases/alphafold/databases"]

        result = container.predict_debug(
            tool=tool,
            entity_args=["--protein", PROTEIN_FASTA],
            output_dir=Path("/output"),
            extra_args=extra,
            binds=binds,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        # Debug output should contain the tool's native CLI name
        assert result.stdout.strip(), "Debug mode produced no output"

    def test_debug_no_prediction_output(self, container, tmp_path):
        """--debug should not produce prediction output (PDB/CIF/confidence)."""
        binds, output_dir = _default_binds(tmp_path)
        container.predict_debug(
            tool="esmfold",
            entity_args=["--protein", PROTEIN_FASTA],
            output_dir=Path("/output"),
            binds=binds,
        )
        # Debug mode may create input.fasta and raw_output/ (from prepare_input),
        # but should NOT produce model_1.pdb or confidence.json
        pdbs = list(output_dir.glob("model_*.pdb"))
        cifs = list(output_dir.glob("model_*.cif"))
        assert len(pdbs) == 0, f"Debug mode produced PDB files: {pdbs}"
        assert len(cifs) == 0, f"Debug mode produced CIF files: {cifs}"


class TestEntityFlags:
    """Entity flag combinations are parsed and dispatched correctly."""

    def test_sequence_auto_detect(self, container, tmp_path):
        """--sequence flag with auto-detect should work like --protein for protein."""
        binds, output_dir = _default_binds(tmp_path)
        result = container.predict(
            tool="esmfold",
            entity_args=["--sequence", PROTEIN_FASTA],
            output_dir=Path("/output"),
            extra_args=["--fp16"],
            binds=binds,
            timeout=120,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
        assert_valid_output(output_dir, tool="esmfold")

    @pytest.mark.slow
    def test_multi_entity_boltz(self, container, tmp_path):
        """Boltz with protein + ligand entity combination."""
        binds, output_dir = _default_binds(tmp_path)
        result = container.predict(
            tool="boltz",
            entity_args=["--protein", PROTEIN_FASTA, "--ligand", "ATP"],
            output_dir=Path("/output"),
            binds=binds,
            timeout=1800,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
        assert_valid_output(output_dir, tool="boltz")

    @pytest.mark.slow
    def test_multi_entity_protein_dna(self, container, tmp_path):
        """Boltz with protein + DNA."""
        binds, output_dir = _default_binds(tmp_path)
        result = container.predict(
            tool="boltz",
            entity_args=["--protein", PROTEIN_FASTA, "--dna", DNA_FASTA],
            output_dir=Path("/output"),
            binds=binds,
            timeout=1800,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
        assert_valid_output(output_dir, tool="boltz")


class TestMSAFileMode:
    """MSA file (--msa) is handled correctly (no MSA server)."""

    @pytest.mark.slow
    @pytest.mark.parametrize("tool", ["boltz", "chai"])
    def test_msa_file_accepted(self, container, tool, tmp_path):
        """Tools that support MSA should accept --msa with a local .a3m file."""
        binds, output_dir = _default_binds(tmp_path)
        result = container.predict(
            tool=tool,
            entity_args=["--protein", PROTEIN_FASTA],
            output_dir=Path("/output"),
            extra_args=["--msa", MSA_FILE],
            binds=binds,
            timeout=1800,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
        assert_valid_output(output_dir, tool=tool, expected_residues=CRAMBIN_RESIDUES)


class TestJobBatchMode:
    """--job batch execution with YAML job spec."""

    @pytest.mark.tier1
    def test_job_full_run(self, container, tmp_path):
        """End-to-end --job batch run produces normalized output per job."""
        import yaml

        job_dir = tmp_path / "jobs"
        job_dir.mkdir()
        # One ESMFold job (fast, no GPU drama)
        jobs = [{
            "protein": [PROTEIN_FASTA],
            "tool": "esmfold",
            "options": {"backend": "subprocess", "fp16": True},
        }]
        job_file = job_dir / "batch.yaml"
        job_file.write_text(yaml.dump(jobs))

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        # /local_databases is rw because tools cache HF weights into it.
        # ApptainerRunner.predict() binds it automatically, but exec()
        # doesn't -- mirror that behavior here.
        binds = {
            str(TEST_DATA_HOST): "/data",
            str(job_dir): "/jobs",
            str(output_dir): "/output",
            "/local_databases": "/local_databases",
        }
        result = container.exec(
            ["predict-structure", "--job", "/jobs/batch.yaml",
             "-o", "/output"],
            gpu=True,
            binds=binds,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"--job batch run failed:\n{result.stderr[-1500:]}"
        )
        # cli.py:_run_job_file names each job dir job_<3-digit-idx>.
        # Discover them rather than hardcoding so this test still works
        # if the naming scheme is generalized later.
        job_dirs = sorted(p for p in output_dir.iterdir() if p.is_dir())
        assert len(job_dirs) == len(jobs), (
            f"Expected {len(jobs)} job dir(s), got {len(job_dirs)}: {job_dirs}"
        )
        for job_dir in job_dirs:
            assert (job_dir / "model_1.pdb").exists(), (
                f"{job_dir.name} produced no model_1.pdb: "
                f"{list(job_dir.iterdir())}"
            )
            assert (job_dir / "results.json").exists()

    def test_job_debug_mode(self, container, tmp_path):
        """Job file with debug mode should print commands for each job."""
        # Create a job YAML inside test_data for bind mounting
        import yaml

        job_dir = tmp_path / "jobs"
        job_dir.mkdir()
        jobs = [
            {
                "protein": [PROTEIN_FASTA],
                "options": {"debug": True},
            },
            {
                "protein": [PROTEIN_FASTA],
                "tool": "esmfold",
                "options": {"debug": True},
            },
        ]
        job_file = job_dir / "batch.yaml"
        job_file.write_text(yaml.dump(jobs))

        binds = {
            str(TEST_DATA_HOST): "/data",
            str(job_dir): "/jobs",
            str(tmp_path / "output"): "/output",
        }
        (tmp_path / "output").mkdir(exist_ok=True)

        result = container.exec(
            ["predict-structure", "--job", "/jobs/batch.yaml", "-o", "/output"],
            gpu=False,
            binds=binds,
            timeout=30,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        # Should mention both jobs
        assert "Job 000" in result.stdout
        assert "Job 001" in result.stdout


# =========================================================================
# Tool x Input Matrix -- predict-structure adapter layer
# =========================================================================

def _run_matrix_test(container, tc: ToolTestCase, tmp_path: Path):
    """Run a matrix test case through predict-structure."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)

    binds = {
        str(TEST_DATA_HOST): "/data",
        str(output_dir): "/output",
    }

    result = container.predict(
        tool=tc.tool,
        entity_args=tc.entity_args,
        output_dir=Path("/output"),
        extra_args=tc.extra_args,
        binds=binds,
        timeout=tc.timeout,
    )

    assert result.returncode == 0, (
        f"{tc.test_id} failed (rc={result.returncode}).\n"
        f"STDOUT:\n{result.stdout[-2000:]}\n"
        f"STDERR:\n{result.stderr[-2000:]}"
    )

    validation = assert_valid_output(
        output_dir,
        tool=tc.tool,
        expected_residues=tc.expected_residues,
    )

    device = "cpu" if "cpu" in tc.input_type else "gpu"
    timing_key = f"{tc.tool}_{tc.input_type}_{device}"
    check_timing(timing_key, result.elapsed)


class TestToolInputMatrix:
    """Test each tool x input type through predict-structure CLI."""

    @pytest.mark.parametrize("tc", parametrize_matrix(TOOL_INPUT_MATRIX))
    def test_tool_input(self, container, tc: ToolTestCase, tmp_path):
        _run_matrix_test(container, tc, tmp_path)


class TestParameterVariations:
    """Test parameter variations through predict-structure CLI."""

    @pytest.mark.parametrize("tc", parametrize_matrix(PARAM_VARIATIONS))
    def test_param_variation(self, container, tc: ToolTestCase, tmp_path):
        _run_matrix_test(container, tc, tmp_path)


# =========================================================================
# Tier coverage matrix -- T1-T5 across every applicable tool, --debug mode
#
# Fast cross-cutting check that the CLI builds a sensible command for
# every (tool, tier) combo respecting the per-tool MSA policy. Runs in
# --debug (no GPU work) so the full matrix completes in seconds. Full
# pipeline runs are covered in Phase 1 (native) and TestToolInputMatrix
# above for the "small" tier.
# =========================================================================


def _tier_marker(tier_name: str):
    """Return the pytest marker matching a tier name."""
    return getattr(pytest.mark, tier_name)


def _tier_param(tool: str, tier: Tier):
    """Build a pytest.param with the right tier marker (and `slow` for T5)."""
    marks = [_tier_marker(tier.name)]
    if tier.name == "tier5":
        marks.append(pytest.mark.slow)
    return pytest.param(tool, tier, id=f"{tool}-{tier.name}", marks=marks)


def _tier_param_grid():
    """Cartesian product of TOOLS_WITH_TIERS x ALL_TIERS, filtered by support."""
    out = []
    for tier in ALL_TIERS:
        for tool in TOOLS_WITH_TIERS:
            if not tier_supported_for_tool(tool, tier):
                continue
            out.append(_tier_param(tool, tier))
    return out


class TestTierCoverage:
    """Every (tool, tier) supported pair builds a sensible CLI command.

    Runs `predict-structure <tool> ... --debug` so we exercise:
      - Tier fixture path resolution
      - msa_args_for(tool, tier) policy is applied correctly
      - Adapter accepts the resulting argv
    Without spending GPU time. Full pipeline correctness lives in
    TestToolInputMatrix (T1) and Phase 1 native tool tests.
    """

    @pytest.mark.parametrize("tool,tier", _tier_param_grid())
    def test_debug_command_builds(
        self, container, tool: str, tier: Tier, tmp_path
    ):
        binds, output_dir = _default_binds(tmp_path)
        cmd = ["predict-structure", tool, "--protein", tier.fasta]
        cmd += tier_entity_args(tier)
        cmd += msa_args_for(tool, tier)
        cmd += ["-o", "/output", "--backend", "subprocess",
                "--seed", "42", "--debug"]
        if tool == "alphafold":
            cmd += ["--af2-data-dir", "/local_databases/alphafold/databases"]

        result = container.exec(cmd, gpu=False, binds=binds, timeout=60)
        assert result.returncode == 0, (
            f"{tool}/{tier.name} --debug failed (rc={result.returncode}).\n"
            f"CMD: {' '.join(cmd)}\n"
            f"STDERR:\n{result.stderr[-1500:]}"
        )
        # --debug should print the resolved command line
        assert tool in result.stdout or tier.fasta in result.stdout, (
            f"--debug output didn't echo the command for {tool}/{tier.name}:\n"
            f"{result.stdout[:1500]}"
        )
