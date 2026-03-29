"""AlphaFold 2 adapter for protein structure prediction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from predict_structure.adapters.base import BaseAdapter
from predict_structure.converters import entities_to_fasta
from predict_structure.entities import EntityList, EntityType
from predict_structure.normalizers import normalize_alphafold_output

logger = logging.getLogger(__name__)


class AlphaFoldAdapter(BaseAdapter):
    """Adapter for AlphaFold 2 protein structure prediction.

    AlphaFold 2 uses co-evolutionary features from MSA databases for
    high-accuracy structure prediction. Requires a data_dir (~2TB)
    containing UniRef90, Mgnify, BFD/small_BFD, PDB70/PDB_seqres,
    and template databases. All database paths are derived from
    data_dir automatically.
    """

    tool_name: str = "alphafold"
    supports_msa: bool = True
    requires_gpu: bool = True
    supported_entities: frozenset[EntityType] = frozenset({EntityType.PROTEIN})

    def __init__(self) -> None:
        self._use_precomputed_msas: bool = False

    def prepare_input(
        self,
        entity_list: EntityList,
        output_dir: Path,
        *,
        msa_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Convert entity list to plain FASTA. Flag precomputed MSA if provided."""
        if msa_path is not None and msa_path.is_dir():
            self._use_precomputed_msas = True
            logger.info("Using precomputed MSAs from %s", msa_path)

        output_dir.mkdir(parents=True, exist_ok=True)
        return entities_to_fasta(entity_list, output_dir / "input.fasta")

    def build_command(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        num_samples: int = 1,
        num_recycles: int = 3,
        seed: int | None = None,
        device: str = "gpu",
        **kwargs: Any,
    ) -> list[str]:
        """Construct the ``run_alphafold.py`` command with all database paths."""
        data_dir = kwargs.get("af2_data_dir")
        if not data_dir:
            raise ValueError(
                "AlphaFold requires --af2-data-dir pointing to the database directory (~2TB). "
                "See https://github.com/deepmind/alphafold#databases for setup."
            )
        data_dir = Path(data_dir)

        model_preset = kwargs.get("af2_model_preset", "monomer")
        db_preset = kwargs.get("af2_db_preset", "reduced_dbs")

        from predict_structure.config import get_command
        cmd = [
            *get_command("alphafold"),
            "--fasta_paths", str(input_path),
            "--output_dir", str(output_dir),
            "--data_dir", str(data_dir),
            "--uniref90_database_path", str(data_dir / "uniref90" / "uniref90.fasta"),
            "--mgnify_database_path", str(data_dir / "mgnify" / "mgy_clusters_2022_05.fa"),
            "--template_mmcif_dir", str(data_dir / "pdb_mmcif" / "mmcif_files"),
            "--obsolete_pdbs_path", str(data_dir / "pdb_mmcif" / "obsolete.dat"),
            "--model_preset", model_preset,
            "--db_preset", db_preset,
            "--max_template_date", kwargs.get("af2_max_template_date", "2022-01-01"),
        ]

        # Database paths depend on db_preset
        if db_preset == "reduced_dbs":
            cmd.extend([
                "--small_bfd_database_path",
                str(data_dir / "small_bfd" / "bfd-first_non_consensus_sequences.fasta"),
            ])
        else:  # full_dbs
            cmd.extend([
                "--bfd_database_path",
                str(data_dir / "bfd" / "bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt"),
                "--uniref30_database_path",
                str(data_dir / "uniref30" / "UniRef30_2021_03"),
            ])

        # Model-preset-specific databases
        if model_preset.startswith("monomer"):
            cmd.extend([
                "--pdb70_database_path",
                str(data_dir / "pdb70" / "pdb70"),
            ])
        elif model_preset == "multimer":
            cmd.extend([
                "--pdb_seqres_database_path",
                str(data_dir / "pdb_seqres" / "pdb_seqres.txt"),
                "--uniprot_database_path",
                str(data_dir / "uniprot" / "uniprot.fasta"),
            ])

        # GPU relax disabled by default (OpenMM compatibility issues on H100/H200)
        cmd.append("--nouse_gpu_relax")

        # Random seed
        if seed is not None:
            cmd.extend(["--random_seed", str(seed)])

        # Precomputed MSAs
        if self._use_precomputed_msas:
            cmd.append("--use_precomputed_msas=true")

        return cmd

    def run(self, command: list[str], **kwargs: Any) -> int:
        """Execute prediction via the configured backend."""
        backend = kwargs.get("backend")
        if backend is None:
            from predict_structure.backends.subprocess import SubprocessBackend
            backend = SubprocessBackend()
        return backend.run(command, tool_name=self.tool_name, **kwargs)

    def normalize_output(self, raw_output_dir: Path, output_dir: Path) -> Path:
        """Normalize AlphaFold output to standardized layout."""
        return normalize_alphafold_output(raw_output_dir, output_dir)

    def preflight(self) -> dict[str, Any]:
        return {
            "cpu": 8,
            "memory": "64G",
            "runtime": 28800,
            "storage": "100G",
            "policy_data": {
                "gpu_count": 1,
                "partition": "gpu2",
                "constraint": "A100|H100|H200",
            },
        }
