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

    def test_af2_data_dir_falls_back_to_config(self, sample_fasta, tmp_path):
        """Without --af2-data-dir, the adapter falls back to tools.yml config."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "alphafold", "--protein", str(sample_fasta), "-o", str(tmp_path / "out"), "--debug",
        ])
        # --debug only builds the command; should succeed and include --data_dir
        # resolved from get_data_dir("alphafold")
        assert result.exit_code == 0
        assert "--data_dir" in result.output

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


class TestPreflightEntityValidation:
    """Preflight must reject impossible jobs before SLURM allocates (#84).

    Preflight runs on the scheduler node with no access to workspace files, so
    every case here declares entity *kinds* via --has-* and never a path.
    """

    def _run(self, *args):
        import json as _json

        from predict_structure.cli import main

        result = CliRunner().invoke(main, ["preflight", *args])
        try:
            payload = _json.loads(result.output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            payload = {}
        return result, payload

    def test_alphafold_rejects_dna_and_smiles(self):
        """The exact shape of production job 23403506."""
        result, payload = self._run(
            "--tool", "alphafold", "--has-dna", "--has-smiles",
        )
        assert result.exit_code == 3
        assert payload["error"]["code"] == "invalid_input"
        assert "does not support" in payload["error"]["message"]

    def test_esmfold_rejects_dna(self):
        result, payload = self._run("--tool", "esmfold", "--has-protein", "--has-dna")
        assert result.exit_code == 3
        assert "dna" in payload["error"]["message"]

    def test_chai_rejects_ccd_ligand(self):
        """#82's CCD rejection must also fire at submit time, not on the worker."""
        result, payload = self._run(
            "--tool", "chai", "--has-protein", "--has-ligand", "--use-msa-server",
        )
        assert result.exit_code == 3
        assert "CCD" in payload["error"]["message"]

    def test_chai_accepts_smiles_ligand(self):
        result, payload = self._run(
            "--tool", "chai", "--has-protein", "--has-smiles", "--use-msa-server",
        )
        assert result.exit_code == 0
        assert payload["resolved_tool"] == "chai"

    def test_protein_only_still_passes(self):
        result, payload = self._run("--tool", "alphafold", "--has-protein")
        assert result.exit_code == 0
        assert payload["resolved_tool"] == "alphafold"
        assert "error" not in payload

    def test_no_flags_is_backward_compatible(self):
        """Callers predating the --has-* flags must keep working."""
        result, payload = self._run("--tool", "esmfold")
        assert result.exit_code == 0
        assert payload["resolved_tool"] == "esmfold"

    def test_rejection_names_the_tool_and_an_alternative(self):
        """Messages reach BV-BRC users, so they must be actionable prose."""
        _, payload = self._run("--tool", "alphafold", "--has-dna")
        message = payload["error"]["message"]
        assert "AlphaFold 2" in message      # display name, not "alphafold"
        assert "Boltz-2" in message          # a tool that would accept DNA
        assert "alphafold" not in message    # no bare identifiers leaking


class TestAutoSelectionRespectsAdapters:
    def test_auto_never_picks_chai_for_ccd_ligand(self):
        """Chai takes ligands only as SMILES, so auto must route CCD elsewhere."""
        from predict_structure.adapters import get_adapter
        from predict_structure.entities import EntityType

        types = frozenset({EntityType.PROTEIN, EntityType.LIGAND})
        assert not get_adapter("chai").supports_entity_types(types)
        assert get_adapter("boltz").supports_entity_types(types)

    def test_unavailable_tools_are_not_reported_as_input_errors(self, monkeypatch):
        """"Nothing installed" must not masquerade as a user input problem."""
        import pytest

        import predict_structure.cli as cli_mod
        from predict_structure.entities import EntityList, EntityType

        monkeypatch.setattr(cli_mod, "_is_tool_available", lambda _t: False)
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        with pytest.raises(Exception, match="No prediction tool found"):
            cli_mod._auto_select_tool(el, device="gpu", use_msa_server=True)


class TestErrorPresentation:
    """Rejections must read as messages, never tracebacks (#84)."""

    def test_auto_unsupported_combo_is_a_clean_click_error(self, tmp_path, monkeypatch):
        """UnsupportedInputError must be formatted by click, not dumped raw.

        Regression: raising a bare ValueError here escaped uncaught through the
        `auto` subcommand and printed a traceback — the exact failure #84 exists
        to remove.
        """
        import predict_structure.cli as cli_mod
        from predict_structure.cli import main

        monkeypatch.setattr(cli_mod, "_is_tool_available", lambda _t: True)
        fasta = tmp_path / "p.fasta"
        fasta.write_text(">p\nMKTIIALSYIFCLVFA\n")

        result = CliRunner().invoke(
            main,
            ["auto", "--protein", str(fasta), "--ligand", "ATP",
             "-o", str(tmp_path / "out")],
        )
        assert result.exit_code == 2
        assert "Error:" in result.output
        assert "Traceback" not in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_msa_message_only_names_tools_it_skipped(self, monkeypatch):
        """No suggesting a fallback that was already rejected.

        By the time this branch runs, every other tool has been tried, so
        naming one would be advice the user cannot act on.
        """
        import pytest

        import predict_structure.cli as cli_mod
        from predict_structure.entities import EntityList, EntityType

        monkeypatch.setattr(cli_mod, "_is_tool_available", lambda _t: True)
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIAL")
        el.add(EntityType.LIGAND, "ATP", name="ATP", format="ccd")
        with pytest.raises(cli_mod.UnsupportedInputError) as excinfo:
            cli_mod._auto_select_tool(el, device="gpu")
        message = str(excinfo.value)
        assert "MSA" in message
        assert "ESMFold" not in message   # can't take a ligand; not a remedy
        assert "Chai-1" not in message    # skipped for CCD, not for MSA


class TestValidateEntityTypesAcceptsIterables:
    def test_chai_ccd_rejection_survives_a_one_shot_iterator(self):
        """The signature promises Iterable, so a generator must work too."""
        import pytest

        from predict_structure.adapters import get_adapter
        from predict_structure.entities import EntityType

        types = [EntityType.PROTEIN, EntityType.LIGAND]
        adapter = get_adapter("chai")
        with pytest.raises(ValueError, match="CCD"):
            adapter.validate_entity_types(iter(types))

    def test_base_rejection_survives_a_one_shot_iterator(self):
        import pytest

        from predict_structure.adapters import get_adapter
        from predict_structure.entities import EntityType

        adapter = get_adapter("alphafold")
        with pytest.raises(ValueError, match="does not support"):
            adapter.validate_entity_types(iter([EntityType.DNA]))


class TestAlphaFoldRetiredFromAuto:
    """AlphaFold 2 is retired from auto selection but stays runnable (#90).

    Auto must never resolve to AlphaFold for any job shape, yet every
    explicit entry point (CLI subcommand, preflight/API tool name, adapter
    registry) has to keep working so old jobs remain reproducible.
    """

    # Entity mixes an auto job can arrive with, protein-only first.
    _MIXES = {
        "protein": [(EntityType.PROTEIN, "MKTIIAL")],
        "protein+dna": [(EntityType.PROTEIN, "MKTIIAL"), (EntityType.DNA, "ACGT")],
        "protein+rna": [(EntityType.PROTEIN, "MKTIIAL"), (EntityType.RNA, "ACGU")],
        "protein+ccd": [(EntityType.PROTEIN, "MKTIIAL"), (EntityType.LIGAND, "ATP")],
        "protein+smiles": [(EntityType.PROTEIN, "MKTIIAL"), (EntityType.SMILES, "CCO")],
        "dna": [(EntityType.DNA, "ACGT")],
        "ligand": [(EntityType.LIGAND, "ATP")],
    }

    @staticmethod
    def _entities(spec):
        el = EntityList()
        for kind, value in spec:
            if kind is EntityType.LIGAND:
                el.add(kind, value, name=value, format="ccd")
            elif kind is EntityType.SMILES:
                el.add(kind, value, name="smiles", format="smiles")
            else:
                el.add(kind, value)
        return el

    def test_auto_never_selects_alphafold(self, monkeypatch):
        """Every entity mix x device x MSA source x availability set.

        Only the two refusal types are tolerated, and the sweep must actually
        resolve some combinations: a bare `except Exception: continue` would let
        this pass against an auto selector that raises unconditionally, which is
        no guard at all.
        """
        import click
        import pytest

        import predict_structure.cli as cli_mod

        availability_sets = [
            {"boltz", "openfold", "chai", "esmfold", "alphafold"},  # production
            {"alphafold"},                                          # AF2 alone
            {"boltz", "alphafold"},
            {"chai", "alphafold"},
            {"boltz", "openfold", "chai", "alphafold"},             # no esmfold
        ]
        resolved = refused = 0
        for installed in availability_sets:
            monkeypatch.setattr(
                cli_mod, "_is_tool_available", lambda t, s=installed: t in s
            )
            for name, spec in self._MIXES.items():
                for device in ("gpu", "cpu"):
                    for msa in ({}, {"has_msa": True}, {"use_msa_server": True}):
                        try:
                            picked = cli_mod._auto_select_tool(
                                self._entities(spec), device=device, **msa
                            )
                        except (cli_mod.UnsupportedInputError, click.UsageError):
                            refused += 1
                            continue
                        resolved += 1
                        assert picked != "alphafold", (
                            f"auto picked alphafold for {name}/{device}/{msa} "
                            f"with {sorted(installed)} installed"
                        )
        assert resolved > 0, "no combination resolved — the assertion never ran"
        assert refused > 0, "expected some combinations to be refused"

    def test_alphafold_only_install_points_at_the_explicit_command(self, monkeypatch):
        """AlphaFold installed alone: say so, and name the escape hatch.

        Claiming "no prediction tool found" would be false, and raising
        click.UsageError instead of UnsupportedInputError means preflight exits 2
        rather than emitting a rejection — which App-PredictStructure.pl reads as
        a broken binary and answers by scheduling the job anyway (#84).
        """
        import pytest

        import predict_structure.cli as cli_mod
        from predict_structure.entities import EntityList, EntityType

        monkeypatch.setattr(cli_mod, "_is_tool_available", lambda t: t == "alphafold")
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSYIFCLVFA")
        with pytest.raises(cli_mod.UnsupportedInputError) as excinfo:
            cli_mod._auto_select_tool(el, device="gpu", use_msa_server=True)
        message = str(excinfo.value)
        assert "predict-structure alphafold" in message
        assert "No prediction tool found" not in message

    def test_protein_only_without_msa_still_resolves(self, monkeypatch):
        """The commonest job shape must not regress into an error.

        Retiring AlphaFold removes the historical no-MSA fallback, so this
        pins ESMFold as the one that now serves it.
        """
        import predict_structure.cli as cli_mod

        monkeypatch.setattr(cli_mod, "_is_tool_available", lambda _t: True)
        el = self._entities(self._MIXES["protein"])
        assert cli_mod._auto_select_tool(el, device="gpu") == "esmfold"
        assert cli_mod._auto_select_tool(el, device="cpu") == "esmfold"

    def test_legacy_discover_tool_skips_alphafold(self, tmp_path, monkeypatch):
        import pytest

        import predict_structure.cli as cli_mod

        fasta = tmp_path / "p.fasta"
        fasta.write_text(">p\nMKTIIAL\n")
        monkeypatch.setattr(
            cli_mod, "_is_tool_available", lambda t: t == "alphafold"
        )
        with pytest.raises(Exception, match="No prediction tool found"):
            cli_mod.discover_tool(fasta, device="gpu")

    def test_path_error_does_not_advertise_alphafold(self, monkeypatch):
        """The install hint must not name a tool auto can no longer pick."""
        import pytest

        import predict_structure.cli as cli_mod

        monkeypatch.setattr(cli_mod, "_is_tool_available", lambda _t: False)
        el = self._entities(self._MIXES["protein"])
        with pytest.raises(Exception) as excinfo:
            cli_mod._auto_select_tool(el, device="gpu")
        assert "run_alphafold.py" not in str(excinfo.value)

    def test_explicit_alphafold_subcommand_still_builds_a_command(self, tmp_path):
        result = CliRunner().invoke(main, [
            "alphafold", "--protein", str(self._fasta(tmp_path)),
            "-o", str(tmp_path / "out"),
            "--af2-data-dir", "/data/alphafold", "--debug",
        ])
        assert result.exit_code == 0
        assert "run_alphafold.py" in result.output

    def test_explicit_alphafold_still_preflights(self):
        import json as _json

        result = CliRunner().invoke(
            main, ["preflight", "--tool", "alphafold", "--has-protein"]
        )
        assert result.exit_code == 0
        payload = _json.loads(result.output.strip().splitlines()[-1])
        assert payload["resolved_tool"] == "alphafold"

    def test_alphafold_adapter_is_still_registered(self):
        from predict_structure.adapters import get_adapter

        assert get_adapter("alphafold").tool_name == "alphafold"

    @staticmethod
    def _fasta(tmp_path):
        fasta = tmp_path / "p.fasta"
        fasta.write_text(">p\nMKTIIALSYIFCLVFA\n")
        return fasta


class TestAlphaFoldApiContractPinned:
    """#90 retires AlphaFold from auto and the UI but must keep API/CLI access.

    The declarative surfaces are what the BV-BRC API and CWL actually dispatch
    on, and nothing else in the suite reads them — so deleting "alphafold" from
    them would break API submissions with every test still green. That is
    precisely the mistake #90's docs make tempting, hence these guards.
    """

    def _repo_root(self):
        from pathlib import Path

        return Path(__file__).resolve().parent.parent

    def test_app_spec_tool_enum_still_offers_alphafold(self):
        import json

        spec = json.loads(
            (self._repo_root() / "app_specs" / "PredictStructure.json").read_text()
        )
        tool = next(p for p in spec["parameters"] if p["id"] == "tool")
        assert "alphafold" in tool["enum"], (
            "removing alphafold from the app-spec enum breaks API submissions "
            "with tool='alphafold', which #90 deliberately preserves"
        )

    def test_alphafold_mode_spec_still_present(self):
        assert (self._repo_root() / "app_specs" / "modes" / "alphafold.json").is_file()

    def test_cwl_tool_symbols_still_offer_alphafold(self):
        text = (self._repo_root() / "cwl" / "tools" / "predict-structure.cwl").read_text()
        assert "alphafold" in text, "CWL dispatch must keep the alphafold symbol"

    def test_adapter_and_subcommand_still_registered(self):
        from click.testing import CliRunner

        from predict_structure.adapters import get_adapter
        from predict_structure.cli import main

        assert get_adapter("alphafold").tool_name == "alphafold"
        assert CliRunner().invoke(main, ["alphafold", "--help"]).exit_code == 0
