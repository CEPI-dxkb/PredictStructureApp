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
        assert path.parent.name == "predictions", (
            "confidence.json now lives under predictions/ in the unified layout"
        )
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

    def test_per_atom_plddt_empty_omitted(self, tmp_output):
        """Empty per_atom_plddt is treated as absent, not as a length error (#81)."""
        from predict_structure.normalizers import write_confidence_json

        path = write_confidence_json(
            tmp_output, plddt_mean=70.0, ptm=0.5,
            per_residue_plddt=[70.0, 72.0],
            per_atom_plddt=[],
        )
        data = json.loads(path.read_text())
        assert "per_atom_plddt" not in data

    def test_per_atom_shorter_than_per_residue_omitted(self, tmp_output):
        """per_atom_plddt shorter than per_residue logs warning, omits data (#81)."""
        from predict_structure.normalizers import write_confidence_json

        path = write_confidence_json(
            tmp_output, plddt_mean=70.0, ptm=0.5,
            per_residue_plddt=[70.0, 72.0, 68.0],
            per_atom_plddt=[70.1],
        )
        data = json.loads(path.read_text())
        assert "per_atom_plddt" not in data


class TestWriteMetadataJson:
    def test_schema(self, tmp_output):
        from predict_structure.normalizers import write_metadata_json

        path = write_metadata_json(
            tmp_output,
            tool="boltz",
            version="0.1.0",
            tool_version="2.1.0",
            status="success",
            started_at="2026-05-04T14:00:00+00:00",
            completed_at="2026-05-04T14:30:23.4+00:00",
            runtime_seconds=1823.4,
            command=["predict-structure", "boltz", "--protein", "x.fa"],
            container_image="folding_prod.sif",
            backend="subprocess",
            params={"num_samples": 5},
            inputs=[],
        )
        assert path.name == "metadata.json"
        assert path.parent.name == "metadata"
        data = json.loads(path.read_text())
        assert data["schema_version"] == "1.1"
        assert data["tool"] == "boltz"
        assert data["params"]["num_samples"] == 5
        assert data["runtime_seconds"] == 1823.4
        assert data["version"] == "0.1.0"
        assert data["tool_version"] == "2.1.0"
        assert data["status"] == "success"
        assert data["started_at"] == "2026-05-04T14:00:00+00:00"
        assert data["completed_at"] == "2026-05-04T14:30:23.4+00:00"
        assert data["command"] == ["predict-structure", "boltz", "--protein", "x.fa"]
        assert data["container_image"] == "folding_prod.sif"
        assert data["backend"] == "subprocess"
        assert data["inputs"] == []


