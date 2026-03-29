"""Tests for CLI argument parsing and error handling."""

from unittest.mock import patch

from click.testing import CliRunner
from predict_structure.cli import main, discover_tool, _is_tool_available, _auto_select_tool
from predict_structure.entities import EntityList, EntityType


class TestCLIGroup:
    """Test the top-level click group."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Predict protein structure" in result.output
        assert "boltz" in result.output
        assert "chai" in result.output
        assert "alphafold" in result.output
        assert "esmfold" in result.output

    def test_unknown_subcommand(self):
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent", "--protein", "input.fasta", "-o", "/tmp/out"])
        assert result.exit_code != 0

    def test_no_subcommand(self):
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert "boltz" in result.output

    def test_job_option_shown_in_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "--job" in result.output


class TestBoltzSubcommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--help"])
        assert result.exit_code == 0
        assert "--output-dir" in result.output
        assert "--num-samples" in result.output
        assert "--backend" in result.output
        assert "--debug" in result.output
        # Entity input options
        assert "--protein" in result.output
        assert "--dna" in result.output
        assert "--ligand" in result.output
        # Boltz-specific
        assert "--sampling-steps" in result.output
        assert "--use-msa-server" in result.output
        assert "--use-potentials" in result.output

    def test_help_does_not_show_other_tool_options(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--help"])
        assert "--fp16" not in result.output
        assert "--af2-data-dir" not in result.output
        assert "--chunk-size" not in result.output

    def test_missing_output_dir(self, sample_fasta):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--protein", str(sample_fasta)])
        assert result.exit_code != 0

    def test_missing_input_entities(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "-o", "/tmp/out"])
        assert result.exit_code != 0

    def test_debug_prints_command(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0
        assert "boltz predict" in result.output
        assert "--diffusion_samples" in result.output

    def test_debug_with_use_potentials(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--debug", "--use-potentials",
        ])
        assert result.exit_code == 0
        assert "--use_potentials" in result.output

    def test_protein_with_ligand(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz", "--protein", str(sample_fasta), "--ligand", "ATP",
            "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0
        assert "boltz predict" in result.output


class TestChaiSubcommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["chai", "--help"])
        assert result.exit_code == 0
        assert "--sampling-steps" in result.output
        assert "--use-msa-server" in result.output
        assert "--protein" in result.output
        # Should not show other tool options
        assert "--fp16" not in result.output
        assert "--af2-data-dir" not in result.output

    def test_debug_prints_command(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "chai", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0
        assert "chai-lab fold" in result.output


class TestAlphaFoldSubcommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["alphafold", "--help"])
        assert result.exit_code == 0
        assert "--af2-data-dir" in result.output
        assert "--af2-model-preset" in result.output
        assert "--af2-db-preset" in result.output
        assert "--af2-max-template-date" in result.output
        assert "--protein" in result.output
        # Should not show other tool options
        assert "--fp16" not in result.output
        assert "--use-potentials" not in result.output

    def test_requires_af2_data_dir(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "alphafold", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code != 0  # --af2-data-dir is required

    def test_debug_prints_command(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "alphafold", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--af2-data-dir", "/data/alphafold", "--debug",
        ])
        assert result.exit_code == 0
        assert "run_alphafold.py" in result.output
        assert "--data_dir" in result.output


class TestESMFoldSubcommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["esmfold", "--help"])
        assert result.exit_code == 0
        assert "--fp16" in result.output
        assert "--chunk-size" in result.output
        assert "--max-tokens-per-batch" in result.output
        assert "--protein" in result.output
        # Should not show other tool options
        assert "--use-potentials" not in result.output
        assert "--af2-data-dir" not in result.output
        assert "--sampling-steps" not in result.output

    def test_debug_prints_command(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "esmfold", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0
        assert "esm-fold-hf" in result.output

    def test_debug_with_fp16(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "esmfold", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--debug", "--fp16",
        ])
        assert result.exit_code == 0
        assert "--fp16" in result.output

    def test_debug_with_chunk_size(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "esmfold", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--debug", "--chunk-size", "64",
        ])
        assert result.exit_code == 0
        assert "--chunk-size 64" in result.output


class TestEntityOptions:
    """Test entity flag behavior across subcommands."""

    def test_no_entities_is_error(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "-o", str(tmp_path / "out"), "--debug"])
        assert result.exit_code != 0
        assert "No input entities" in result.output

    def test_multiple_protein_files(self, sample_fasta, multi_chain_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz",
            "--protein", str(sample_fasta),
            "--protein", str(multi_chain_fasta),
            "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0

    def test_protein_and_dna(self, sample_fasta, dna_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz",
            "--protein", str(sample_fasta),
            "--dna", str(dna_fasta),
            "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0

    def test_nonexistent_protein_file(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz", "--protein", "/nonexistent/file.fasta", "-o", str(tmp_path / "out"),
        ])
        assert result.exit_code != 0


class TestSharedOptions:
    """Test that shared options work across subcommands."""

    def test_backend_choices_shown(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--help"])
        assert "docker" in result.output
        assert "subprocess" in result.output
        assert "cwl" in result.output

    def test_cwl_options_shown(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--help"])
        assert "--cwl-runner" in result.output
        assert "--cwl-tool" in result.output

    def test_image_option_shown(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--help"])
        assert "--image" in result.output


class TestAutoSubcommand:
    """Test the auto-discovery subcommand."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["auto", "--help"])
        assert result.exit_code == 0
        assert "Auto-discover" in result.output
        assert "--output-dir" in result.output
        assert "--backend" in result.output
        assert "--protein" in result.output
        # auto should NOT show tool-specific options
        assert "--sampling-steps" not in result.output
        assert "--fp16" not in result.output
        assert "--af2-data-dir" not in result.output

    def test_auto_shown_in_group_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "auto" in result.output

    @patch("predict_structure.cli._auto_select_tool", return_value="esmfold")
    def test_auto_debug_prints_selected_tool(self, mock_select, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "auto", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0
        assert "Auto-selected: esmfold" in result.output
        assert "esm-fold-hf" in result.output

    @patch("predict_structure.cli._auto_select_tool", return_value="boltz")
    def test_auto_debug_boltz(self, mock_select, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "auto", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        assert result.exit_code == 0
        assert "Auto-selected: boltz" in result.output
        assert "boltz predict" in result.output


class TestAutoSelectTool:
    """Test the _auto_select_tool function."""

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "boltz")
    def test_selects_boltz_with_msa(self, mock_avail):
        el = EntityList()
        el.add(EntityType.PROTEIN, "ACDE")
        result = _auto_select_tool(el, device="gpu", has_msa=True)
        assert result == "boltz"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "boltz")
    def test_selects_boltz_with_msa_server(self, mock_avail):
        el = EntityList()
        el.add(EntityType.PROTEIN, "ACDE")
        result = _auto_select_tool(el, device="gpu", use_msa_server=True)
        assert result == "boltz"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t in ("boltz", "esmfold"))
    def test_skips_boltz_without_msa(self, mock_avail):
        el = EntityList()
        el.add(EntityType.PROTEIN, "ACDE")
        result = _auto_select_tool(el, device="gpu")
        assert result == "esmfold"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "esmfold")
    def test_cpu_prefers_esmfold(self, mock_avail):
        el = EntityList()
        el.add(EntityType.PROTEIN, "ACDE")
        result = _auto_select_tool(el, device="cpu")
        assert result == "esmfold"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t in ("boltz", "chai"))
    def test_non_protein_excludes_af2_esmfold(self, mock_avail):
        el = EntityList()
        el.add(EntityType.PROTEIN, "ACDE")
        el.add(EntityType.LIGAND, "ATP")
        result = _auto_select_tool(el, device="gpu", use_msa_server=True)
        assert result == "boltz"

    @patch("predict_structure.cli._is_tool_available", return_value=False)
    def test_no_tools_available_raises(self, mock_avail):
        import pytest
        el = EntityList()
        el.add(EntityType.PROTEIN, "ACDE")
        with pytest.raises(Exception, match="No prediction tool found"):
            _auto_select_tool(el, device="gpu")


