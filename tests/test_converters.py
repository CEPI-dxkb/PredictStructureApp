"""Tests for format conversion functions."""

import pytest
from pathlib import Path

from predict_structure.entities import EntityList, EntityType


class TestFastaToBoltzYaml:
    def test_single_chain(self, sample_fasta, tmp_output):
        from predict_structure.converters import fasta_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        result = fasta_to_boltz_yaml(sample_fasta, out)
        assert result == out
        assert out.exists()

        data = yaml.safe_load(out.read_text())
        assert data["version"] == 1
        assert len(data["sequences"]) == 1
        assert data["sequences"][0]["protein"]["id"] == "A"
        assert "TTCCPSIVAR" in data["sequences"][0]["protein"]["sequence"]

    def test_multi_chain(self, multi_chain_fasta, tmp_output):
        from predict_structure.converters import fasta_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        fasta_to_boltz_yaml(multi_chain_fasta, out)

        data = yaml.safe_load(out.read_text())
        assert len(data["sequences"]) == 2
        assert data["sequences"][0]["protein"]["id"] == "A"
        assert data["sequences"][1]["protein"]["id"] == "B"

    def test_with_msa(self, sample_fasta, tmp_output, sample_a3m):
        from predict_structure.converters import fasta_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        fasta_to_boltz_yaml(sample_fasta, out, msa_path=sample_a3m)

        data = yaml.safe_load(out.read_text())
        assert "msa" in data["sequences"][0]["protein"]
        assert str(sample_a3m) in data["sequences"][0]["protein"]["msa"]

    def test_empty_fasta(self, tmp_path, tmp_output):
        empty = tmp_path / "empty.fasta"
        empty.write_text("")
        from predict_structure.converters import fasta_to_boltz_yaml

        with pytest.raises(ValueError, match="No sequences"):
            fasta_to_boltz_yaml(empty, tmp_output / "out.yaml")


class TestA3mToParquet:
    def test_fallback_parse(self, sample_a3m, tmp_output):
        """Test manual A3M parsing fallback (no chai CLI available)."""
        from predict_structure.converters import a3m_to_parquet
        import pandas as pd

        out = tmp_output / "test.aligned.pqt"
        result = a3m_to_parquet(sample_a3m, out)
        assert result == out
        assert out.exists()

        df = pd.read_parquet(str(out))
        assert "sequence" in df.columns
        assert len(df) == 3  # query + 2 hits


class TestStructureConversion:
    """Test mmCIF ↔ PDB round-trip using a minimal PDB."""

    @pytest.fixture
    def minimal_pdb(self, tmp_path):
        """Create a minimal valid PDB file with one CA atom."""
        pdb = tmp_path / "minimal.pdb"
        pdb.write_text(
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.50           C\n"
            "END\n"
        )
        return pdb

    def test_pdb_to_mmcif(self, minimal_pdb, tmp_output):
        from predict_structure.converters import pdb_to_mmcif

        cif = tmp_output / "out.cif"
        result = pdb_to_mmcif(minimal_pdb, cif)
        assert result == cif
        assert cif.exists()
        content = cif.read_text()
        assert "loop_" in content or "data_" in content

    def test_mmcif_to_pdb(self, minimal_pdb, tmp_output):
        from predict_structure.converters import pdb_to_mmcif, mmcif_to_pdb

        cif = tmp_output / "out.cif"
        pdb_to_mmcif(minimal_pdb, cif)

        pdb_back = tmp_output / "back.pdb"
        result = mmcif_to_pdb(cif, pdb_back)
        assert result == pdb_back
        assert pdb_back.exists()
        assert "ATOM" in pdb_back.read_text()


class TestEntitiesToBoltzYaml:
    def test_single_protein(self, protein_entity_list, tmp_output):
        from predict_structure.converters import entities_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        result = entities_to_boltz_yaml(protein_entity_list, out)
        assert result == out
        assert out.exists()

        data = yaml.safe_load(out.read_text())
        assert data["version"] == 1
        assert len(data["sequences"]) == 1
        assert "protein" in data["sequences"][0]
        assert data["sequences"][0]["protein"]["id"] == "A"

    def test_protein_with_ligand(self, multi_entity_list, tmp_output):
        from predict_structure.converters import entities_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        entities_to_boltz_yaml(multi_entity_list, out)

        data = yaml.safe_load(out.read_text())
        assert len(data["sequences"]) == 2
        assert "protein" in data["sequences"][0]
        assert "ligand" in data["sequences"][1]
        assert data["sequences"][1]["ligand"]["ccd"] == "ATP"

    def test_with_msa(self, protein_entity_list, tmp_output, sample_a3m):
        from predict_structure.converters import entities_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        entities_to_boltz_yaml(protein_entity_list, out, msa_path=sample_a3m)

        data = yaml.safe_load(out.read_text())
        assert "msa" in data["sequences"][0]["protein"]

    def test_dna_entity(self, dna_entity_list, tmp_output):
        from predict_structure.converters import entities_to_boltz_yaml
        import yaml

        out = tmp_output / "input.yaml"
        entities_to_boltz_yaml(dna_entity_list, out)

        data = yaml.safe_load(out.read_text())
        assert "dna" in data["sequences"][0]

    def test_smiles_entity(self, tmp_output):
        from predict_structure.converters import entities_to_boltz_yaml
        import yaml

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.SMILES, "CCO")
        out = tmp_output / "input.yaml"
        entities_to_boltz_yaml(el, out)

        data = yaml.safe_load(out.read_text())
        assert "ligand" in data["sequences"][1]
        assert data["sequences"][1]["ligand"]["smiles"] == "CCO"


