"""Tests for predict_structure.results (results.json + RO-Crate writers)."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _make_normalized_dir(tmp_path: Path, *, with_reports: bool = False) -> Path:
    """Build a minimal normalized output dir (as the normalizers would produce)."""
    out = tmp_path / "out"
    out.mkdir()

    # model_1.pdb (tiny, but real bytes)
    (out / "model_1.pdb").write_text(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 80.00           C\n"
        "END\n"
    )
    (out / "model_1.cif").write_text("data_test\n_entry.id test\n")

    (out / "confidence.json").write_text(json.dumps({
        "plddt_mean": 82.14,
        "ptm": 0.78,
        "per_residue_plddt": [80.0, 82.0, 84.0],
        "per_atom_plddt": [80.0, 80.0, 82.0, 82.0, 84.0, 84.0],
    }))

    (out / "metadata.json").write_text(json.dumps({
        "tool": "boltz",
        "params": {"num_samples": 1, "num_recycles": 3},
        "runtime_seconds": 842.3,
        "version": "0.2.0",
        "timestamp": "2026-04-24T12:34:56+00:00",
    }))

    (out / "raw").mkdir()
    (out / "raw" / "pred.model_idx_0.cif").write_text("data_raw\n")

    if with_reports:
        (out / "report.html").write_text("<html>report</html>")
        (out / "report.json").write_text(json.dumps({"metrics": []}))
        (out / "report.pdf").write_bytes(b"%PDF-1.4\n%EOF\n")

    return out


class TestWriteResultsJson:
    def test_schema_and_fields(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        path = write_results_json(
            out,
            command=["predict-structure", "boltz", "--protein", "x.fa"],
            backend="subprocess",
            container_image="folding_prod.sif",
        )
        assert path.name == "results.json"
        data = json.loads(path.read_text())

        assert data["schema_version"] == "1.0"
        assert data["tool"] == "boltz"
        assert data["version"] == "0.2.0"
        assert data["status"] == "success"
        assert data["runtime_seconds"] == 842.3
        assert data["backend"] == "subprocess"
        assert data["container_image"] == "folding_prod.sif"
        assert data["command"] == ["predict-structure", "boltz", "--protein", "x.fa"]
        assert data["metrics"]["plddt_mean"] == 82.14
        assert data["metrics"]["ptm"] == 0.78
        assert data["metrics"]["num_residues"] == 3
        assert data["metrics"]["num_atoms"] == 6

    def test_outputs_manifest(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        path = write_results_json(out, command=[], backend="subprocess")
        data = json.loads(path.read_text())

        paths = {o["path"] for o in data["outputs"]}
        assert "model_1.pdb" in paths
        assert "model_1.cif" in paths
        assert "confidence.json" in paths
        assert "metadata.json" in paths
        assert "raw" in paths  # directory entry
        # results.json must NOT list itself (self-reference)
        assert "results.json" not in paths
        # No raw/* files should appear (raw is opaque)
        assert not any(p.startswith("raw/") for p in paths)

    def test_sha256_and_size_match(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path)
        path = write_results_json(out, command=[], backend="subprocess")
        data = json.loads(path.read_text())

        for entry in data["outputs"]:
            if entry["role"] == "raw_dir":
                assert entry["size"] is None
                assert entry["sha256"] is None
                continue
            fp = out / entry["path"]
            assert entry["size"] == fp.stat().st_size
            expected = hashlib.sha256(fp.read_bytes()).hexdigest()
            assert entry["sha256"] == expected

    def test_roles_assigned(self, tmp_path):
        from predict_structure.results import write_results_json

        out = _make_normalized_dir(tmp_path, with_reports=True)
        # Simulate post-relocation: reports in report/ subdir
        report_dir = out / "report"
        report_dir.mkdir(exist_ok=True)
        for name in ("report.html", "report.json", "report.pdf"):
            (out / name).rename(report_dir / name)

        path = write_results_json(out, command=[], backend="subprocess")
        data = json.loads(path.read_text())

        roles = {o["path"]: o["role"] for o in data["outputs"]}
        assert roles["model_1.pdb"] == "structure"
        assert roles["model_1.cif"] == "structure"
        assert roles["confidence.json"] == "confidence"
        assert roles["metadata.json"] == "metadata"
        assert roles["report/report.html"] == "report"
        assert roles["report/report.json"] == "report"
        assert roles["report/report.pdf"] == "report"
        assert roles["raw"] == "raw_dir"

    def test_missing_metadata_raises(self, tmp_path):
        from predict_structure.results import write_results_json

        out = tmp_path / "empty"
        out.mkdir()
        (out / "confidence.json").write_text(json.dumps({"plddt_mean": 0}))

        with pytest.raises(FileNotFoundError):
            write_results_json(out, command=[], backend="subprocess")

    def test_schema_validation(self, tmp_path):
        """results.json validates against the committed JSON Schema."""
        from predict_structure.results import write_results_json

        jsonschema = pytest.importorskip("jsonschema")

        schema_path = (
            Path(__file__).parent / "acceptance" / "schemas" / "results.schema.json"
        )
        if not schema_path.exists():
            pytest.skip(f"Schema not found: {schema_path}")

        out = _make_normalized_dir(tmp_path, with_reports=True)
        report_dir = out / "report"
        report_dir.mkdir(exist_ok=True)
        for name in ("report.html", "report.json", "report.pdf"):
            (out / name).rename(report_dir / name)

        path = write_results_json(
            out,
            command=["predict-structure", "boltz"],
            backend="subprocess",
        )
        data = json.loads(path.read_text())
        schema = json.loads(schema_path.read_text())
        jsonschema.validate(instance=data, schema=schema)


class TestWriteRoCrate:
    def test_missing_rocrate_package_returns_none(self, tmp_path, monkeypatch):
        """If rocrate is not installed, write_ro_crate logs + returns None."""
        from predict_structure.results import write_results_json, write_ro_crate

        # Simulate import failure by stuffing None into sys.modules
        monkeypatch.setitem(sys.modules, "rocrate", None)

        out = _make_normalized_dir(tmp_path)
        results_path = write_results_json(out, command=[], backend="subprocess")

        result = write_ro_crate(out, results_path)
        assert result is None
        assert not (out / "ro-crate-metadata.json").exists()

    def test_write_with_rocrate_installed(self, tmp_path):
        """With rocrate present, a valid ro-crate-metadata.json is produced."""
        pytest.importorskip("rocrate")
        from predict_structure.results import write_results_json, write_ro_crate

        out = _make_normalized_dir(tmp_path)
        results_path = write_results_json(
            out,
            command=["predict-structure", "boltz", "--protein", "x.fa"],
            backend="subprocess",
            container_image="folding_prod.sif",
        )
        crate_path = write_ro_crate(out, results_path)
        assert crate_path is not None
        assert crate_path.name == "ro-crate-metadata.json"
        assert crate_path.exists()

        crate = json.loads(crate_path.read_text())
        assert "@context" in crate
        assert "@graph" in crate
        # Root Dataset should be present
        types = [e.get("@type") for e in crate["@graph"] if isinstance(e, dict)]
        assert "Dataset" in types or any(
            isinstance(t, list) and "Dataset" in t for t in types
        )
