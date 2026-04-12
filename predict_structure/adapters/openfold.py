"""OpenFold 3 adapter for biomolecular structure prediction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from predict_structure.adapters.base import BaseAdapter
from predict_structure.converters import entities_to_openfold_json
from predict_structure.entities import EntityList, EntityType
from predict_structure.normalizers import normalize_openfold_output

logger = logging.getLogger(__name__)


class OpenFoldAdapter(BaseAdapter):
    """Adapter for OpenFold 3 biomolecular structure prediction.

    OpenFold 3 is an open-source (Apache 2.0) reproduction of AlphaFold 3.
    It supports protein, DNA, RNA, and ligand complexes via a structured
    JSON input format with diffusion-based structure generation.

    Key differences from other adapters:
      - Input is JSON (not FASTA/YAML) — requires entities_to_openfold_json()
      - Built-in ColabFold MSA server (--use-msa-server, default True)
      - Rich confidence: pLDDT, PAE, PDE, pTM, ipTM, ranking score
      - Requires 32GB+ GPU VRAM (A100 class)
    """

    tool_name: str = "openfold"
    supports_msa: bool = True
    requires_gpu: bool = True
    supported_entities: frozenset[EntityType] = frozenset({
        EntityType.PROTEIN, EntityType.DNA, EntityType.RNA,
        EntityType.LIGAND, EntityType.SMILES,
    })

    def prepare_input(
        self,
        entity_list: EntityList,
        output_dir: Path,
        *,
        msa_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Convert entity list to OpenFold 3 JSON query format.

        Args:
            entity_list: Entities for the prediction.
            output_dir: Working directory for prepared input.
            msa_path: Optional precomputed MSA file (.a3m, .sto).
            **kwargs: Additional options (use_msa_server controls MSA lookup).

        Returns:
            Path to the written JSON query file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        # use_msas controls MSA feature processing in the OpenFold JSON.
        # Enable when a precomputed MSA file is provided OR the MSA server
        # is requested. Disable (empty features) when neither is available.
        use_msas = msa_path is not None or kwargs.get("use_msa_server", False)
        return entities_to_openfold_json(
            entity_list,
            output_dir / "query.json",
            msa_path=msa_path,
            use_msas=use_msas,
        )

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
        """Construct the ``run_openfold predict`` CLI command.

        Parameter mapping:
          --num-samples    → --num-diffusion-samples
          --num-recycles   → ignored (controlled via runner YAML)
          --seed           → not directly mapped (OF3 uses --num-model-seeds)
          --device         → implicit (always GPU)
        """
        from predict_structure.config import get_command, get_data_dir

        cmd = [
            *get_command("openfold"),
            "--query-json", str(input_path),
            "--output-dir", str(output_dir),
            "--num-diffusion-samples", str(kwargs.get("num_diffusion_samples", num_samples)),
        ]

        num_model_seeds = kwargs.get("num_model_seeds", 1)
        cmd.extend(["--num-model-seeds", str(num_model_seeds)])

        # MSA server disabled by default -- our use case is all-local
        # (either no MSA or a precomputed MSA file)
        use_msa_server = kwargs.get("use_msa_server", False)
        cmd.extend(["--use-msa-server", str(use_msa_server)])

        # Templates disabled by default (evoformer_attn JIT fails on H200)
        use_templates = kwargs.get("use_templates", False)
        cmd.extend(["--use-templates", str(use_templates)])

        # Checkpoint: explicit path from data dir, or named checkpoint
        checkpoint = kwargs.get("checkpoint")
        if checkpoint:
            cmd.extend(["--inference-ckpt-name", checkpoint])
        else:
            # Auto-resolve checkpoint from data directory
            try:
                data_dir = get_data_dir("openfold")
                ckpt = data_dir / "of3-p2-155k.pt"
                if ckpt.exists():
                    cmd.extend(["--inference-ckpt-path", str(ckpt)])
            except (FileNotFoundError, KeyError):
                pass  # Let OF3 use its default download location

        # Runner YAML for platform-specific settings (e.g. H200 DeepSpeed fix).
        # Auto-resolve from data directory if not explicitly provided.
        runner_yaml = kwargs.get("runner_yaml")
        if runner_yaml:
            cmd.extend(["--runner-yaml", str(runner_yaml)])
        else:
            try:
                data_dir = get_data_dir("openfold")
                runner = data_dir / "runner.yml"
                if runner.exists():
                    cmd.extend(["--runner-yaml", str(runner)])
            except (FileNotFoundError, KeyError):
                pass

        return cmd

    def run(self, command: list[str], **kwargs: Any) -> int:
        """Execute prediction via the configured backend."""
        backend = kwargs.get("backend")
        if backend is None:
            from predict_structure.backends.subprocess import SubprocessBackend
            backend = SubprocessBackend()
        return backend.run(command, tool_name=self.tool_name, **kwargs)

    def normalize_output(self, raw_output_dir: Path, output_dir: Path) -> Path:
        """Normalize OpenFold 3 output to standardized layout."""
        return normalize_openfold_output(raw_output_dir, output_dir)

    def preflight(self) -> dict[str, Any]:
        return {
            "cpu": 8,
            "memory": "96G",
            "runtime": 14400,
            "storage": "50G",
            "policy_data": {
                "gpu_count": 1,
                "partition": "gpu2",
                "constraint": "A100|H100|H200",
            },
        }