class TestEntitiesToOpenFoldJson:
    def test_single_protein(self, protein_entity_list, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        out = tmp_output / "query.json"
        result = entities_to_openfold_json(protein_entity_list, out)
        assert result == out
        assert out.exists()

        data = json.loads(out.read_text())
        assert "queries" in data
        chains = data["queries"]["prediction"]["chains"]
        assert len(chains) == 1
        assert chains[0]["molecule_type"] == "protein"
        assert chains[0]["chain_ids"] == "A"
        assert "TTCCPSIVAR" in chains[0]["sequence"]
        assert data["queries"]["prediction"]["use_msas"] is True

    def test_protein_with_ligand(self, multi_entity_list, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        out = tmp_output / "query.json"
        entities_to_openfold_json(multi_entity_list, out)

        data = json.loads(out.read_text())
        chains = data["queries"]["prediction"]["chains"]
        assert len(chains) == 2
        assert chains[0]["molecule_type"] == "protein"
        assert chains[1]["molecule_type"] == "ligand"
        assert chains[1]["ccd_codes"] == ["ATP"]

    def test_dna_entity(self, dna_entity_list, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        out = tmp_output / "query.json"
        entities_to_openfold_json(dna_entity_list, out)

        data = json.loads(out.read_text())
        chains = data["queries"]["prediction"]["chains"]
        assert chains[0]["molecule_type"] == "dna"

    def test_smiles_entity(self, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.SMILES, "CCO")
        out = tmp_output / "query.json"
        entities_to_openfold_json(el, out)

        data = json.loads(out.read_text())
        chains = data["queries"]["prediction"]["chains"]
        assert chains[1]["molecule_type"] == "ligand"
        assert chains[1]["smiles"] == "CCO"

    def test_glycan_raises(self, tmp_output):
        from predict_structure.converters import entities_to_openfold_json

        el = EntityList()
        el.add(EntityType.GLYCAN, "MAN")
        with pytest.raises(ValueError, match="OpenFold 3 does not yet support glycan"):
            entities_to_openfold_json(el, tmp_output / "query.json")

    def test_with_msa(self, protein_entity_list, sample_a3m, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        out = tmp_output / "query.json"
        entities_to_openfold_json(protein_entity_list, out, msa_path=sample_a3m)

        data = json.loads(out.read_text())
        chains = data["queries"]["prediction"]["chains"]
        assert "main_msa_file_paths" in chains[0]
        # OpenFold 3 requires recognized MSA filenames (from aln_order).
        # The converter stages the file as colabfold_main.<ext>.
        staged_path = chains[0]["main_msa_file_paths"][0]
        assert "colabfold_main" in staged_path
        assert staged_path.endswith(sample_a3m.suffix)
        # Verify staged file exists and matches original content
        from pathlib import Path
        assert Path(staged_path).read_text() == sample_a3m.read_text()

    def test_no_msa_server(self, protein_entity_list, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        out = tmp_output / "query.json"
        entities_to_openfold_json(protein_entity_list, out, use_msas=False)

        data = json.loads(out.read_text())
        chains = data["queries"]["prediction"]["chains"]
        assert data["queries"]["prediction"]["use_msas"] is False

    def test_custom_query_name(self, protein_entity_list, tmp_output):
        from predict_structure.converters import entities_to_openfold_json
        import json

        out = tmp_output / "query.json"
        entities_to_openfold_json(protein_entity_list, out, query_name="my_query")

        data = json.loads(out.read_text())
        assert "my_query" in data["queries"]


class TestEntitiesToChaiFasta:
    def test_single_protein(self, protein_entity_list, tmp_output):
        from predict_structure.converters import entities_to_chai_fasta

        out = tmp_output / "input.fasta"
        result = entities_to_chai_fasta(protein_entity_list, out)
        assert result == out
        assert out.exists()

        content = out.read_text()
        assert ">protein|name=A" in content
        assert "TTCCPSIVAR" in content

    def test_protein_with_ligand(self, multi_entity_list, tmp_output):
        from predict_structure.converters import entities_to_chai_fasta

        out = tmp_output / "input.fasta"
        entities_to_chai_fasta(multi_entity_list, out)

        content = out.read_text()
        assert ">protein|name=A" in content
        assert ">ligand|name=B" in content
        assert "ATP" in content

    def test_dna_entity(self, tmp_output):
        from predict_structure.converters import entities_to_chai_fasta

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.DNA, "ACGTACGT")
        out = tmp_output / "input.fasta"
        entities_to_chai_fasta(el, out)

        content = out.read_text()
        assert ">protein|name=A" in content
        assert ">dna|name=B" in content


class TestEntitiesToFasta:
    def test_protein_only(self, protein_entity_list, tmp_output):
        from predict_structure.converters import entities_to_fasta

        out = tmp_output / "input.fasta"
        result = entities_to_fasta(protein_entity_list, out)
        assert result == out
        assert out.exists()

        content = out.read_text()
        assert ">crambin" in content
        assert "TTCCPSIVAR" in content

    def test_skips_inline_entities(self, multi_entity_list, tmp_output):
        from predict_structure.converters import entities_to_fasta

        out = tmp_output / "input.fasta"
        entities_to_fasta(multi_entity_list, out)

        content = out.read_text()
        assert "MKTIIAL" in content
        assert "ATP" not in content

    def test_no_fasta_entities_raises(self, tmp_output):
        from predict_structure.converters import entities_to_fasta

        el = EntityList()
        el.add(EntityType.LIGAND, "ATP")
        with pytest.raises(ValueError, match="No sequence entities"):
            entities_to_fasta(el, tmp_output / "input.fasta")
