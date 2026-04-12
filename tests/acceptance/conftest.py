"""Acceptance test fixtures: container runner, GPU management, workspace token."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DATA = PROJECT_ROOT / "test_data"

# Default container paths
CONTAINERS = {
    "prod": "/scout/containers/folding_prod.sif",
    "all": "/scout/containers/all-2026-0410.01.sif",
}

# Host path for tool model weights / databases (read-only)
LOCAL_DATABASES = "/local_databases"


@dataclass
class ExecResult:
    """Result of a container execution."""

    returncode: int
    stdout: str
    stderr: str
    elapsed: float


class ApptainerRunner:
    """Execute commands inside an Apptainer/Singularity container."""

    def __init__(self, sif_path: str, gpu_id: str | None = None):
        self.sif = sif_path
        self.name = Path(sif_path).stem
        # Pin to a single GPU. Inherits CUDA_VISIBLE_DEVICES from env if set,
        # otherwise defaults to "0". This prevents tools like AlphaFold (JAX)
        # from grabbing all GPUs.
        # Accepts a single GPU ("0") or multiple ("1,2,3,4") for tools
        # that benefit from multi-GPU (e.g. AlphaFold/JAX).
        self.gpu_id = gpu_id or os.environ.get("CUDA_VISIBLE_DEVICES", "0")

    def exec(
        self,
        command: list[str],
        gpu: bool = True,
        binds: dict[str, str] | None = None,
        ro_binds: dict[str, str] | None = None,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run a command inside the container.

        Args:
            command: Command and arguments to execute.
            gpu: Enable GPU passthrough (--nv).
            binds: Host:container read-write bind mount pairs.
            ro_binds: Host:container read-only bind mount pairs.
            timeout: Timeout in seconds.
            env: Extra environment variables.

        Returns:
            ExecResult with returncode, stdout, stderr, and elapsed time.
        """
        # --pwd /tmp prevents CWD from leaking the dev repo into Python path.
        # Home dir remains accessible (required by numba/boltz to stat source
        # files inside the SIF for JIT cache keys). Cache env vars redirect
        # all writable caches to /local_databases/cache.
        cmd = ["apptainer", "exec", "--pwd", "/tmp"]
        # Point all HF / model caches to /local_databases/cache (bound via
        # the standard /local_databases ro-bind). Writable tmp caches go to
        # /local_databases/cache/tmp.
        cache_env = {
            "HF_HOME": "/local_databases/cache",
            "HF_DATASETS_CACHE": "/local_databases/cache",
            "TRANSFORMERS_CACHE": "/local_databases/cache",
            "TORCH_HOME": "/local_databases/cache",
            "XDG_CACHE_HOME": "/local_databases/cache/tmp",
            "TRITON_CACHE_DIR": "/local_databases/cache/tmp",
            "NUMBA_CACHE_DIR": "/local_databases/cache/tmp",
        }
        for key, val in cache_env.items():
            cmd.extend(["--env", f"{key}={val}"])
        # Mount dev code at /mnt and prepend to PYTHONPATH so it takes
        # precedence over the container's installed version. This avoids
        # binding over /opt/conda-predict/ which breaks JIT compilation
        # in other conda envs (numba in Boltz, triton/evoformer in OpenFold).
        dev_pkg = PROJECT_ROOT / "predict_structure"
        if dev_pkg.is_dir():
            cmd.extend(["--bind", f"{PROJECT_ROOT}:/mnt/predict-structure"])
            cmd.extend(["--env", "PYTHONPATH=/mnt/predict-structure"])
        if gpu:
            cmd.append("--nv")
            # Pin to a single GPU to prevent tools (JAX/AlphaFold) from
            # grabbing all visible devices
            cmd.extend(["--env", f"CUDA_VISIBLE_DEVICES={self.gpu_id}"])
        if binds:
            for host_path, container_path in binds.items():
                cmd.extend(["--bind", f"{host_path}:{container_path}"])
        if ro_binds:
            for host_path, container_path in ro_binds.items():
                cmd.extend(["--bind", f"{host_path}:{container_path}:ro"])
        if env:
            for key, val in env.items():
                cmd.extend(["--env", f"{key}={val}"])
        cmd.append(self.sif)
        cmd.extend(command)

        start = time.monotonic()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        return ExecResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed=elapsed,
        )

    def predict(
        self,
        tool: str,
        entity_args: list[str],
        output_dir: Path,
        extra_args: list[str] | None = None,
        binds: dict[str, str] | None = None,
        ro_binds: dict[str, str] | None = None,
        timeout: int = 600,
    ) -> ExecResult:
        """Run predict-structure <tool> inside the container.

        Automatically binds /local_databases read-only for model weights.

        Args:
            tool: Tool subcommand (boltz, chai, esmfold, etc.).
            entity_args: Entity flags (e.g. ["--protein", "/data/input.fasta"]).
            output_dir: Container-side output directory path.
            extra_args: Additional CLI flags.
            binds: Host:container read-write bind mount pairs.
            ro_binds: Host:container read-only bind mount pairs (merged with
                /local_databases default).
            timeout: Timeout in seconds.

        Returns:
            ExecResult from the prediction run.
        """
        # Bind /local_databases rw (cache/ subdir needs writes for HF model cache)
        default_binds = {}
        if Path(LOCAL_DATABASES).is_dir():
            default_binds[LOCAL_DATABASES] = LOCAL_DATABASES
        if binds:
            default_binds.update(binds)

        cmd = ["predict-structure", tool] + entity_args
        cmd.extend(["-o", str(output_dir), "--backend", "subprocess", "--seed", "42"])
        if extra_args:
            cmd.extend(extra_args)
        return self.exec(cmd, gpu=True, binds=default_binds, ro_binds=ro_binds, timeout=timeout)

    def predict_debug(
        self,
        tool: str,
        entity_args: list[str],
        output_dir: Path,
        extra_args: list[str] | None = None,
        binds: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run predict-structure <tool> --debug (print command, no execution)."""
        default_binds = {}
        if Path(LOCAL_DATABASES).is_dir():
            default_binds[LOCAL_DATABASES] = LOCAL_DATABASES
        if binds:
            default_binds.update(binds)

        cmd = ["predict-structure", tool] + entity_args
        cmd.extend(["-o", str(output_dir), "--backend", "subprocess", "--debug"])
        if extra_args:
            cmd.extend(extra_args)
        return self.exec(cmd, gpu=False, binds=default_binds, timeout=30)

    def service(
        self,
        params_json: Path,
        binds: dict[str, str] | None = None,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run App-PredictStructure.pl with a params.json file.

        The BV-BRC AppScript expects:
            perl App-PredictStructure.pl <app_service_url> <app_spec.json> <params.json>
        and P3_WORKDIR env var for the working directory.
        """
        default_binds = {}
        if Path(LOCAL_DATABASES).is_dir():
            default_binds[LOCAL_DATABASES] = LOCAL_DATABASES
        if binds:
            default_binds.update(binds)

        service_env = {"P3_WORKDIR": "/output"}
        if env:
            service_env.update(env)

        cmd = [
            "perl",
            "/kb/module/service-scripts/App-PredictStructure.pl",
            "http://localhost",                        # app_service_url (unused in local mode)
            "/kb/module/app_specs/PredictStructure.json",  # app_spec
            str(params_json),                          # params.json
        ]
        return self.exec(cmd, gpu=True, binds=default_binds,
                         timeout=timeout, env=service_env)

    def preflight(
        self,
        tool: str,
        entity_args: list[str] | None = None,
        timeout: int = 30,
    ) -> dict:
        """Run predict-structure preflight, return parsed JSON."""
        cmd = ["predict-structure", "preflight", "--tool", tool]
        if entity_args:
            cmd.extend(entity_args)
        result = self.exec(cmd, gpu=False, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(
                f"Preflight failed (rc={result.returncode}): {result.stderr}"
            )
        return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _resolve_sif(label: str) -> str:
    """Resolve a container label to a SIF path, respecting env override."""
    override = os.environ.get("PREDICT_STRUCTURE_SIF")
    if override:
        return override
    return CONTAINERS.get(label, label)


def pytest_addoption(parser):
    """Add acceptance-test CLI options."""
    parser.addoption(
        "--sif",
        action="store",
        default=None,
        help="Path to a single SIF to test (overrides dual-container parametrization)",
    )
    parser.addoption(
        "--container-label",
        action="store",
        default=None,
        choices=["prod", "all"],
        help="Test only one container label (prod or all)",
    )
    parser.addoption(
        "--gpu-id",
        action="store",
        default=None,
        help="CUDA device index to pin tests to (e.g. '0', '1'). "
             "Prevents tools like AlphaFold/JAX from grabbing all GPUs.",
    )


def _get_container_params(config):
    """Determine which containers to parametrize over."""
    sif_override = config.getoption("--sif") or os.environ.get("PREDICT_STRUCTURE_SIF")
    if sif_override:
        return [sif_override]

    label = config.getoption("--container-label")
    if label:
        return [CONTAINERS[label]]

    return list(CONTAINERS.values())


@pytest.fixture(params=None, scope="session")
def container(request):
    """Provide an ApptainerRunner for the production container under test.

    By default tests run on both prod and all containers. Override with:
      --sif /path/to/specific.sif
      --container-label prod
      PREDICT_STRUCTURE_SIF=/path/to.sif
    """
    sif_path = request.param
    if not Path(sif_path).exists():
        pytest.skip(f"SIF not found: {sif_path}")
    gpu_id = request.config.getoption("--gpu-id")
    return ApptainerRunner(sif_path, gpu_id=gpu_id)


def pytest_generate_tests(metafunc):
    """Dynamically parametrize the 'container' fixture over available SIFs."""
    if "container" in metafunc.fixturenames:
        sifs = _get_container_params(metafunc.config)
        metafunc.parametrize(
            "container",
            sifs,
            ids=[Path(s).stem for s in sifs],
            indirect=True,
            scope="session",
        )


@pytest.fixture(scope="session")
def gpu_available():
    """Check GPU availability; skip test if no GPU."""
    result = subprocess.run(["nvidia-smi"], capture_output=True)
    if result.returncode != 0:
        pytest.skip("No GPU available (nvidia-smi failed)")
    return True


@pytest.fixture(scope="session")
def workspace_token():
    """Require a valid BV-BRC workspace token for Phase 3 workspace tests."""
    token_path = os.environ.get(
        "PATRIC_TOKEN_PATH", os.path.expanduser("~/.patric_token")
    )
    if not Path(token_path).exists():
        pytest.skip(
            f"Workspace token not found: {token_path}. "
            "Set PATRIC_TOKEN_PATH or create ~/.patric_token"
        )
    return Path(token_path)


@pytest.fixture
def test_output(tmp_path):
    """Create a temporary output directory for a single test."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def bind_test_data(tmp_path):
    """Return bind-mount dict mapping test_data and tmp output into container."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    return {
        str(TEST_DATA): "/data",
        str(output_dir): "/output",
    }, output_dir
