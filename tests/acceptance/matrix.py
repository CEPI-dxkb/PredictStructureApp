"""Test matrix definitions for acceptance tests.

Defines the tool x input_type x parameter combinations. MSA server is excluded --
only 'none' and 'file' MSA modes. All execution is inside the container.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

# --- Container-side test data paths (bind-mounted from test_data/) ---
PROTEIN_FASTA = "/data/simple_protein.fasta"
MULTIMER_FASTA = "/data/multimer.fasta"
DNA_FASTA = "/data/dna.fasta"
RNA_FASTA = "/data/rna.fasta"
MSA_FILE = "/data/msa/crambin.a3m"

# Crambin has 46 residues
CRAMBIN_RESIDUES = 46


@dataclass
class ToolTestCase:
    """A single cell in the acceptance testing matrix."""

    tool: str
    input_type: str
    entity_args: list[str]
    extra_args: list[str] = field(default_factory=list)
    xfail_reason: str | None = None
    timeout: int = 600
    expected_residues: int | None = None

    @property
    def test_id(self) -> str:
        return f"{self.tool}-{self.input_type}"

    def as_param(self):
        """Convert to a pytest.param with appropriate marks."""
        marks = []
        if self.xfail_reason:
            marks.append(pytest.mark.xfail(reason=self.xfail_reason, strict=True))
        if self.timeout > 300:
            marks.append(pytest.mark.slow)
        return pytest.param(self, id=self.test_id, marks=marks)


# ---------------------------------------------------------------------------
# Phase 1 & 2: Tool x Input Type Matrix
# No MSA server -- only 'none' (no MSA) or 'file' (local .a3m)
# ---------------------------------------------------------------------------

TOOL_INPUT_MATRIX: list[ToolTestCase] = [
    # --- Boltz ---
    # Protein + MSA file (full accuracy)
    ToolTestCase("boltz", "protein_msa", ["--protein", PROTEIN_FASTA],
                 extra_args=["--msa", MSA_FILE],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    # Protein without MSA (single-sequence mode via msa: empty)
    ToolTestCase("boltz", "protein", ["--protein", PROTEIN_FASTA],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    # DNA only (no MSA needed)
    ToolTestCase("boltz", "dna", ["--dna", DNA_FASTA],
                 timeout=1800),

    # --- OpenFold ---
    ToolTestCase("openfold", "protein", ["--protein", PROTEIN_FASTA],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    ToolTestCase("openfold", "protein_msa", ["--protein", PROTEIN_FASTA],
                 extra_args=["--msa", MSA_FILE],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    ToolTestCase("openfold", "multimer", ["--protein", MULTIMER_FASTA],
                 timeout=1800),
    ToolTestCase("openfold", "protein_dna",
                 ["--protein", PROTEIN_FASTA, "--dna", DNA_FASTA],
                 timeout=1800),
    ToolTestCase("openfold", "protein_rna",
                 ["--protein", PROTEIN_FASTA, "--rna", RNA_FASTA],
                 timeout=1800),
    ToolTestCase("openfold", "protein_ligand",
                 ["--protein", PROTEIN_FASTA, "--ligand", "ATP"],
                 timeout=1800),
    ToolTestCase("openfold", "protein_smiles",
                 ["--protein", PROTEIN_FASTA, "--smiles", "c1ccccc1"],
                 timeout=1800),

    # --- Chai ---
    ToolTestCase("chai", "protein", ["--protein", PROTEIN_FASTA],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    ToolTestCase("chai", "protein_msa", ["--protein", PROTEIN_FASTA],
                 extra_args=["--msa", MSA_FILE],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    ToolTestCase("chai", "multimer", ["--protein", MULTIMER_FASTA],
                 timeout=1800),
    ToolTestCase("chai", "protein_dna",
                 ["--protein", PROTEIN_FASTA, "--dna", DNA_FASTA],
                 timeout=1800),
    ToolTestCase("chai", "protein_rna",
                 ["--protein", PROTEIN_FASTA, "--rna", RNA_FASTA],
                 timeout=1800),
    ToolTestCase("chai", "protein_ligand",
                 ["--protein", PROTEIN_FASTA, "--ligand", "ATP"],
                 timeout=1800),
    ToolTestCase("chai", "protein_smiles",
                 ["--protein", PROTEIN_FASTA, "--smiles", "c1ccccc1"],
                 xfail_reason="Chai does not support SMILES input",
                 timeout=60),

    # --- AlphaFold ---
    # NOTE: AlphaFold data is at /local_databases/alphafold/databases
    ToolTestCase("alphafold", "protein", ["--protein", PROTEIN_FASTA],
                 extra_args=["--af2-data-dir", "/local_databases/alphafold/databases"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=3600),
    ToolTestCase("alphafold", "multimer", ["--protein", MULTIMER_FASTA],
                 extra_args=["--af2-data-dir", "/local_databases/alphafold/databases",
                             "--af2-model-preset", "multimer"],
                 timeout=3600),
    ToolTestCase("alphafold", "protein_dna",
                 ["--protein", PROTEIN_FASTA, "--dna", DNA_FASTA],
                 extra_args=["--af2-data-dir", "/local_databases/alphafold/databases"],
                 xfail_reason="AlphaFold 2 does not support DNA entities",
                 timeout=60),
    ToolTestCase("alphafold", "protein_ligand",
                 ["--protein", PROTEIN_FASTA, "--ligand", "ATP"],
                 extra_args=["--af2-data-dir", "/local_databases/alphafold/databases"],
                 xfail_reason="AlphaFold 2 does not support ligand entities",
                 timeout=60),

    # --- ESMFold ---
    ToolTestCase("esmfold", "protein", ["--protein", PROTEIN_FASTA],
                 extra_args=["--fp16"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=120),
    ToolTestCase("esmfold", "protein_cpu", ["--protein", PROTEIN_FASTA],
                 extra_args=["--device", "cpu"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=300),
    ToolTestCase("esmfold", "multimer", ["--protein", MULTIMER_FASTA],
                 extra_args=["--fp16"],
                 timeout=300),
    ToolTestCase("esmfold", "protein_dna",
                 ["--protein", PROTEIN_FASTA, "--dna", DNA_FASTA],
                 xfail_reason="ESMFold does not support DNA entities",
                 timeout=60),
    ToolTestCase("esmfold", "protein_ligand",
                 ["--protein", PROTEIN_FASTA, "--ligand", "ATP"],
                 xfail_reason="ESMFold does not support ligand entities",
                 timeout=60),
]


# ---------------------------------------------------------------------------
# Parameter variation matrix (sampled, not full cartesian)
# ---------------------------------------------------------------------------

PARAM_VARIATIONS: list[ToolTestCase] = [
    # Boltz: sampling_steps variation
    ToolTestCase("boltz", "protein_steps50", ["--protein", PROTEIN_FASTA],
                 extra_args=["--sampling-steps", "50"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),
    # Boltz: num_samples=3
    ToolTestCase("boltz", "protein_samples3", ["--protein", PROTEIN_FASTA],
                 extra_args=["--num-samples", "3"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=3600),

    # Chai: sampling_steps variation
    ToolTestCase("chai", "protein_steps50", ["--protein", PROTEIN_FASTA],
                 extra_args=["--sampling-steps", "50"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),

    # OpenFold: num_diffusion_samples variation
    ToolTestCase("openfold", "protein_diff3", ["--protein", PROTEIN_FASTA],
                 extra_args=["--num-diffusion-samples", "3"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=1800),

    # ESMFold: num_recycles variation
    ToolTestCase("esmfold", "protein_recycles8", ["--protein", PROTEIN_FASTA],
                 extra_args=["--num-recycles", "8", "--fp16"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=180),

    # Output format: mmcif
    ToolTestCase("esmfold", "protein_mmcif", ["--protein", PROTEIN_FASTA],
                 extra_args=["--output-format", "mmcif", "--fp16"],
                 expected_residues=CRAMBIN_RESIDUES, timeout=120),
]


# ---------------------------------------------------------------------------
# Helper: parametrize from matrix
# ---------------------------------------------------------------------------

def parametrize_matrix(matrix: list[ToolTestCase]):
    """Convert a list of ToolTestCase into pytest.mark.parametrize params."""
    return [tc.as_param() for tc in matrix]


# Filter helpers
def tool_cases(matrix: list[ToolTestCase], tool: str) -> list[ToolTestCase]:
    """Filter matrix to a specific tool."""
    return [tc for tc in matrix if tc.tool == tool]


def gpu_cases(matrix: list[ToolTestCase]) -> list[ToolTestCase]:
    """Filter to GPU-required cases (everything except esmfold_cpu)."""
    return [tc for tc in matrix if "cpu" not in tc.input_type]
