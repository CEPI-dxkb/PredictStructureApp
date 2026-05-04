"""Tests for the Apptainer execution backend.

All tests mock subprocess.run to avoid requiring apptainer at runtime.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestApptainerBackendRegistry:
    """Verify Apptainer backend is properly registered."""

    def test_backend_registered(self):
        from predict_structure.backends import BACKENDS
        assert "apptainer" in BACKENDS

    def test_get_backend_apptainer(self):
        from predict_structure.backends import get_backend
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = get_backend("apptainer")
        assert isinstance(backend, ApptainerBackend)

    def test_get_backend_with_sif(self):
        from predict_structure.backends import get_backend

        backend = get_backend("apptainer", sif_path="/path/to/image.sif")
        assert backend._sif_path == "/path/to/image.sif"


class TestSIFResolution:
    """Test SIF image resolution order."""

    def test_explicit_sif_path(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/explicit/image.sif")
        assert backend._resolve_sif() == "/explicit/image.sif"

    def test_explicit_overrides_shared(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/explicit/image.sif")
        # Even with a tool_name, explicit path wins
        assert backend._resolve_sif("boltz") == "/explicit/image.sif"

    @patch("predict_structure.backends.apptainer.get_shared_sif")
    def test_shared_sif_from_config(self, mock_shared):
        from predict_structure.backends.apptainer import ApptainerBackend

        mock_shared.return_value = Path("/shared/all.sif")
        with patch.object(Path, "exists", return_value=True):
            backend = ApptainerBackend()
            assert backend._resolve_sif() == "/shared/all.sif"

    def test_no_sif_raises(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        with patch("predict_structure.backends.apptainer.get_shared_sif", return_value=None):
            backend = ApptainerBackend()
            with pytest.raises(ValueError, match="No SIF image"):
                backend._resolve_sif()


class TestCommandConstruction:
    """Test apptainer exec command building."""

    def test_basic_command(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/images/all.sif")
        cmd = backend._build_apptainer_cmd(
            ["predict-structure", "boltz", "--protein", "input.fasta"],
            gpu=True,
        )

        assert cmd[0] == "apptainer"
        assert cmd[1] == "exec"
        assert "--nv" in cmd
        assert "/images/all.sif" in cmd
        assert cmd[-4:] == ["predict-structure", "boltz", "--protein", "input.fasta"]

    def test_no_gpu(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/images/all.sif")
        cmd = backend._build_apptainer_cmd(
            ["predict-structure", "esmfold"],
            gpu=False,
        )

        assert "--nv" not in cmd

    def test_bind_mounts(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/images/all.sif")
        cmd = backend._build_apptainer_cmd(
            ["predict-structure", "boltz"],
            binds={"/local_databases": "/databases", "/tmp/cache": "/cache"},
        )

        assert "--bind" in cmd
        idx = cmd.index("--bind")
        # Two bind mounts → two --bind flags
        bind_count = cmd.count("--bind")
        assert bind_count == 2

    def test_format_command(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/images/all.sif")
        lines = backend.format_command(
            ["predict-structure", "boltz", "--protein", "input.fasta"],
            gpu=True,
        )

        assert len(lines) == 1
        assert "apptainer exec" in lines[0]
        assert "--nv" in lines[0]
        assert "/images/all.sif" in lines[0]


class TestEnvironment:
    """Test environment variable handling."""

    def test_strips_pythonpath(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/images/all.sif")

        with patch.dict("os.environ", {"PYTHONPATH": "/some/path", "HOME": "/home/user"}):
            env = backend._build_env()
            assert "PYTHONPATH" not in env
            assert "HOME" in env

    def test_extra_env_merged(self):
        from predict_structure.backends.apptainer import ApptainerBackend

        backend = ApptainerBackend(sif_path="/images/all.sif")
        env = backend._build_env(env={"MY_VAR": "value"})
        assert env["MY_VAR"] == "value"


class TestRun:
    """Test the run() method with mocked subprocess."""

    @patch("predict_structure.backends.apptainer.subprocess.run")
    def test_run_success(self, mock_run):
        from predict_structure.backends.apptainer import ApptainerBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = ApptainerBackend(sif_path="/images/all.sif")

        rc = backend.run(
            ["predict-structure", "boltz", "--protein", "input.fasta"],
            gpu=True,
        )

        assert rc == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "apptainer"
        assert "--nv" in call_args
        # Verify PYTHONPATH stripped
        call_env = mock_run.call_args[1]["env"]
        assert "PYTHONPATH" not in call_env

    @patch("predict_structure.backends.apptainer.subprocess.run")
    def test_run_failure(self, mock_run):
        from predict_structure.backends.apptainer import ApptainerBackend

        mock_run.return_value = MagicMock(returncode=1)
        backend = ApptainerBackend(sif_path="/images/all.sif")

        rc = backend.run(
            ["predict-structure", "boltz", "--protein", "input.fasta"],
        )
        assert rc == 1

    @patch("predict_structure.backends.apptainer.subprocess.run")
    def test_timeout_passed(self, mock_run):
        from predict_structure.backends.apptainer import ApptainerBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = ApptainerBackend(sif_path="/images/all.sif")

        backend.run(
            ["predict-structure", "boltz", "--protein", "input.fasta"],
            timeout=3600,
        )

        assert mock_run.call_args[1]["timeout"] == 3600
