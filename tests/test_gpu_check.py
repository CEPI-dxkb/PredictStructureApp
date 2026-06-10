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


def test_uuid_visible_devices_resolves_assigned_gpu(fake_gpus, monkeypatch):
    # Regression: physical GPU0 is busy (vLLM), but the SLURM-assigned
    # GPU is a free card further down the bus, named by UUID. The
    # precheck must probe the assigned GPU, not index 0.
    fake_gpus([
        GpuStatus(0, 5000, 95000, "GPU-busy0000-0000"),
        GpuStatus(6, 95000, 95000, "GPU-8a75dad1-393e-8006-585f-b185e9fa7bc3"),
    ])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES",
                       "GPU-8a75dad1-393e-8006-585f-b185e9fa7bc3")
    r = check_gpu_memory(30000)
    assert r.ok  # assigned GPU6 has 95000 free
    assert "GPU6=95000MiB free" in r.message


def test_uuid_visible_devices_fails_when_assigned_gpu_busy(fake_gpus, monkeypatch):
    fake_gpus([
        GpuStatus(0, 95000, 95000, "GPU-free0000-0000"),
        GpuStatus(6, 5000, 95000, "GPU-8a75dad1-393e-8006-585f-b185e9fa7bc3"),
    ])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES",
                       "GPU-8a75dad1-393e-8006-585f-b185e9fa7bc3")
    r = check_gpu_memory(30000)
    assert not r.ok
    assert "GPU6=5000/95000" in r.message


def test_uuid_visible_devices_unknown_uuid_skips(fake_gpus, monkeypatch):
    fake_gpus([GpuStatus(0, 5000, 95000, "GPU-aaaa-0000")])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-nomatch-9999")
    r = check_gpu_memory(30000)
    assert r.ok  # no matching GPU — skip precheck rather than false-fail
    assert "no matching GPU" in r.message