class TestNormalizeBoltzOutput:
    def test_normalize(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_boltz_output

        # Create mock Boltz raw output
        raw = tmp_path / "raw"
        pred_dir = raw / "predictions" / "test_input"
        pred_dir.mkdir(parents=True)

        # Minimal PDB with 3 residues (matching length of mock plddt array below)
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.91           C\n"
            "ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00  0.88           C\n"
            "ATOM      3  CA  SER A   3       7.000   8.000   9.000  1.00  0.85           C\n"
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

        # Canonical files live under predictions/
        assert (tmp_output / "predictions" / "model_1.cif").exists()
        assert (tmp_output / "predictions" / "model_1.pdb").exists()
        assert (tmp_output / "predictions" / "confidence.json").exists()
        assert (tmp_output / "raw").exists()
        # Best PDB also promoted to top level
        assert (tmp_output / "model_1.pdb").exists()

        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
        # Should be scaled to 0-100
        assert data["per_residue_plddt"][0] == 91.0
        assert data["ptm"] == 0.92

    def test_hetatm_only_structure(self, tmp_path, tmp_output):
        """Boltz + SMILES ligands: all atoms as HETATM still extracts B-factors (#81)."""
        from predict_structure.normalizers import normalize_boltz_output

        raw = tmp_path / "raw"
        pred_dir = raw / "predictions" / "test_input"
        pred_dir.mkdir(parents=True)

        # PDB where protein residues are HETATM (mimics Boltz SMILES output)
        pdb_content = (
            "HETATM    1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.91           C\n"
            "HETATM    2  CA  GLY A   2       4.000   5.000   6.000  1.00  0.88           C\n"
            "END\n"
        )
        pdb_tmp = pred_dir / "temp.pdb"
        pdb_tmp.write_text(pdb_content)
        from predict_structure.converters import pdb_to_mmcif
        cif_file = pred_dir / "test_input_model_0.cif"
        pdb_to_mmcif(pdb_tmp, cif_file)
        pdb_tmp.unlink()

        conf = pred_dir / "confidence_test_input_model_0.json"
        conf.write_text(json.dumps({"ptm": 0.85, "plddt": [0.91, 0.88]}))

        normalize_boltz_output(raw, tmp_output)

        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
        assert data["ptm"] == 0.85
        assert len(data["per_residue_plddt"]) == 2


def _make_boltz_raw(tmp_path, *, pae=None, conf=None, n_res=3, name="test_input"):
    """Build a minimal Boltz raw output tree, optionally with a PAE npz."""
    raw = tmp_path / "raw"
    pred_dir = raw / "predictions" / name
    pred_dir.mkdir(parents=True)

    lines = []
    for i in range(n_res):
        lines.append(
            "ATOM  {:5d}  CA  ALA A{:4d}       1.000   2.000   3.000  1.00  0.90"
            "           C\n".format(i + 1, i + 1)
        )
    (pred_dir / "temp.pdb").write_text("".join(lines) + "END\n")
    from predict_structure.converters import pdb_to_mmcif
    pdb_to_mmcif(pred_dir / "temp.pdb", pred_dir / f"{name}_model_0.cif")
    (pred_dir / "temp.pdb").unlink()

    if conf is None:
        conf = {"ptm": 0.92, "iptm": 0.0, "chains_ptm": {"0": 0.92},
                "plddt": [0.9] * n_res}
    (pred_dir / f"confidence_{name}_model_0.json").write_text(json.dumps(conf))

    if pae is not None:
        np.savez(pred_dir / f"pae_{name}_model_0.npz", pae=np.asarray(pae))

    return raw


class TestWritePaeJson:
    """predictions/pae.json must match protein_compare's PAELoader Format 1."""

    def test_schema_and_rounding(self, tmp_output):
        from predict_structure.normalizers import write_pae_json

        path = write_pae_json(tmp_output, [[0.0, 1.234], [1.236, 0.0]])
        assert path == tmp_output / "predictions" / "pae.json"
        data = json.loads(path.read_text())
        assert data["pae"] == [[0.0, 1.23], [1.24, 0.0]]
        # ptm/iptm are omitted entirely unless the caller supplies them
        assert "ptm" not in data
        assert "iptm" not in data

    def test_max_pae_is_the_fixed_colormap_ceiling(self, tmp_output):
        """max_pae is a render scale, not a statistic of the matrix.

        protein_compare passes it as ``vmax`` to the PAE heatmap; deriving it
        from the data would give every job its own colour scale and make two
        predictions visually incomparable.
        """
        from predict_structure.normalizers import DEFAULT_MAX_PAE, write_pae_json

        data = json.loads(
            write_pae_json(tmp_output, [[0.0, 2.0], [2.0, 0.0]]).read_text()
        )
        assert data["max_pae"] == DEFAULT_MAX_PAE == 31.75
        assert data["max_pae"] != np.max(data["pae"])

    def test_caller_supplied_max_pae_is_honoured(self, tmp_output):
        from predict_structure.normalizers import write_pae_json

        data = json.loads(
            write_pae_json(tmp_output, [[0.0, 2.0], [2.0, 0.0]],
                           max_pae=20.0).read_text()
        )
        assert data["max_pae"] == 20.0

    def test_ptm_and_iptm_written_when_passed(self, tmp_output):
        from predict_structure.normalizers import write_pae_json

        data = json.loads(
            write_pae_json(tmp_output, [[0.0, 1.0], [1.0, 0.0]],
                           ptm=0.87634, iptm=0.4211).read_text()
        )
        assert data["ptm"] == 0.8763
        assert data["iptm"] == 0.4211

    @pytest.mark.parametrize("bad", [
        [1.0, 2.0, 3.0],            # 1-D
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],  # 2x3, not square
        [[]],                        # empty
    ])
    def test_bad_shapes_write_nothing(self, tmp_output, bad):
        """The loader validates nothing (a 1-D or 2x3 matrix loads fine)."""
        from predict_structure.normalizers import write_pae_json

        assert write_pae_json(tmp_output, bad) is None
        assert not (tmp_output / "predictions" / "pae.json").exists()

    def test_over_token_cap_writes_nothing(self, tmp_output, monkeypatch):
        import predict_structure.normalizers as norm

        monkeypatch.setattr(norm, "PAE_MAX_TOKENS", 2)
        assert norm.write_pae_json(tmp_output, np.zeros((3, 3))) is None
        assert not (tmp_output / "predictions" / "pae.json").exists()
        # …and just under the cap still writes
        assert norm.write_pae_json(tmp_output, np.zeros((2, 2))) is not None

    def test_never_writes_a_file_without_the_pae_key(self, tmp_output):
        """A dict lacking "pae" makes PAELoader raise, which aborts the whole
        report (StructureReport calls it unguarded in its constructor)."""
        from predict_structure.normalizers import write_pae_json

        path = write_pae_json(tmp_output, np.zeros((4, 4)), ptm=0.5)
        assert "pae" in json.loads(path.read_text())


