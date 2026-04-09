"""Abstract base adapter for structure prediction tools."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from predict_structure.entities import EntityList, EntityType

logger = logging.getLogger(__name__)

# Characters expected for each sequence-based entity type
_VALID_CHARS: dict[EntityType, set[str]] = {
    EntityType.PROTEIN: set("ACDEFGHIKLMNPQRSTVWXYUBZJO*"),
    EntityType.DNA: set("ACGTNRYSWKMBDHV"),
    EntityType.RNA: set("ACGUNRYSWKMBDHV"),
}

# Characters that distinguish protein from nucleic acid
_DNA_ONLY = set("ACGTN")
_PROTEIN_ONLY = set("DEFHIKLMPQRSVWY")  # never appear in DNA


class BaseAdapter(ABC):
    """Base class for tool-specific adapters.

    Each adapter implements four methods that handle the full prediction lifecycle:
    1. prepare_input  — convert universal FASTA/MSA to tool-native format
    2. build_command   — construct the CLI invocation for the tool
    3. run             — execute the prediction (delegates to a backend)
    4. normalize_output — standardize output to unified directory layout

    Subclasses: BoltzAdapter, ChaiAdapter, AlphaFoldAdapter, ESMFoldAdapter
    """

    #: Short tool identifier used in CLI dispatch (e.g. "boltz", "chai", "alphafold", "esmfold")
    tool_name: str = ""

    #: Whether this tool supports MSA input
    supports_msa: bool = True

    #: Whether this tool requires a GPU
    requires_gpu: bool = True

    #: Entity types supported by this tool
    supported_entities: frozenset[EntityType] = frozenset({EntityType.PROTEIN})

    def validate_entities(self, entity_list: EntityList) -> None:
        """Check that all entity types in the list are supported by this tool.

        Raises:
            ValueError: If any entity type is not in ``supported_entities``.
        """
        unsupported = entity_list.entity_types - self.supported_entities
        if unsupported:
            names = ", ".join(sorted(e.value for e in unsupported))
            supported = ", ".join(sorted(e.value for e in self.supported_entities))
            raise ValueError(
                f"{self.tool_name} does not support entity type(s): {names}. "
                f"Supported: {supported}"
            )

    def validate_sequences(self, entity_list: EntityList) -> None:
        """Warn if sequence characters are inconsistent with declared entity type.

        Checks protein, DNA, and RNA entities against expected character sets.
        Also detects DNA sequences misclassified as protein (all ACGTN, no
        protein-only characters, length > 10).
        Logs warnings but does not raise — callers may use ``--force`` to proceed.
        """
        for entity in entity_list:
            expected_chars = _VALID_CHARS.get(entity.entity_type)
            if expected_chars is None:
                continue  # ligand, SMILES, glycan — no character validation
            upper = set(entity.value.upper())
            invalid = upper - expected_chars
            if invalid:
                logger.warning(
                    "Sequence '%s' contains characters %s unexpected for %s",
                    entity.name or entity.chain_id,
                    "".join(sorted(invalid)),
                    entity.entity_type.value,
                )
            # Detect DNA masquerading as protein: all DNA chars, no protein-only, long
            if (
                entity.entity_type == EntityType.PROTEIN
                and upper <= _DNA_ONLY
                and not (upper & _PROTEIN_ONLY)
                and len(entity.value) > 10
            ):
                logger.warning(
                    "Sequence '%s' looks like DNA (all ACGTN, %d nt) but declared as protein",
                    entity.name or entity.chain_id,
                    len(entity.value),
                )

    @abstractmethod
    def prepare_input(
        self,
        entity_list: EntityList,
        output_dir: Path,
        *,
        msa_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Convert entity list to tool-native input format.

        Args:
            entity_list: Entities to predict (proteins, DNA, RNA, ligands, etc.).
            output_dir: Working directory for prepared files.
            msa_path: Optional MSA file (.a3m, .sto, .pqt).

        Returns:
            Path to the prepared input file in tool-native format.
        """
        ...

    @abstractmethod
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
        """Construct the CLI command for the native tool.

        Args:
            input_path: Prepared input file (from prepare_input).
            output_dir: Where the tool should write results.
            num_samples: Number of structure samples to generate.
            num_recycles: Number of recycling iterations.
            seed: Random seed for reproducibility.
            device: Compute device ("gpu" or "cpu").

        Returns:
            Command as a list of strings (for subprocess).
        """
        ...

    @abstractmethod
    def run(self, command: list[str], **kwargs: Any) -> int:
        """Execute the prediction command.

        Args:
            command: CLI command from build_command.

        Returns:
            Process return code (0 = success).
        """
        ...

    @abstractmethod
    def normalize_output(self, raw_output_dir: Path, output_dir: Path) -> Path:
        """Standardize tool output to unified directory layout.

        Expected output structure:
            output_dir/
            ├── model_1.pdb
            ├── model_1.cif
            ├── confidence.json   # {plddt_mean, ptm, per_residue_plddt[]}
            ├── metadata.json     # {tool, params, runtime, version}
            └── raw/              # Original tool output (unmodified)

        Args:
            raw_output_dir: Directory containing native tool output.
            output_dir: Target directory for normalized output.

        Returns:
            Path to the normalized output directory.
        """
        ...

    def preflight(self) -> dict[str, Any]:
        """Return resource requirements for BV-BRC preflight check.

        Returns:
            Dict with cpu, memory, runtime, storage, and optional policy_data.
        """
        return {
            "cpu": 8,
            "memory": "64G",
            "runtime": 7200,
            "storage": "50G",
        }
