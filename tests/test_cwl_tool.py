"""Tests for per-tool and unified CWL tool definitions.

Validates CWL structure by parsing YAML directly and by running
cwltool --validate. No Docker or GPU required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

CWL_DIR = Path(__file__).resolve().parents[1] / "cwl" / "tools"
JOBS_DIR = Path(__file__).resolve().parents[1] / "cwl" / "jobs"

# Per-tool CWL definitions
PER_TOOL_CWLS = {
    "boltz": CWL_DIR / "boltz.cwl",
    "chai": CWL_DIR / "chai.cwl",
    "alphafold": CWL_DIR / "alphafold.cwl",
    "esmfold": CWL_DIR / "esmfold.cwl",
}

# Expected input file key per tool (matching _INPUT_FILE_KEY in cwl.py)
INPUT_KEY = {
    "boltz": "input_file",
    "chai": "input_fasta",
    "alphafold": "fasta_paths",
    "esmfold": "sequences",
}


class TestPerToolCWLStructure:
    """Validate per-tool CWL definitions."""

    @pytest.fixture(params=sorted(PER_TOOL_CWLS.keys()))
    def tool_and_doc(self, request):
        tool = request.param
        doc = yaml.safe_load(PER_TOOL_CWLS[tool].read_text())
        return tool, doc

    def test_cwl_version(self, tool_and_doc):
        _, doc = tool_and_doc
        assert doc["cwlVersion"] == "v1.2"

    def test_class_is_command_line_tool(self, tool_and_doc):
        _, doc = tool_and_doc
        assert doc["class"] == "CommandLineTool"

    def test_has_base_command(self, tool_and_doc):
        _, doc = tool_and_doc
        assert "baseCommand" in doc
        assert isinstance(doc["baseCommand"], list)
        assert len(doc["baseCommand"]) >= 1

    def test_has_docker_requirement(self, tool_and_doc):
        _, doc = tool_and_doc
        hints = doc.get("hints", {})
        assert "DockerRequirement" in hints
        assert "dockerPull" in hints["DockerRequirement"]

    def test_all_use_same_image(self, tool_and_doc):
        _, doc = tool_and_doc
        image = doc["hints"]["DockerRequirement"]["dockerPull"]
        assert image.endswith(".sif")

    def test_has_input_file(self, tool_and_doc):
        tool, doc = tool_and_doc
        key = INPUT_KEY[tool]
        assert key in doc["inputs"], f"{tool} missing input '{key}'"
        assert doc["inputs"][key]["type"] == "File"

    def test_has_output_dir(self, tool_and_doc):
        tool, doc = tool_and_doc
        # chai uses output_directory, others use output_dir
        has_output = "output_dir" in doc["inputs"] or "output_directory" in doc["inputs"]
        assert has_output, f"{tool} missing output directory input"

    def test_has_predictions_output(self, tool_and_doc):
        _, doc = tool_and_doc
        assert "predictions" in doc["outputs"]
        assert doc["outputs"]["predictions"]["type"] == "Directory"


class TestPerToolCWLValidation:
    """Run cwltool --validate on each per-tool CWL definition."""

    @pytest.fixture(params=sorted(PER_TOOL_CWLS.items()), ids=lambda x: x[0])
    def cwl_path(self, request):
        return request.param[1]

    def test_cwltool_validates(self, cwl_path):
        result = subprocess.run(
            ["cwltool", "--validate", str(cwl_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"cwltool validation failed for {cwl_path.name}:\n{result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "is valid CWL" in combined


class TestUnifiedCWLStructure:
    """Validate the unified predict-structure.cwl (kept alongside per-tool)."""

    @pytest.fixture
    def cwl_doc(self):
        unified = CWL_DIR / "predict-structure.cwl"
        if not unified.exists():
            pytest.skip("Unified CWL not present")
        return yaml.safe_load(unified.read_text())

    def test_has_entity_inputs(self, cwl_doc):
        for entity in ("protein", "dna", "rna", "ligand", "smiles", "glycan"):
            assert entity in cwl_doc["inputs"]

    def test_tool_enum_includes_auto(self, cwl_doc):
        symbols = set(cwl_doc["inputs"]["tool"]["type"]["symbols"])
        assert "auto" in symbols

    def test_cwltool_validates(self):
        unified = CWL_DIR / "predict-structure.cwl"
        if not unified.exists():
            pytest.skip("Unified CWL not present")
        result = subprocess.run(
            ["cwltool", "--validate", str(unified)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Validation failed:\n{result.stderr}"


class TestJobYAMLs:
    """Validate that job YAML files match per-tool CWL definitions."""

    @pytest.fixture(params=sorted(JOBS_DIR.glob("*.yml")), ids=lambda p: p.stem)
    def job_doc(self, request):
        return yaml.safe_load(request.param.read_text())

    def test_has_input_file(self, job_doc):
        """Each job has an input file matching its tool's input key."""
        accepted_keys = set(INPUT_KEY.values()) | {"protein"}
        has_input = any(key in job_doc for key in accepted_keys)
        assert has_input, f"Job missing input file key (expected one of {sorted(accepted_keys)})"

    def test_has_output_dir(self, job_doc):
        has_output = "output_dir" in job_doc or "output_directory" in job_doc
        assert has_output
