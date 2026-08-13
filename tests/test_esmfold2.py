"""Tests for the ESMFold2 adapter — spec conversion, command construction, normalization.

Mirrors the style of ``TestESMFoldAdapter`` in ``tests/test_adapters.py``. All
tests are hermetic: no GPU, no network, no real model — they exercise the
conversion / command / normalization logic only.
"""

import json
import logging

import pytest

from predict_structure.entities import EntityList, EntityType


class TestESMFold2Adapter:
    def test_prepare_input_creates_json(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        result = adapter.prepare_input(protein_entity_list, tmp_output)

        assert result.suffix == ".json"
        assert result.name == "input.json"
        assert result.exists()

        data = json.loads(result.read_text())
        assert "sequences" in data
        assert len(data["sequences"]) == 1
        rec = data["sequences"][0]
        assert rec["type"] == "protein"
        assert rec["sequence"].startswith("TTCCPS")
        assert rec["id"]  # chain id assigned during conversion

    def test_prepare_input_multi_entity(self, multi_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        result = adapter.prepare_input(multi_entity_list, tmp_output)

        data = json.loads(result.read_text())
        seqs = data["sequences"]
        assert len(seqs) == 2
        assert seqs[0]["type"] == "protein"
        assert seqs[0]["sequence"] == "MKTIIALSY"
        assert seqs[1]["type"] == "ligand"
        # CCD ligand is rendered as a one-element ccd list
        assert seqs[1]["ccd"] == ["ATP"]

    def test_prepare_input_smiles_ligand(self, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSY", name="protA")
        el.add(EntityType.SMILES, "CCO", name="ethanol")

        adapter = ESMFold2Adapter()
        result = adapter.prepare_input(el, tmp_output)

        seqs = json.loads(result.read_text())["sequences"]
        assert seqs[1]["type"] == "ligand"
        assert seqs[1]["smiles"] == "CCO"
        assert "ccd" not in seqs[1]

    def test_build_command_defaults(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(prepared, tmp_output / "raw")

        # Runner invocation: python -m predict_structure.runners.esmfold2
        assert "predict_structure.runners.esmfold2" in cmd
        assert cmd[cmd.index("-m") + 1] == "predict_structure.runners.esmfold2"
        assert "--spec" in cmd
        assert cmd[cmd.index("--spec") + 1] == str(prepared)
        assert "--output-dir" in cmd
        assert cmd[cmd.index("--output-dir") + 1] == str(tmp_output / "raw")
        # Defaults: num_recycles=3 -> --num-loops, num_samples=5 -> --num-diffusion-samples
        assert cmd[cmd.index("--num-loops") + 1] == "3"
        assert cmd[cmd.index("--num-diffusion-samples") + 1] == "5"
        assert cmd[cmd.index("--num-sampling-steps") + 1] == "50"
        assert cmd[cmd.index("--checkpoint") + 1] == "biohub/ESMFold2"
        # No seed / cpu flag by default
        assert "--seed" not in cmd
        assert "--cpu-only" not in cmd

    def test_build_command_custom(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            num_samples=3, num_recycles=6, seed=42, device="cpu",
            sampling_steps=80, checkpoint="biohub/ESMFold2-mini",
        )

        assert cmd[cmd.index("--num-loops") + 1] == "6"
        assert cmd[cmd.index("--num-diffusion-samples") + 1] == "3"
        assert cmd[cmd.index("--num-sampling-steps") + 1] == "80"
        assert cmd[cmd.index("--checkpoint") + 1] == "biohub/ESMFold2-mini"
        assert cmd[cmd.index("--seed") + 1] == "42"
        assert "--cpu-only" in cmd

    def test_msa_warning(self, protein_entity_list, sample_a3m, tmp_output, caplog):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        with caplog.at_level(logging.WARNING):
            adapter = ESMFold2Adapter()
            adapter.prepare_input(protein_entity_list, tmp_output, msa_path=sample_a3m)

        assert "does not use MSA" in caplog.text

    def test_supported_entities(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        assert EntityType.PROTEIN in adapter.supported_entities
        assert EntityType.DNA in adapter.supported_entities
        assert EntityType.RNA in adapter.supported_entities
        assert EntityType.LIGAND in adapter.supported_entities
        assert EntityType.SMILES in adapter.supported_entities

    def test_validate_entities_ok(self, multi_entity_list):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        adapter.validate_entities(multi_entity_list)  # should not raise

    def test_requires_gpu(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        assert ESMFold2Adapter.requires_gpu is True

    def test_supports_msa_false(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        assert ESMFold2Adapter.supports_msa is False

    def test_preflight(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        pf = ESMFold2Adapter().preflight()
        assert pf["cpu"] == 8
        assert pf["memory"] == "32G"
        assert pf["policy_data"]["partition"] == "gpu2"
        assert pf["policy_data"]["gpu_count"] == 1
        # H200 only: torch+cu130 needs driver >= 580 (#38, #75)
        assert pf["policy_data"]["constraint"] == "H200"

    def test_normalize_output(self, tmp_path, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter
        from predict_structure.converters import pdb_to_mmcif

        raw = tmp_path / "raw"
        raw.mkdir()

        # Build a minimal CIF fixture the way other normalize tests do.
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.91           C\n"
            "ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00  0.88           C\n"
            "END\n"
        )
        pdb_tmp = raw / "temp.pdb"
        pdb_tmp.write_text(pdb_content)
        pdb_to_mmcif(pdb_tmp, raw / "model_1.cif")
        pdb_tmp.unlink()

        # Runner-produced confidence summary; pLDDT on 0-1 scale.
        (raw / "confidence.json").write_text(json.dumps({
            "plddt": 0.895,
            "per_residue_plddt": [0.91, 0.88],
            "ptm": 0.92,
            "iptm": 0.80,
        }))

        adapter = ESMFold2Adapter()
        adapter.normalize_output(raw, tmp_output)

        # Canonical files under predictions/
        assert (tmp_output / "predictions" / "model_1.cif").exists()
        assert (tmp_output / "predictions" / "model_1.pdb").exists()
        conf_path = tmp_output / "predictions" / "confidence.json"
        assert conf_path.exists()
        assert (tmp_output / "raw").exists()
        # Best model promoted to top level
        assert (tmp_output / "model_1.pdb").exists()

        conf = json.loads(conf_path.read_text())
        # pLDDT scaled from 0-1 to 0-100
        assert conf["per_residue_plddt"][0] == 91.0
        assert conf["plddt_mean"] == 89.5
        assert conf["ptm"] == 0.92
        # ipTM persisted alongside the standard confidence file
        assert conf["iptm"] == 0.8

    def test_normalize_output_missing_cif_raises(self, tmp_path, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        raw = tmp_path / "raw"
        raw.mkdir()
        adapter = ESMFold2Adapter()
        with pytest.raises(FileNotFoundError, match="No .cif"):
            adapter.normalize_output(raw, tmp_output)


class TestESMFold2SchedulingContract:
    """Scheduling facts verified by real GPU runs on 2026-08-13 (#75).

    Four predictions in folding_260813.2.sif on coconut (H200) measured a peak
    of 13.9-14.0 GB allocated / 14.1-14.3 GB reserved.
    """

    def test_vram_floor_exceeds_measured_peak(self):
        from predict_structure.adapters.base import BaseAdapter
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        assert adapter.min_gpu_memory_mb > 14_500, (
            "measured peak is ~14 GB; a lower floor lets the GPU precheck pass "
            "a host that will then OOM"
        )
        assert adapter.min_gpu_memory_mb != BaseAdapter.min_gpu_memory_mb, (
            "must not silently inherit the 8000 MiB default"
        )

    def test_constraint_is_h200_only(self):
        """torch+cu130 needs driver >= 580 — only coconut has it (#38)."""
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        constraint = ESMFold2Adapter().preflight()["policy_data"]["constraint"]
        assert constraint == "H200"
        assert "A100" not in constraint, "no A100 host exists in the cluster"

    def test_perl_service_constraint_matches_adapter(self):
        """The Perl carries its own copy; drift would silently misschedule."""
        import re
        from pathlib import Path

        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        perl = (Path(__file__).resolve().parent.parent
                / "service-scripts" / "App-PredictStructure.pl").read_text()
        block = re.search(r'\$tool eq "esmfold2".*?\n    \}', perl, re.S)
        assert block, "esmfold2 preflight block not found in the service script"
        expected = ESMFold2Adapter().preflight()["policy_data"]["constraint"]
        assert f"constraint => '{expected}'" in block.group(0)
