"""Tests for tool-specific adapters — parameter mapping and command construction."""

import pytest
from pathlib import Path

from predict_structure.entities import EntityList, EntityType


class TestBoltzAdapter:
    def test_build_command_defaults(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.boltz import BoltzAdapter

        adapter = BoltzAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(prepared, tmp_output / "raw")

        assert cmd[0].endswith("boltz")
        assert cmd[1] == "predict"
        assert "--diffusion_samples" in cmd
        assert cmd[cmd.index("--diffusion_samples") + 1] == "1"
        assert "--recycling_steps" in cmd
        assert "--output_format" in cmd
        assert cmd[cmd.index("--output_format") + 1] == "mmcif"
        assert "--accelerator" in cmd
        assert cmd[cmd.index("--accelerator") + 1] == "gpu"

    def test_build_command_custom(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.boltz import BoltzAdapter

        adapter = BoltzAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            num_samples=5, num_recycles=10, device="cpu",
            use_msa_server=True, boltz_use_potentials=True,
        )

        assert cmd[cmd.index("--diffusion_samples") + 1] == "5"
        assert cmd[cmd.index("--recycling_steps") + 1] == "10"
        assert cmd[cmd.index("--accelerator") + 1] == "cpu"
        assert "--use_msa_server" in cmd
        assert "--use_potentials" in cmd

    def test_prepare_input_creates_yaml(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.boltz import BoltzAdapter

        adapter = BoltzAdapter()
        result = adapter.prepare_input(protein_entity_list, tmp_output)
        assert result.suffix == ".yaml"
        assert result.exists()

    def test_prepare_input_yaml_passthrough(self, tmp_path, tmp_output):
        from predict_structure.adapters.boltz import BoltzAdapter
        import yaml

        yaml_file = tmp_path / "input.yaml"
        yaml_file.write_text(yaml.dump({"version": 1, "sequences": []}))

        el = EntityList()
        el.add(EntityType.PROTEIN, str(yaml_file), name="yaml_input")

        adapter = BoltzAdapter()
        result = adapter.prepare_input(el, tmp_output)
        assert result == yaml_file

    def test_prepare_input_multi_entity(self, multi_entity_list, tmp_output):
        from predict_structure.adapters.boltz import BoltzAdapter
        import yaml

        adapter = BoltzAdapter()
        result = adapter.prepare_input(multi_entity_list, tmp_output)
        assert result.suffix == ".yaml"

        data = yaml.safe_load(result.read_text())
        assert len(data["sequences"]) == 2
        assert "protein" in data["sequences"][0]
        assert "ligand" in data["sequences"][1]

    def test_supported_entities(self):
        from predict_structure.adapters.boltz import BoltzAdapter

        adapter = BoltzAdapter()
        assert EntityType.PROTEIN in adapter.supported_entities
        assert EntityType.DNA in adapter.supported_entities
        assert EntityType.LIGAND in adapter.supported_entities
        assert EntityType.GLYCAN not in adapter.supported_entities

    def test_validate_entities_ok(self, multi_entity_list):
        from predict_structure.adapters.boltz import BoltzAdapter

        adapter = BoltzAdapter()
        adapter.validate_entities(multi_entity_list)  # should not raise

    def test_preflight(self):
        from predict_structure.adapters.boltz import BoltzAdapter

        pf = BoltzAdapter().preflight()
        assert pf["cpu"] == 8
        assert pf["memory"] == "96G"
        assert "policy_data" in pf


class TestChaiAdapter:
    def test_build_command(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.chai import ChaiAdapter

        adapter = ChaiAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            num_samples=3, num_recycles=5, seed=42,
        )

        assert cmd[0].endswith("chai-lab")
        assert cmd[1] == "fold"
        assert "--num-diffn-samples" in cmd
        assert cmd[cmd.index("--num-diffn-samples") + 1] == "3"
        assert "--num-trunk-recycles" in cmd
        assert cmd[cmd.index("--num-trunk-recycles") + 1] == "5"
        assert "--seed" in cmd
        assert cmd[cmd.index("--seed") + 1] == "42"

    def test_prepare_creates_typed_fasta(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.chai import ChaiAdapter

        adapter = ChaiAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        content = prepared.read_text()
        assert ">protein|name=A" in content

    def test_msa_conversion(self, protein_entity_list, sample_a3m, tmp_output):
        from predict_structure.adapters.chai import ChaiAdapter

        adapter = ChaiAdapter()
        adapter.prepare_input(protein_entity_list, tmp_output, msa_path=sample_a3m)
        assert adapter._msa_dir is not None

        prepared = tmp_output / "input.fasta"
        cmd = adapter.build_command(prepared, tmp_output / "raw")
        assert "--msa-directory" in cmd

    def test_supported_entities(self):
        from predict_structure.adapters.chai import ChaiAdapter

        adapter = ChaiAdapter()
        assert EntityType.PROTEIN in adapter.supported_entities
        assert EntityType.DNA in adapter.supported_entities
        assert EntityType.LIGAND in adapter.supported_entities
        assert EntityType.SMILES not in adapter.supported_entities

    def test_validate_rejects_smiles(self):
        from predict_structure.adapters.chai import ChaiAdapter

        el = EntityList()
        el.add(EntityType.SMILES, "CCO")
        adapter = ChaiAdapter()
        with pytest.raises(ValueError, match="does not support"):
            adapter.validate_entities(el)


class TestAlphaFoldAdapter:
    def test_build_command_falls_back_to_config(self, protein_entity_list, tmp_output):
        """Without --af2-data-dir, adapter falls back to tools.yml data_dir."""
        from predict_structure.adapters.alphafold import AlphaFoldAdapter

        adapter = AlphaFoldAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        # Should not raise -- falls back to get_data_dir("alphafold")
        cmd = adapter.build_command(prepared, tmp_output / "raw")
        assert "--data_dir" in cmd

    def test_build_command_with_data_dir(self, protein_entity_list, tmp_output, tmp_path):
        from predict_structure.adapters.alphafold import AlphaFoldAdapter

        adapter = AlphaFoldAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            af2_data_dir=str(tmp_path / "databases"),
            seed=123,
        )

        assert "run_alphafold.py" in cmd[1]
        assert "--fasta_paths" in cmd
        assert "--data_dir" in cmd
        assert "--uniref90_database_path" in cmd
        assert "--random_seed" in cmd
        assert cmd[cmd.index("--random_seed") + 1] == "123"

    def test_build_command_multimer(self, protein_entity_list, tmp_output, tmp_path):
        from predict_structure.adapters.alphafold import AlphaFoldAdapter

        adapter = AlphaFoldAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            af2_data_dir=str(tmp_path / "databases"),
            af2_model_preset="multimer",
        )

        assert "--pdb_seqres_database_path" in cmd
        assert "--uniprot_database_path" in cmd

    def test_validate_rejects_dna(self, dna_entity_list):
        from predict_structure.adapters.alphafold import AlphaFoldAdapter

        adapter = AlphaFoldAdapter()
        with pytest.raises(ValueError, match="does not support.*dna"):
            adapter.validate_entities(dna_entity_list)


class TestESMFoldAdapter:
    def test_build_command(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold import ESMFoldAdapter

        adapter = ESMFoldAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            num_recycles=8, device="cpu",
        )

        assert cmd[0].endswith("esm-fold-hf")
        assert "-i" in cmd
        assert "-o" in cmd
        assert "--num-recycles" in cmd
        assert cmd[cmd.index("--num-recycles") + 1] == "8"
        assert "--cpu-only" in cmd

    def test_msa_warning(self, protein_entity_list, sample_a3m, tmp_output, caplog):
        from predict_structure.adapters.esmfold import ESMFoldAdapter
        import logging

        with caplog.at_level(logging.WARNING):
            adapter = ESMFoldAdapter()
            adapter.prepare_input(protein_entity_list, tmp_output, msa_path=sample_a3m)

        assert "does not use MSA" in caplog.text

    def test_preflight_no_gpu(self):
        from predict_structure.adapters.esmfold import ESMFoldAdapter

        pf = ESMFoldAdapter().preflight()
        assert "policy_data" not in pf
        assert pf["memory"] == "32G"

    def test_requires_gpu_false(self):
        from predict_structure.adapters.esmfold import ESMFoldAdapter

        assert ESMFoldAdapter.requires_gpu is False

    def test_validate_rejects_ligand(self):
        from predict_structure.adapters.esmfold import ESMFoldAdapter

        el = EntityList()
        el.add(EntityType.LIGAND, "ATP")
        adapter = ESMFoldAdapter()
        with pytest.raises(ValueError, match="does not support"):
            adapter.validate_entities(el)


class TestOpenFoldAdapter:
    def test_build_command_defaults(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        adapter = OpenFoldAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(prepared, tmp_output / "raw")

        assert cmd[0].endswith("run_openfold")
        assert cmd[1] == "predict"
        assert "--query-json" in cmd
        assert "--output-dir" in cmd
        assert "--num-diffusion-samples" in cmd
        assert cmd[cmd.index("--num-diffusion-samples") + 1] == "1"
        assert "--use-msa-server" in cmd

    def test_build_command_custom(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        adapter = OpenFoldAdapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            num_samples=5, num_recycles=3,
            num_diffusion_samples=10, num_model_seeds=3,
            use_msa_server=False, use_templates=False,
            checkpoint="openfold3_p2_v1",
        )

        assert cmd[cmd.index("--num-diffusion-samples") + 1] == "10"
        assert cmd[cmd.index("--num-model-seeds") + 1] == "3"
        assert cmd[cmd.index("--use-msa-server") + 1] == "False"
        assert cmd[cmd.index("--use-templates") + 1] == "False"
        assert "--inference-ckpt-name" in cmd
        assert cmd[cmd.index("--inference-ckpt-name") + 1] == "openfold3_p2_v1"

    def test_prepare_input_creates_json(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.openfold import OpenFoldAdapter
        import json

        adapter = OpenFoldAdapter()
        result = adapter.prepare_input(protein_entity_list, tmp_output)
        assert result.suffix == ".json"
        assert result.exists()

        data = json.loads(result.read_text())
        assert "queries" in data
        chains = data["queries"]["prediction"]["chains"]
        assert len(chains) == 1
        assert chains[0]["molecule_type"] == "protein"

    def test_prepare_input_multi_entity(self, multi_entity_list, tmp_output):
        from predict_structure.adapters.openfold import OpenFoldAdapter
        import json

        adapter = OpenFoldAdapter()
        result = adapter.prepare_input(multi_entity_list, tmp_output)

        data = json.loads(result.read_text())
        chains = data["queries"]["prediction"]["chains"]
        assert len(chains) == 2
        assert chains[0]["molecule_type"] == "protein"
        assert chains[1]["molecule_type"] == "ligand"
        assert chains[1]["ccd_codes"] == ["ATP"]

    def test_supported_entities(self):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        adapter = OpenFoldAdapter()
        assert EntityType.PROTEIN in adapter.supported_entities
        assert EntityType.DNA in adapter.supported_entities
        assert EntityType.RNA in adapter.supported_entities
        assert EntityType.LIGAND in adapter.supported_entities
        assert EntityType.SMILES in adapter.supported_entities
        assert EntityType.GLYCAN not in adapter.supported_entities

    def test_validate_entities_ok(self, multi_entity_list):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        adapter = OpenFoldAdapter()
        adapter.validate_entities(multi_entity_list)  # should not raise

    def test_validate_rejects_glycan(self):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        el = EntityList()
        el.add(EntityType.GLYCAN, "MAN")
        adapter = OpenFoldAdapter()
        with pytest.raises(ValueError, match="does not support"):
            adapter.validate_entities(el)

    def test_preflight(self):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        pf = OpenFoldAdapter().preflight()
        assert pf["cpu"] == 8
        assert pf["memory"] == "96G"
        assert "policy_data" in pf
        assert pf["policy_data"]["gpu_count"] == 1

    def test_requires_gpu(self):
        from predict_structure.adapters.openfold import OpenFoldAdapter

        assert OpenFoldAdapter.requires_gpu is True


class TestAdapterSequenceValidation:
    def test_valid_protein(self, protein_entity_list):
        from predict_structure.adapters.boltz import BoltzAdapter

        adapter = BoltzAdapter()
        adapter.validate_sequences(protein_entity_list)  # should not warn

    def test_dna_as_protein_warns(self, caplog):
        import logging
        from predict_structure.adapters.boltz import BoltzAdapter

        el = EntityList()
        el.add(EntityType.PROTEIN, "ACGTACGTACGTACGT")
        adapter = BoltzAdapter()
        with caplog.at_level(logging.WARNING):
            adapter.validate_sequences(el)
        assert "looks like dna" in caplog.text.lower()

    def test_ligand_skips_validation(self, caplog):
        import logging
        from predict_structure.adapters.boltz import BoltzAdapter

        el = EntityList()
        el.add(EntityType.LIGAND, "ATP")
        adapter = BoltzAdapter()
        with caplog.at_level(logging.WARNING):
            adapter.validate_sequences(el)
        assert caplog.text == ""  # no warnings for ligands


class TestAdapterRegistry:
    def test_get_adapter_all_tools(self):
        from predict_structure.adapters import get_adapter

        for tool in ["boltz", "chai", "alphafold", "esmfold", "openfold"]:
            adapter = get_adapter(tool)
            assert adapter.tool_name == tool

    def test_get_adapter_unknown(self):
        from predict_structure.adapters import get_adapter

        with pytest.raises(ValueError, match="Unknown tool"):
            get_adapter("nonexistent")

    def test_case_insensitive(self):
        from predict_structure.adapters import get_adapter

        adapter = get_adapter("Boltz")
        assert adapter.tool_name == "boltz"
