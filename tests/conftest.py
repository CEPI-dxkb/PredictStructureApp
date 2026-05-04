"""Shared test fixtures."""

from pathlib import Path

import pytest

from predict_structure.entities import EntityList, EntityType

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def sample_fasta(tmp_path):
    """Create a simple single-sequence FASTA file."""
    fasta = tmp_path / "test.fasta"
    fasta.write_text(">1CRN|Crambin|46 residues\nTTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN\n")
    return fasta


@pytest.fixture
def multi_chain_fasta(tmp_path):
    """Create a multi-chain FASTA file."""
    fasta = tmp_path / "multi.fasta"
    fasta.write_text(
        ">chainA\nMKTIIALSYIFCLVFA\n"
        ">chainB\nGIVLAAVLLLLVAGSS\n"
    )
    return fasta


@pytest.fixture
def dna_fasta(tmp_path):
    """Create a DNA FASTA file."""
    fasta = tmp_path / "dna.fasta"
    fasta.write_text(">dna_seq\nACGTACGTACGTACGTACGT\n")
    return fasta


@pytest.fixture
def rna_fasta(tmp_path):
    """Create an RNA FASTA file."""
    fasta = tmp_path / "rna.fasta"
    fasta.write_text(">rna_seq\nAUGCAUGCAUGCAUGC\n")
    return fasta


@pytest.fixture
def sample_a3m(tmp_path):
    """Create a simple A3M alignment file."""
    a3m = tmp_path / "test.a3m"
    a3m.write_text(
        ">query\nTTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN\n"
        ">hit1\nTTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN\n"
        ">hit2\nTTCCASIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN\n"
    )
    return a3m


@pytest.fixture
def tmp_output(tmp_path):
    """Create and return a temporary output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def protein_entity_list():
    """Create an EntityList with a single protein."""
    el = EntityList()
    el.add(EntityType.PROTEIN, "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN", name="crambin")
    return el


@pytest.fixture
def multi_entity_list():
    """Create an EntityList with protein + ligand."""
    el = EntityList()
    el.add(EntityType.PROTEIN, "MKTIIALSY", name="protA")
    el.add(EntityType.LIGAND, "ATP", name="ATP")
    return el


@pytest.fixture
def dna_entity_list():
    """Create an EntityList with a DNA sequence."""
    el = EntityList()
    el.add(EntityType.DNA, "ACGTACGTACGTACGTACGT", name="dna_seq")
    return el


@pytest.fixture
def sample_job_yaml(tmp_path, sample_fasta):
    """Create a sample job YAML file."""
    import yaml
    jobs = [
        {
            "protein": [str(sample_fasta)],
            "options": {"debug": True},
        },
        {
            "protein": [str(sample_fasta)],
            "ligands": ["ATP"],
            "tool": "boltz",
            "options": {"debug": True},
        },
    ]
    job_file = tmp_path / "jobs.yaml"
    job_file.write_text(yaml.dump(jobs))
    return job_file
