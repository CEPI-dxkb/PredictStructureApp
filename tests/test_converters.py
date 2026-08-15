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


class TestLigandCodesReachingConverters:
    """#48 — a malformed CCD code can no longer be written into a tool input.

    The converters pass ``Entity.value`` straight through (``ccd:`` in the
    Boltz YAML, ``ccd_codes`` in the OpenFold JSON), so the guard has to be
    upstream: an EntityList carrying a glycan string cannot be built at all.
    """

    def test_glycan_string_cannot_be_put_in_an_entity_list(self):
        el = EntityList()
        with pytest.raises(ValueError, match="linked glycan strings"):
            el.add(EntityType.LIGAND, "NAG(4-1 NAG(4-1 NAG))", format="ccd")
        assert len(el) == 0

    def test_boltz_yaml_gets_the_normalized_code(self, tmp_output):
        import yaml as _yaml

        from predict_structure.converters import entities_to_boltz_yaml

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSYIFCLVFA", name="p")
        el.add(EntityType.LIGAND, "a1h1f", name="a1h1f", format="ccd")
        out = entities_to_boltz_yaml(el, tmp_output / "input.yaml")
        doc = _yaml.safe_load(Path(out).read_text())
        ccds = [s["ligand"]["ccd"] for s in doc["sequences"] if "ligand" in s]
        assert ccds == ["A1H1F"]

    def test_openfold_json_gets_the_normalized_code(self, tmp_output):
        import json as _json

        from predict_structure.converters import entities_to_openfold_json

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSYIFCLVFA", name="p")
        el.add(EntityType.LIGAND, "a1h1f", name="a1h1f", format="ccd")
        out = entities_to_openfold_json(el, tmp_output / "input.json")
        doc = _json.loads(Path(out).read_text())
        text = _json.dumps(doc)
        assert "A1H1F" in text
        assert "a1h1f" not in text


class TestMsaNulSanitization:
    """Regression tests for issue #67: ColabFold MSA trailing NUL bytes."""

    @pytest.fixture
    def nul_a3m(self, tmp_path):
        """A3M file with trailing NUL byte (mimics ColabFold MSA server output)."""
        p = tmp_path / "nul.a3m"
        p.write_bytes(
            b">query\nMKTIIALSYIFCLVFA\n"
            b">hit1\nMKTIIALSYIFCLVFA\n\x00"
        )
        return p

    @pytest.fixture
    def clean_a3m(self, tmp_path):
        """A3M file without NUL bytes."""
        p = tmp_path / "clean.a3m"
        p.write_bytes(
            b">query\nMKTIIALSYIFCLVFA\n"
            b">hit1\nMKTIIALSYIFCLVFA\n"
        )
        return p

    def test_stage_msa_sanitized_strips_trailing_nul(self, nul_a3m, tmp_path):
        from predict_structure.converters import _stage_msa_sanitized

        dest = tmp_path / "staged.a3m"
        _stage_msa_sanitized(nul_a3m, dest)

        raw = dest.read_bytes()
        assert b"\x00" not in raw
        assert raw.endswith(b"\n")

    def test_stage_msa_sanitized_clean_file_unchanged(self, clean_a3m, tmp_path):
        from predict_structure.converters import _stage_msa_sanitized

        dest = tmp_path / "staged.a3m"
        _stage_msa_sanitized(clean_a3m, dest)

        assert dest.read_bytes() == clean_a3m.read_bytes()

    def test_read_a3m_sequences_with_nul(self, nul_a3m):
        from predict_structure.converters import _read_a3m_sequences

        seqs = _read_a3m_sequences(nul_a3m)
        assert len(seqs) == 2
        assert all("\x00" not in s for s in seqs)
        assert seqs[0] == "MKTIIALSY IFCLVFA".replace(" ", "")

    def test_openfold_json_with_nul_msa(self, nul_a3m, tmp_path):
        from predict_structure.converters import entities_to_openfold_json
        import json

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSY IFCLVFA".replace(" ", ""))
        out = tmp_path / "output" / "query.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        entities_to_openfold_json(el, out, msa_path=nul_a3m)

        data = json.loads(out.read_text())
        staged_path = data["queries"]["prediction"]["chains"][0]["main_msa_file_paths"][0]
        staged_bytes = Path(staged_path).read_bytes()
        assert b"\x00" not in staged_bytes

    def test_a3m_depth_with_nul(self, nul_a3m):
        from predict_structure.converters import a3m_depth

        assert a3m_depth(nul_a3m) == 2