class TestPaeLoaderContract:
    """Round-trip our pae.json through the real protein_compare PAELoader.

    Loaded by path: protein_compare is not importable in this env (scipy is
    missing) but parser.py itself needs only json/numpy/Bio. Schema drift here
    is the one failure mode that kills report generation outright.
    """

    PARSER = Path(
        "/home/wilke/Development/protein_structure_analysis/"
        "protein_compare/io/parser.py"
    )

    def _load_parser(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pc_parser", self.PARSER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.mark.skipif(not PARSER.exists(),
                        reason="protein_compare checkout not available")
    def test_round_trip(self, tmp_output):
        from predict_structure.normalizers import write_pae_json

        parser = self._load_parser()
        matrix = np.array([[0.0, 1.5, 3.0], [1.5, 0.0, 2.0], [3.0, 2.0, 0.0]])
        path = write_pae_json(tmp_output, matrix, ptm=0.8763, iptm=0.42)

        pae = parser.PAELoader.load(path)
        assert pae.pae_matrix.shape == (3, 3)
        assert pae.max_pae == 31.75
        assert pae.ptm == pytest.approx(0.8763)
        assert pae.iptm == pytest.approx(0.42)
        assert pae.mean_pae == pytest.approx(float(matrix.mean()))

    @pytest.mark.skipif(not PARSER.exists(),
                        reason="protein_compare checkout not available")
    def test_round_trip_without_scores(self, tmp_output):
        """The monomer case: no iptm key at all must still load."""
        from predict_structure.normalizers import write_pae_json

        parser = self._load_parser()
        path = write_pae_json(tmp_output, np.zeros((2, 2)))
        pae = parser.PAELoader.load(path)
        assert pae.ptm is None and pae.iptm is None
        assert pae.max_pae == 31.75


