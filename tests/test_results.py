"""Tests for predict_structure.results (results.json v2.0 + RO-Crate writers)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


def _make_normalized_dir(tmp_path: Path, *, with_reports: bool = False) -> Path:
    """Build a minimal normalized output dir matching the v2.0 layout."""
    out = tmp_path / "out"
    out.mkdir()

    # Top-level user-facing files
    (out / "model_1.pdb").write_text(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 80.00           C\n"
        "END\n"
    )

    # predictions/ subdir
    pred = out / "predictions"
    pred.mkdir()
    (pred / "model_1.pdb").write_text(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 80.00           C\n"
        "END\n"
    )
    (pred / "model_1.cif").write_text("data_test\n_entry.id test\n")
    (pred / "confidence.json").write_text(json.dumps({
        "plddt_mean": 82.14,
        "ptm": 0.78,
        "per_residue_plddt": [80.0, 82.0, 84.0],
        "per_atom_plddt": [80.0, 80.0, 82.0, 82.0, 84.0, 84.0],
    }))

    # metadata/ subdir
    meta_dir = out / "metadata"
    meta_dir.mkdir()
    (meta_dir / "metadata.json").write_text(json.dumps({
        "schema_version": "1.1",
        "tool": "boltz",
        "version": "0.2.0",
        "tool_version": "2.1.0",
        "status": "success",
        "started_at": "2026-04-24T12:00:00+00:00",
        "completed_at": "2026-04-24T12:34:56+00:00",
        "runtime_seconds": 842.3,
        "command": ["predict-structure", "boltz", "--protein", "x.fa"],
        "container_image": "folding_prod.sif",
        "backend": "subprocess",
        "params": {"num_samples": 1, "num_recycles": 3},
        "inputs": [],
    }))

    # raw/ (opaque)
    (out / "raw").mkdir()
    (out / "raw" / "pred.model_idx_0.cif").write_text("data_raw\n")

    if with_reports:
        # Top-level report.html (UI-facing copy)
        (out / "report.html").write_text("<html>report</html>")
        # reports/ subdir holds the rest
        reports = out / "reports"
        reports.mkdir()
        (reports / "report.html").write_text("<html>report</html>")
        (reports / "report.json").write_text(json.dumps({"metrics": []}))
        (reports / "report.pdf").write_bytes(b"%PDF-1.4\n%EOF\n")

    return out


class TestWriteResultsJson:
    def test_header_and_state(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        path = write_results_json(out)
        assert path.name == "results.json"
        data = json.loads(path.read_text())

        assert data["schema_version"] == "2.0"
        assert data["state"] == "COMPLETED"
        assert data["tool"] == "boltz"
        assert data["completed_at"] == "2026-04-24T12:34:56+00:00"
        assert data["runtime_seconds"] == 842.3

    def test_metrics_block(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        path = write_results_json(out)
        data = json.loads(path.read_text())

        assert data["metrics"]["plddt_mean"] == 82.14
        assert data["metrics"]["ptm"] == 0.78
        assert data["metrics"]["num_residues"] == 3
        assert data["metrics"]["num_atoms"] == 6

    def test_outputs_named_dict(self, tmp_path):
        """outputs is a named dict (not array) with stable port names."""
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path, with_reports=True)
        path = write_results_json(out)
        data = json.loads(path.read_text())

        assert isinstance(data["outputs"], dict)
        assert "best_model" in data["outputs"]
        assert "report" in data["outputs"]
        assert "predictions" in data["outputs"]
        assert "reports" in data["outputs"]
        assert "metadata" in data["outputs"]
        assert "raw" in data["outputs"]

    def test_best_model_file_entry(self, tmp_path):
        """best_model is a CWL File entry pointing at the top-level PDB."""
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        data = json.loads(write_results_json(out).read_text())

        bm = data["outputs"]["best_model"]
        assert bm["class"] == "File"
        assert bm["basename"] == "model_1.pdb"
        assert bm["nameroot"] == "model_1"
        assert bm["nameext"] == ".pdb"
        assert bm["checksum"].startswith("sha256$")
        assert bm["location"] == "model_1.pdb"
        # Checksum matches actual file content
        expected = hashlib.sha256((out / "model_1.pdb").read_bytes()).hexdigest()
        assert bm["checksum"] == f"sha256${expected}"

    def test_predictions_directory_entry(self, tmp_path):
        """predictions is a CWL Directory with listing[] for its contents."""
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        data = json.loads(write_results_json(out).read_text())

        pred = data["outputs"]["predictions"]
        assert pred["class"] == "Directory"
        assert pred["basename"] == "predictions"
        listing_names = {item["basename"] for item in pred["listing"]}
        assert listing_names == {"model_1.pdb", "model_1.cif", "confidence.json"}

    def test_raw_is_opaque(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        data = json.loads(write_results_json(out).read_text())

        raw = data["outputs"]["raw"]
        assert raw["class"] == "Directory"
        assert raw["opaque"] is True
        assert "listing" not in raw, "opaque dirs must NOT include listing"

    def test_skips_missing_outputs(self, tmp_path):
        """Optional ports (report, reports) are skipped when files don't exist."""
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path, with_reports=False)
        data = json.loads(write_results_json(out).read_text())

        assert "report" not in data["outputs"]
        assert "reports" not in data["outputs"]
        # predictions and metadata always present
        assert "predictions" in data["outputs"]
        assert "metadata" in data["outputs"]

    def test_missing_metadata_raises(self, tmp_path):
        from predict_structure.results import write_results_json

        out = tmp_path / "empty"
        out.mkdir()
        (out / "predictions").mkdir()
        (out / "predictions" / "confidence.json").write_text(
            json.dumps({"plddt_mean": 0, "per_residue_plddt": [0]})
        )

        with pytest.raises(FileNotFoundError):
            write_results_json(out)

    def test_schema_validation(self, tmp_path):
        """results.json validates against the committed v2.0 JSON Schema."""
        from predict_structure.results import write_results_json

        jsonschema = pytest.importorskip("jsonschema")

        schemas_dir = (
            Path(__file__).parent / "acceptance" / "schemas"
        )
        results_schema = schemas_dir / "results.schema.json"
        if not results_schema.exists():
            pytest.skip(f"Schema not found: {results_schema}")

        out = _make_normalized_dir(tmp_path, with_reports=True)
        data = json.loads(write_results_json(out).read_text())

        # Build a referencing registry so the $refs to cwl-file/directory resolve
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        def _load(name):
            return Resource.from_contents(
                json.loads((schemas_dir / name).read_text()),
                default_specification=DRAFT202012,
            )

        registry = Registry().with_resources([
            ("cwl-file.schema.json", _load("cwl-file.schema.json")),
            ("cwl-directory.schema.json", _load("cwl-directory.schema.json")),
        ])
        schema = json.loads(results_schema.read_text())
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
        validator.validate(data)


