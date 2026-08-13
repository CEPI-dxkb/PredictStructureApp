"""Lock the per-tool preflight GPU constraint contract (issue #35).

Each adapter's ``preflight()`` emits resource sizing plus a ``policy_data``
block (partition, gpu_count, constraint string) that drives SLURM/BV-BRC
GPU scheduling. These values are surfaced by ``predict-structure preflight``
and mirrored by the Perl ``App-PredictStructure.pl`` ``_default_preflight``
fallback.

This module asserts the EXACT constraint string, partition, gpu_count,
needs_gpu, cpu, memory, and runtime each tool emits so that future drift is
caught WITHOUT needing a GPU. It is fully hermetic (no GPU, no container):
adapters are instantiated directly and the CLI ``preflight`` subcommand is
exercised via Click's in-process test runner.

Timing/throughput verification (does Boltz really finish within ``runtime``
seconds on an H200?) requires real GPU runs and is intentionally OUT OF
SCOPE here -- see the skipped placeholder at the bottom of this file.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from predict_structure.adapters import get_adapter
from predict_structure.cli import main

# Canonical per-tool contract. Each entry is the full expected preflight
# result for that tool. ``policy_data`` is the exact dict the adapter emits
# (esmfold is CPU-capable, so it carries NO gpu_count/constraint).
EXPECTED = {
    "boltz": {
        "needs_gpu": True,
        "cpu": 8,
        "memory": "96G",
        "runtime": 14400,
        "storage": "50G",
        # Boltz torch+cu130 needs CUDA 13.0+, available only on H200 nodes.
        "policy_data": {"gpu_count": 1, "partition": "gpu2", "constraint": "H200"},
    },
    "chai": {
        "needs_gpu": True,
        "cpu": 8,
        "memory": "64G",
        "runtime": 10800,
        "storage": "50G",
        "policy_data": {
            "gpu_count": 1,
            "partition": "gpu2",
            "constraint": "V100|H100|H200",
        },
    },
    "openfold": {
        "needs_gpu": True,
        "cpu": 8,
        "memory": "200G",
        "runtime": 14400,
        "storage": "50G",
        "policy_data": {
            "gpu_count": 1,
            "partition": "gpu2",
            "constraint": "H100|H200",
        },
    },
    "alphafold": {
        "needs_gpu": True,
        "cpu": 8,
        "memory": "64G",
        "runtime": 28800,
        "storage": "100G",
        "policy_data": {
            "gpu_count": 1,
            "partition": "gpu2",
            "constraint": "V100|H100|H200",
        },
    },
    "esmfold2": {
        "needs_gpu": True,
        "cpu": 8,
        "memory": "32G",
        "runtime": 3600,
        "storage": "50G",
        "policy_data": {
            "gpu_count": 1,
            "partition": "gpu2",
            "constraint": "H200",
        },
    },
    "esmfold": {
        "needs_gpu": False,
        "cpu": 8,
        "memory": "32G",
        "runtime": 3600,
        # CPU-capable: scheduled on gpu2 but requests NO GPU device, so the
        # policy_data carries neither gpu_count nor constraint.
        "policy_data": {"partition": "gpu2"},
    },
}

GPU_TOOLS = [t for t, e in EXPECTED.items() if e["needs_gpu"]]
ALL_TOOLS = list(EXPECTED)


class TestAdapterPreflightContract:
    """Adapter-level: ``adapter.preflight()`` + ``requires_gpu``."""

    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_requires_gpu_flag(self, tool):
        adapter = get_adapter(tool)
        assert adapter.requires_gpu is EXPECTED[tool]["needs_gpu"]

    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_cpu_memory_runtime(self, tool):
        res = get_adapter(tool).preflight()
        exp = EXPECTED[tool]
        assert res["cpu"] == exp["cpu"]
        assert res["memory"] == exp["memory"]
        assert res["runtime"] == exp["runtime"]

    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_policy_data_exact(self, tool):
        res = get_adapter(tool).preflight()
        assert res["policy_data"] == EXPECTED[tool]["policy_data"]

    @pytest.mark.parametrize("tool", GPU_TOOLS)
    def test_gpu_tools_constraint_and_partition(self, tool):
        pd = get_adapter(tool).preflight()["policy_data"]
        exp_pd = EXPECTED[tool]["policy_data"]
        assert pd["partition"] == "gpu2"
        assert pd["gpu_count"] == 1
        assert pd["constraint"] == exp_pd["constraint"]

    def test_esmfold_does_not_require_gpu(self):
        """ESMFold (HuggingFace) must run without a GPU policy."""
        adapter = get_adapter("esmfold")
        assert adapter.requires_gpu is False
        pd = adapter.preflight()["policy_data"]
        assert pd == {"partition": "gpu2"}
        assert "gpu_count" not in pd
        assert "constraint" not in pd

    def test_boltz_constraint_is_h200_only(self):
        """Boltz needs CUDA 13.0+ -> H200 only (issue #35 reconciliation)."""
        pd = get_adapter("boltz").preflight()["policy_data"]
        assert pd["constraint"] == "H200"


class TestCliPreflightContract:
    """End-to-end: ``predict-structure preflight --tool <tool>`` JSON."""

    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_cli_preflight_matches_contract(self, tool):
        runner = CliRunner()
        result = runner.invoke(main, ["preflight", "--tool", tool])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        exp = EXPECTED[tool]
        assert data["resolved_tool"] == tool
        assert data["needs_gpu"] is exp["needs_gpu"]
        assert data["cpu"] == exp["cpu"]
        assert data["memory"] == exp["memory"]
        assert data["runtime"] == exp["runtime"]
        assert data["policy_data"] == exp["policy_data"]


@pytest.mark.skip(
    reason="Timing/throughput verification needs a real GPU run "
    "(deferred per issue #35); placeholder documents the on-GPU check."
)
@pytest.mark.parametrize("tool", GPU_TOOLS)
def test_runtime_estimate_holds_on_gpu(tool):
    """DEFERRED (needs GPU): assert a real run on the smallest allowed GPU
    in ``constraint`` completes within the advertised ``runtime`` seconds
    for a representative input. Locks that the runtime estimate is not just
    self-consistent but actually achievable on hardware."""
    raise NotImplementedError