class TestBoltzPaeConversion:
    """Boltz emits pae_*.npz and never a JSON — this is why the report has
    never received a PAE matrix (issue #50)."""

    def test_pae_npz_converted(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_boltz_output

        matrix = np.array([[0.0, 1.111, 2.0],
                           [1.111, 0.0, 3.0],
                           [2.0, 3.0, 0.0]], dtype=np.float32)
        raw = _make_boltz_raw(tmp_path, pae=matrix)
        normalize_boltz_output(raw, tmp_output)

        data = json.loads((tmp_output / "predictions" / "pae.json").read_text())
        assert len(data["pae"]) == 3 and len(data["pae"][0]) == 3
        assert data["pae"][0][1] == 1.11
        assert data["max_pae"] == 31.75
        assert data["ptm"] == 0.92

    def test_iptm_omitted_for_monomer(self, tmp_path, tmp_output):
        """Boltz writes iptm 0.0 for a single chain; surfacing it would show a
        misleading "ipTM 0.00" box in the report."""
        from predict_structure.normalizers import normalize_boltz_output

        raw = _make_boltz_raw(
            tmp_path, pae=np.zeros((3, 3)),
            conf={"ptm": 0.92, "iptm": 0.0, "chains_ptm": {"0": 0.92},
                  "plddt": [0.9, 0.9, 0.9]},
        )
        normalize_boltz_output(raw, tmp_output)
        data = json.loads((tmp_output / "predictions" / "pae.json").read_text())
        assert "iptm" not in data

    def test_iptm_included_for_multimer(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_boltz_output

        raw = _make_boltz_raw(
            tmp_path, pae=np.zeros((3, 3)),
            conf={"ptm": 0.92, "iptm": 0.71,
                  "chains_ptm": {"0": 0.92, "1": 0.88},
                  "plddt": [0.9, 0.9, 0.9]},
        )
        normalize_boltz_output(raw, tmp_output)
        data = json.loads((tmp_output / "predictions" / "pae.json").read_text())
        assert data["iptm"] == 0.71

    def test_no_pae_npz_is_not_fatal(self, tmp_path, tmp_output):
        """Regression guard: tools without PAE must still normalize."""
        from predict_structure.normalizers import normalize_boltz_output

        raw = _make_boltz_raw(tmp_path, pae=None)
        normalize_boltz_output(raw, tmp_output)
        assert (tmp_output / "predictions" / "confidence.json").exists()
        assert not (tmp_output / "predictions" / "pae.json").exists()

    def test_token_count_mismatch_warns_but_writes(self, tmp_path, tmp_output, caplog):
        """protein_compare never cross-checks PAE size against the structure —
        a mismatch yields wrong axis labels, not a crash. Warn, don't fail."""
        import logging

        from predict_structure.normalizers import normalize_boltz_output

        raw = _make_boltz_raw(tmp_path, pae=np.zeros((5, 5)), n_res=3)
        with caplog.at_level(logging.WARNING):
            normalize_boltz_output(raw, tmp_output)
        assert (tmp_output / "predictions" / "pae.json").exists()
        assert any("pLDDT tokens" in r.getMessage() for r in caplog.records)

    def test_over_cap_skips_but_normalization_succeeds(self, tmp_path, tmp_output,
                                                       monkeypatch):
        import predict_structure.normalizers as norm

        monkeypatch.setattr(norm, "PAE_MAX_TOKENS", 2)
        raw = _make_boltz_raw(tmp_path, pae=np.zeros((3, 3)))
        norm.normalize_boltz_output(raw, tmp_output)
        assert (tmp_output / "predictions" / "confidence.json").exists()
        assert not (tmp_output / "predictions" / "pae.json").exists()

    def test_pae_reaches_results_json(self, tmp_path, tmp_output):
        """End-to-end: normalize a run WITH a pae npz, then check the file is
        listed in the results.json outputs map that UIs consume."""
        from predict_structure.normalizers import (
            normalize_boltz_output,
            write_metadata_json,
        )
        from predict_structure.results import write_results_json

        raw = _make_boltz_raw(tmp_path, pae=np.zeros((3, 3)))
        normalize_boltz_output(raw, tmp_output)
        write_metadata_json(
            tmp_output, tool="boltz", version="0.1.0", tool_version="2.1.0",
            status="success", started_at="2026-05-04T14:00:00+00:00",
            completed_at="2026-05-04T14:30:00+00:00", runtime_seconds=1800.0,
            command=["predict-structure", "boltz"], container_image=None,
            backend="subprocess", params={}, inputs=[],
        )
        data = json.loads(write_results_json(tmp_output).read_text())
        names = [e["basename"] for e in data["outputs"]["predictions"]["listing"]]
        assert "pae.json" in names


class TestPerlReportContract:
    """The Perl must hand protein_compare the normalized pae.json."""

    def _run_report(self):
        import re

        perl = (Path(__file__).resolve().parent.parent
                / "service-scripts" / "App-PredictStructure.pl").read_text()
        block = re.search(r"sub run_report \{.*?\n\}", perl, re.S)
        assert block, "run_report not found in the service script"
        return block.group(0)

    def test_prefers_normalized_pae_json(self):
        import re

        body = self._run_report()
        # The --pae flag must be pushed from the branch that tested for
        # predictions/pae.json, not only from the raw-output scan.
        m = re.search(
            r'\$output_dir/predictions/pae\.json.*?push \@cmd, "--pae"',
            body, re.S,
        )
        assert m, "run_report does not push --pae for predictions/pae.json"
        # …and the two must be close together (same if-block), not merely
        # both present somewhere in the sub.
        assert m.group(0).count("push @cmd") == 1


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

        assert (tmp_output / "predictions" / "model_1.pdb").exists()
        assert (tmp_output / "model_1.pdb").exists()  # top-level copy
        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
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

        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
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

        assert (tmp_output / "predictions" / "model_1.cif").exists()
        assert (tmp_output / "predictions" / "model_1.pdb").exists()
        assert (tmp_output / "predictions" / "confidence.json").exists()
        assert (tmp_output / "raw").exists()
        assert (tmp_output / "model_1.pdb").exists()  # promoted

        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
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

        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
        assert data["plddt_mean"] == 90.0
        assert data["ptm"] == 0.95

    def test_missing_output_raises(self, tmp_path, tmp_output):
        from predict_structure.normalizers import normalize_openfold_output

        raw = tmp_path / "raw"
        raw.mkdir()

        with pytest.raises(FileNotFoundError):
            normalize_openfold_output(raw, tmp_output)


class TestStageInputs:
    def test_file_input_descriptor(self, tmp_path, tmp_output):
        """File-backed Entity becomes one descriptor with source/staged/checksum."""
        from predict_structure.entities import EntityList, EntityType
        from predict_structure.normalizers import stage_inputs

        fasta = tmp_path / "demo.fasta"
        fasta.write_text(">chain_A\nMKTLV\n")

        el = EntityList()
        el.add(
            EntityType.PROTEIN, "MKTLV", name="chain_A",
            source_path=fasta, format="fasta",
        )

        descriptors = stage_inputs(el, None, tmp_output)
        assert len(descriptors) == 1
        d = descriptors[0]
        assert d["kind"] == "protein"
        assert d["name"] == "demo"
        assert d["source"] == str(fasta)
        assert d["staged"] == "inputs/demo.fasta"
        assert d["checksum"].startswith("sha256$")
        assert d["size"] > 0
        assert d["length"] == 5
        assert d["format"] == "fasta"
        # File copied
        assert (tmp_output / "inputs" / "demo.fasta").is_file()

    def test_inline_entity_descriptor(self, tmp_output):
        """Ligand CCD code becomes a value-only descriptor with no file fields."""
        from predict_structure.entities import EntityList, EntityType
        from predict_structure.normalizers import stage_inputs

        el = EntityList()
        el.add(EntityType.LIGAND, "ATP", name="ATP", format="ccd")

        descriptors = stage_inputs(el, None, tmp_output)
        assert len(descriptors) == 1
        d = descriptors[0]
        assert d["kind"] == "ligand"
        assert d["value"] == "ATP"
        assert d["format"] == "ccd"
        assert "source" not in d
        assert "staged" not in d
        assert "checksum" not in d

    def test_msa_descriptor(self, tmp_path, tmp_output):
        """MSA file gets staged with depth annotation when a3m."""
        from predict_structure.entities import EntityList
        from predict_structure.normalizers import stage_inputs

        msa = tmp_path / "demo.a3m"
        msa.write_text(">seq1\nMKTLV\n>seq2\nMKTLA\n>seq3\nMKTLG\n")

        descriptors = stage_inputs(EntityList(), msa, tmp_output)
        assert len(descriptors) == 1
        d = descriptors[0]
        assert d["kind"] == "msa"
        assert d["staged"] == "inputs/demo.a3m"
        assert d["format"] == "a3m"
        assert d["depth"] == 3
        assert (tmp_output / "inputs" / "demo.a3m").is_file()

    def test_multi_chain_fasta_groups_into_one(self, tmp_path, tmp_output):
        """Multi-chain FASTA → one descriptor with sequences[] breakdown."""
        from predict_structure.entities import EntityList, EntityType
        from predict_structure.normalizers import stage_inputs

        fasta = tmp_path / "complex.fasta"
        fasta.write_text(">chain_A\nMKTLV\n>chain_B\nGGSST\n")

        el = EntityList()
        for name, seq in [("chain_A", "MKTLV"), ("chain_B", "GGSST")]:
            el.add(
                EntityType.PROTEIN, seq, name=name,
                source_path=fasta, format="fasta",
            )

        descriptors = stage_inputs(el, None, tmp_output)
        # One descriptor for the file, two sequences inside
        file_descs = [d for d in descriptors if "staged" in d]
        assert len(file_descs) == 1
        d = file_descs[0]
        assert "sequences" in d
        assert len(d["sequences"]) == 2
        assert {s["name"] for s in d["sequences"]} == {"chain_A", "chain_B"}


class TestMetadataLayout:
    def test_metadata_lands_in_metadata_subdir(self, tmp_output):
        """write_metadata_json places the file under metadata/, not at top."""
        from predict_structure.normalizers import write_metadata_json

        path = write_metadata_json(
            tmp_output,
            tool="boltz",
            version="0.2.0",
            runtime_seconds=10.5,
            command=[],
            params={"num_samples": 1},
        )
        assert path == tmp_output / "metadata" / "metadata.json"
        assert not (tmp_output / "metadata.json").exists(), (
            "metadata.json should NOT be at top level"
        )


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

        assert (tmp_output / "predictions" / "model_1.pdb").exists()
        assert (tmp_output / "predictions" / "model_1.cif").exists()
        assert (tmp_output / "model_1.pdb").exists()  # promoted to top level
        data = json.loads((tmp_output / "predictions" / "confidence.json").read_text())
        # AF2 mean pLDDT from ranking_debug.json for top model
        assert data["plddt_mean"] == 78.5
        assert data["ptm"] is None