class TestWriteRoCrate:
    def test_missing_rocrate_package_returns_none(self, tmp_path, monkeypatch):
        from predict_structure.results import write_results_json, write_ro_crate

        monkeypatch.setitem(sys.modules, "rocrate", None)

        out = _make_normalized_dir(tmp_path)
        write_results_json(out)

        result = write_ro_crate(out)
        assert result is None
        assert not (out / "metadata" / "ro-crate-metadata.json").exists()

    def test_write_with_rocrate_installed(self, tmp_path):
        """With rocrate present, a valid ro-crate-metadata.json is produced."""
        pytest.importorskip("rocrate")
        from predict_structure.results import write_results_json, write_ro_crate

        out = _make_normalized_dir(tmp_path)
        write_results_json(out)
        crate_path = write_ro_crate(out)
        assert crate_path is not None
        assert crate_path.name == "ro-crate-metadata.json"
        assert crate_path.parent.name == "metadata"
        assert crate_path.exists()

        crate = json.loads(crate_path.read_text())
        assert "@context" in crate
        assert "@graph" in crate
        # Root Dataset should be present
        types = [e.get("@type") for e in crate["@graph"] if isinstance(e, dict)]
        assert "Dataset" in types or any(
            isinstance(t, list) and "Dataset" in t for t in types
        )
