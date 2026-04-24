"""Phase 3: Real BV-BRC workspace integration tests.

Tests workspace file download/upload via the service script. Requires
a valid .patric_token for real workspace access.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.phase3, pytest.mark.workspace, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"


def _parse_ws_user(token_text: str) -> str:
    """Extract the workspace user (e.g. 'awilke@bvbrc') from a .patric_token.

    Token format: 'un=<user>@<domain>|tokenid=...'
    Returns: '<user>@<domain>' (e.g. 'awilke@bvbrc').
    """
    for part in token_text.split("|"):
        if part.startswith("un="):
            return part[3:]
    raise ValueError("Could not find 'un=' field in token")


def _ws_home(token_text: str) -> str:
    """Return the workspace home path for the token's user."""
    return f"/{_parse_ws_user(token_text)}/home"


class TestWorkspaceConnectivity:
    """Verify workspace access is available."""

    def test_p3_whoami(self, container, workspace_token):
        """p3-whoami should return a valid user with the workspace token."""
        result = container.exec(
            ["p3-whoami"],
            gpu=False,
            env={"KB_AUTH_TOKEN": workspace_token.read_text().strip()},
            timeout=30,
        )
        assert result.returncode == 0, (
            f"p3-whoami failed: {result.stderr}"
        )
        assert result.stdout.strip(), "p3-whoami returned empty output"

    def test_p3_ls_home(self, container, workspace_token):
        """p3-ls should be able to list the user's workspace home directory."""
        token = workspace_token.read_text().strip()
        home = _ws_home(token)
        result = container.exec(
            ["p3-ls", home],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            timeout=30,
        )
        assert result.returncode == 0, (
            f"p3-ls {home} failed: {result.stderr}"
        )


class TestWorkspaceUpload:
    """Upload test results to workspace and verify."""

    def test_upload_and_verify(self, container, workspace_token, tmp_path):
        """Upload a test file to workspace, verify it exists, then clean up."""
        token = workspace_token.read_text().strip()

        # Create a small test file
        test_file = tmp_path / "test_upload.txt"
        test_file.write_text("acceptance test upload")

        # Derive workspace path from the token itself (p3-whoami returns a
        # human-readable string, not a workspace path).
        ws_path = f"{_ws_home(token)}/acceptance_test"

        binds = {str(tmp_path): "/upload"}

        # Create test folder
        container.exec(
            ["p3-mkdir", ws_path],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            binds=binds,
            timeout=30,
        )

        try:
            # Upload
            result = container.exec(
                ["p3-cp", "/upload/test_upload.txt", f"ws:{ws_path}/test_upload.txt"],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                binds=binds,
                timeout=30,
            )
            assert result.returncode == 0, f"Upload failed: {result.stderr}"

            # Verify
            ls_result = container.exec(
                ["p3-ls", ws_path],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            assert "test_upload" in ls_result.stdout, (
                f"Uploaded file not found in workspace:\n{ls_result.stdout}"
            )
        finally:
            # Clean up
            container.exec(
                ["p3-rm", "-r", ws_path],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )


class TestServiceScriptWithWorkspace:
    """Full service script execution with workspace integration."""

    def test_service_esmfold_workspace_roundtrip(
        self, container, workspace_token, tmp_path
    ):
        """Run ESMFold via service script and verify workspace upload."""
        token = workspace_token.read_text().strip()
        ws_output = f"{_ws_home(token)}/acceptance_test_output"

        params = {
            "tool": "esmfold",
            "input_file": "/data/simple_protein.fasta",
            "output_path": ws_output,
            "output_file": "esmfold_acceptance",
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

            # Verify files exist in workspace
            ls_result = container.exec(
                ["p3-ls", "-l", ws_output],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            # Should have uploaded prediction results
            assert ls_result.returncode == 0, f"Cannot list ws output: {ls_result.stderr}"

        finally:
            # Clean up workspace
            container.exec(
                ["p3-rm", "-r", ws_output],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )

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
        ws_base = f"{_ws_home(token)}/acceptance_test_chai_report"
        ws_input = f"{ws_base}/simple_protein.fasta"
        ws_output = ws_base

        # Step 1: Upload input FASTA to workspace so the service script can
        # download it (production path). Use p3-cp, which the service script
        # also uses for upload.
        container.exec(
            ["p3-mkdir", ws_base],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            timeout=30,
        )
        upload_input = container.exec(
            ["p3-cp",
             "/data/simple_protein.fasta",
             f"ws:{ws_input}"],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            binds={str(TEST_DATA_HOST): "/data"},
            timeout=60,
        )
        assert upload_input.returncode == 0, (
            f"Input upload failed: {upload_input.stderr}"
        )

        params = {
            "tool": "chai",
            "input_file": ws_input,
            "output_path": ws_output,
            "output_file": "chai_report_test",
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

            # The BV-BRC AppScript framework uploads results into the hidden
            # progress folder: <output_path>/.<output_file>/<run_folder>/
            # where run_folder = <output_file>_<timestamp>_<task_id>.
            result_parent = f"{ws_output}/.{params['output_file']}"
            ls_parent = container.exec(
                ["p3-ls", result_parent],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            assert ls_parent.returncode == 0, (
                f"Cannot list result folder {result_parent}: {ls_parent.stderr}"
            )
            run_dirs = [
                s for s in ls_parent.stdout.strip().split("\n") if s
            ]
            assert run_dirs, (
                f"No run subdirectory created under {result_parent}:\n"
                f"{ls_parent.stdout}"
            )
            run_dir = f"{result_parent}/{run_dirs[0]}"

            # List the run directory contents
            ls_run = container.exec(
                ["p3-ls", run_dir],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
            assert ls_run.returncode == 0, (
                f"Cannot list run dir: {ls_run.stderr}"
            )
            files = ls_run.stdout.strip().split("\n")

            assert any("model_1" in f for f in files), (
                f"model_1.pdb not uploaded under {run_dir}:\n{ls_run.stdout}"
            )
            assert "confidence.json" in files, (
                f"confidence.json not uploaded under {run_dir}:\n{ls_run.stdout}"
            )
            assert "metadata.json" in files, (
                f"metadata.json not uploaded under {run_dir}:\n{ls_run.stdout}"
            )

            # Characterization report from `protein_compare characterize`.
            # `-o <prefix>` writes <prefix>.html/.json/.pdf (not a directory),
            # so these land at the top level of the run dir.
            assert "report.html" in files, (
                f"report.html not uploaded under {run_dir}. Files: {files}\n"
                "protein_compare characterize may have failed -- check logs."
            )
            assert "report.json" in files, (
                f"report.json not uploaded under {run_dir}. Files: {files}"
            )

        finally:
            container.exec(
                ["p3-rm", "-r", ws_output],
                gpu=False,
                env={"KB_AUTH_TOKEN": token},
                timeout=30,
            )
