"""Phase 2: Auto tool selection with real tools inside the container.

Tests that 'predict-structure auto' selects the correct tool based on
entity types and device. Uses --debug mode to check selection without
running full predictions.

Auto-select priority (from cli.py):
  CPU + protein-only -> ESMFold
  GPU: Boltz > OpenFold > Chai > AlphaFold > ESMFold
  Boltz/Chai skipped without MSA for protein input
  AlphaFold/ESMFold skipped for non-protein entities
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.acceptance.matrix import DNA_FASTA, MSA_FILE, PROTEIN_FASTA

pytestmark = [pytest.mark.phase2, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"


def _run_auto_debug(container, entity_args, extra_args=None, binds=None):
    """Run predict-structure auto --debug and return stdout."""
    cmd = ["predict-structure", "auto"] + entity_args
    cmd.extend(["-o", "/output", "--backend", "subprocess", "--debug"])
    if extra_args:
        cmd.extend(extra_args)
    result = container.exec(cmd, gpu=False, binds=binds, timeout=30)
    return result


class TestAutoSelectionProteinOnly:
    """Auto-select for protein-only input."""

    def test_auto_protein_gpu_no_msa(self, container, tmp_path):
        """Protein + GPU + no MSA -> should select openfold (boltz/chai need MSA)."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        binds = {str(TEST_DATA_HOST): "/data", str(output_dir): "/output"}

        result = _run_auto_debug(
            container,
            ["--protein", PROTEIN_FASTA],
            binds=binds,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        # Should print "Auto-selected: openfold" (boltz/chai need MSA)
        assert "Auto-selected:" in result.stdout
        selected = result.stdout.split("Auto-selected:")[1].strip().split()[0]
        assert selected == "openfold", f"Expected openfold, got {selected}"

    def test_auto_protein_gpu_with_msa(self, container, tmp_path):
        """Protein + GPU + MSA file -> should select boltz (highest priority with MSA)."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        binds = {str(TEST_DATA_HOST): "/data", str(output_dir): "/output"}

        result = _run_auto_debug(
            container,
            ["--protein", PROTEIN_FASTA],
            extra_args=["--msa", MSA_FILE],
            binds=binds,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        assert "Auto-selected:" in result.stdout
        selected = result.stdout.split("Auto-selected:")[1].strip().split()[0]
        assert selected == "boltz", f"Expected boltz, got {selected}"

    def test_auto_protein_cpu(self, container, tmp_path):
        """Protein + CPU -> should select esmfold."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        binds = {str(TEST_DATA_HOST): "/data", str(output_dir): "/output"}

        result = _run_auto_debug(
            container,
            ["--protein", PROTEIN_FASTA],
            extra_args=["--device", "cpu"],
            binds=binds,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        assert "Auto-selected:" in result.stdout
        selected = result.stdout.split("Auto-selected:")[1].strip().split()[0]
        assert selected == "esmfold", f"Expected esmfold, got {selected}"


class TestAutoSelectionMixedEntities:
    """Auto-select for non-protein entity combinations."""

    def test_auto_protein_dna_excludes_af_esm(self, container, tmp_path):
        """Protein + DNA -> should exclude AlphaFold and ESMFold."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        binds = {str(TEST_DATA_HOST): "/data", str(output_dir): "/output"}

        result = _run_auto_debug(
            container,
            ["--protein", PROTEIN_FASTA, "--dna", DNA_FASTA],
            binds=binds,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        assert "Auto-selected:" in result.stdout
        selected = result.stdout.split("Auto-selected:")[1].strip().split()[0]
        # Must be boltz, openfold, or chai -- not alphafold or esmfold
        assert selected in ("boltz", "openfold", "chai"), (
            f"Expected boltz/openfold/chai for protein+DNA, got {selected}"
        )

    def test_auto_protein_ligand_excludes_af_esm(self, container, tmp_path):
        """Protein + ligand -> should exclude AlphaFold and ESMFold."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        binds = {str(TEST_DATA_HOST): "/data", str(output_dir): "/output"}

        result = _run_auto_debug(
            container,
            ["--protein", PROTEIN_FASTA, "--ligand", "ATP"],
            binds=binds,
        )
        assert result.returncode == 0, f"STDERR:\n{result.stderr[-1000:]}"
        assert "Auto-selected:" in result.stdout
        selected = result.stdout.split("Auto-selected:")[1].strip().split()[0]
        assert selected in ("boltz", "openfold", "chai"), (
            f"Expected boltz/openfold/chai for protein+ligand, got {selected}"
        )
