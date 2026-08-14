"""Tests for the ESMFold2 adapter — spec conversion, command construction, normalization.

Mirrors the style of ``TestESMFoldAdapter`` in ``tests/test_adapters.py``. All
tests are hermetic: no GPU, no network, no real model — they exercise the
conversion / command / normalization logic only.
"""

import json
import logging

import pytest

from predict_structure.entities import EntityList, EntityType


class TestESMFold2Adapter:
    def test_prepare_input_creates_json(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        result = adapter.prepare_input(protein_entity_list, tmp_output)

        assert result.suffix == ".json"
        assert result.name == "input.json"
        assert result.exists()

        data = json.loads(result.read_text())
        assert "sequences" in data
        assert len(data["sequences"]) == 1
        rec = data["sequences"][0]
        assert rec["type"] == "protein"
        assert rec["sequence"].startswith("TTCCPS")
        assert rec["id"]  # chain id assigned during conversion

    def test_prepare_input_multi_entity(self, multi_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        result = adapter.prepare_input(multi_entity_list, tmp_output)

        data = json.loads(result.read_text())
        seqs = data["sequences"]
        assert len(seqs) == 2
        assert seqs[0]["type"] == "protein"
        assert seqs[0]["sequence"] == "MKTIIALSY"
        assert seqs[1]["type"] == "ligand"
        # CCD ligand is rendered as a one-element ccd list
        assert seqs[1]["ccd"] == ["ATP"]

    def test_prepare_input_smiles_ligand(self, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSY", name="protA")
        el.add(EntityType.SMILES, "CCO", name="ethanol")

        adapter = ESMFold2Adapter()
        result = adapter.prepare_input(el, tmp_output)

        seqs = json.loads(result.read_text())["sequences"]
        assert seqs[1]["type"] == "ligand"
        assert seqs[1]["smiles"] == "CCO"
        assert "ccd" not in seqs[1]

    def test_build_command_defaults(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(prepared, tmp_output / "raw")

        # Runner invocation: python -m predict_structure.runners.esmfold2
        assert "predict_structure.runners.esmfold2" in cmd
        assert cmd[cmd.index("-m") + 1] == "predict_structure.runners.esmfold2"
        assert "--spec" in cmd
        assert cmd[cmd.index("--spec") + 1] == str(prepared)
        assert "--output-dir" in cmd
        assert cmd[cmd.index("--output-dir") + 1] == str(tmp_output / "raw")
        # Defaults: num_recycles=3 -> --num-loops, num_samples=5 -> --num-diffusion-samples
        assert cmd[cmd.index("--num-loops") + 1] == "3"
        assert cmd[cmd.index("--num-diffusion-samples") + 1] == "5"
        assert cmd[cmd.index("--num-sampling-steps") + 1] == "50"
        assert cmd[cmd.index("--checkpoint") + 1] == "biohub/ESMFold2"
        # No seed / cpu flag by default
        assert "--seed" not in cmd
        assert "--cpu-only" not in cmd

    def test_build_command_custom(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        prepared = adapter.prepare_input(protein_entity_list, tmp_output)
        cmd = adapter.build_command(
            prepared, tmp_output / "raw",
            num_samples=3, num_recycles=6, seed=42, device="cpu",
            sampling_steps=80, checkpoint="biohub/ESMFold2-mini",
        )

        assert cmd[cmd.index("--num-loops") + 1] == "6"
        assert cmd[cmd.index("--num-diffusion-samples") + 1] == "3"
        assert cmd[cmd.index("--num-sampling-steps") + 1] == "80"
        assert cmd[cmd.index("--checkpoint") + 1] == "biohub/ESMFold2-mini"
        assert cmd[cmd.index("--seed") + 1] == "42"
        assert "--cpu-only" in cmd

    def test_msa_is_attached_to_the_matching_chain(self, tmp_output, tmp_path):
        """An uploaded A3M lands on the protein chain its query row describes."""
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        seq = "MKTIIALSY"
        a3m = tmp_path / "aln.a3m"
        a3m.write_text(f">query\n{seq}\n>hit1\nMKTIIALSF\n>hit2\nMKTLIALSY\n")

        el = EntityList()
        el.add(EntityType.PROTEIN, seq, name="protA")
        result = ESMFold2Adapter().prepare_input(el, tmp_output, msa_path=a3m)

        rec = json.loads(result.read_text())["sequences"][0]
        assert rec["msa"] == str(a3m)

    def test_a3m_insertions_are_ignored_when_matching(self, tmp_output, tmp_path):
        """Lowercase insertion columns and gaps must not defeat the match.

        Real A3Ms mark insertions relative to the query in lowercase; the query
        row therefore is not literally the chain sequence.
        """
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        a3m = tmp_path / "aln.a3m"
        a3m.write_text(
            ">query\n"
            "MKTiiIALSY-\n"      # 'ii' insertions + a trailing gap
            ">hit\n"
            "MKT--IALSF-\n"
        )
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIALSY", name="protA")
        result = ESMFold2Adapter().prepare_input(el, tmp_output, msa_path=a3m)
        assert json.loads(result.read_text())["sequences"][0]["msa"] == str(a3m)

    def test_mismatched_msa_is_rejected_not_dropped(self, tmp_output, tmp_path):
        """A wrong MSA must fail loudly rather than fold single-sequence (#95)."""
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        a3m = tmp_path / "other.a3m"
        a3m.write_text(">query\nWWWWWWWWWWWW\n>hit\nWWWWWWWWWWWY\n")
        el = EntityList()
        el.add(EntityType.PROTEIN, "MKTIIALSY", name="protA")
        with pytest.raises(ValueError, match="does not match any protein chain"):
            ESMFold2Adapter().prepare_input(el, tmp_output, msa_path=a3m)

    def test_msa_without_protein_chain_is_rejected(self, tmp_output, tmp_path):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        a3m = tmp_path / "aln.a3m"
        a3m.write_text(">query\nMKTIIALSY\n")
        el = EntityList()
        el.add(EntityType.SMILES, "CCO", name="ethanol")
        with pytest.raises(ValueError, match="no protein chain"):
            ESMFold2Adapter().prepare_input(el, tmp_output, msa_path=a3m)

    def test_no_msa_leaves_the_field_absent(self, protein_entity_list, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        result = ESMFold2Adapter().prepare_input(protein_entity_list, tmp_output)
        assert "msa" not in json.loads(result.read_text())["sequences"][0]

    def test_supported_entities(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        assert EntityType.PROTEIN in adapter.supported_entities
        assert EntityType.DNA in adapter.supported_entities
        assert EntityType.RNA in adapter.supported_entities
        assert EntityType.LIGAND in adapter.supported_entities
        assert EntityType.SMILES in adapter.supported_entities

    def test_validate_entities_ok(self, multi_entity_list):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        adapter.validate_entities(multi_entity_list)  # should not raise

    def test_requires_gpu(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        assert ESMFold2Adapter.requires_gpu is True

    def test_supports_msa(self):
        """True since #95 — uploaded A3Ms are wired through to ProteinInput.msa.

        Server-side fetching is still absent (esm ships no client, #96), which
        is why the service script still withholds --use-msa-server.
        """
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        assert ESMFold2Adapter.supports_msa is True

    def test_preflight(self):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        pf = ESMFold2Adapter().preflight()
        assert pf["cpu"] == 8
        assert pf["memory"] == "32G"
        assert pf["policy_data"]["partition"] == "gpu2"
        assert pf["policy_data"]["gpu_count"] == 1
        # H200 only: torch+cu130 needs driver >= 580 (#38, #75)
        assert pf["policy_data"]["constraint"] == "H200"

    def test_normalize_output(self, tmp_path, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter
        from predict_structure.converters import pdb_to_mmcif

        raw = tmp_path / "raw"
        raw.mkdir()

        # Build a minimal CIF fixture the way other normalize tests do.
        pdb_content = (
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.91           C\n"
            "ATOM      2  CA  GLY A   2       4.000   5.000   6.000  1.00  0.88           C\n"
            "END\n"
        )
        pdb_tmp = raw / "temp.pdb"
        pdb_tmp.write_text(pdb_content)
        pdb_to_mmcif(pdb_tmp, raw / "model_1.cif")
        pdb_tmp.unlink()

        # Runner-produced confidence summary; pLDDT on 0-1 scale.
        (raw / "confidence.json").write_text(json.dumps({
            "plddt": 0.895,
            "per_residue_plddt": [0.91, 0.88],
            "ptm": 0.92,
            "iptm": 0.80,
        }))

        adapter = ESMFold2Adapter()
        adapter.normalize_output(raw, tmp_output)

        # Canonical files under predictions/
        assert (tmp_output / "predictions" / "model_1.cif").exists()
        assert (tmp_output / "predictions" / "model_1.pdb").exists()
        conf_path = tmp_output / "predictions" / "confidence.json"
        assert conf_path.exists()
        assert (tmp_output / "raw").exists()
        # Best model promoted to top level
        assert (tmp_output / "model_1.pdb").exists()

        conf = json.loads(conf_path.read_text())
        # pLDDT scaled from 0-1 to 0-100
        assert conf["per_residue_plddt"][0] == 91.0
        assert conf["plddt_mean"] == 89.5
        assert conf["ptm"] == 0.92
        # ipTM persisted alongside the standard confidence file
        assert conf["iptm"] == 0.8

    def test_normalize_output_missing_cif_raises(self, tmp_path, tmp_output):
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        raw = tmp_path / "raw"
        raw.mkdir()
        adapter = ESMFold2Adapter()
        with pytest.raises(FileNotFoundError, match="No .cif"):
            adapter.normalize_output(raw, tmp_output)


class TestESMFold2SchedulingContract:
    """Scheduling facts verified by real GPU runs on 2026-08-13 (#75).

    Four predictions in folding_260813.2.sif on coconut (H200) measured a peak
    of 13.9-14.0 GB allocated / 14.1-14.3 GB reserved.
    """

    def test_vram_floor_exceeds_measured_peak(self):
        from predict_structure.adapters.base import BaseAdapter
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        adapter = ESMFold2Adapter()
        assert adapter.min_gpu_memory_mb > 14_500, (
            "measured peak is ~14 GB; a lower floor lets the GPU precheck pass "
            "a host that will then OOM"
        )
        assert adapter.min_gpu_memory_mb != BaseAdapter.min_gpu_memory_mb, (
            "must not silently inherit the 8000 MiB default"
        )

    def test_constraint_is_h200_only(self):
        """torch+cu130 needs driver >= 580 — only coconut has it (#38)."""
        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        constraint = ESMFold2Adapter().preflight()["policy_data"]["constraint"]
        assert constraint == "H200"
        assert "A100" not in constraint, "no A100 host exists in the cluster"

    def test_perl_service_constraint_matches_adapter(self):
        """The Perl carries its own copy; drift would silently misschedule."""
        import re
        from pathlib import Path

        from predict_structure.adapters.esmfold2 import ESMFold2Adapter

        perl = (Path(__file__).resolve().parent.parent
                / "service-scripts" / "App-PredictStructure.pl").read_text()
        block = re.search(r'\$tool eq "esmfold2".*?\n    \}', perl, re.S)
        assert block, "esmfold2 preflight block not found in the service script"
        expected = ESMFold2Adapter().preflight()["policy_data"]["constraint"]
        assert f"constraint => '{expected}'" in block.group(0)


class TestMsaServerFlagContract:
    """The Perl must not pass --use-msa-server to a tool that has no such option.

    The Perl passing it to esmfold2 made click exit 2 and killed every ESMFold2
    job through BV-BRC (#75); it went unnoticed because ESMFold2 had no matrix
    coverage. The invariant is about the CLI surface, not about whether a model
    understands MSAs: biohub/ESMFold2 does accept per-chain MSAs, it simply has
    no server to fetch them from. So this pins the exclusion list against which
    subcommands actually expose the flag.
    """

    def _exclusion_regex(self):
        import re
        from pathlib import Path

        perl = (Path(__file__).resolve().parent.parent
                / "service-scripts" / "App-PredictStructure.pl").read_text()
        m = re.search(r'\$tool !~ /\^\(([^)]+)\)\$/', perl)
        assert m, "MSA-server exclusion regex not found in the service script"
        return set(m.group(1).split("|"))

    def test_every_tool_lacking_the_flag_is_excluded(self):
        """Any subcommand without the option must be in the exclusion list."""
        from click.testing import CliRunner

        from predict_structure.adapters import ADAPTERS
        from predict_structure.cli import main

        excluded = self._exclusion_regex()
        runner = CliRunner()
        missing = set()
        for name in ADAPTERS:
            result = runner.invoke(main, [name, "--help"])
            if result.exit_code != 0:
                continue  # no subcommand for this adapter
            if "--use-msa-server" not in result.output and name not in excluded:
                missing.add(name)
        assert not missing, (
            f"{sorted(missing)} have no --use-msa-server option but the service "
            f"script would still pass it, which click rejects with exit 2"
        )

    def test_excluded_tools_really_lack_the_option(self):
        """Guards the converse: don't exclude a tool that does support MSA."""
        from click.testing import CliRunner

        from predict_structure.cli import main

        for tool in self._exclusion_regex():
            result = CliRunner().invoke(main, [tool, "--help"])
            assert result.exit_code == 0, f"{tool} --help failed"
            if tool == "alphafold":
                continue  # excluded for local-DB reasons, not a missing option
            assert "--use-msa-server" not in result.output, (
                f"{tool} is excluded from the MSA-server flag but its CLI "
                f"accepts it — the exclusion may be wrong"
            )


class TestRunnerBuildsProteinInput:
    """Cover the runner half of #95.

    The adapter-side tests only inspect the JSON spec. Without these, deleting
    the runner's MSA loading entirely left the suite green — the code that
    actually delivers the feature was untested.

    These use a stub esm module rather than the real one so they run without a
    GPU or the container; the real library is exercised separately.
    """

    def _stub_esm(self, monkeypatch, *, protein_accepts_msa=True):
        import sys
        import types
        from dataclasses import dataclass, field
        from typing import Any, Optional

        @dataclass
        class _MSA:
            sequences: list

            @classmethod
            def from_a3m(cls, path, remove_insertions=True):
                seqs, cur = [], []
                for line in open(path):
                    line = line.strip()
                    if line.startswith(">"):
                        if cur:
                            seqs.append("".join(cur)); cur = []
                    elif line:
                        cur.append(line)
                if cur:
                    seqs.append("".join(cur))
                return cls(sequences=seqs)

        if protein_accepts_msa:
            @dataclass
            class _ProteinInput:
                id: str
                sequence: str
                modifications: Any = None
                msa: Optional[_MSA] = None
        else:
            # Mirrors an esm build whose ProteinInput predates MSA support,
            # e.g. a single-sequence variant.
            @dataclass
            class _ProteinInput:
                id: str
                sequence: str
                modifications: Any = None

        @dataclass
        class _Other:
            id: str
            sequence: str = ""
            modifications: Any = None
            ccd: Any = None
            smiles: Any = None

        mod = types.ModuleType("esm.models.esmfold2")
        mod.ProteinInput = _ProteinInput
        mod.DNAInput = _Other
        mod.RNAInput = _Other
        mod.LigandInput = _Other
        mod.Modification = None
        mod.MSA = _MSA if protein_accepts_msa else None
        pkg = types.ModuleType("esm.models"); pkg.esmfold2 = mod
        root = types.ModuleType("esm"); root.models = pkg
        monkeypatch.setitem(sys.modules, "esm", root)
        monkeypatch.setitem(sys.modules, "esm.models", pkg)
        monkeypatch.setitem(sys.modules, "esm.models.esmfold2", mod)
        return mod

    def test_msa_reaches_protein_input(self, monkeypatch, tmp_path):
        """The whole point of #95: the MSA must land on ProteinInput."""
        from predict_structure.runners.esmfold2 import _build_inputs

        self._stub_esm(monkeypatch)
        a3m = tmp_path / "a.a3m"
        a3m.write_text(">q\nMKTIIALSY\n>h\nMKTIIALSF\n")
        spec = {"sequences": [
            {"id": "A", "type": "protein", "sequence": "MKTIIALSY", "msa": str(a3m)},
        ]}
        built = _build_inputs(spec)
        assert built[0].msa is not None, "MSA was not passed to ProteinInput"
        assert len(built[0].msa.sequences) == 2

    def test_no_msa_leaves_it_unset(self, monkeypatch):
        from predict_structure.runners.esmfold2 import _build_inputs

        self._stub_esm(monkeypatch)
        spec = {"sequences": [{"id": "A", "type": "protein", "sequence": "MKTIIALSY"}]}
        assert _build_inputs(spec)[0].msa is None

    def test_msa_less_job_works_on_an_esm_without_the_field(self, monkeypatch):
        """Regression: msa= must not be passed when the spec has no MSA.

        Passing it unconditionally broke every ESMFold2 job — not just MSA ones
        — on any esm build whose ProteinInput lacks the field.
        """
        from predict_structure.runners.esmfold2 import _build_inputs

        self._stub_esm(monkeypatch, protein_accepts_msa=False)
        spec = {"sequences": [{"id": "A", "type": "protein", "sequence": "MKTIIALSY"}]}
        built = _build_inputs(spec)          # must not raise TypeError
        assert built[0].sequence == "MKTIIALSY"

    def test_unreadable_msa_names_the_chain(self, monkeypatch):
        import pytest

        from predict_structure.runners.esmfold2 import _build_inputs

        self._stub_esm(monkeypatch)
        spec = {"sequences": [
            {"id": "B", "type": "protein", "sequence": "MKTIIALSY", "msa": "/nope/gone.a3m"},
        ]}
        with pytest.raises(ValueError, match="chain 'B'"):
            _build_inputs(spec)


class TestHFCacheProbeContract:
    """The service script must pick an HF cache by CONTENT, not writability.

    Regression for task 23418633: the probe tested `-w` on the cache root, so a
    worker where /local_databases/esmfold failed that test fell through to
    /local_databases/cache — which holds facebook/esmfold_v1 but not
    biohub/ESMFold2. ESMFold worked, every ESMFold2 job died offline against a
    cache lacking the model, and the choice was only logged under P3_DEBUG.
    """

    def _perl(self):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent
                / "service-scripts" / "App-PredictStructure.pl").read_text()

    def test_probe_checks_the_model_directory(self):
        perl = self._perl()
        assert "models--biohub--ESMFold2" in perl, (
            "the probe must look for the ESMFold2 repo dir, not just a writable root"
        )
        assert "models--facebook--esmfold_v1" in perl

    def test_probe_requires_the_esmc_encoder_too(self):
        """ESMFold2 loads an ESMC-6B encoder (24G) besides its own 1.3G weights.

        Checking only the headline repo selected a cache holding ESMFold2 but
        not ESMC, which failed one layer deeper at model-load with the same
        opaque "couldn't connect" error (task 23418786).
        """
        import re

        perl = self._perl()
        block = re.search(r"# Ensure the HuggingFace cache.*?\n    \}\n", perl, re.S).group(0)
        m = re.search(r"esmfold2\s*=>\s*\[([^\]]+)\]", block)
        assert m, "esmfold2 repo list not found"
        repos = m.group(1)
        assert "models--biohub--ESMFold2" in repos
        assert "models--biohub--ESMC-6B" in repos, (
            "ESMFold2 cannot load without the ESMC encoder; a cache missing it "
            "must not be selected"
        )

    def test_probe_does_not_gate_on_writability(self):
        """HF_HUB_OFFLINE means we only ever read; -w rejects good read-only caches."""
        import re

        perl = self._perl()
        block = re.search(r"# Ensure the HuggingFace cache.*?\n    \}\n", perl, re.S)
        assert block, "HF cache block not found"
        assert "-w " not in block.group(0), (
            "the HF cache probe must not test writability — that is what sent "
            "ESMFold2 jobs to a cache without the model"
        )

    def test_per_tool_directory_is_preferred(self):
        """/local_databases/<tool> wins over the shared cache.

        Those dirs are owned by the service account and are independently
        updatable per tool; the shared cache is the fallback. Depending on a
        personal account's group permissions for production weights is what
        broke ESMFold2 in the first place.
        """
        import re

        perl = self._perl()
        # Match the candidate list itself, not the prose above it — the comment
        # mentions /local_databases/cache while explaining the old bug.
        decl = re.search(r"my \@hf_candidates\s*=(.*?);", perl, re.S)
        assert decl, "candidate list not found"
        listing = decl.group(1)
        i_tool = listing.index("/local_databases/$hf_tool")
        i_cache = listing.index("/local_databases/cache")
        assert i_tool < i_cache, (
            f"the tool's own directory must be probed before the shared cache: {listing}"
        )

    def test_cache_choice_is_logged_unconditionally(self):
        """The silent pick is what made this cost a production job to diagnose."""
        import re

        perl = self._perl()
        block = re.search(r"# Ensure the HuggingFace cache.*?\n    \}\n", perl, re.S).group(0)
        for line in block.splitlines():
            if "Set HF_HOME=" in line or "Set HF_HUB_OFFLINE" in line:
                assert "P3_DEBUG" not in line, f"cache choice still debug-gated: {line.strip()}"


class TestAutoToolHFCache:
    """`auto` is resolved by the CLI *after* the Perl picks a cache.

    The probe therefore sees tool="auto". Without an entry it verified nothing
    and accepted any existing directory — so an auto job that resolved to
    ESMFold could be handed a cache without esmfold_v1 and then fail offline.
    """

    def test_auto_requires_the_esmfold_weights(self):
        import re
        from pathlib import Path

        perl = (Path(__file__).resolve().parent.parent
                / "service-scripts" / "App-PredictStructure.pl").read_text()
        block = re.search(r"# Ensure the HuggingFace cache.*?\n    \}\n", perl, re.S).group(0)
        m = re.search(r"auto\s*=>\s*\[([^\]]+)\]", block)
        assert m, "auto has no repo list — the probe would verify nothing for auto jobs"
        assert "models--facebook--esmfold_v1" in m.group(1)

    def test_auto_cannot_resolve_to_esmfold2(self):
        """If that ever changes, auto's repo list must gain ESMC-6B too."""
        import inspect

        from predict_structure import cli

        src = inspect.getsource(cli._auto_select_tool)
        tuple_src = src.split("for tool in (")[1].split(")")[0]
        assert "esmfold2" not in tuple_src, (
            "auto can now pick esmfold2 — add its repos to %REPOS_FOR_TOOL{auto} "
            "in App-PredictStructure.pl or auto jobs will fail offline"
        )