class TestToolDiscovery:
    """Test the legacy discover_tool function."""

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "boltz")
    def test_discovers_boltz_first(self, mock_avail, tmp_path):
        fasta = tmp_path / "test.fasta"
        fasta.write_text(">seq\nACDE\n")
        result = discover_tool(fasta, device="gpu")
        assert result == "boltz"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "esmfold")
    def test_cpu_prefers_esmfold(self, mock_avail, tmp_path):
        fasta = tmp_path / "test.fasta"
        fasta.write_text(">seq\nACDE\n")
        result = discover_tool(fasta, device="cpu")
        assert result == "esmfold"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "boltz")
    def test_yaml_input_forces_boltz(self, mock_avail, tmp_path):
        yaml_file = tmp_path / "input.yaml"
        yaml_file.write_text("sequences:\n  - protein:\n      id: A\n")
        result = discover_tool(yaml_file, device="gpu")
        assert result == "boltz"

    @patch("predict_structure.cli._is_tool_available", return_value=False)
    def test_yaml_input_without_boltz_raises(self, mock_avail, tmp_path):
        import pytest
        yaml_file = tmp_path / "input.yaml"
        yaml_file.write_text("sequences:\n  - protein:\n      id: A\n")
        with pytest.raises(Exception, match="YAML input requires Boltz"):
            discover_tool(yaml_file, device="gpu")

    @patch("predict_structure.cli._is_tool_available", return_value=False)
    def test_no_tools_available_raises(self, mock_avail, tmp_path):
        import pytest
        fasta = tmp_path / "test.fasta"
        fasta.write_text(">seq\nACDE\n")
        with pytest.raises(Exception, match="No prediction tool found"):
            discover_tool(fasta, device="gpu")

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "chai")
    def test_falls_through_to_chai(self, mock_avail, tmp_path):
        fasta = tmp_path / "test.fasta"
        fasta.write_text(">seq\nACDE\n")
        result = discover_tool(fasta, device="gpu")
        assert result == "chai"

    @patch("predict_structure.cli._is_tool_available", side_effect=lambda t: t == "esmfold")
    def test_esmfold_as_last_resort_on_gpu(self, mock_avail, tmp_path):
        fasta = tmp_path / "test.fasta"
        fasta.write_text(">seq\nACDE\n")
        result = discover_tool(fasta, device="gpu")
        assert result == "esmfold"


