"""Tests for the GPU VRAM precheck.

The check shells out to ``nvidia-smi``; here we monkeypatch the two
internal helpers so the tests run on hosts without a GPU.
"""

from __future__ import annotations

import pytest

from predict_structure import gpu_check
from predict_structure.gpu_check import (
    GpuStatus,
    check_gpu_memory,
)


@pytest.fixture
def fake_gpus(monkeypatch):
    """Return a setter that replaces nvidia-smi output with given GpuStatus list."""
    def _set(gpus):
        monkeypatch.setattr(gpu_check, "_query_nvidia_smi", lambda: list(gpus))
        monkeypatch.setattr(gpu_check, "_compute_processes",
                            lambda idxs: "fake-process-info")
    return _set


def test_passes_when_visible_gpu_has_enough_vram(fake_gpus, monkeypatch):
    fake_gpus([GpuStatus(0, 80000, 95000), GpuStatus(1, 5000, 95000)])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    r = check_gpu_memory(12000)
    assert r.ok
    assert "GPU0=80000MiB free" in r.message


def test_fails_when_visible_gpu_below_threshold(fake_gpus, monkeypatch):
    fake_gpus([GpuStatus(0, 80000, 95000), GpuStatus(1, 5000, 95000)])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    r = check_gpu_memory(12000)
    assert not r.ok
    assert "GPU1=5000/95000" in r.message
    assert "fake-process-info" in r.message


def test_skips_when_nvidia_smi_unavailable(monkeypatch):
    monkeypatch.setattr(gpu_check, "_query_nvidia_smi", lambda: [])
    r = check_gpu_memory(12000)
    assert r.ok
    assert "nvidia-smi unavailable" in r.message


def test_cuda_visible_devices_unset_checks_gpu0(fake_gpus, monkeypatch):
    fake_gpus([GpuStatus(0, 80000, 95000), GpuStatus(1, 5000, 95000)])
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    r = check_gpu_memory(12000)
    assert r.ok  # GPU0 has 80000 free


def test_multiple_visible_gpus_all_must_pass(fake_gpus, monkeypatch):
    fake_gpus([
        GpuStatus(0, 80000, 95000),
        GpuStatus(1, 5000, 95000),
        GpuStatus(2, 80000, 95000),
    ])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1,2")
    r = check_gpu_memory(12000)
    assert not r.ok
    assert "GPU1=5000" in r.message


def test_uuid_visible_devices_falls_back_to_gpu0(fake_gpus, monkeypatch):
    fake_gpus([GpuStatus(0, 80000, 95000), GpuStatus(1, 5000, 95000)])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-deadbeef-...")
    r = check_gpu_memory(12000)
    assert r.ok  # falls back to checking GPU 0
