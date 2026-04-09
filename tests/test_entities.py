"""Tests for entity data model, sequence detection, and FASTA parsing."""

import pytest
from pathlib import Path

from predict_structure.entities import (
    Entity,
    EntityList,
    EntityType,
    detect_sequence_type,
    is_boltz_yaml,
    parse_fasta_entities,
)


class TestDetectSequenceType:
    def test_protein(self):
        assert detect_sequence_type("MKTIIALSY") == EntityType.PROTEIN

    def test_protein_long_mixed(self):
        # Has amino acids beyond ACGTN
        assert detect_sequence_type("MKTIIALSYNFNVCRLPGTPEALCAT") == EntityType.PROTEIN

    def test_dna_long(self):
        assert detect_sequence_type("ACGTACGTACGTACGT") == EntityType.DNA

    def test_dna_with_n(self):
        assert detect_sequence_type("ACGTNNNNACGTACGT") == EntityType.DNA

    def test_dna_short_is_protein(self):
        # Short ACGT-only is classified as protein (ambiguous)
        assert detect_sequence_type("ACGT") == EntityType.PROTEIN

    def test_rna(self):
        assert detect_sequence_type("ACGUACGU") == EntityType.RNA

    def test_rna_no_t(self):
        # U present, no T → RNA
        assert detect_sequence_type("AUGCAUGCAUGC") == EntityType.RNA

    def test_whitespace_ignored(self):
        assert detect_sequence_type("ACGT ACGT ACGT ACGT") == EntityType.DNA


class TestEntity:
    def test_defaults(self):
        e = Entity(entity_type=EntityType.PROTEIN, value="MKTIIAL")
        assert e.entity_type == EntityType.PROTEIN
        assert e.value == "MKTIIAL"
        assert e.chain_id == ""
        assert e.name == ""


class TestEntityList:
    def test_add_and_chain_ids(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.LIGAND, "ATP")
        assert len(el) == 2
        assert el.entities[0].chain_id == "A"
        assert el.entities[1].chain_id == "B"

    def test_entity_types(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.LIGAND, "ATP")
        el.add(EntityType.PROTEIN, "ACDE")
        assert el.entity_types == {EntityType.PROTEIN, EntityType.LIGAND}

    def test_fasta_entities(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.LIGAND, "ATP")
        el.add(EntityType.DNA, "ACGTACGTACGTACGT")
        fasta = el.fasta_entities()
        assert len(fasta) == 2
        assert all(e.entity_type in (EntityType.PROTEIN, EntityType.DNA) for e in fasta)

    def test_inline_entities(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.LIGAND, "ATP")
        el.add(EntityType.SMILES, "CCO")
        inline = el.inline_entities()
        assert len(inline) == 2
        assert all(e.entity_type in (EntityType.LIGAND, EntityType.SMILES) for e in inline)

    def test_empty_is_falsy(self):
        el = EntityList()
        assert not el

    def test_nonempty_is_truthy(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        assert el

    def test_iter(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.LIGAND, "ATP")
        items = list(el)
        assert len(items) == 2


class TestParseFastaEntities:
    def test_single_protein(self, sample_fasta):
        entities = parse_fasta_entities(sample_fasta)
        assert len(entities) == 1
        assert entities[0].entity_type == EntityType.PROTEIN
        assert "TTCCPSIVAR" in entities[0].value

    def test_multi_chain(self, multi_chain_fasta):
        entities = parse_fasta_entities(multi_chain_fasta)
        assert len(entities) == 2

    def test_explicit_dna_type(self, sample_fasta):
        entities = parse_fasta_entities(sample_fasta, explicit_type=EntityType.DNA)
        assert all(e.entity_type == EntityType.DNA for e in entities)

    def test_empty_fasta_raises(self, tmp_path):
        empty = tmp_path / "empty.fasta"
        empty.write_text("")
        with pytest.raises(ValueError, match="No sequences"):
            parse_fasta_entities(empty)

    def test_auto_detect_dna(self, tmp_path):
        dna_fasta = tmp_path / "dna.fasta"
        dna_fasta.write_text(">dna_seq\nACGTACGTACGTACGT\n")
        entities = parse_fasta_entities(dna_fasta)
        assert entities[0].entity_type == EntityType.DNA

    def test_max_sequences_exceeded(self, tmp_path):
        fasta = tmp_path / "many.fasta"
        seqs = "".join(f">seq_{i}\nMKTIIAL\n" for i in range(30))
        fasta.write_text(seqs)
        with pytest.raises(ValueError, match="30.*sequences.*limit.*26"):
            parse_fasta_entities(fasta)

    def test_max_sequences_at_limit(self, tmp_path):
        fasta = tmp_path / "ok.fasta"
        seqs = "".join(f">seq_{i}\nMKTIIAL\n" for i in range(26))
        fasta.write_text(seqs)
        entities = parse_fasta_entities(fasta)
        assert len(entities) == 26

    def test_max_sequences_none_bypasses(self, tmp_path):
        fasta = tmp_path / "many.fasta"
        seqs = "".join(f">seq_{i}\nMKTIIAL\n" for i in range(100))
        fasta.write_text(seqs)
        entities = parse_fasta_entities(fasta, max_sequences=None)
        assert len(entities) == 100

    def test_type_mismatch_warning(self, tmp_path, caplog):
        """DNA sequences submitted as protein should log a warning."""
        import logging
        fasta = tmp_path / "dna_as_protein.fasta"
        fasta.write_text(">read1\nACGTACGTACGTACGTACGT\n")
        with caplog.at_level(logging.WARNING):
            entities = parse_fasta_entities(fasta, explicit_type=EntityType.PROTEIN)
        assert entities[0].entity_type == EntityType.PROTEIN  # type forced
        assert "appears to be dna but was declared as protein" in caplog.text.lower()


class TestEntityListValidation:
    def test_total_residues(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")     # 7
        el.add(EntityType.LIGAND, "ATP")            # skipped
        el.add(EntityType.DNA, "ACGTACGTACGT")      # 12
        assert el.total_residues == 19

    def test_validate_size_ok(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.validate_size(max_residues=100)  # should not raise

    def test_validate_size_exceeded(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "M" * 500)
        with pytest.raises(ValueError, match="500.*exceeds.*100"):
            el.validate_size(max_residues=100)

    def test_validate_size_none_bypasses(self):
        el = EntityList()
        el.add(EntityType.PROTEIN, "M" * 100_000)
        el.validate_size(max_residues=None)  # should not raise


class TestIsBoltzYaml:
    def test_valid_boltz_yaml(self, tmp_path):
        import yaml
        yaml_file = tmp_path / "input.yaml"
        yaml_file.write_text(yaml.dump({"version": 1, "sequences": []}))
        assert is_boltz_yaml(yaml_file) is True

    def test_plain_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n")
        assert is_boltz_yaml(yaml_file) is False

    def test_non_yaml_extension(self, tmp_path):
        txt_file = tmp_path / "input.txt"
        txt_file.write_text("version: 1\nsequences: []\n")
        assert is_boltz_yaml(txt_file) is False

    def test_nonexistent_file(self, tmp_path):
        assert is_boltz_yaml(tmp_path / "missing.yaml") is False
