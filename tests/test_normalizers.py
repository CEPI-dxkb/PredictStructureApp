"""Tests for output normalization and confidence extraction."""

import json
import pytest
from pathlib import Path

import numpy as np


class TestWriteConfidenceJson:
    def test_schema(self, tmp_output):
        from predict_structure.normalizers import write_confidence_json

        path = write_confidence_json(
            tmp_output, plddt_mean=87.3, ptm=0.92,
            per_residue_plddt=[91.2, 88.5, 85.1, 84.0],
        )
        assert path.name == "confidence.json"
        data = json.loads(path.read_text())
        assert data["plddt_mean"] == 87.3
        assert data["ptm"] == 0.92
        assert len(data["per_residue_plddt"]) == 4

    def test_null_ptm(self, tmp_output):
        from predict_structure.normalizers import write_confidence_json

        path = write_confidence_json(
            tmp_output, plddt_mean=50.0, ptm=None,
            per_residue_plddt=[50.0],
        )
        data = json.loads(path.read_text())
        assert data["ptm"] is None

    def test_per_atom_plddt_optional(self, tmp_output):
        """per_atom_plddt is optional; omitted when not provided."""
        from predict_structure.normalizers import write_confidence_json

        path = write_confidence_json(
            tmp_output, plddt_mean=50.0, ptm=None,
            per_residue_plddt=[50.0],
        )
        data = json.loads(path.read_text())
        assert "per_atom_plddt" not in data

    def test_per_atom_plddt_included(self, tmp_output):
        """per_atom_plddt is written when provided, length >= per_residue."""
        from predict_structure.normalizers import write_confidence_json

        path = write_confidence_json(
            tmp_output, plddt_mean=70.0, ptm=0.5,
            per_residue_plddt=[70.0, 72.0],  # 2 residues
            per_atom_plddt=[70.1, 70.0, 70.2, 69.8, 70.0, 72.1, 72.0, 72.3, 71.8, 72.0],  # 10 atoms
        )
        data = json.loads(path.read_text())
        assert "per_atom_plddt" in data
        assert len(data["per_atom_plddt"]) == 10
        assert len(data["per_atom_plddt"]) >= len(data["per_residue_plddt"])


class TestWriteMetadataJson:
    def test_schema(self, tmp_output):
        from predict_structure.normalizers import write_metadata_json

        path = write_metadata_json(
            tmp_output, tool="boltz",
            params={"num_samples": 5},
            runtime_seconds=1823.4,
            version="0.1.0",
        )
        assert path.name == "metadata.json"
        data = json.loads(path.read_text())
        assert data["tool"] == "boltz"
        assert data["params"]["num_samples"] == 5
        assert data["runtime_seconds"] == 1823.4
        assert data["version"] == "0.1.0"
        assert "timestamp" in data


class TestNormalizeBoltzOutput:
    def test_normalize(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_boltz_output

        # Create mock Boltz raw output
        raw = tmp_path / "raw"
        pred_dir = raw / "predictions" / "test_input"
        pred_dir.mkdir(parents=True)

        # Minimal PDB content for CIF conversion test — write as .cif
        # Use a minimal PDB file and rename it to test the flow
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.85           C\n"
            "END\n"
        )
        # Write a real PDB and convert to CIF for the test fixture
        pdb_tmp = pred_dir / "temp.pdb"
        pdb_tmp.write_text(pdb_content)
        from predict_structure.converters import pdb_to_mmcif
        cif_file = pred_dir / "test_input_model_0.cif"
        pdb_to_mmcif(pdb_tmp, cif_file)
        pdb_tmp.unlink()

        # Confidence JSON
        conf = pred_dir / "confidence_test_input_model_0.json"
        conf.write_text(json.dumps({
            "confidence_score": 0.87,
            "ptm": 0.92,
            "plddt": [0.91, 0.88, 0.85],
        }))

        normalize_boltz_output(raw, tmp_output)

        assert (tmp_output / "model_1.cif").exists()
        assert (tmp_output / "model_1.pdb").exists()
        assert (tmp_output / "confidence.json").exists()
        assert (tmp_output / "raw").exists()

        data = json.loads((tmp_output / "confidence.json").read_text())
        # Should be scaled to 0-100
        assert data["per_residue_plddt"][0] == 91.0
        assert data["ptm"] == 0.92


class TestNormalizeChaiOutput:
    def test_normalize(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_chai_output

        raw = tmp_path / "raw"
        raw.mkdir()

        # Create mock CIF (from PDB with Chai-style B-factors: 0-100 scale)
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 75.00           C\n"
            "END\n"
        )
        pdb_tmp = raw / "temp.pdb"
        pdb_tmp.write_text(pdb_content)
        from predict_structure.converters import pdb_to_mmcif
        pdb_to_mmcif(pdb_tmp, raw / "pred.model_idx_0.cif")
        pdb_tmp.unlink()

        # Scores NPZ (Chai format: aggregate_score, ptm, iptm — no plddt)
        np.savez(
            str(raw / "scores.model_idx_0.npz"),
            aggregate_score=np.array([0.85]),
            ptm=np.array([0.88]),
            iptm=np.array([0.90]),
        )

        normalize_chai_output(raw, tmp_output)

        assert (tmp_output / "model_1.pdb").exists()
        data = json.loads((tmp_output / "confidence.json").read_text())
        assert data["per_residue_plddt"][0] == 75.0  # from PDB B-factors
        assert data["ptm"] == 0.88


