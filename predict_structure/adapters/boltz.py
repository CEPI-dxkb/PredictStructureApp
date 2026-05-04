"""Boltz-2 adapter for biomolecular structure prediction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from predict_structure.adapters.base import BaseAdapter
from predict_structure.converters import entities_to_boltz_yaml
from predict_structure.entities import EntityList, EntityType
from predict_structure.normalizers import normalize_boltz_output

logger = logging.getLogger(__name__)


class BoltzAdapter(BaseAdapter):
    """Adapter for Boltz-2 biomolecular structure prediction.

    Boltz-2 is a diffusion-based model for predicting structures of proteins,
    DNA, RNA, and ligand complexes. It uses YAML input format (auto-converted
    from entity list) and outputs mmCIF structures with confidence metrics.
    """

    tool_name: str = "boltz"
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
        """Convert entity list to Boltz YAML format.

        If the entity list contains a single entity whose value is a path to
        a Boltz YAML file, it is passed through (with optional MSA injection).
        Otherwise, entities are converted to YAML via ``entities_to_boltz_yaml``.
        """
        # Single-entity YAML pass-through
        if len(entity_list) == 1:
            first = entity_list.entities[0]
            yaml_path = Path(first.value)
            if yaml_path.suffix.lower() in (".yaml", ".yml") and yaml_path.exists():
                if msa_path is not None:
                    data = yaml.safe_load(yaml_path.read_text())
                    for entry in data.get("sequences", []):
                        if "protein" in entry:
                            entry["protein"]["msa"] = str(msa_path.resolve())
                    prepared = output_dir / "input.yaml"
                    prepared.parent.mkdir(parents=True, exist_ok=True)
                    with open(prepared, "w") as f:
                        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                    return prepared
                return yaml_path

        output_dir.mkdir(parents=True, exist_ok=True)
        return entities_to_boltz_yaml(entity_list, output_dir / "input.yaml", msa_path)

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
        """Construct the ``boltz predict`` CLI command."""
        from predict_structure.config import get_command
        cmd = [*get_command("boltz"), str(input_path),
            "--out_dir", str(output_dir),
            "--diffusion_samples", str(num_samples),
            "--recycling_steps", str(num_recycles),
            "--sampling_steps", str(kwargs.get("sampling_steps", 200)),
            "--output_format", "mmcif",
            "--write_full_pae",
            "--accelerator", "cpu" if device == "cpu" else "gpu",
        ]

        if kwargs.get("use_msa_server"):
            cmd.append("--use_msa_server")
        if kwargs.get("msa_server_url"):
            cmd.extend(["--msa_server_url", kwargs["msa_server_url"]])
        if kwargs.get("boltz_use_potentials"):
            cmd.append("--use_potentials")

        return cmd

    def run(self, command: list[str], **kwargs: Any) -> int:
        """Execute prediction via the configured backend."""
        backend = kwargs.get("backend")
        if backend is None:
            from predict_structure.backends.subprocess import SubprocessBackend
            backend = SubprocessBackend()
        return backend.run(command, tool_name=self.tool_name, **kwargs)

    def normalize_output(self, raw_output_dir: Path, output_dir: Path) -> Path:
        """Normalize Boltz output to standardized layout."""
        return normalize_boltz_output(raw_output_dir, output_dir)

    def preflight(self) -> dict[str, Any]:
        return {
            "cpu": 8,
            "memory": "96G",
            "runtime": 14400,
            "storage": "50G",
            "policy_data": {
                "gpu_count": 1,
                "partition": "gpu2",
                "constraint": "V100|H100|H200",
            },
        }
