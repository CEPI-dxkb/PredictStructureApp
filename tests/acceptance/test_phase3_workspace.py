"""Phase 3: BV-BRC workspace connectivity and raw upload/download tests.

Tests direct workspace operations (`p3-whoami`, `p3-ls`, `p3-cp`) without
any service-script involvement. Requires a valid `.patric_token` for real
workspace access.

For service-script-with-workspace tests (end-to-end App-PredictStructure.pl
roundtrips), see `test_phase3_appscript_workspace.py`.
"""

from __future__ import annotations

import pytest

from tests.acceptance.ws_utils import (
    cleanup_ws,
    make_output_path,
    ws_home,
)

pytestmark = [pytest.mark.phase3, pytest.mark.workspace, pytest.mark.container]


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
        home = ws_home(token)
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

        # Convention: AppTests/{tool}/{testname}-{ts}/
        ws_path = make_output_path(container, token, "misc", "upload_and_verify")

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
            cleanup_ws(container, token, ws_path)
