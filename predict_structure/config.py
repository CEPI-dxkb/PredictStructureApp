"""Tool configuration loader.

Reads ``tools.yml`` from the package directory (or a path set via the
``PREDICT_STRUCTURE_CONFIG`` environment variable) and exposes helpers
for resolving container images, CWL tool definitions, and local
execution paths.

Image URIs use a scheme prefix:
    docker://dxkb/boltz-bvbrc:latest-gpu   → Docker image
    file:///path/to/image.sif              → Apptainer/Singularity image

Local execution fields:
    conda_env   — Conda environment name (subprocess wraps with conda run)
    executable  — Tool command name or path
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# Default config ships with the package.
_DEFAULT_CONFIG = Path(__file__).resolve().parent / "tools.yml"

# Project root: one level up from predict_structure/config.py
# (predict_structure/ → PredictStructureApp/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Workspace root: two levels up (PredictStructureApp/ → dxkb/)
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load and cache the tools configuration."""
    config_path = os.environ.get("PREDICT_STRUCTURE_CONFIG", str(_DEFAULT_CONFIG))
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return yaml.safe_load(path.read_text())


def get_tools() -> dict[str, dict]:
    """Return the full tools dict from config."""
    return _load_config().get("tools", {})


def get_tool_config(tool_name: str) -> dict:
    """Return config for a single tool. Raises KeyError if not found."""
    tools = get_tools()
    if tool_name not in tools:
        raise KeyError(
            f"Unknown tool '{tool_name}'. "
            f"Known tools: {', '.join(tools)}"
        )
    return tools[tool_name]


# -----------------------------------------------------------------
# Image helpers
# -----------------------------------------------------------------

def get_image_uri(tool_name: str) -> str:
    """Return the raw image URI (e.g. ``docker://dxkb/boltz:latest-gpu``)."""
    return get_tool_config(tool_name)["image"]


def get_image_scheme(tool_name: str) -> str:
    """Return the URI scheme: ``docker`` or ``file``."""
    uri = get_image_uri(tool_name)
    return uri.split("://", 1)[0]


def get_docker_image(tool_name: str) -> str:
    """Return the Docker image name (strip ``docker://`` prefix).

    Raises ValueError if the image is not a Docker image.
    """
    uri = get_image_uri(tool_name)
    if not uri.startswith("docker://"):
        raise ValueError(
            f"Tool '{tool_name}' image is not a Docker image: {uri}. "
            f"Use get_image_uri() for the raw URI."
        )
    return uri[len("docker://"):]


def get_sif_path(tool_name: str) -> Path:
    """Return the Apptainer .sif file path (strip ``file://`` prefix).

    Raises ValueError if the image is not a file URI.
    """
    uri = get_image_uri(tool_name)
    if not uri.startswith("file://"):
        raise ValueError(
            f"Tool '{tool_name}' image is not a file URI: {uri}. "
            f"Use get_image_uri() for the raw URI."
        )
    return Path(uri[len("file://"):])


# -----------------------------------------------------------------
# Data directory helpers
# -----------------------------------------------------------------

# Native env vars that tools use directly for their data/cache paths.
_NATIVE_ENV_VARS: dict[str, str] = {
    "boltz": "BOLTZ_CACHE",
    "chai": "CHAI_DOWNLOADS_DIR",
}


def get_data_root() -> Path:
    """Return the base data directory.

    Resolution order:
      1. ``PREDICT_STRUCTURE_DATA`` env var
      2. ``data_root`` in tools.yml
      3. ``/local_databases`` (fallback)
    """
    env = os.environ.get("PREDICT_STRUCTURE_DATA")
    if env:
        return Path(env)
    cfg_root = _load_config().get("data_root")
    if cfg_root:
        return Path(cfg_root)
    return Path("/local_databases")


def get_data_dir(tool_name: str) -> Path:
    """Return the data directory for a specific tool.

    Resolution order (highest wins):
      1. Native env var (``BOLTZ_CACHE``, ``CHAI_DOWNLOADS_DIR``, etc.)
      2. ``PREDICT_STRUCTURE_DATA`` / per-tool ``data_dir``
      3. ``data_root`` / per-tool ``data_dir`` from tools.yml
      4. ``data_root`` / ``tool_name``

    Returns:
        Absolute path to the tool's data directory.
    """
    # 1. Native env var override
    native_var = _NATIVE_ENV_VARS.get(tool_name)
    if native_var:
        native_val = os.environ.get(native_var)
        if native_val:
            return Path(native_val)

    # 2-3. data_root + per-tool data_dir
    root = get_data_root()
    tool_cfg = get_tools().get(tool_name, {})
    rel = tool_cfg.get("data_dir", tool_name)

    # Normalize to string (guards against null/non-string in YAML)
    if not isinstance(rel, str):
        rel = str(rel) if rel is not None else tool_name

    # Absolute data_dir → use as-is
    if rel.startswith("/"):
        return Path(rel)

    return root / rel


# -----------------------------------------------------------------
# Local execution helpers
# -----------------------------------------------------------------

def get_conda_env(tool_name: str) -> str | None:
    """Return the conda environment name, or None if not configured."""
    return get_tool_config(tool_name).get("conda_env")


def get_command(tool_name: str) -> list[str]:
    """Return the base command (executable + subcommand) as a list.

    Example: ``["boltz", "predict"]`` or
    ``["/opt/conda-alphafold/bin/python", "/app/alphafold/run_alphafold.py"]``
    """
    cmd = get_tool_config(tool_name).get("command", [])
    if isinstance(cmd, str):
        return cmd.split()
    return list(cmd)


def get_shared_sif() -> Path | None:
    """Return the shared Apptainer .sif path from ``container.sif``, or None.

    Used when all tools live in a single container with per-tool conda envs.
    """
    container = _load_config().get("container", {})
    sif = container.get("sif")
    if sif and sif.startswith("file://"):
        return Path(sif[len("file://"):])
    return None


# -----------------------------------------------------------------
# CWL helpers
# -----------------------------------------------------------------

def get_cwl_path(tool_name: str) -> Path:
    """Return the absolute path to the tool's CWL definition.

    Resolves relative to PROJECT_ROOT (PredictStructureApp/).
    """
    rel = get_tool_config(tool_name).get("cwl")
    if not rel:
        raise KeyError(f"No CWL path configured for tool '{tool_name}'")
    return PROJECT_ROOT / rel
