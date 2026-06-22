"""Phase 1: Native folding tool execution inside the container.

Tests each folding tool DIRECTLY (bypassing predict-structure) to establish
a baseline of what each tool can do on its own. This isolates tool behavior
from adapter/CLI behavior so we can detect differences.

Each test:
1. Prepares input in the tool's native format
2. Calls the tool binary directly via apptainer exec
3. Validates that output files were produced

Phase 2 then tests the same inputs through predict-structure to verify
the adapter layer doesn't change behavior.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml

from tests.acceptance.conftest import TEST_DATA
from tests.acceptance import matrix

pytestmark = [pytest.mark.phase1, pytest.mark.gpu, pytest.mark.container]

TEST_DATA_HOST = TEST_DATA

# Container-side paths
PROTEIN_FASTA = "/data/simple_protein.fasta"
DNA_FASTA = "/data/dna.fasta"
MSA_FILE = "/data/msa/crambin.a3m"

# Tier fixtures (T2 functional, T5 large) -- data/args come from matrix.py so
# the native tests stay in lock-step with the adapter-level matrix.
TIER2 = matrix.TIER2
TIER5 = matrix.TIER5


LOCAL_DATABASES = "/local_databases"


def _binds(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Standard bind mounts: test_data, output, and local_databases."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(exist_ok=True)
    return {
        str(TEST_DATA_HOST): "/data",
        str(output_dir): "/output",
        LOCAL_DATABASES: LOCAL_DATABASES,
    }, output_dir


def _read_fasta_sequence(container_path: str) -> str:
    """Read the single-record sequence from a tier FASTA fixture.

    The native tools embed sequences inline; tier tests instead pull the
    sequence from the bind-mounted FASTA (container path like
    ``/data/medium_protein.fasta``) by mapping it back to the host file.
    """
    host_path = TEST_DATA_HOST / Path(container_path).relative_to("/data")
    seq_lines: list[str] = []
    for line in host_path.read_text().splitlines():
        if line.startswith(">"):
            if seq_lines:
                break  # only the first record
            continue
        seq_lines.append(line.strip())
    return "".join(seq_lines)


# =========================================================================
# Boltz -- native CLI: boltz predict <input.yaml>
# =========================================================================

class TestBoltzNative:
    """Test boltz predict directly, bypassing predict-structure."""

    def _write_boltz_yaml(self, tmp_path: Path, sequences: list[dict],
                          msa: str | None = None) -> Path:
        """Write a Boltz YAML manifest."""
        if msa is not None:
            for seq in sequences:
                if "protein" in seq:
                    seq["protein"]["msa"] = msa
        manifest = {"version": 1, "sequences": sequences}
        yaml_path = tmp_path / "input.yaml"
        yaml_path.write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))
        return yaml_path

    def test_protein_with_msa(self, container, tmp_path):
        """Boltz with protein + MSA file -- expected to work."""
        binds, output_dir = _binds(tmp_path)
        yaml_host = self._write_boltz_yaml(tmp_path, [
            {"protein": {"id": "A", "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN",
                         "msa": MSA_FILE}},
        ])
        binds[str(yaml_host)] = "/input/input.yaml"

        result = container.exec(
            ["/opt/conda-boltz/bin/boltz", "predict", "/input/input.yaml",
             "--out_dir", "/output",
             "--diffusion_samples", "1",
             "--recycling_steps", "3",
             "--output_format", "mmcif",
             "--accelerator", "gpu"],
            gpu=True, binds=binds, timeout=1800,            env={"BOLTZ_CACHE": "/local_databases/boltz"},
        )
        assert result.returncode == 0, (
            f"boltz protein+msa failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_protein_no_msa(self, container, tmp_path):
        """Boltz with protein, no MSA, no msa:empty -- does boltz reject this?"""
        binds, output_dir = _binds(tmp_path)
        yaml_host = self._write_boltz_yaml(tmp_path, [
            {"protein": {"id": "A", "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN"}},
        ])
        binds[str(yaml_host)] = "/input/input.yaml"

        result = container.exec(
            ["/opt/conda-boltz/bin/boltz", "predict", "/input/input.yaml",
             "--out_dir", "/output",
             "--diffusion_samples", "1",
             "--recycling_steps", "3",
             "--output_format", "mmcif",
             "--accelerator", "gpu"],
            gpu=True, binds=binds, timeout=60,            env={"BOLTZ_CACHE": "/local_databases/boltz"},
        )
        # Document: does boltz reject protein without MSA?
        if result.returncode != 0:
            assert "Missing MSA" in result.stdout or "msa" in result.stdout.lower(), (
                f"Unexpected boltz failure: {result.stdout[-500:]}"
            )
            pytest.skip("Boltz requires MSA for protein (confirmed native behavior)")
        # If it passes, that's also valid info

    def test_protein_msa_empty(self, container, tmp_path):
        """Boltz with protein + msa:empty (single-sequence mode)."""
        binds, output_dir = _binds(tmp_path)
        yaml_host = self._write_boltz_yaml(tmp_path, [
            {"protein": {"id": "A", "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN",
                         "msa": "empty"}},
        ])
        binds[str(yaml_host)] = "/input/input.yaml"

        result = container.exec(
            ["/opt/conda-boltz/bin/boltz", "predict", "/input/input.yaml",
             "--out_dir", "/output",
             "--diffusion_samples", "1",
             "--recycling_steps", "3",
             "--output_format", "mmcif",
             "--accelerator", "gpu"],
            gpu=True, binds=binds, timeout=1800,            env={"BOLTZ_CACHE": "/local_databases/boltz"},
        )
        assert result.returncode == 0, (
            f"boltz protein+msa:empty failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_dna_only(self, container, tmp_path):
        """Boltz with DNA only -- no MSA should be needed."""
        binds, output_dir = _binds(tmp_path)
        yaml_host = self._write_boltz_yaml(tmp_path, [
            {"dna": {"id": "A", "sequence": "ACGTACGTACGTACGTACGT"}},
        ])
        binds[str(yaml_host)] = "/input/input.yaml"

        result = container.exec(
            ["/opt/conda-boltz/bin/boltz", "predict", "/input/input.yaml",
             "--out_dir", "/output",
             "--diffusion_samples", "1",
             "--recycling_steps", "3",
             "--output_format", "mmcif",
             "--accelerator", "gpu"],
            gpu=True, binds=binds, timeout=1800,            env={"BOLTZ_CACHE": "/local_databases/boltz"},
        )
        assert result.returncode == 0, (
            f"boltz dna-only failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier2
    def test_protein_t2_with_msa(self, container, tmp_path):
        """T2 functional: medium protein (~214 aa) + MSA file."""
        binds, output_dir = _binds(tmp_path)
        seq = _read_fasta_sequence(TIER2.fasta)
        yaml_host = self._write_boltz_yaml(tmp_path, [
            {"protein": {"id": "A", "sequence": seq, "msa": TIER2.msa}},
        ])
        binds[str(yaml_host)] = "/input/input.yaml"

        result = container.exec(
            ["/opt/conda-boltz/bin/boltz", "predict", "/input/input.yaml",
             "--out_dir", "/output",
             "--diffusion_samples", "1",
             "--recycling_steps", "3",
             "--output_format", "mmcif",
             "--accelerator", "gpu"],
            gpu=True, binds=binds, timeout=1800,
            env={"BOLTZ_CACHE": "/local_databases/boltz"},
        )
        assert result.returncode == 0, (
            f"boltz T2 protein+msa failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_protein_t5_large(self, container, tmp_path):
        """T5 large: ~434 aa protein + MSA file (scaling regression)."""
        binds, output_dir = _binds(tmp_path)
        seq = _read_fasta_sequence(TIER5.fasta)
        yaml_host = self._write_boltz_yaml(tmp_path, [
            {"protein": {"id": "A", "sequence": seq, "msa": TIER5.msa}},
        ])
        binds[str(yaml_host)] = "/input/input.yaml"

        result = container.exec(
            ["/opt/conda-boltz/bin/boltz", "predict", "/input/input.yaml",
             "--out_dir", "/output",
             "--diffusion_samples", "1",
             "--recycling_steps", "3",
             "--output_format", "mmcif",
             "--accelerator", "gpu"],
            gpu=True, binds=binds, timeout=3600,
            env={"BOLTZ_CACHE": "/local_databases/boltz"},
        )
        assert result.returncode == 0, (
            f"boltz T5 large failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )


# =========================================================================
# ESMFold -- native CLI: esm-fold-hf -i <fasta> -o <dir>
# =========================================================================

class TestESMFoldNative:
    """Test esm-fold-hf directly."""

    def test_protein(self, container, tmp_path):
        """ESMFold with protein FASTA -- baseline test."""
        binds, output_dir = _binds(tmp_path)

        result = container.exec(
            ["/opt/conda-esmfold/bin/esm-fold-hf",
             "-i", PROTEIN_FASTA,
             "-o", "/output",
             "--num-recycles", "4",
             "--fp16"],
            gpu=True, binds=binds, timeout=120,        )
        assert result.returncode == 0, (
            f"esm-fold-hf failed (rc={result.returncode}).\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
        # Check output: ESMFold writes PDB files directly
        pdbs = list(output_dir.glob("*.pdb"))
        assert len(pdbs) > 0, f"No PDB files in output: {list(output_dir.iterdir())}"

    def test_protein_cpu(self, container, tmp_path):
        """ESMFold on CPU."""
        binds, output_dir = _binds(tmp_path)

        result = container.exec(
            ["/opt/conda-esmfold/bin/esm-fold-hf",
             "-i", PROTEIN_FASTA,
             "-o", "/output",
             "--num-recycles", "4",
             "--cpu-only"],
            gpu=False, binds=binds, timeout=300,        )
        assert result.returncode == 0, (
            f"esm-fold-hf CPU failed (rc={result.returncode}).\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier2
    def test_protein_t2_with_msa(self, container, tmp_path):
        """T2 functional: ESMFold on the medium protein.

        ESMFold is a single-sequence model and ignores MSA entirely
        (``msa_args_for('esmfold', TIER2)`` is empty), so this folds the
        T2 FASTA directly with no MSA argument.
        """
        binds, output_dir = _binds(tmp_path)
        assert matrix.msa_args_for("esmfold", TIER2) == [], (
            "esmfold should ignore MSA in the tier matrix"
        )

        result = container.exec(
            ["/opt/conda-esmfold/bin/esm-fold-hf",
             "-i", TIER2.fasta,
             "-o", "/output",
             "--num-recycles", "4",
             "--fp16"],
            gpu=True, binds=binds, timeout=300,
        )
        assert result.returncode == 0, (
            f"esm-fold-hf T2 failed (rc={result.returncode}).\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
        pdbs = list(output_dir.glob("*.pdb"))
        assert len(pdbs) > 0, f"No PDB files in output: {list(output_dir.iterdir())}"


# =========================================================================
# Chai -- native CLI: chai-lab fold <fasta> <output_dir>
# =========================================================================

class TestChaiNative:
    """Test chai-lab fold directly.

    Chai requires entity-typed FASTA headers: >protein|name=A
    """

    def _write_chai_fasta(self, tmp_path: Path, entries: list[tuple[str, str, str]]) -> Path:
        """Write a Chai entity-typed FASTA.

        Args:
            entries: List of (entity_type, chain_id, sequence) tuples.
                     e.g. [("protein", "A", "MKTIIAL...")]
        """
        fasta_path = tmp_path / "input.fasta"
        lines = []
        for etype, cid, seq in entries:
            lines.append(f">{etype}|name={cid}")
            lines.append(seq)
        fasta_path.write_text("\n".join(lines) + "\n")
        return fasta_path

    def test_protein(self, container, tmp_path):
        """Chai with protein in entity-typed FASTA."""
        binds, output_dir = _binds(tmp_path)
        fasta = self._write_chai_fasta(tmp_path, [
            ("protein", "A", "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN"),
        ])
        binds[str(fasta)] = "/input/input.fasta"

        result = container.exec(
            ["/opt/conda-chai/bin/chai-lab", "fold",
             "/input/input.fasta", "/output",
             "--num-diffn-samples", "1",
             "--num-trunk-recycles", "3",
             "--num-diffn-timesteps", "200",
             "--device", "cuda"],
            gpu=True, binds=binds, timeout=1800,            env={"CHAI_DOWNLOADS_DIR": "/local_databases/chai"},
        )
        assert result.returncode == 0, (
            f"chai-lab protein failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_protein_with_msa(self, container, tmp_path):
        """Chai with protein + precomputed MSA file (.a3m)."""
        binds, output_dir = _binds(tmp_path)
        fasta = self._write_chai_fasta(tmp_path, [
            ("protein", "A", "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN"),
        ])
        binds[str(fasta)] = "/input/input.fasta"

        # Chai needs MSA as a directory containing .aligned.pqt files.
        # For this native test, pass the a3m via --msa-directory and let
        # Chai handle it, or convert manually. Chai CLI accepts --msa-directory.
        # We'll pass the raw MSA dir -- Chai may need .pqt format.
        # Use the a3m file directly via predict-structure's converter would be
        # adapter logic. For native test, skip if Chai rejects raw a3m.
        result = container.exec(
            ["/opt/conda-chai/bin/chai-lab", "fold",
             "/input/input.fasta", "/output",
             "--num-diffn-samples", "1",
             "--num-trunk-recycles", "3",
             "--num-diffn-timesteps", "200",
             "--msa-directory", "/data/msa",
             "--device", "cuda"],
            gpu=True, binds=binds, timeout=1800,            env={"CHAI_DOWNLOADS_DIR": "/local_databases/chai"},
        )
        assert result.returncode == 0, (
            f"chai-lab protein+msa failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_dna(self, container, tmp_path):
        """Chai with DNA only."""
        binds, output_dir = _binds(tmp_path)
        fasta = self._write_chai_fasta(tmp_path, [
            ("dna", "A", "ACGTACGTACGTACGTACGT"),
        ])
        binds[str(fasta)] = "/input/input.fasta"

        result = container.exec(
            ["/opt/conda-chai/bin/chai-lab", "fold",
             "/input/input.fasta", "/output",
             "--num-diffn-samples", "1",
             "--num-trunk-recycles", "3",
             "--num-diffn-timesteps", "200",
             "--device", "cuda"],
            gpu=True, binds=binds, timeout=1800,            env={"CHAI_DOWNLOADS_DIR": "/local_databases/chai"},
        )
        assert result.returncode == 0, (
            f"chai-lab dna failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier2
    def test_protein_t2_with_msa(self, container, tmp_path):
        """T2 functional: medium protein + precomputed MSA directory."""
        binds, output_dir = _binds(tmp_path)
        seq = _read_fasta_sequence(TIER2.fasta)
        fasta = self._write_chai_fasta(tmp_path, [
            ("protein", "A", seq),
        ])
        binds[str(fasta)] = "/input/input.fasta"

        # Chai consumes MSA from a directory of .a3m/.pqt files; the tier MSA
        # lives under /data/msa (matrix.msa_args_for confirms Chai uses it).
        assert matrix.msa_args_for("chai", TIER2) == ["--msa", TIER2.msa]
        msa_dir = str(Path(TIER2.msa).parent)
        result = container.exec(
            ["/opt/conda-chai/bin/chai-lab", "fold",
             "/input/input.fasta", "/output",
             "--num-diffn-samples", "1",
             "--num-trunk-recycles", "3",
             "--num-diffn-timesteps", "200",
             "--msa-directory", msa_dir,
             "--device", "cuda"],
            gpu=True, binds=binds, timeout=1800,
            env={"CHAI_DOWNLOADS_DIR": "/local_databases/chai"},
        )
        assert result.returncode == 0, (
            f"chai-lab T2 protein+msa failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )


# =========================================================================
# OpenFold -- native CLI: run_openfold predict --query-json <json>
# =========================================================================

class TestOpenFoldNative:
    """Test run_openfold predict directly.

    OpenFold 3 expects JSON in the format:
        {"queries": {"query_name": {"chains": [...], "use_msas": bool}}}
    """

    def _write_query_json(self, tmp_path: Path, chains: list[dict],
                          use_msas: bool = False) -> Path:
        """Write an OpenFold 3 query JSON in the correct schema."""
        query = {
            "queries": {
                "prediction": {
                    "chains": chains,
                    "use_msas": use_msas,
                }
            }
        }
        json_path = tmp_path / "query.json"
        json_path.write_text(json.dumps(query, indent=2))
        return json_path

    def test_protein(self, container, tmp_path):
        """OpenFold with protein query JSON."""
        binds, output_dir = _binds(tmp_path)

        query_host = self._write_query_json(tmp_path, [
            {"molecule_type": "protein",
             "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN",
             "chain_ids": "A"},
        ], use_msas=False)
        binds[str(query_host)] = "/input/query.json"

        result = container.exec(
            ["/opt/conda-openfold/bin/run_openfold", "predict",
             "--query-json", "/input/query.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--num-model-seeds", "1",
             "--use-msa-server", "False",
             "--use-templates", "False",
             "--inference-ckpt-path", "/local_databases/openfold/of3-p2-155k.pt"],
            gpu=True, binds=binds, timeout=1800,        )
        assert result.returncode == 0, (
            f"run_openfold protein failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_protein_with_msa(self, container, tmp_path):
        """OpenFold with protein + precomputed MSA file."""
        binds, output_dir = _binds(tmp_path)

        query_host = self._write_query_json(tmp_path, [
            {"molecule_type": "protein",
             "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN",
             "chain_ids": "A",
             "main_msa_file_paths": [MSA_FILE]},
        ], use_msas=False)
        binds[str(query_host)] = "/input/query.json"

        result = container.exec(
            ["/opt/conda-openfold/bin/run_openfold", "predict",
             "--query-json", "/input/query.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--num-model-seeds", "1",
             "--use-msa-server", "False",
             "--use-templates", "False",
             "--inference-ckpt-path", "/local_databases/openfold/of3-p2-155k.pt"],
            gpu=True, binds=binds, timeout=1800,        )
        assert result.returncode == 0, (
            f"run_openfold protein+msa failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    def test_dna(self, container, tmp_path):
        """OpenFold with DNA only."""
        binds, output_dir = _binds(tmp_path)

        query_host = self._write_query_json(tmp_path, [
            {"molecule_type": "dna",
             "sequence": "ACGTACGTACGTACGTACGT",
             "chain_ids": "A"},
        ], use_msas=False)
        binds[str(query_host)] = "/input/query.json"

        result = container.exec(
            ["/opt/conda-openfold/bin/run_openfold", "predict",
             "--query-json", "/input/query.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--num-model-seeds", "1",
             "--use-msa-server", "False",
             "--use-templates", "False",
             "--inference-ckpt-path", "/local_databases/openfold/of3-p2-155k.pt"],
            gpu=True, binds=binds, timeout=1800,        )
        assert result.returncode == 0, (
            f"run_openfold dna failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier2
    def test_protein_t2_with_msa(self, container, tmp_path):
        """T2 functional: medium protein + precomputed MSA file."""
        binds, output_dir = _binds(tmp_path)

        query_host = self._write_query_json(tmp_path, [
            {"molecule_type": "protein",
             "sequence": _read_fasta_sequence(TIER2.fasta),
             "chain_ids": "A",
             "main_msa_file_paths": [TIER2.msa]},
        ], use_msas=False)
        binds[str(query_host)] = "/input/query.json"

        result = container.exec(
            ["/opt/conda-openfold/bin/run_openfold", "predict",
             "--query-json", "/input/query.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--num-model-seeds", "1",
             "--use-msa-server", "False",
             "--use-templates", "False",
             "--inference-ckpt-path", "/local_databases/openfold/of3-p2-155k.pt"],
            gpu=True, binds=binds, timeout=1800,
        )
        assert result.returncode == 0, (
            f"run_openfold T2 protein+msa failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_protein_t5_large(self, container, tmp_path):
        """T5 large: ~434 aa protein + MSA file (scaling regression)."""
        binds, output_dir = _binds(tmp_path)

        query_host = self._write_query_json(tmp_path, [
            {"molecule_type": "protein",
             "sequence": _read_fasta_sequence(TIER5.fasta),
             "chain_ids": "A",
             "main_msa_file_paths": [TIER5.msa]},
        ], use_msas=False)
        binds[str(query_host)] = "/input/query.json"

        result = container.exec(
            ["/opt/conda-openfold/bin/run_openfold", "predict",
             "--query-json", "/input/query.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--num-model-seeds", "1",
             "--use-msa-server", "False",
             "--use-templates", "False",
             "--inference-ckpt-path", "/local_databases/openfold/of3-p2-155k.pt"],
            gpu=True, binds=binds, timeout=3600,
        )
        assert result.returncode == 0, (
            f"run_openfold T5 large failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )


# =========================================================================
# AlphaFold -- native CLI: python run_alphafold.py --fasta_paths ...
# =========================================================================

class TestAlphaFoldNative:
    """Test run_alphafold.py directly."""

    @pytest.mark.slow
    def test_protein(self, container, tmp_path):
        """AlphaFold with protein FASTA + reduced_dbs."""
        binds, output_dir = _binds(tmp_path)
        data_dir = "/local_databases/alphafold/databases"

        result = container.exec(
            ["/opt/conda-alphafold/bin/python", "/app/alphafold/run_alphafold.py",
             "--fasta_paths", PROTEIN_FASTA,
             "--output_dir", "/output",
             "--data_dir", data_dir,
             "--uniref90_database_path", f"{data_dir}/uniref90/uniref90.fasta",
             "--mgnify_database_path", f"{data_dir}/mgnify/mgy_clusters_2022_05.fa",
             "--template_mmcif_dir", f"{data_dir}/pdb_mmcif/mmcif_files",
             "--obsolete_pdbs_path", f"{data_dir}/pdb_mmcif/obsolete.dat",
             "--model_preset", "monomer",
             "--db_preset", "reduced_dbs",
             "--small_bfd_database_path", f"{data_dir}/small_bfd/bfd-first_non_consensus_sequences.fasta",
             "--pdb70_database_path", f"{data_dir}/pdb70/pdb70",
             "--max_template_date", "2022-01-01",
             "--nouse_gpu_relax",
             "--random_seed", "42"],
            gpu=True, binds=binds, timeout=3600,        )
        assert result.returncode == 0, (
            f"run_alphafold.py failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    @pytest.mark.tier2
    @pytest.mark.slow
    def test_protein_t2_with_msa(self, container, tmp_path):
        """T2 functional: medium protein. AlphaFold builds its own MSA from
        the bound database, so no --msa arg is passed (msa_args_for is [])."""
        binds, output_dir = _binds(tmp_path)
        data_dir = "/local_databases/alphafold/databases"
        assert matrix.msa_args_for("alphafold", TIER2) == [], (
            "AlphaFold builds its own MSA; no --msa arg expected"
        )

        result = container.exec(
            ["/opt/conda-alphafold/bin/python", "/app/alphafold/run_alphafold.py",
             "--fasta_paths", TIER2.fasta,
             "--output_dir", "/output",
             "--data_dir", data_dir,
             "--uniref90_database_path", f"{data_dir}/uniref90/uniref90.fasta",
             "--mgnify_database_path", f"{data_dir}/mgnify/mgy_clusters_2022_05.fa",
             "--template_mmcif_dir", f"{data_dir}/pdb_mmcif/mmcif_files",
             "--obsolete_pdbs_path", f"{data_dir}/pdb_mmcif/obsolete.dat",
             "--model_preset", "monomer",
             "--db_preset", "reduced_dbs",
             "--small_bfd_database_path", f"{data_dir}/small_bfd/bfd-first_non_consensus_sequences.fasta",
             "--pdb70_database_path", f"{data_dir}/pdb70/pdb70",
             "--max_template_date", "2022-01-01",
             "--nouse_gpu_relax",
             "--random_seed", "42"],
            gpu=True, binds=binds, timeout=7200,
        )
        assert result.returncode == 0, (
            f"run_alphafold.py T2 failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )


# =========================================================================
# ESMFold2 -- native runner: python -m predict_structure.runners.esmfold2
#   ESMFold2 ships only a Python API; the in-repo argparse runner consumes
#   a JSON spec ({"sequences": [{"id","type","sequence"}]}) and ignores MSA.
# =========================================================================

class TestESMFold2Native:
    """Test the ESMFold2 runner directly (single-sequence, no MSA)."""

    def _write_spec(self, tmp_path: Path, sequences: list[dict]) -> Path:
        """Write an ESMFold2 input spec JSON."""
        spec_path = tmp_path / "input.json"
        spec_path.write_text(json.dumps({"sequences": sequences}, indent=2))
        return spec_path

    def test_protein(self, container, tmp_path):
        """ESMFold2 with a single protein (smoke)."""
        binds, output_dir = _binds(tmp_path)
        spec_host = self._write_spec(tmp_path, [
            {"id": "A", "type": "protein",
             "sequence": "TTCCPSIVARSNFNVCRLPGTPEALCATYTGCIIIPGATCPGDYAN"},
        ])
        binds[str(spec_host)] = "/input/input.json"

        result = container.exec(
            ["/opt/conda-esmfold2/bin/python", "-m",
             "predict_structure.runners.esmfold2",
             "--spec", "/input/input.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--seed", "42"],
            gpu=True, binds=binds, timeout=600,
            env={"HF_HOME": "/local_databases/esmfold2"},
        )
        assert result.returncode == 0, (
            f"esmfold2 protein failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
        cifs = list(output_dir.glob("*.cif"))
        assert len(cifs) > 0, f"No .cif files in output: {list(output_dir.iterdir())}"

    @pytest.mark.tier2
    def test_protein_t2_with_msa(self, container, tmp_path):
        """T2 functional: ESMFold2 on the medium protein.

        ESMFold2 is single-sequence and ignores MSA (msa_args_for is []),
        so this folds the T2 sequence directly with no MSA argument.
        """
        binds, output_dir = _binds(tmp_path)
        assert matrix.msa_args_for("esmfold2", TIER2) == []
        spec_host = self._write_spec(tmp_path, [
            {"id": "A", "type": "protein",
             "sequence": _read_fasta_sequence(TIER2.fasta)},
        ])
        binds[str(spec_host)] = "/input/input.json"

        result = container.exec(
            ["/opt/conda-esmfold2/bin/python", "-m",
             "predict_structure.runners.esmfold2",
             "--spec", "/input/input.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--seed", "42"],
            gpu=True, binds=binds, timeout=900,
            env={"HF_HOME": "/local_databases/esmfold2"},
        )
        assert result.returncode == 0, (
            f"esmfold2 T2 failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
        cifs = list(output_dir.glob("*.cif"))
        assert len(cifs) > 0, f"No .cif files in output: {list(output_dir.iterdir())}"

    @pytest.mark.tier5
    @pytest.mark.slow
    def test_protein_t5_large(self, container, tmp_path):
        """T5 large: ESMFold2 on the ~434 aa protein (scaling regression)."""
        binds, output_dir = _binds(tmp_path)
        spec_host = self._write_spec(tmp_path, [
            {"id": "A", "type": "protein",
             "sequence": _read_fasta_sequence(TIER5.fasta)},
        ])
        binds[str(spec_host)] = "/input/input.json"

        result = container.exec(
            ["/opt/conda-esmfold2/bin/python", "-m",
             "predict_structure.runners.esmfold2",
             "--spec", "/input/input.json",
             "--output-dir", "/output",
             "--num-diffusion-samples", "1",
             "--seed", "42"],
            gpu=True, binds=binds, timeout=1800,
            env={"HF_HOME": "/local_databases/esmfold2"},
        )
        assert result.returncode == 0, (
            f"esmfold2 T5 large failed (rc={result.returncode}).\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
        cifs = list(output_dir.glob("*.cif"))
        assert len(cifs) > 0, f"No .cif files in output: {list(output_dir.iterdir())}"
