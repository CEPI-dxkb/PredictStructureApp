"""Tests for the CWL execution backend.

Tests cover both the unified CWL approach (build_unified_job / run_unified)
and the legacy per-tool approach (_build_job_yaml / run).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestCWLBackendRegistry:
    """Verify CWL backend is properly registered."""

    def test_backend_registered(self):
        from predict_structure.backends import BACKENDS
        assert "cwl" in BACKENDS

    def test_get_backend_cwl(self):
        from predict_structure.backends import get_backend
        from predict_structure.backends.cwl import CWLBackend

        backend = get_backend("cwl")
        assert isinstance(backend, CWLBackend)

    def test_get_backend_cwl_with_runner(self):
        from predict_structure.backends import get_backend

        backend = get_backend("cwl", runner="toil-cwl-runner")
        assert backend._runner == "toil-cwl-runner"

    def test_get_backend_cwl_with_tool(self, tmp_path):
        from predict_structure.backends import get_backend

        tool_path = tmp_path / "my-tool.cwl"
        backend = get_backend("cwl", cwl_tool=str(tool_path))
        assert backend._cwl_tool_override == str(tool_path)

    def test_get_backend_cwl_with_singularity(self):
        from predict_structure.backends import get_backend

        backend = get_backend("cwl", use_singularity=True)
        assert backend._use_singularity is True


class TestCWLBackendDefaults:
    """Verify default configuration."""

    def test_default_runner(self):
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        assert backend._runner == "cwltool"

    def test_default_no_singularity(self):
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        assert backend._use_singularity is False

    def test_cwl_definitions_exist(self):
        """All tools point to a CWL definition that exists."""
        from predict_structure.config import get_tools, get_cwl_path

        for tool in get_tools():
            cwl_path = get_cwl_path(tool)
            assert cwl_path.exists(), f"CWL tool for '{tool}' not found at {cwl_path}"

    def test_each_tool_has_own_cwl(self):
        """Each tool has its own per-tool CWL definition."""
        from predict_structure.config import get_tools, get_cwl_path

        for tool in get_tools():
            cwl_path = get_cwl_path(tool)
            assert tool in cwl_path.stem or tool[:4] in cwl_path.stem, (
                f"CWL path for '{tool}' should contain tool name: {cwl_path}"
            )

    def test_override_takes_precedence(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        override = tmp_path / "custom.cwl"
        override.touch()
        backend = CWLBackend(cwl_tool=str(override))
        assert backend._resolve_cwl_tool("boltz") == str(override)


class TestBuildUnifiedJob:
    """Test the unified job builder for predict-structure.cwl."""

    def test_basic_protein_job(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
        )

        assert job["tool"] == "boltz"
        assert job["output_dir"] == "/tmp/output"
        assert len(job["protein"]) == 1
        assert job["protein"][0]["class"] == "File"
        assert job["num_samples"] == 1
        assert job["num_recycles"] == 3
        assert job["device"] == "gpu"

    def test_multi_entity_job(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta1 = tmp_path / "chain_a.fasta"
        fasta1.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")
        fasta2 = tmp_path / "chain_b.fasta"
        fasta2.write_text(">B\nMGSSHHHHHHSSGLVPRGS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta1), str(fasta2)), "dna": (), "rna": (),
             "ligand": ("ATP",), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
        )

        assert len(job["protein"]) == 2
        assert job["ligand"] == ["ATP"]

    def test_tool_specific_options_mapped(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
            boltz_use_potentials=True,
            sampling_steps=200,
        )

        # boltz_use_potentials → use_potentials
        assert job["use_potentials"] is True
        assert job["sampling_steps"] == 200

    def test_esmfold_options_mapped(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "esmfold",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
            esm_fp16=True,
            esm_chunk_size=128,
            esm_max_tokens=1024,
        )

        assert job["fp16"] is True
        assert job["chunk_size"] == 128
        assert job["max_tokens_per_batch"] == 1024

    def test_alphafold_data_dir_as_directory(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "alphafold",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
            af2_data_dir="/databases",
            af2_model_preset="monomer",
        )

        assert job["af2_data_dir"]["class"] == "Directory"
        assert job["af2_model_preset"] == "monomer"

    def test_seed_omitted_when_none(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
        )

        assert "seed" not in job

    def test_seed_included_when_set(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
            seed=42,
        )

        assert job["seed"] == 42

    def test_msa_included_as_file(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")
        msa = tmp_path / "align.a3m"
        msa.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "chai",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
            msa=str(msa),
        )

        assert job["msa"]["class"] == "File"

    def test_false_options_excluded(self, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        backend = CWLBackend()
        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir="/tmp/output",
            boltz_use_potentials=False,
            use_msa_server=False,
        )

        assert "use_potentials" not in job
        assert "use_msa_server" not in job


class TestCWLBackendRunUnified:
    """Test run_unified() with mocked subprocess."""

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_invokes_cwltool(self, mock_run, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=0)
        # Use explicit cwl_tool override to target the unified CWL definition
        unified_cwl = tmp_path / "predict-structure.cwl"
        unified_cwl.touch()
        backend = CWLBackend(cwl_tool=str(unified_cwl))

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir=str(tmp_path / "output"),
        )
        rc = backend.run_unified(job, tool_name="boltz")

        assert rc == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "cwltool"
        assert "predict-structure.cwl" in call_args[1]

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_singularity_flag(self, mock_run, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = CWLBackend(use_singularity=True)

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")

        job = backend.build_unified_job(
            "esmfold",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir=str(tmp_path / "output"),
        )
        backend.run_unified(job, tool_name="esmfold")

        call_args = mock_run.call_args[0][0]
        assert "--singularity" in call_args

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_job_yaml_written(self, mock_run, tmp_path):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = CWLBackend()

        fasta = tmp_path / "test.fasta"
        fasta.write_text(">A\nMKTAYIAKQRQISFVKSHFS\n")
        out_dir = tmp_path / "output"

        job = backend.build_unified_job(
            "boltz",
            {"protein": (str(fasta),), "dna": (), "rna": (),
             "ligand": (), "smiles": (), "glycan": ()},
            output_dir=str(out_dir / "raw"),
            sampling_steps=200,
        )
        backend.run_unified(job, tool_name="boltz", output_dir=str(out_dir))

        job_path = out_dir / "job.yml"
        assert job_path.exists()
        job_doc = yaml.safe_load(job_path.read_text())
        assert job_doc["tool"] == "boltz"
        assert job_doc["sampling_steps"] == 200


class TestBuildJobYAMLLegacy:
    """Test legacy command-to-job-YAML conversion (backward compat)."""

    def test_boltz_command(self):
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "boltz", "predict", "/data/input.yaml",
            "--out_dir", "/data/output",
            "--diffusion_samples", "3",
        ]
        job = backend._build_job_yaml(command, tool_name="boltz")

        assert "tool" not in job
        assert job["input_file"]["class"] == "File"
        assert job["input_file"]["path"] == "/data/input.yaml"
        # CWL uses relative output path
        assert job["output_dir"] == "output"
        assert job["diffusion_samples"] == 3

    def test_esmfold_command(self):
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "esm-fold-hf", "-i", "/data/input.fasta",
            "-o", "/data/output",
            "--num-recycles", "4",
        ]
        job = backend._build_job_yaml(command, tool_name="esmfold")

        assert "tool" not in job
        assert job["sequences"]["class"] == "File"
        assert job["sequences"]["path"] == "/data/input.fasta"
        assert job["output_dir"] == "output"
        assert job["num_recycles"] == 4

    def test_chai_positional_output(self):
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "chai-lab", "fold", "/data/input.fasta", "/data/output",
            "--num-diffn-samples", "5",
            "--num-trunk-recycles", "3",
            "--num-diffn-timesteps", "200",
            "--device", "cuda",
            "--use-msa-server",
        ]
        job = backend._build_job_yaml(command, tool_name="chai")

        assert "tool" not in job
        assert job["input_fasta"]["class"] == "File"
        assert job["input_fasta"]["path"] == "/data/input.fasta"
        assert job["output_directory"] == "output"
        assert job["num_diffn_samples"] == 5
        assert job["num_trunk_recycles"] == 3
        assert job["num_diffn_timesteps"] == 200
        assert job["device"] == "cuda"
        assert job["use_msa_server"] is True

    def test_alphafold_with_data_dir(self):
        from predict_structure.backends.cwl import CWLBackend

        backend = CWLBackend()
        command = [
            "python", "/app/alphafold/run_alphafold.py",
            "--fasta_paths", "/data/input.fasta",
            "--output_dir", "/data/output",
            "--data_dir", "/databases",
            "--model_preset", "monomer",
            "--db_preset", "reduced_dbs",
            "--max_template_date", "2022-01-01",
            "--uniref90_database_path", "/databases/uniref90/uniref90.fasta",
            "--pdb70_database_path", "/databases/pdb70/pdb70",
            "--use_gpu_relax=true",
        ]
        job = backend._build_job_yaml(command, tool_name="alphafold")

        assert "tool" not in job
        assert job["fasta_paths"]["class"] == "File"
        assert job["fasta_paths"]["path"] == "/data/input.fasta"
        assert job["output_dir"] == "output"
        assert job["data_dir"] == "/databases"
        assert job["model_preset"] == "monomer"
        assert job["use_gpu_relax"] is True
        assert "uniref90_database_path" not in job
        assert "pdb70_database_path" not in job


class TestCWLBackendRunLegacy:
    """Test the legacy run() method with mocked subprocess."""

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_invokes_cwl(self, mock_run):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = CWLBackend()

        command = ["boltz", "predict", "/data/input.yaml", "--out_dir", "/data/output"]
        rc = backend.run(command, tool_name="boltz")

        assert rc == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "cwltool"
        assert "boltz.cwl" in call_args[1]
        assert call_args[2].endswith(".yml")

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_returns_nonzero_exit_code(self, mock_run):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=1)
        backend = CWLBackend()

        rc = backend.run(
            ["boltz", "predict", "/data/input.yaml", "--out_dir", "/data/output"],
            tool_name="boltz",
        )
        assert rc == 1

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_custom_runner(self, mock_run):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = CWLBackend(runner="toil-cwl-runner")

        backend.run(
            ["boltz", "predict", "/data/input.yaml", "--out_dir", "/data/output"],
            tool_name="boltz",
        )

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "toil-cwl-runner"

    @patch("predict_structure.backends.cwl.subprocess.run")
    def test_timeout_passed(self, mock_run):
        from predict_structure.backends.cwl import CWLBackend

        mock_run.return_value = MagicMock(returncode=0)
        backend = CWLBackend()

        backend.run(
            ["boltz", "predict", "/data/input.yaml", "--out_dir", "/data/output"],
            tool_name="boltz",
            timeout=3600,
        )

        assert mock_run.call_args[1]["timeout"] == 3600
