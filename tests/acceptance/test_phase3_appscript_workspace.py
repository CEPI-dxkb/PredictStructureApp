"""Phase 3: App-PredictStructure.pl end-to-end roundtrips with workspace I/O.

Tests the BV-BRC service script in its production configuration: reading
inputs from / writing outputs to the BV-BRC workspace. Requires a valid
`.patric_token`.

For pure workspace ops (connectivity, raw p3-cp), see
`test_phase3_workspace.py`. For service-script tests that run offline
against local files, see `test_phase3_service_script.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance.ws_utils import (
    cleanup_ws,
    make_output_path,
    upload_test_input,
)

pytestmark = [pytest.mark.phase3, pytest.mark.workspace, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"


class TestServiceScriptWithWorkspace:
    """Full service script execution with workspace integration."""

    def test_service_esmfold_workspace_roundtrip(
        self, container, workspace_token, tmp_path
    ):
        """Run ESMFold via service script and verify workspace upload."""
        token = workspace_token.read_text().strip()
        # Upload input to a separate staging path so ws_output stays fresh
        # (pre-existing ws_output causes p3-cp -r to nest under output/).
        ws_input = upload_test_input(
            container, token, TEST_DATA_HOST, "simple_protein.fasta",
            "esmfold_roundtrip",
        )
        ws_output = make_output_path(container, token, "esmfold", "workspace_roundtrip")

        params = {
            "tool": "esmfold",
            "input_file": ws_input,
            "output_path": ws_output,
            "num_recycles": 4,
            "output_format": "pdb",
            "msa_mode": "none",
            "seed": 42,
            "fp16": True,
        }

        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps(params, indent=2))

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        binds = {
            str(TEST_DATA_HOST): "/data",
            str(output_dir): "/output",
            str(tmp_path): "/params",
        }

        try:
            result = container.service(
                params_json=Path(f"/params/{params_file.name}"),
                binds=binds,
                timeout=300,
                env={"KB_AUTH_TOKEN": token},
            )
            assert result.returncode == 0, (
                f"Service script with workspace failed.\n"
                f"STDERR:\n{result.stderr[-2000:]}"
            )

            # Without output_file, upload lands directly in <output_path>/
            ls_result = container.exec(
                ["p3-ls", ws_output],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            assert ls_result.returncode == 0, f"Cannot list ws output: {ls_result.stderr}"
            files = [s for s in ls_result.stdout.strip().split("\n") if s]
            assert any("model_1" in f for f in files), (
                f"model_1.pdb not uploaded under {ws_output}:\n{ls_result.stdout}"
            )
            assert "confidence.json" in files, (
                f"confidence.json not uploaded under {ws_output}:\n{ls_result.stdout}"
            )
            assert "results.json" in files, (
                f"results.json not uploaded under {ws_output}:\n{ls_result.stdout}"
            )

        finally:
            cleanup_ws(container, token, ws_output)
            cleanup_ws(container, token, ws_input)

    @pytest.mark.slow
    def test_service_chai_report_workspace_roundtrip(
        self, container, workspace_token, tmp_path
    ):
        """Full Chai + report + workspace upload roundtrip.

        Exercises the BV-BRC production flow end-to-end:
          1. Upload the input FASTA to the workspace (mimics user upload)
          2. Service script downloads input from workspace
          3. Runs Chai-1 prediction on GPU
          4. Runs protein_compare characterize to generate HTML/PDF/JSON report
          5. Uploads the full normalized output directory to the workspace via p3-cp

        Verifies the uploaded workspace contains both prediction artifacts
        (model_1.pdb, confidence.json, metadata.json) and the characterization
        report (report.html, report.json).
        """
        token = workspace_token.read_text().strip()
        # Upload input FASTA to a staging path (production path mimic). Keep
        # it OUT of ws_output so ws_output is still fresh when the service
        # script uploads into it -- otherwise p3-cp -r nests under output/.
        ws_input = upload_test_input(
            container, token, TEST_DATA_HOST, "simple_protein.fasta",
            "chai_report_roundtrip",
        )
        ws_output = make_output_path(container, token, "chai", "report_workspace_roundtrip")

        # Omit output_file -- the versioned output_path is the run container,
        # so the run folder lives directly under it.
        params = {
            "tool": "chai",
            "input_file": ws_input,
            "output_path": ws_output,
            "num_samples": 1,
            "num_recycles": 3,
            "sampling_steps": 200,
            "output_format": "pdb",
            "msa_mode": "none",
            "seed": 42,
        }

        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps(params, indent=2))

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        binds = {
            str(TEST_DATA_HOST): "/data",
            str(output_dir): "/output",
            str(tmp_path): "/params",
        }

        try:
            result = container.service(
                params_json=Path(f"/params/{params_file.name}"),
                binds=binds,
                timeout=1800,
                env={"KB_AUTH_TOKEN": token},
            )
            assert result.returncode == 0, (
                f"Service script chai+report failed.\n"
                f"STDERR:\n{result.stderr[-2000:]}"
            )

            # Without output_file, upload lands directly in <output_path>/
            # (the service script no longer nests under a per-run subfolder).
            ls_run = container.exec(
                ["p3-ls", ws_output],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            assert ls_run.returncode == 0, (
                f"Cannot list {ws_output}: {ls_run.stderr}"
            )
            files = ls_run.stdout.strip().split("\n")
            run_dir = ws_output  # for error messages below

            assert any("model_1" in f for f in files), (
                f"model_1.pdb not uploaded under {run_dir}:\n{ls_run.stdout}"
            )
            assert "confidence.json" in files, (
                f"confidence.json not uploaded under {run_dir}:\n{ls_run.stdout}"
            )
            assert "metadata.json" in files, (
                f"metadata.json not uploaded under {run_dir}:\n{ls_run.stdout}"
            )

            # Characterization reports from `protein_compare characterize`
            # live under the report/ subdir (unified layout; see
            # docs/OUTPUT_NORMALIZATION.md §7).
            assert "report" in files, (
                f"report/ subdir not uploaded under {run_dir}. Files: {files}\n"
                "protein_compare characterize may have failed -- check logs."
            )
            ls_report = container.exec(
                ["p3-ls", f"{run_dir}/report"],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            report_files = ls_report.stdout.strip().split("\n")
            assert "report.html" in report_files, (
                f"report.html missing in report/:\n{ls_report.stdout}"
            )
            assert "report.json" in report_files, (
                f"report.json missing in report/:\n{ls_report.stdout}"
            )

            # New provenance files
            assert "results.json" in files, (
                f"results.json not uploaded under {run_dir}. Files: {files}"
            )

        finally:
            cleanup_ws(container, token, ws_output)
            cleanup_ws(container, token, ws_input)
