"""Abstract base adapter for structure prediction tools."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
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


def join_names(items: Iterable[str]) -> str:
    """Join names the way prose does: "a", "a and b", "a, b, and c"."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _tools_supporting(
    entity_types: Iterable[EntityType], *, exclude: str = ""
) -> list[str]:
    """Display names of tools that accept every one of ``entity_types``.

    Used to turn a rejection into a suggestion. Asks each adapter via
    ``supports_entity_types``, the pure predicate — never
    ``validate_entity_types``, which builds a message and would recurse back
    into this function.
    """
    from predict_structure.adapters import ADAPTERS

    types = frozenset(entity_types)
    return [
        cls.display_name or name
        for name, cls in ADAPTERS.items()
        if name != exclude and cls().supports_entity_types(types)
    ]


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

    #: Human-readable tool name used in user-facing error messages. Errors reach
    #: BV-BRC users who know the tool as "AlphaFold 2", not "alphafold".
    display_name: str = ""

    #: Whether this tool supports MSA input
    supports_msa: bool = True

    #: Whether this tool requires a GPU
    requires_gpu: bool = True

    #: Minimum free VRAM (MiB) needed at job start. Used by the GPU
    #: precheck in cli.run_prediction to fail fast when the assigned
    #: GPU is already busy. Conservative; overestimate over underestimate.
    min_gpu_memory_mb: int = 8000

    #: Entity types supported by this tool
    supported_entities: frozenset[EntityType] = frozenset({EntityType.PROTEIN})

    def validate_entities(self, entity_list: EntityList) -> None:
        """Check that all entity types in the list are supported by this tool.

        Raises:
            ValueError: If any entity type is not in ``supported_entities``.
        """
        self.validate_entity_types(entity_list.entity_types)

    def validate_entity_types(self, entity_types: Iterable[EntityType]) -> None:
        """Check entity *types* alone, without needing the entities themselves.

        Preflight runs on the scheduler node, where workspace files are not
        mounted (issue #84). It knows only which kinds of input were declared —
        never their contents — so validation has to be expressible over bare
        types. ``validate_entities`` delegates here so the submit-time check and
        the runtime check can never drift apart.

        Raises:
            ValueError: If any entity type is not in ``supported_entities``.
        """
        requested = frozenset(entity_types)
        unsupported = requested - self.supported_entities
        if unsupported:
            raise ValueError(self._unsupported_entity_message(requested, unsupported))

    def supports_entity_types(self, entity_types: Iterable[EntityType]) -> bool:
        """Whether this tool accepts every one of ``entity_types``.

        The pure predicate behind ``validate_entity_types``. Subclasses with
        constraints beyond ``supported_entities`` (see ``ChaiAdapter``) override
        both, so suggestions never name a tool that would itself reject the input.
        """
        return frozenset(entity_types) <= self.supported_entities

    def _unsupported_entity_message(
        self,
        requested: frozenset[EntityType],
        unsupported: frozenset[EntityType],
    ) -> str:
        """Build a user-facing message naming the problem and a way forward.

        These messages surface to BV-BRC users in job error streams, so they name
        the tool as users know it, say which inputs were rejected, and point at
        tools that would accept them.
        """
        rejected = join_names(sorted(e.value for e in unsupported))
        supported = join_names(sorted(e.value for e in self.supported_entities))
        msg = (
            f"{self.display_name or self.tool_name} does not support {rejected} "
            f"input (it supports {supported} only)."
        )
        alternatives = _tools_supporting(requested, exclude=self.tool_name)
        if alternatives:
            msg += f" Use {join_names(alternatives)}, which support {rejected}."
        msg += (
            f" Otherwise remove the {rejected} input to run "
            f"{self.display_name or self.tool_name}."
        )
        return msg

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
                continue  # ligand CCD / SMILES — no sequence-character validation
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
