"""GPU VRAM precheck.

Slurm GRES allocates GPUs by count but does not track VRAM consumed by
processes outside slurm. When non-slurm processes (e.g. long-running
inference servers under interactive sessions) hold most of a GPU's
memory, slurm can still assign that GPU to a new job, which then OOMs
mid-run after model load — visible to the user as a silent exit 1 with
no output.

This module probes ``nvidia-smi`` from the GPU host *before* the tool
subprocess launches, so a doomed run can fail fast with an actionable
error pointing at the busy GPU and the processes holding it.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GpuStatus:
    index: int
    free_mb: int
    total_mb: int
    uuid: str = ""


@dataclass
class GpuCheckResult:
    ok: bool
    gpus: list[GpuStatus]
    message: str
    threshold_mb: int


def _visible_tokens() -> list[str] | None:
    """Parse CUDA_VISIBLE_DEVICES into a list of raw device tokens.

    Tokens are either integer indices ("0", "1") or GPU UUIDs
    ("GPU-8a75dad1-..."); Slurm GRES commonly sets the UUID form.
    Returns None if the env var is unset/empty (caller should fall back
    to a best-effort GPU-0 proxy).
    """
    raw = os.environ.get("CUDA_VISIBLE_DEVICES")
    if raw is None or raw == "":
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or None


def _match_visible(tokens: list[str], all_gpus: list[GpuStatus]) -> list[GpuStatus]:
    """Resolve CUDA_VISIBLE_DEVICES tokens to GpuStatus entries.

    Integer tokens match by nvidia-smi index; UUID tokens (and any
    non-integer token) match by GPU UUID. Unmatched tokens are silently
    dropped — the caller treats an empty result as "skip precheck."
    """
    by_index = {g.index: g for g in all_gpus}
    matched: list[GpuStatus] = []
    for tok in tokens:
        try:
            g = by_index.get(int(tok))
            if g is not None:
                matched.append(g)
            continue
        except ValueError:
            pass
        # UUID form: nvidia-smi reports the full "GPU-<uuid>" string.
        for g in all_gpus:
            if g.uuid and (g.uuid == tok or g.uuid.startswith(tok) or tok.startswith(g.uuid)):
                matched.append(g)
                break
    return matched


def _query_nvidia_smi() -> list[GpuStatus]:
    """Return per-GPU memory status from nvidia-smi.

    Empty list if nvidia-smi is unavailable or the query fails — callers
    should treat that as "unknown, proceed."
    """
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        proc = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,memory.free,memory.total,uuid",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("nvidia-smi query failed: %s", exc)
        return []
    if proc.returncode != 0:
        logger.warning("nvidia-smi exited %d: %s", proc.returncode, proc.stderr.strip())
        return []
    gpus: list[GpuStatus] = []
    for line in proc.stdout.splitlines():
        try:
            idx, free, total, uuid = (s.strip() for s in line.split(",", 3))
            gpus.append(GpuStatus(int(idx), int(free), int(total), uuid))
        except ValueError:
            continue
    return gpus


def _compute_processes(gpu_indices: list[int]) -> str:
    """Return a human-readable summary of processes on the given GPUs.

    Empty string if the query fails or finds nothing.
    """
    if not gpu_indices or shutil.which("nvidia-smi") is None:
        return ""
    try:
        proc = subprocess.run(
            ["nvidia-smi",
             f"--id={','.join(str(i) for i in gpu_indices)}",
             "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0 or not proc.stdout.strip():
        return ""
    return proc.stdout.strip()


def check_gpu_memory(min_free_mb: int) -> GpuCheckResult:
    """Verify the GPU(s) visible to this process have enough free VRAM.

    Args:
        min_free_mb: Minimum free VRAM (MiB) the tool needs.

    Returns:
        GpuCheckResult.ok is False only when nvidia-smi succeeded *and*
        at least one visible GPU is below threshold. If nvidia-smi is
        absent or fails, ok is True with an explanatory message — we
        never block on missing diagnostics.
    """
    all_gpus = _query_nvidia_smi()
    if not all_gpus:
        return GpuCheckResult(
            ok=True, gpus=[], threshold_mb=min_free_mb,
            message="nvidia-smi unavailable — skipping VRAM precheck",
        )

    visible = _visible_tokens()
    if visible is None:
        # CUDA_VISIBLE_DEVICES unset. Tool will pick the first CUDA
        # device — check GPU 0 as a best-effort proxy.
        target_gpus = [g for g in all_gpus if g.index == 0] or all_gpus[:1]
    else:
        # CUDA_VISIBLE_DEVICES holds either nvidia-smi indices or, as
        # Slurm GRES sets it, GPU UUIDs. Resolve both forms so we probe
        # the *assigned* GPU, not physical index 0.
        target_gpus = _match_visible(visible, all_gpus)
        if not target_gpus:
            return GpuCheckResult(
                ok=True, gpus=[], threshold_mb=min_free_mb,
                message=(
                    f"CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')} "
                    f"but no matching GPU in nvidia-smi output — skipping precheck"
                ),
            )

    insufficient = [g for g in target_gpus if g.free_mb < min_free_mb]
    if not insufficient:
        summary = ", ".join(f"GPU{g.index}={g.free_mb}MiB free" for g in target_gpus)
        return GpuCheckResult(
            ok=True, gpus=target_gpus, threshold_mb=min_free_mb,
            message=f"VRAM ok (need {min_free_mb} MiB): {summary}",
        )

    busy_indices = [g.index for g in insufficient]
    procs = _compute_processes(busy_indices)
    detail = ", ".join(
        f"GPU{g.index}={g.free_mb}/{g.total_mb} MiB free" for g in insufficient
    )
    msg_lines = [
        f"Insufficient GPU VRAM: need {min_free_mb} MiB free, "
        f"but assigned GPU(s) have: {detail}.",
        "This usually means another process is holding the GPU memory.",
    ]
    if procs:
        msg_lines.append(f"Processes on busy GPU(s):\n{procs}")
    return GpuCheckResult(
        ok=False, gpus=target_gpus, threshold_mb=min_free_mb,
        message="\n".join(msg_lines),
    )
