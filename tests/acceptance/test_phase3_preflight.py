"""Phase 3: Preflight resource estimation tests.

Tests predict-structure preflight --tool <tool> inside the container.
Validates JSON output structure, GPU requirements, and resource estimates.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.phase3, pytest.mark.container]

TOOLS_GPU = ["boltz", "openfold", "chai", "alphafold"]
TOOLS_ALL = TOOLS_GPU + ["esmfold"]


class TestPreflightOutput:
    """Preflight returns valid JSON with required fields."""

    @pytest.mark.parametrize("tool", TOOLS_ALL)
    def test_preflight_returns_json(self, container, tool):
        """Preflight produces valid JSON for each tool."""
        data = container.preflight(tool)
        assert "resolved_tool" in data
        assert data["resolved_tool"] == tool

    @pytest.mark.parametrize("tool", TOOLS_ALL)
    def test_preflight_has_resource_fields(self, container, tool):
        """Preflight JSON contains cpu, memory, and runtime."""
        data = container.preflight(tool)
        assert "cpu" in data
        assert "memory" in data
        assert "runtime" in data

    @pytest.mark.parametrize("tool", TOOLS_ALL)
    def test_preflight_cpu_reasonable(self, container, tool):
        """CPU count is a reasonable value (1-32)."""
        data = container.preflight(tool)
        cpu = data["cpu"]
        assert isinstance(cpu, int)
        assert 1 <= cpu <= 32, f"Unexpected CPU count: {cpu}"


class TestPreflightGPU:
    """GPU requirements are correctly reported."""

    @pytest.mark.parametrize("tool", TOOLS_GPU)
    def test_gpu_tools_need_gpu(self, container, tool):
        """Boltz, OpenFold, Chai, AlphaFold all require GPU."""
        data = container.preflight(tool)
        assert data["needs_gpu"] is True

    def test_esmfold_no_gpu(self, container):
        """ESMFold does not require GPU."""
        data = container.preflight("esmfold")
        assert data["needs_gpu"] is False

    @pytest.mark.parametrize("tool", TOOLS_GPU)
    def test_gpu_tools_have_policy_data(self, container, tool):
        """GPU tools include policy_data with constraint."""
        data = container.preflight(tool)
        policy = data.get("policy_data", {})
        assert "constraint" in policy or "gpu_count" in policy, (
            f"Missing GPU policy data for {tool}: {data}"
        )


class TestPreflightAutoResolution:
    """Preflight resolves 'auto' to a concrete tool."""

    def test_auto_resolves_to_tool(self, container):
        """--tool auto should resolve to a concrete tool name."""
        data = container.preflight("auto")
        assert data["resolved_tool"] in TOOLS_ALL
        assert data["resolved_tool"] != "auto"