class TestNormalizeESMFoldOutput:
    def test_bfactor_scaling(self, tmp_path, tmp_output):
        """ESMFold B-factors are 0-1, must be scaled to 0-100."""
        from predict_structure.normalizers import normalize_esmfold_output

        raw = tmp_path / "raw"
        raw.mkdir()

        # PDB with B-factors in 0-1 range (ESMFold style)
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.85           C\n"
            "ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00  0.72           C\n"
            "END\n"
        )
        (raw / "1CRN.pdb").write_text(pdb_content)

        normalize_esmfold_output(raw, tmp_output)

        data = json.loads((tmp_output / "confidence.json").read_text())
        # 0.85 * 100 = 85.0, 0.72 * 100 = 72.0
        assert data["per_residue_plddt"][0] == 85.0
        assert data["per_residue_plddt"][1] == 72.0
        assert 70 < data["plddt_mean"] < 90
        assert data["ptm"] is None  # ESMFold doesn't write pTM to file


class TestNormalizeOpenFoldOutput:
    def test_normalize(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_openfold_output

        # Create mock OpenFold 3 raw output
        raw = tmp_path / "raw"
        seed_dir = raw / "prediction" / "seed_42"
        seed_dir.mkdir(parents=True)

        # Write a minimal PDB and convert to CIF for the model file
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 85.00           C\n"
            "ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00 72.00           C\n"
            "END\n"
        )
        pdb_tmp = seed_dir / "temp.pdb"
        pdb_tmp.write_text(pdb_content)
        from predict_structure.converters import pdb_to_mmcif
        pdb_to_mmcif(pdb_tmp, seed_dir / "prediction_seed_42_sample_1_model.cif")
        pdb_tmp.unlink()

        # Aggregated confidences
        import json
        agg = {
            "avg_plddt": 78.5,
            "ptm": 0.88,
            "iptm": 0.85,
            "sample_ranking_score": 0.75,
        }
        (seed_dir / "prediction_seed_42_sample_1_confidences_aggregated.json").write_text(
            json.dumps(agg)
        )

        # Detailed confidences with per-residue pLDDT
        conf = {
            "plddt": [85.0, 72.0],
        }
        (seed_dir / "prediction_seed_42_sample_1_confidences.json").write_text(
            json.dumps(conf)
        )

        normalize_openfold_output(raw, tmp_output)

        assert (tmp_output / "model_1.cif").exists()
        assert (tmp_output / "model_1.pdb").exists()
        assert (tmp_output / "confidence.json").exists()
        assert (tmp_output / "raw").exists()

        data = json.loads((tmp_output / "confidence.json").read_text())
        assert data["plddt_mean"] == 78.5
        assert data["ptm"] == 0.88
        assert data["per_residue_plddt"] == [85.0, 72.0]

    def test_best_sample_selection(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_openfold_output
        import json

        raw = tmp_path / "raw"
        seed_dir = raw / "prediction" / "seed_42"
        seed_dir.mkdir(parents=True)

        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 60.00           C\n"
            "END\n"
        )
        from predict_structure.converters import pdb_to_mmcif

        # Sample 1 (lower score)
        pdb_tmp = seed_dir / "temp1.pdb"
        pdb_tmp.write_text(pdb_content)
        pdb_to_mmcif(pdb_tmp, seed_dir / "prediction_seed_42_sample_1_model.cif")
        pdb_tmp.unlink()
        (seed_dir / "prediction_seed_42_sample_1_confidences_aggregated.json").write_text(
            json.dumps({"avg_plddt": 60.0, "ptm": 0.5, "sample_ranking_score": 0.4})
        )

        # Sample 2 (higher score — should be selected)
        pdb_tmp = seed_dir / "temp2.pdb"
        pdb_tmp.write_text(pdb_content.replace("60.00", "90.00"))
        pdb_to_mmcif(pdb_tmp, seed_dir / "prediction_seed_42_sample_2_model.cif")
        pdb_tmp.unlink()
        (seed_dir / "prediction_seed_42_sample_2_confidences_aggregated.json").write_text(
            json.dumps({"avg_plddt": 90.0, "ptm": 0.95, "sample_ranking_score": 0.9})
        )

        normalize_openfold_output(raw, tmp_output)

        data = json.loads((tmp_output / "confidence.json").read_text())
        assert data["plddt_mean"] == 90.0
        assert data["ptm"] == 0.95

    def test_missing_output_raises(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_openfold_output

        raw = tmp_path / "raw"
        raw.mkdir()

        with pytest.raises(FileNotFoundError):
            normalize_openfold_output(raw, tmp_output)


class TestNormalizeAlphaFoldOutput:
    def test_normalize(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_alphafold_output

        raw = tmp_path / "raw"
        target_dir = raw / "test_target"
        target_dir.mkdir(parents=True)

        # ranked_0.pdb with B-factors already at 0-100 scale (AF2 convention)
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 85.00           C\n"
            "ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00 72.00           C\n"
            "END\n"
        )
        (target_dir / "ranked_0.pdb").write_text(pdb_content)

        ranking = {
            "plddts": {"model_1": 78.5, "model_2": 75.0},
            "order": ["model_1", "model_2"],
        }
        (target_dir / "ranking_debug.json").write_text(json.dumps(ranking))

        normalize_alphafold_output(raw, tmp_output)

        assert (tmp_output / "model_1.pdb").exists()
        assert (tmp_output / "model_1.cif").exists()
        data = json.loads((tmp_output / "confidence.json").read_text())
        # AF2 mean pLDDT from ranking_debug.json for top model
        assert data["plddt_mean"] == 78.5
        assert data["ptm"] is None
