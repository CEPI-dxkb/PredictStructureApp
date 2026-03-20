"""Subprocess execution backend for local tool invocation."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class SubprocessBackend:
    """Run prediction commands as local subprocesses.

    Use when the prediction tool is installed locally (inside a container,
    conda env, or system-wide). Streams stdout/stderr to the terminal.
    """

    def format_command(
        self,
        command: list[str],
        **kwargs,
    ) -> list[str]:
        """Return the command as a single shell-ready string."""
        return [" ".join(str(c) for c in command)]

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs,
    ) -> int:
        """Execute a command as a local subprocess.

        Args:
            command: CLI command as list of strings.
            cwd: Working directory for the subprocess.
            env: Environment variables (merged with os.environ).
            timeout: Max seconds before killing the process.

        Returns:
            Exit code (0 = success).
        """
        # Start from a clean copy of the environment.  Remove PYTHONPATH
        # so that per-tool conda envs (e.g. /opt/conda-boltz) are not
        # polluted by the predict-structure deps overlay.
        run_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

        # Inject tool-specific data directory env vars from config,
        # unless already set by the caller or host environment.
        tool_name = kwargs.get("tool_name")
        if tool_name:
            from predict_structure.config import get_data_dir

            data_dir = str(get_data_dir(tool_name))
            _DATA_ENV_VARS = {
                "boltz": "BOLTZ_CACHE",
                "chai": "CHAI_DOWNLOADS_DIR",
            }
            var = _DATA_ENV_VARS.get(tool_name)
            if var and var not in run_env:
                run_env[var] = data_dir
                logger.info("Set %s=%s", var, data_dir)

        if env:
            run_env.update(env)

        logger.info("Running: %s", " ".join(command))
        result = subprocess.run(
            command,
            cwd=cwd,
            env=run_env,
            timeout=timeout,
        )
        return result.returncode
