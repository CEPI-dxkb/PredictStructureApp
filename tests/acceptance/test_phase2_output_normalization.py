"""Phase 2: Output normalization validation.

Verifies that real predictions produce correctly normalized output:
- model_1.pdb with ATOM records
- model_1.cif (mmCIF)
- confidence.json matching JSON Schema
- metadata.json with correct tool and positive runtime
- raw_output/ directory with original files
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance.matrix import CRAMBIN_RESIDUES, PROTEIN_FASTA
from tests.acceptance.validators import assert_valid_output, validate_output_directory

pytestmark = [pytest.mark.phase2, pytest.mark.gpu, pytest.mark.container]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"


def _run_and_validate(container, tool, tmp_path, extra_args=None, timeout=120):
    """Run prediction and return (output_dir, result)."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    binds = {
        str(TEST_DATA_HOST): "/data",
        str(output_dir): "/output",
    }
    result = container.predict(
        tool=tool,
        entity_args=["--protein", PROTEIN_FASTA],
        output_dir=Path("/output"),
        extra_args=extra_args or [],
        binds=binds,
        timeout=timeout,
    )
    assert result.returncode == 0, f"STDERR:\n{result.stderr[-2000:]}"
    return output_dir, result


class TestOutputStructure:
    """Normalized output directory has all required files."""

    def test_esmfold_output_complete(self, container, tmp_path):
        """ESMFold produces complete normalized output."""
        output_dir, _ = _run_and_validate(
            container, "esmfold", tmp_path, extra_args=["--fp16"]
        )
        assert_valid_output(
            output_dir, tool="esmfold", expected_residues=CRAMBIN_RESIDUES
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("tool,extra", [
        ("boltz", []),
        ("openfold", []),
        ("chai", []),
    ])
    def test_gpu_tool_output_complete(self, container, tool, extra, tmp_path):
        """GPU tools produce complete normalized output."""
        output_dir, _ = _run_and_validate(
            container, tool, tmp_path, extra_args=extra, timeout=1800
        )
        assert_valid_output(output_dir, tool=tool, expected_residues=CRAMBIN_RESIDUES)


class TestConfidenceJSON:
    """confidence.json contains valid metrics."""

    def test_plddt_range(self, container, tmp_path):
        """pLDDT values are in 0-100 range."""
        output_dir, _ = _run_and_validate(
            container, "esmfold", tmp_path, extra_args=["--fp16"]
        )
        conf = json.loads((output_dir / "confidence.json").read_text())

        assert 0 <= conf["plddt_mean"] <= 100
        for val in conf["per_residue_plddt"]:
            assert 0 <= val <= 100, f"pLDDT value {val} out of range"

    def test_residue_count_matches_input(self, container, tmp_path):
        """per_residue_plddt array length matches input sequence length."""
        output_dir, _ = _run_and_validate(
            container, "esmfold", tmp_path, extra_args=["--fp16"]
        )
        conf = json.loads((output_dir / "confidence.json").read_text())
        assert len(conf["per_residue_plddt"]) == CRAMBIN_RESIDUES


class TestMetadataJSON:
    """metadata.json contains valid execution info."""

    def test_metadata_tool_name(self, container, tmp_path):
        """metadata.json reports the correct tool name."""
        output_dir, _ = _run_and_validate(
            container, "esmfold", tmp_path, extra_args=["--fp16"]
        )
        meta = json.loads((output_dir / "metadata.json").read_text())
        assert meta["tool"] == "esmfold"

    def test_metadata_positive_runtime(self, container, tmp_path):
        """metadata.json reports a positive runtime."""
        output_dir, _ = _run_and_validate(
            container, "esmfold", tmp_path, extra_args=["--fp16"]
        )
        meta = json.loads((output_dir / "metadata.json").read_text())
        assert meta.get("runtime_seconds", 0) > 0


class TestOutputFormat:
    """Output format flag (pdb vs mmcif) is respected."""

    def test_mmcif_output_format(self, container, tmp_path):
        """--output-format mmcif should still produce model_1.cif."""
        output_dir, _ = _run_and_validate(
            container,
            "esmfold",
            tmp_path,
            extra_args=["--output-format", "mmcif", "--fp16"],
        )
        assert (output_dir / "model_1.cif").exists(), "model_1.cif not found"

    def test_pdb_output_format(self, container, tmp_path):
        """--output-format pdb should produce model_1.pdb."""
        output_dir, _ = _run_and_validate(
            container,
            "esmfold",
            tmp_path,
            extra_args=["--output-format", "pdb", "--fp16"],
        )
        assert (output_dir / "model_1.pdb").exists(), "model_1.pdb not found"
