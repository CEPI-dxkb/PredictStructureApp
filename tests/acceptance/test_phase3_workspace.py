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

    def test_p3_ls_workspace(self, container, workspace_token):
        """p3-ls should be able to list the home workspace."""
        token = workspace_token.read_text().strip()
        result = container.exec(
            ["p3-ls", "/"],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            timeout=30,
        )
        assert result.returncode == 0, (
            f"p3-ls failed: {result.stderr}"
        )


class TestWorkspaceUpload:
    """Upload test results to workspace and verify."""

    def test_upload_and_verify(self, container, workspace_token, tmp_path):
        """Upload a test file to workspace, verify it exists, then clean up."""
        token = workspace_token.read_text().strip()

        # Create a small test file
        test_file = tmp_path / "test_upload.txt"
        test_file.write_text("acceptance test upload")

        # Get workspace home path
        whoami = container.exec(
            ["p3-whoami"],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            timeout=30,
        )
        user = whoami.stdout.strip()
        ws_path = f"/{user}@patricbrc.org/home/acceptance_test"

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

        # Get user for workspace path
        whoami = container.exec(
            ["p3-whoami"],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            timeout=30,
        )
        user = whoami.stdout.strip()
        ws_output = f"/{user}@patricbrc.org/home/acceptance_test_output"

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
