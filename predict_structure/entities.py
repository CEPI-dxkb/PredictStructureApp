"""Entity data model for multi-entity structure prediction.

Defines entity types (protein, DNA, RNA, ligand, SMILES), sequence type
detection, and FASTA parsing with entity classification.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator

from Bio import SeqIO

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input size limits — override with --force
# ---------------------------------------------------------------------------

MAX_SEQUENCES = 26          # A-Z chain IDs
MAX_TOTAL_RESIDUES = 10_000


class EntityType(Enum):
    """Biological entity types supported by structure prediction tools.

    Glycans are intentionally NOT a separate type: neither Boltz nor Chai
    has a distinct glycan entity, both expect glycans as CCD-coded
    ligands. Pass each monosaccharide via ``--ligand <CCD>`` (e.g.
    ``--ligand NAG --ligand NAG``); they are placed as separate, unlinked
    residues. Linked glycan strings (``NAG(4-1 NAG)``) are not supported —
    supply the whole molecule as SMILES instead.
    """

    PROTEIN = "protein"
    DNA = "dna"
    RNA = "rna"
    LIGAND = "ligand"   # CCD code (1-3 or exactly 5 alphanumeric chars)
    SMILES = "smiles"   # SMILES string for arbitrary small molecules


# Entity types that are represented as sequences in FASTA format
_FASTA_TYPES = frozenset({EntityType.PROTEIN, EntityType.DNA, EntityType.RNA})

# Entity types that are inline values (CCD codes, SMILES strings).
_INLINE_TYPES = frozenset({EntityType.LIGAND, EntityType.SMILES})

# Chain ID alphabet for entity assignment
_CHAIN_IDS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# ---------------------------------------------------------------------------
# Ligand CCD codes
# ---------------------------------------------------------------------------
#
# A PDB Chemical Component Dictionary (CCD) ID is 1-3 OR exactly 5
# alphanumeric characters. Four is impossible by design: wwPDB reserved
# that length so component IDs can never be confused with 4-character PDB
# entry IDs, and when the 3-character space neared exhaustion it began
# issuing 5-character "extended" IDs in 2023 (A1H1F, A1AJ7, ...), asking
# developers to lift any hard-coded length limits.
#
# Verified by enumerating RCSB's entire component space (50,983 IDs):
#   len 1: 16 | len 2: 129 | len 3: 43,387 | len 4: 0 | len 5: 6,647
# Boltz's own bundled CCD snapshot has the same shape (no 4-character
# entries) and does contain A1H1F. The remaining 804 10-character IDs are
# ``PRD_xxxxxx`` BIRD identifiers — a different namespace, deliberately
# excluded here (they are not CCD codes and carry an underscore).
#
# All archive IDs are uppercase, so codes are upper-cased on the way in.
#
# The pattern is intentionally UNANCHORED and must always be applied with
# ``fullmatch``: ``$`` also matches just before a trailing newline, so an
# anchored ``match`` would accept ``"ATP\n"``. Keeping it anchor-free also
# lets tests compare it character-for-character against the Perl copy in
# service-scripts/App-PredictStructure.pl (which anchors with \A ... \z).
CCD_CODE_RE = re.compile(r"(?:[A-Za-z0-9]{1,3}|[A-Za-z0-9]{5})")


def _invalid_ccd_message(code: str) -> str:
    """Build the user-facing message for a rejected CCD code.

    One builder for both branches so the generic and glycan wordings
    cannot drift (mirrors ``ChaiAdapter._ccd_ligand_message``).

    The glycan branch is gated on ``(`` alone: a linked-glycan string is
    the only thing that looks like ``NAG(4-1 NAG)``. Whitespace is NOT a
    trigger — ``"NA G"`` is just a typo, and telling that user about
    glycan linkage would be wrong advice.
    """
    if "(" in code:
        return (
            f"Invalid ligand CCD code '{code}': linked glycan strings are not "
            f"supported. Pass each monosaccharide as its own --ligand code "
            f"(--ligand NAG --ligand NAG), which places them as separate "
            f"unlinked residues, or supply the whole molecule as SMILES with "
            f"--smiles."
        )
    return (
        f"Invalid ligand CCD code '{code}'. A PDB Chemical Component "
        f"Dictionary code is 1-3 or 5 alphanumeric characters "
        f"(e.g. ATP, NAG, A1H1F). Use --smiles for a molecule with no "
        f"CCD code."
    )


def validate_ccd_code(code: str) -> str:
    """Validate and normalize a ligand CCD code.

    Surrounding whitespace is stripped and the code is upper-cased to match
    the archive (every CCD ID is uppercase, and Boltz/OpenFold look codes up
    by exact key).

    Args:
        code: User-supplied CCD code.

    Returns:
        The normalized (stripped, uppercased) code.

    Raises:
        ValueError: If the code is not 1-3 or exactly 5 alphanumeric
            characters. SMILES strings are never routed here — they are a
            separate entity type and legitimately contain parentheses.
    """
    stripped = (code or "").strip()
    if not CCD_CODE_RE.fullmatch(stripped):
        raise ValueError(_invalid_ccd_message(stripped))
    return stripped.upper()


def _chain_ids_exhausted_message() -> str:
    """Build the user-facing message for chain-ID exhaustion (#108).

    Spells out that the budget is shared across *all* inputs, because the
    way users hit this is one FASTA per flag (``--protein a.fasta --dna
    b.fasta``), each under the per-file limit but over it combined.
    """
    return (
        f"Too many entities: a prediction can have at most {len(_CHAIN_IDS)} "
        f"chains, one per chain ID {_CHAIN_IDS[0]}-{_CHAIN_IDS[-1]}. That "
        f"budget is shared by every input — one chain per FASTA record "
        f"across all --protein/--dna/--rna/--sequence files, plus one per "
        f"--ligand and --smiles entity. Submit fewer entities, or split the "
        f"complex into separate jobs. --force does not lift this limit: it "
        f"is a structural limit of single-letter chain IDs, not a size "
        f"guard. A 27th entity would have to reuse chain ID "
        f"'{_CHAIN_IDS[0]}', giving the tool duplicate chains and a "
        f"silently wrong complex."
    )


# DNA-only nucleotides (no U)
_DNA_BASES = set("ACGTN")

# RNA includes U
_RNA_BASES = set("ACGUN")


def detect_sequence_type(sequence: str) -> EntityType:
    """Detect whether a sequence is protein, DNA, or RNA.

    Rules:
      - Contains U and no T → RNA
      - All characters in {A, C, G, T, N} and length > 10 → DNA
      - Otherwise → protein

    Args:
        sequence: Uppercase sequence string.

    Returns:
        Detected EntityType (PROTEIN, DNA, or RNA).
    """
    seq_upper = sequence.upper().replace("\n", "").replace(" ", "")
    chars = set(seq_upper)

    # U present, no T → RNA
    if "U" in chars and "T" not in chars:
        return EntityType.RNA

    # All ACGTN and long enough → DNA
    if chars <= _DNA_BASES and len(seq_upper) > 10:
        return EntityType.DNA

    return EntityType.PROTEIN


@dataclass
class Entity:
    """A single biological entity for structure prediction.

    Attributes:
        entity_type: Type of entity (protein, DNA, RNA, ligand, etc.).
        value: Sequence string (for FASTA entities) or inline value (CCD, SMILES).
        name: Optional descriptive name (from FASTA header or user label).
        chain_id: Chain identifier assigned during conversion.
        source_path: Original user-supplied file path for file-backed entities;
            None for inline entities. Used by input staging to preserve the
            original input alongside the prediction outputs.
        format: Source format (``fasta`` / ``a3m`` / ``ccd`` / ``smiles``).
            Drives staged-file metadata.
    """

    entity_type: EntityType
    value: str
    name: str = ""
    chain_id: str = ""
    source_path: Path | None = None
    format: str | None = None


@dataclass
class EntityList:
    """Ordered collection of entities for a single prediction job.

    Manages chain ID assignment and provides filtered views by entity category.
    """

    entities: list[Entity] = field(default_factory=list)

    def add(
        self,
        entity_type: EntityType,
        value: str,
        name: str = "",
        *,
        source_path: Path | None = None,
        format: str | None = None,
    ) -> None:
        """Add an entity and assign the next available chain ID.

        Ligand values are validated and normalized here rather than at the
        CLI edge: a malformed CCD code is invalid for every tool, so it is
        a data-model invariant. Enforcing it at ``add`` also covers the
        batch job-file path, adapters, and direct library use. The chain-ID
        cap below is enforced here for the same reason.

        Raises:
            ValueError: If ``entity_type`` is LIGAND and ``value`` is not a
                valid CCD code, or if all chain IDs are already taken.
        """
        # Chain IDs come from a fixed 26-letter alphabet, so the entity count
        # is capped by the data model itself (#108). This used to wrap with
        # ``% len(_CHAIN_IDS)``, handing entity 27 chain ID 'A' again:
        # duplicate chains that Boltz YAML and Chai FASTA headers both accept
        # and then fold as the wrong complex. Refusing is the only honest
        # answer, and it is deliberately not bypassable by --force (which
        # lifts the per-file sequence and residue limits) — there is no 27th
        # chain ID to hand out.
        if len(self.entities) >= len(_CHAIN_IDS):
            raise ValueError(_chain_ids_exhausted_message())

        if entity_type is EntityType.LIGAND:
            normalized = validate_ccd_code(value)
            # Callers commonly use the raw code as the name (``name=code``).
            # Re-point that at the normalized code so Entity.name and
            # Entity.value cannot disagree — both reach metadata.json and
            # the RO-Crate independently. A distinct label is left alone.
            if name.strip() == value.strip():
                name = normalized
            value = normalized

        chain_id = _CHAIN_IDS[len(self.entities)]
        self.entities.append(Entity(
            entity_type=entity_type,
            value=value,
            name=name or chain_id,
            chain_id=chain_id,
            source_path=source_path,
            format=format,
        ))

    @property
    def entity_types(self) -> set[EntityType]:
        """Return the set of distinct entity types present."""
        return {e.entity_type for e in self.entities}

    def fasta_entities(self) -> list[Entity]:
        """Return entities that are sequence-based (protein, DNA, RNA)."""
        return [e for e in self.entities if e.entity_type in _FASTA_TYPES]

    def inline_entities(self) -> list[Entity]:
        """Return entities that are inline values (ligand CCD, SMILES)."""
        return [e for e in self.entities if e.entity_type in _INLINE_TYPES]

    @property
    def total_residues(self) -> int:
        """Total residue/nucleotide count across all sequence entities."""
        return sum(len(e.value) for e in self.fasta_entities())

    def validate_size(
        self,
        max_residues: int | None = MAX_TOTAL_RESIDUES,
    ) -> None:
        """Raise if total residues exceed the limit.

        Args:
            max_residues: Maximum total residues (None to skip check).

        Raises:
            ValueError: If total residues exceed the limit.
        """
        if max_residues is not None and self.total_residues > max_residues:
            raise ValueError(
                f"Total residues ({self.total_residues:,}) exceeds limit "
                f"({max_residues:,}). Use --force to override."
            )

    def __len__(self) -> int:
        return len(self.entities)

    def __iter__(self) -> Iterator[Entity]:
        return iter(self.entities)

    def __bool__(self) -> bool:
        return len(self.entities) > 0


def parse_fasta_entities(
    fasta_path: Path,
    explicit_type: EntityType | None = None,
    *,
    max_sequences: int | None = MAX_SEQUENCES,
) -> list[Entity]:
    """Parse a FASTA file and return one Entity per sequence.

    If ``explicit_type`` is given, all sequences are assigned that type.
    Otherwise, each sequence is auto-detected via ``detect_sequence_type``.

    Args:
        fasta_path: Path to FASTA file.
        explicit_type: Force all sequences to this type (PROTEIN, DNA, or RNA).
        max_sequences: Maximum number of sequences allowed (None to skip check).

    Returns:
        List of Entity objects (without chain IDs — caller assigns via EntityList.add).

    Raises:
        ValueError: If no sequences found or sequence count exceeds max_sequences.
    """
    records = list(SeqIO.parse(str(fasta_path), "fasta"))
    if not records:
        raise ValueError(f"No sequences found in {fasta_path}")

    if max_sequences is not None and len(records) > max_sequences:
        raise ValueError(
            f"Input FASTA has {len(records):,} sequences (limit: {max_sequences}). "
            f"Use --force to override."
        )

    entities = []
    for record in records:
        seq = str(record.seq)
        detected = detect_sequence_type(seq)
        etype = explicit_type if explicit_type is not None else detected

        # Warn on type mismatch when explicit type overrides detection
        if explicit_type is not None and detected != explicit_type:
            logger.warning(
                "Sequence '%s' appears to be %s but was declared as %s",
                record.id, detected.value, explicit_type.value,
            )

        entities.append(Entity(
            entity_type=etype,
            value=seq,
            name=record.id,
            source_path=fasta_path,
            format="fasta",
        ))
    return entities


def is_boltz_yaml(path: Path) -> bool:
    """Check if a file is a Boltz-2 YAML input manifest.

    A valid Boltz YAML has a ``.yaml`` or ``.yml`` extension and contains
    both ``version`` and ``sequences`` keys at the top level.

    Args:
        path: File path to check.

    Returns:
        True if the file is a Boltz YAML manifest.
    """
    if path.suffix.lower() not in (".yaml", ".yml"):
        return False
    try:
        import yaml

        data = yaml.safe_load(path.read_text())
        return isinstance(data, dict) and "version" in data and "sequences" in data
    except Exception:
        return False
