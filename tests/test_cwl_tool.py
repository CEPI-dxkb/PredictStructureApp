"""Tests for per-tool and unified CWL tool definitions.

Validates CWL structure by parsing YAML directly and by running
cwltool --validate. No Docker or GPU required.
"""

from __future__ import annotations

import hashlib
import json
import shutil
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
    "esmfold2": CWL_DIR / "esmfold2.cwl",
}

# Expected input file key per tool (matching _INPUT_FILE_KEY in cwl.py)
INPUT_KEY = {
    "boltz": "input_file",
    "chai": "input_fasta",
    "alphafold": "fasta_paths",
    "esmfold": "sequences",
    "esmfold2": "spec",
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


class TestNoDuplicateCWLDefinitions:
    """No two CWL definitions may be byte-identical copies (#104).

    boltz-report-msa.cwl was a byte-for-byte copy of boltz-report.cwl, so its
    name promised MSA behavior it did not add. A distinctly named CWL file has
    to differ from every other one, or it is a lie about what it does.
    """

    CWL_ROOT = Path(__file__).resolve().parents[1] / "cwl"

    def test_no_two_cwl_files_are_identical(self):
        by_digest: dict[str, list[str]] = {}
        for path in sorted(self.CWL_ROOT.rglob("*.cwl")):
            digest = hashlib.md5(path.read_bytes()).hexdigest()
            by_digest.setdefault(digest, []).append(str(path.relative_to(self.CWL_ROOT)))
        dupes = [names for names in by_digest.values() if len(names) > 1]
        assert not dupes, f"Byte-identical CWL definitions: {dupes}"

    def test_boltz_report_msa_variant_is_gone(self):
        """Removed in favor of boltz-report.cwl's use_msa_server input."""
        assert not (self.CWL_ROOT / "workflows" / "boltz-report-msa.cwl").exists()

    def test_boltz_report_exposes_msa_server_toggle(self):
        """The MSA behavior the deleted variant promised lives here."""
        doc = yaml.safe_load(
            (self.CWL_ROOT / "workflows" / "boltz-report.cwl").read_text()
        )
        assert "use_msa_server" in doc["inputs"]
        assert doc["steps"]["predict"]["in"]["use_msa_server"] == "use_msa_server"


class TestPaeCWLWiring:
    """The CWL report path must receive predictions/pae.json too (#50).

    The Perl service and the CWL workflows are two independent routes to the
    same report; fixing only the Perl leaves CWL-run reports without PAE.
    """

    WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "cwl" / "workflows"

    def test_select_pae_validates(self):
        result = subprocess.run(
            ["cwltool", "--validate", str(CWL_DIR / "select-pae.cwl")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "is valid CWL" in result.stdout + result.stderr

    def test_select_pae_output_is_optional(self):
        """Tools without PAE (ESMFold, Chai) must not fail the workflow."""
        doc = yaml.safe_load((CWL_DIR / "select-pae.cwl").read_text())
        assert doc["outputs"]["pae"]["type"] == "File?"
        # pae.json lives under predictions/, one level down
        assert doc["requirements"]["LoadListingRequirement"]["loadListing"] == \
            "deep_listing"

    @pytest.mark.parametrize("wf", ["boltz-report.cwl"])
    def test_boltz_workflows_pass_pae_to_report(self, wf):
        doc = yaml.safe_load((self.WORKFLOW_DIR / wf).read_text())
        steps = doc["steps"]
        assert "extract_pae" in steps, f"{wf} has no PAE extraction step"
        assert steps["extract_pae"]["run"].endswith("select-pae.cwl")
        assert steps["report"]["in"]["pae"] == "extract_pae/pae"


@pytest.mark.timeout(180)
@pytest.mark.skipif(shutil.which("cwltool") is None, reason="cwltool not on PATH")
class TestSelectPaeExecution:
    """Actually run select-pae.cwl (#105).

    --validate only proves the schema parses; a broken glob or JavaScript
    expression still passes it and fails in production. These run the tool
    against tiny fixture directories -- no real prediction output needed.
    """

    @staticmethod
    def _run(predictions: Path, outdir: Path) -> dict:
        result = subprocess.run(
            [
                "cwltool",
                "--outdir", str(outdir),
                str(CWL_DIR / "select-pae.cwl"),
                "--predictions", str(predictions),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"select-pae.cwl execution failed (rc={result.returncode}):\n{result.stderr}"
        )
        return json.loads(result.stdout)

    def test_selects_pae_under_predictions(self, tmp_path):
        """The normalized layout: pae.json one level down, under predictions/."""
        preds = tmp_path / "out" / "predictions"
        preds.mkdir(parents=True)
        (preds / "model_1.pdb").write_text("ATOM\n")
        (preds / "pae.json").write_text('{"pae": [[0.5]]}')

        outputs = self._run(tmp_path / "out", tmp_path / "outdir")

        assert outputs["pae"] is not None, "pae.json under predictions/ was not selected"
        assert outputs["pae"]["basename"] == "pae.json"
        assert Path(outputs["pae"]["path"]).read_text() == '{"pae": [[0.5]]}'

    def test_selects_pae_at_top_level(self, tmp_path):
        """A raw tool directory may hold pae.json directly."""
        preds = tmp_path / "out"
        preds.mkdir()
        (preds / "pae.json").write_text('{"pae": [[0.25]]}')

        outputs = self._run(preds, tmp_path / "outdir")

        assert outputs["pae"]["basename"] == "pae.json"
        assert Path(outputs["pae"]["path"]).read_text() == '{"pae": [[0.25]]}'

    def test_returns_null_when_no_pae(self, tmp_path):
        """Tools without PAE (ESMFold, Chai) must not fail the workflow."""
        preds = tmp_path / "out" / "predictions"
        preds.mkdir(parents=True)
        (preds / "model_1.pdb").write_text("ATOM\n")

        outputs = self._run(tmp_path / "out", tmp_path / "outdir")

        assert outputs["pae"] is None


class TestUnifiedCWLStructure:
    """Validate the unified predict-structure.cwl (kept alongside per-tool)."""

    @pytest.fixture
    def cwl_doc(self):
        unified = CWL_DIR / "predict-structure.cwl"
        if not unified.exists():
            pytest.skip("Unified CWL not present")
        return yaml.safe_load(unified.read_text())

    def test_has_entity_inputs(self, cwl_doc):
        for entity in ("protein", "dna", "rna", "ligand", "smiles"):
            assert entity in cwl_doc["inputs"]

    def test_tool_enum_includes_auto(self, cwl_doc):
        symbols = set(cwl_doc["inputs"]["tool"]["type"]["symbols"])
        assert "auto" in symbols

    def test_exposes_provenance_outputs(self, cwl_doc):
        """predict-structure.cwl exposes results.json + ro-crate outputs.

        Reports are produced by a separate workflow step (protein-compare),
        not by predict-structure itself, so there is no `reports` output here.
        """
        outputs = cwl_doc["outputs"]
        for name in ("results", "ro_crate"):
            assert name in outputs, f"Missing CWL output: {name}"
        assert outputs["results"]["outputBinding"]["glob"].endswith("results.json")
        assert outputs["ro_crate"]["outputBinding"]["glob"].endswith(
            "ro-crate-metadata.json"
        )

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
        # App-wrapper jobs (predict-structure-app.cwl) use P3_WORKDIR
        # instead of an explicit output_dir in the job spec.
        if "tool" in job_doc and "output_dir" not in job_doc and "output_directory" not in job_doc:
            pytest.skip("App-wrapper job uses P3_WORKDIR, not output_dir")
        has_output = "output_dir" in job_doc or "output_directory" in job_doc
        assert has_output
