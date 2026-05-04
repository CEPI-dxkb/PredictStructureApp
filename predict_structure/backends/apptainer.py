"""Apptainer/Singularity execution backend for containerized tool invocation."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from predict_structure.config import get_shared_sif, get_sif_path, get_data_dir

logger = logging.getLogger(__name__)


class ApptainerBackend:
    """Run prediction commands inside an Apptainer/Singularity container.

    Unlike Docker, Apptainer exposes the host filesystem by default,
    so minimal bind-mounting and no path rewriting is needed.  GPU
    access uses ``--nv`` instead of ``--gpus all``.

    SIF resolution order:
      1. Explicit ``sif_path`` (constructor / ``--sif`` CLI flag)
      2. Shared SIF from ``container.sif`` in tools.yml
      3. Per-tool SIF from ``image: file://...`` in tools.yml
    """

    def __init__(self, sif_path: str | None = None):
        self._sif_path = sif_path

    def _resolve_sif(self, tool_name: str | None = None) -> str:
        """Resolve the SIF image path."""
        if self._sif_path:
            return self._sif_path
        shared = get_shared_sif()
        if shared and shared.exists():
            return str(shared)
        if tool_name:
            return str(get_sif_path(tool_name))
        raise ValueError(
            "No SIF image specified. Use --sif or configure "
            "container.sif in tools.yml."
        )

    def _build_apptainer_cmd(
        self,
        command: list[str],
        *,
        sif: str | None = None,
        tool_name: str | None = None,
        gpu: bool = True,
        binds: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
    ) -> list[str]:
        """Build the full ``apptainer exec`` command list."""
        resolved_sif = sif or self._resolve_sif(tool_name)

        cmd: list[str] = ["apptainer", "exec"]

        if gpu:
            cmd.append("--nv")

        for host_path, container_path in (binds or {}).items():
            cmd.extend(["--bind", f"{host_path}:{container_path}"])

        cmd.append(resolved_sif)
        cmd.extend(command)
        return cmd

    def _build_env(
        self,
        *,
        tool_name: str | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build environment for the subprocess.

        Strips PYTHONPATH so per-tool conda envs inside the container
        are not polluted by host packages.  Injects tool-specific data
        directory env vars.
        """
        run_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

        # Inject tool data env vars
        if tool_name:
            _DATA_ENV_VARS = {
                "boltz": "BOLTZ_CACHE",
                "chai": "CHAI_DOWNLOADS_DIR",
            }
            var = _DATA_ENV_VARS.get(tool_name)
            if var and var not in run_env:
                data_dir = str(get_data_dir(tool_name))
                run_env[var] = data_dir
                logger.info("Set %s=%s", var, data_dir)

        if env:
            run_env.update(env)

        return run_env

    def format_command(
        self,
        command: list[str],
        **kwargs,
    ) -> list[str]:
        """Return the full ``apptainer exec ...`` command as a shell-ready string."""
        apptainer_cmd = self._build_apptainer_cmd(command, **kwargs)
        return [" ".join(apptainer_cmd)]

    def run(
        self,
        command: list[str],
        *,
        sif: str | None = None,
        tool_name: str | None = None,
        gpu: bool = True,
        binds: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs,
    ) -> int:
        """Build and execute an apptainer exec command.

        Args:
            command: The tool command to run inside the container.
            sif: SIF image path override.
            tool_name: Tool name for resolving SIF/env from config.
            gpu: Whether to pass ``--nv`` for GPU access.
            binds: Host→container bind mounts ({host: container}).
            env: Extra environment variables.
            timeout: Max seconds for the container to run.

        Returns:
            Exit code from ``apptainer exec``.
        """
        apptainer_cmd = self._build_apptainer_cmd(
            command, sif=sif, tool_name=tool_name,
            gpu=gpu, binds=binds, env=env,
        )

        run_env = self._build_env(tool_name=tool_name, env=env)

        logger.info("Running: %s", " ".join(apptainer_cmd))
        result = subprocess.run(apptainer_cmd, env=run_env, timeout=timeout)
        return result.returncode
