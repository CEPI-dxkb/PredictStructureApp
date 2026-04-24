"""Phase 3: App-PredictStructure.pl service script tests.

Tests the Perl service script end-to-end inside the container:
- Syntax check
- Execution with params JSON for each tool
- text_input mode (inline sequences)
- MSA file mode (no server)
- Output validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.phase3, pytest.mark.gpu, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"


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


SERVICE_PARAMS_DIR = TEST_DATA_HOST / "service_params"


def _load_service_params(filename: str, tmp_path: Path) -> Path:
    """Copy a canonical service-params file into tmp_path for binding."""
    src = SERVICE_PARAMS_DIR / filename
    dst = tmp_path / "params.json"
    dst.write_text(src.read_text())
    return dst


class TestServiceScriptExecution:
    """Execute App-PredictStructure.pl with canonical params JSON files.

    Param files live in test_data/service_params/ and are also used by
    the BV-BRC test harness, so changes here track production usage.
    """

    def _run(self, container, tmp_path, params_filename, timeout):
        params_file = _load_service_params(params_filename, tmp_path)
        binds, output_dir = _make_binds(tmp_path)
        result = container.service(
            params_json=Path(f"/params/{params_file.name}"),
            binds=binds,
            timeout=timeout,
        )
        assert result.returncode == 0, (
            f"Service script {params_filename} failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_esmfold_input_file(self, container, tmp_path):
        """ESMFold with input_file mode (fastest tool)."""
        self._run(container, tmp_path, "esmfold_input_file.json", 300)

    def test_esmfold_text_input(self, container, tmp_path):
        """ESMFold with text_input mode (inline sequences)."""
        self._run(container, tmp_path, "esmfold_text_input.json", 300)

    @pytest.mark.slow
    @pytest.mark.parametrize("params_file", [
        "boltz_input_file.json",
        "openfold_input_file.json",
        "chai_input_file.json",
    ])
    def test_gpu_tools(self, container, params_file, tmp_path):
        """GPU tools via service script with input_file mode."""
        self._run(container, tmp_path, params_file, 3600)


class TestServiceScriptMSAMode:
    """MSA modes: none and file upload (no server)."""

    @pytest.mark.slow
    def test_msa_upload_mode(self, container, tmp_path):
        """Boltz with msa_mode=upload and local MSA file."""
        params_file = _load_service_params("boltz_msa_upload.json", tmp_path)
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
