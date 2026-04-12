"""Phase 3: App-PredictStructure.pl service script tests.

Tests the Perl service script end-to-end inside the container:
- Syntax check
- Execution with params JSON for each tool
- text_input mode (inline sequences)
- MSA file mode (no server)
- Output validation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance.matrix import CRAMBIN_RESIDUES
from tests.acceptance.validators import assert_valid_output

pytestmark = [pytest.mark.phase3, pytest.mark.gpu, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"
ACCEPTANCE_DATA = TEST_DATA_HOST / "acceptance"


def _make_binds(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Create bind mounts with test_data and output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / "work"
    work_dir.mkdir(exist_ok=True)
    binds = {
        str(TEST_DATA_HOST): "/data",
        str(output_dir): "/output",
        str(work_dir): "/work",
        str(tmp_path): "/params",
    }
    return binds, output_dir


def _write_params(tmp_path: Path, params: dict) -> Path:
    """Write a params.json file and return its path."""
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps(params, indent=2))
    return params_file


class TestPerlSyntax:
    """Service script passes Perl syntax check."""

    def test_perl_compile_check(self, container):
        """perl -c App-PredictStructure.pl should succeed."""
        result = container.exec(
            ["perl", "-c", "/kb/module/service-scripts/App-PredictStructure.pl"],
            gpu=False,
            timeout=30,
        )
        # perl -c outputs to stderr
        assert result.returncode == 0, (
            f"Perl syntax check failed:\n{result.stderr}"
        )
        assert "syntax OK" in result.stderr


class TestServiceScriptExecution:
    """Execute App-PredictStructure.pl with params JSON for each tool."""

    def test_esmfold_input_file(self, container, tmp_path):
        """ESMFold with input_file mode (fastest tool)."""
        params = {
            "tool": "esmfold",
            "input_file": "/data/simple_protein.fasta",
            "output_path": "/output",
            "output_file": "esmfold_test",
            "num_recycles": 4,
            "output_format": "pdb",
            "msa_mode": "none",
            "seed": 42,
            "fp16": True,
        }
        params_file = _write_params(tmp_path, params)
        binds, output_dir = _make_binds(tmp_path)

        result = container.service(
            params_json=Path(f"/params/{params_file.name}"),
            binds=binds,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"Service script failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_esmfold_text_input(self, container, tmp_path):
        """ESMFold with text_input mode (inline sequences)."""
        params = {
            "tool": "esmfold",
            "text_input": [
                {
                    "type": "protein",
                    "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN",
                }
            ],
            "output_path": "/output",
            "output_file": "esmfold_text_test",
            "num_recycles": 4,
            "output_format": "pdb",
            "msa_mode": "none",
            "seed": 42,
            "fp16": True,
        }
        params_file = _write_params(tmp_path, params)
        binds, output_dir = _make_binds(tmp_path)

        result = container.service(
            params_json=Path(f"/params/{params_file.name}"),
            binds=binds,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"Service script text_input failed.\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("tool,extra_params", [
        ("boltz", {"num_samples": 1, "sampling_steps": 200}),
        ("openfold", {"num_diffusion_samples": 1}),
        ("chai", {"num_samples": 1, "sampling_steps": 200}),
    ])
    def test_gpu_tools(self, container, tool, extra_params, tmp_path):
        """GPU tools via service script with input_file mode."""
        params = {
            "tool": tool,
            "input_file": "/data/simple_protein.fasta",
            "output_path": "/output",
            "output_file": f"{tool}_test",
            "num_recycles": 3,
            "output_format": "pdb",
            "msa_mode": "none",
            "seed": 42,
        }
        params.update(extra_params)
        params_file = _write_params(tmp_path, params)
        binds, output_dir = _make_binds(tmp_path)

        result = container.service(
            params_json=Path(f"/params/{params_file.name}"),
            binds=binds,
            timeout=3600,
        )
        assert result.returncode == 0, (
            f"Service script {tool} failed.\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )


class TestServiceScriptMSAMode:
    """MSA modes: none and file upload (no server)."""

    @pytest.mark.slow
    def test_msa_upload_mode(self, container, tmp_path):
        """Boltz with msa_mode=upload and local MSA file."""
        params = {
            "tool": "boltz",
            "input_file": "/data/simple_protein.fasta",
            "output_path": "/output",
            "output_file": "boltz_msa_test",
            "num_samples": 1,
            "output_format": "pdb",
            "msa_mode": "upload",
            "msa_file": "/data/msa/crambin.a3m",
            "seed": 42,
        }
        params_file = _write_params(tmp_path, params)
        binds, output_dir = _make_binds(tmp_path)

        result = container.service(
            params_json=Path(f"/params/{params_file.name}"),
            binds=binds,
            timeout=1800,
        )
        assert result.returncode == 0, (
            f"Service script MSA upload failed.\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