class TestMSAServerURL:
    """Test --msa-server-url option on boltz and chai."""

    def test_boltz_help_shows_msa_server_url(self):
        runner = CliRunner()
        result = runner.invoke(main, ["boltz", "--help"])
        assert "--msa-server-url" in result.output

    def test_chai_help_shows_msa_server_url(self):
        runner = CliRunner()
        result = runner.invoke(main, ["chai", "--help"])
        assert "--msa-server-url" in result.output

    def test_boltz_msa_server_url_in_debug(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--debug", "--msa-server-url", "https://my-server.com",
        ])
        assert result.exit_code == 0
        assert "--use_msa_server" in result.output
        assert "--msa_server_url" in result.output
        assert "https://my-server.com" in result.output

    def test_chai_msa_server_url_in_debug(self, sample_fasta, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, [
            "chai", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--debug", "--msa-server-url", "https://my-server.com",
        ])
        assert result.exit_code == 0
        assert "--use-msa-server" in result.output
        assert "--msa-server-url" in result.output
        assert "https://my-server.com" in result.output

    def test_boltz_msa_server_url_implies_use_msa_server(self, sample_fasta, tmp_path):
        """Passing --msa-server-url without --use-msa-server should still enable MSA server."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "boltz", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"),
            "--debug", "--msa-server-url", "https://my-server.com",
        ])
        assert result.exit_code == 0
        assert "--use_msa_server" in result.output

    def test_esmfold_has_no_msa_server_url(self):
        runner = CliRunner()
        result = runner.invoke(main, ["esmfold", "--help"])
        assert "--msa-server-url" not in result.output

    def test_alphafold_has_no_msa_server_url(self):
        runner = CliRunner()
        result = runner.invoke(main, ["alphafold", "--help"])
        assert "--msa-server-url" not in result.output


class TestBackendRegistry:
    def test_get_backend_subprocess(self):
        from predict_structure.backends import get_backend
        from predict_structure.backends.subprocess import SubprocessBackend

        backend = get_backend("subprocess")
        assert isinstance(backend, SubprocessBackend)

    def test_get_backend_docker(self):
        from predict_structure.backends import get_backend
        from predict_structure.backends.docker import DockerBackend

        backend = get_backend("docker")
        assert isinstance(backend, DockerBackend)

    def test_get_backend_docker_with_image(self):
        from predict_structure.backends import get_backend
        from predict_structure.backends.docker import DockerBackend

        backend = get_backend("docker", default_image="my/image:latest")
        assert isinstance(backend, DockerBackend)
        assert backend._default_image == "my/image:latest"

    def test_get_backend_cwl(self):
        from predict_structure.backends import get_backend
        from predict_structure.backends.cwl import CWLBackend

        backend = get_backend("cwl")
        assert isinstance(backend, CWLBackend)

    def test_get_backend_cwl_with_runner(self):
        from predict_structure.backends import get_backend

        backend = get_backend("cwl", runner="toil-cwl-runner")
        assert backend._runner == "toil-cwl-runner"

    def test_get_backend_unknown(self):
        from predict_structure.backends import get_backend

        import pytest
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend("nonexistent")
