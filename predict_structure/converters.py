"""Format conversion functions for structure prediction I/O.

Stateless converters that bridge universal FASTA/A3M input to tool-native
formats (Boltz YAML, Chai Parquet) and convert between structure file
formats (mmCIF ↔ PDB).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from Bio import SeqIO
from Bio.PDB import MMCIFParser, MMCIFIO, PDBParser, PDBIO

# OpenFold 3 only recognizes MSA files with basenames from its aln_order list
# (see its dataset_config_components.py). We stage user-provided MSAs with
# this name so OpenFold loads them. Other recognized names: uniref90_hits,
# mgnify_hits, bfd_uniref_hits, etc. colabfold_main is the generic single-MSA
# slot.
OPENFOLD3_MSA_BASENAME = "colabfold_main"

if TYPE_CHECKING:
    from predict_structure.entities import EntityList

logger = logging.getLogger(__name__)

_CHAIN_IDS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Bytes that ColabFold MSA servers (and raw mmseqs2 result2msa) leave as
# trailing padding.  Stripping only from the end avoids silently mutating
# the body of the alignment while still fixing the most common corruption.
_MSA_TRAILING_JUNK = b"\x00 \t\r\n"


def _stage_msa_sanitized(source: Path, dest: Path) -> None:
    """Copy *source* to *dest*, stripping trailing NUL bytes.

    ColabFold MSA servers append a trailing ``\\x00`` that crashes parsers
    expecting clean text (notably OpenFold 3's ``parse_a3m``).  This mirrors
    the defensive strip in ``scripts/_colabfold_api_msa.py:121``.
    """
    raw = source.read_bytes()
    clean = raw.rstrip(_MSA_TRAILING_JUNK)
    if len(clean) != len(raw):
        logger.info(
            "Stripped %d trailing byte(s) from MSA file %s",
            len(raw) - len(clean),
            source.name,
        )
    if clean and not clean.endswith(b"\n"):
        clean += b"\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(clean)


def fasta_to_boltz_yaml(
    fasta_path: Path,
    output_path: Path,
    msa_path: Path | None = None,
) -> Path:
    """Convert a FASTA file to a Boltz-2 YAML input manifest.

    Boltz-2 requires YAML input for full feature support (multi-entity
    complexes, ligands, constraints, MSA paths). This wraps a standard
    FASTA into the required YAML format.

    Args:
        fasta_path: Input FASTA file with one or more protein sequences.
        output_path: Where to write the generated YAML file.
        msa_path: Optional A3M MSA file to reference in the YAML.

    Returns:
        Path to the written YAML file.
    """
    records = list(SeqIO.parse(str(fasta_path), "fasta"))
    if not records:
        raise ValueError(f"No sequences found in {fasta_path}")

    sequences = []
    for i, record in enumerate(records):
        chain_id = _CHAIN_IDS[i % len(_CHAIN_IDS)]
        entry: dict = {
            "id": chain_id,
            "sequence": str(record.seq),
        }
        if msa_path is not None:
            entry["msa"] = str(msa_path.resolve())
        sequences.append({"protein": entry})

    manifest = {"version": 1, "sequences": sequences}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

    logger.info("Wrote Boltz YAML with %d chain(s) to %s", len(records), output_path)
    return output_path


def _read_a3m_sequences(a3m_path: Path) -> list[str]:
    """Parse an A3M file and return its concatenated sequences (one per record).

    Reads as bytes and strips trailing NUL padding before decoding so that
    ColabFold-server .a3m files don't inject NUL into sequence data.
    """
    raw = a3m_path.read_bytes().rstrip(_MSA_TRAILING_JUNK)
    text = raw.decode("utf-8", errors="replace")
    sequences = []
    current_seq: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        if line.startswith(">"):
            if current_seq:
                sequences.append("".join(current_seq))
            current_seq = []
        elif line:
            current_seq.append(line)
    if current_seq:
        sequences.append("".join(current_seq))
    return sequences


def a3m_depth(a3m_path: Path) -> int:
    """Return the number of sequences (rows) in an A3M alignment."""
    return len(_read_a3m_sequences(a3m_path))


def a3m_to_parquet(a3m_path: Path, output_path: Path) -> Path:
    """Convert an A3M multiple sequence alignment to Chai-1's Parquet format.

    Tries Chai's built-in converter first; falls back to manual parsing
    with pandas + pyarrow.  Sanitizes trailing NUL bytes before conversion.

    Args:
        a3m_path: Input A3M alignment file.
        output_path: Where to write the .aligned.pqt Parquet file.

    Returns:
        Path to the written Parquet file.
    """
    # Stage a sanitized copy so the Chai CLI doesn't choke on NUL padding.
    clean_a3m = output_path.parent / (a3m_path.stem + ".clean.a3m")
    _stage_msa_sanitized(a3m_path, clean_a3m)

    # Try Chai's built-in converter
    if shutil.which("chai"):
        result = subprocess.run(
            ["chai", "a3m-to-pqt", str(clean_a3m), str(output_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("Converted A3M to Parquet via chai CLI: %s", output_path)
            return output_path
        logger.warning("chai a3m-to-pqt failed: %s; falling back to manual parsing", result.stderr)

    # Manual fallback
    try:
        import pandas as pd
        import pyarrow  # noqa: F401 — ensure engine is available
    except ImportError:
        raise RuntimeError(
            "pyarrow is required for A3M→Parquet conversion. "
            "Install with: pip install predict-structure[chai]"
        )

    sequences = _read_a3m_sequences(clean_a3m)
    if not sequences:
        raise ValueError(f"No sequences found in {a3m_path}")

    df = pd.DataFrame({"sequence": sequences})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(str(output_path), engine="pyarrow")
    logger.info("Converted A3M (%d seqs) to Parquet: %s", len(sequences), output_path)
    return output_path


def _patch_mmcif_occupancy(cif_path: Path) -> None:
    """Add _atom_site.occupancy to a CIF file that's missing it.

    Some tools (e.g. OpenFold 3 / biotite) produce CIF files without
    the occupancy field.  BioPython's MMCIFParser requires it, so we
    inject it in-place: add the header line after B_iso_or_equiv and
    append "1.00" to each atom data row at the matching position.
    """
    text = cif_path.read_text()
    if "_atom_site.occupancy" in text:
        return

    lines = text.split("\n")
    out: list[str] = []
    fields: list[str] = []
    biso_idx = -1
    in_header = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("_atom_site."):
            in_header = True
            fields.append(stripped.split()[0])
            out.append(line)
            if "B_iso_or_equiv" in stripped:
                biso_idx = len(fields) - 1
                out.append("_atom_site.occupancy ")
            continue

        if in_header and not stripped.startswith("_atom_site."):
            in_header = False
            if biso_idx == -1 and fields:
                biso_idx = len(fields) - 1
                out.append("_atom_site.occupancy ")

        if fields and stripped and not stripped.startswith(("_", "#", "loop_", "data_")):
            parts = line.split()
            if len(parts) >= len(fields):
                parts.insert(biso_idx + 1, "1.00")
                out.append(" ".join(parts))
                continue

        out.append(line)

    cif_path.write_text("\n".join(out))


def mmcif_to_pdb(cif_path: Path, pdb_path: Path) -> Path:
    """Convert an mmCIF structure file to PDB format.

    Patches missing _atom_site.occupancy (e.g. OpenFold 3 output) before
    parsing, since BioPython's MMCIFParser requires this field.

    Args:
        cif_path: Input mmCIF file.
        pdb_path: Where to write the PDB file.

    Returns:
        Path to the written PDB file.
    """
    _patch_mmcif_occupancy(cif_path)
    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure("s", str(cif_path))
    io = PDBIO()
    io.set_structure(structure)
    pdb_path.parent.mkdir(parents=True, exist_ok=True)
    io.save(str(pdb_path))
    return pdb_path


def pdb_to_mmcif(pdb_path: Path, cif_path: Path) -> Path:
    """Convert a PDB structure file to mmCIF format.

    Args:
        pdb_path: Input PDB file.
        cif_path: Where to write the mmCIF file.

    Returns:
        Path to the written mmCIF file.
    """
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", str(pdb_path))
    io = MMCIFIO()
    io.set_structure(structure)
    cif_path.parent.mkdir(parents=True, exist_ok=True)
    io.save(str(cif_path))
    return cif_path


# ---------------------------------------------------------------------------
# Entity-based converters
# ---------------------------------------------------------------------------

def entities_to_boltz_yaml(
    entity_list: EntityList,
    output_path: Path,
    msa_path: Path | None = None,
) -> Path:
    """Convert an EntityList to a Boltz-2 YAML input manifest.

    Maps entity types to Boltz YAML sequence entries:
      - protein → ``{protein: {id, sequence}}``
      - dna → ``{dna: {id, sequence}}``
      - rna → ``{rna: {id, sequence}}``
      - ligand → ``{ligand: {ccd: code, id}}``  (CCD includes glycan codes)
      - smiles → ``{ligand: {smiles: value, id}}``

    Args:
        entity_list: Entities to include in the manifest.
        output_path: Where to write the generated YAML file.
        msa_path: Optional A3M MSA file to reference for protein entries.

    Returns:
        Path to the written YAML file.
    """
    from predict_structure.entities import EntityType

    sequences = []
    for entity in entity_list:
        entry: dict = {"id": entity.chain_id}

        if entity.entity_type == EntityType.PROTEIN:
            entry["sequence"] = entity.value
            if msa_path is not None:
                entry["msa"] = str(msa_path.resolve())
            else:
                # Single-sequence mode: Boltz requires an explicit msa field
                # for protein chains. Setting "empty" avoids the error
                # "Missing MSA's in input and --use_msa_server flag not set"
                # at the cost of reduced prediction accuracy.
                entry["msa"] = "empty"
            sequences.append({"protein": entry})

        elif entity.entity_type == EntityType.DNA:
            entry["sequence"] = entity.value
            sequences.append({"dna": entry})

        elif entity.entity_type == EntityType.RNA:
            entry["sequence"] = entity.value
            sequences.append({"rna": entry})

        elif entity.entity_type == EntityType.LIGAND:
            entry["ccd"] = entity.value
            sequences.append({"ligand": entry})

        elif entity.entity_type == EntityType.SMILES:
            entry["smiles"] = entity.value
            sequences.append({"ligand": entry})

    manifest = {"version": 1, "sequences": sequences}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

    logger.info("Wrote Boltz YAML with %d entity/ies to %s", len(entity_list), output_path)
    return output_path


def entities_to_chai_fasta(entity_list: EntityList, output_path: Path) -> Path:
    """Convert an EntityList to a Chai-1 entity-typed FASTA file.

    Chai-1 requires entity type annotations in FASTA headers::

        >protein|name=A
        MKTIIALSY...
        >ligand|name=B
        ATP

    Args:
        entity_list: Entities to include.
        output_path: Where to write the typed FASTA file.

    Returns:
        Path to the written FASTA file.
    """
    from predict_structure.entities import EntityType

    # Chai's native types are protein / dna / rna / ligand. Both CCD codes
    # and SMILES strings are submitted as a `ligand` entity; the value
    # itself encodes which (Chai parses the value form).
    _TYPE_LABELS = {
        EntityType.PROTEIN: "protein",
        EntityType.DNA: "dna",
        EntityType.RNA: "rna",
        EntityType.LIGAND: "ligand",
        EntityType.SMILES: "ligand",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for entity in entity_list:
            label = _TYPE_LABELS[entity.entity_type]
            f.write(f">{label}|name={entity.chain_id}\n")
            f.write(f"{entity.value}\n")

    logger.info("Wrote Chai FASTA with %d entity/ies to %s", len(entity_list), output_path)
    return output_path


def entities_to_fasta(entity_list: EntityList, output_path: Path) -> Path:
    """Convert an EntityList to a plain FASTA file (protein/DNA/RNA only).

    Non-sequence entities (ligand CCD, SMILES) are silently skipped.

    Args:
        entity_list: Entities to include.
        output_path: Where to write the FASTA file.

    Returns:
        Path to the written FASTA file.
    """
    fasta_ents = entity_list.fasta_entities()
    if not fasta_ents:
        raise ValueError("No sequence entities (protein/DNA/RNA) to write")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for entity in fasta_ents:
            f.write(f">{entity.name}\n{entity.value}\n")

    logger.info("Wrote FASTA with %d sequence(s) to %s", len(fasta_ents), output_path)
    return output_path


def entities_to_openfold_json(
    entity_list: EntityList,
    output_path: Path,
    query_name: str = "prediction",
    *,
    msa_path: Path | None = None,
    use_msas: bool = True,
) -> Path:
    """Convert an EntityList to an OpenFold 3 JSON query file.

    OpenFold 3 requires a structured JSON input with explicit molecule types
    and chain IDs. Each entity becomes one chain entry.

    Entity type mapping:
      - protein → ``{"molecule_type": "protein", "sequence": ...}``
      - dna → ``{"molecule_type": "dna", "sequence": ...}``
      - rna → ``{"molecule_type": "rna", "sequence": ...}``
      - ligand → ``{"molecule_type": "ligand", "ccd_codes": [...]}``
        (CCD includes glycan codes — OpenFold has no separate glycan type)
      - smiles → ``{"molecule_type": "ligand", "smiles": ...}``

    Args:
        entity_list: Entities to include in the query.
        output_path: Where to write the JSON file.
        query_name: Name for the query entry (default: "prediction").
        msa_path: Optional precomputed MSA file for protein chains.
        use_msas: Whether to enable MSA lookups (default True = ColabFold).

    Returns:
        Path to the written JSON file.
    """
    from predict_structure.entities import EntityType

    # Stage MSA files with a recognized basename so OpenFold's aln_order
    # accepts them. Prefer symlink (cheap for large MSAs, identical chains
    # can share the source); fall back to copy on symlink failure
    # (cross-device mounts, Windows without privileges, etc.).
    msa_staging_dir: Path | None = None
    if msa_path is not None:
        msa_staging_dir = output_path.parent / "msa_staging"
        msa_staging_dir.mkdir(parents=True, exist_ok=True)
        msa_source = msa_path.resolve()
        msa_ext = msa_path.suffix.lower() or ".a3m"

    chains = []
    for entity in entity_list:
        chain: dict = {
            "chain_ids": entity.chain_id,
        }

        if entity.entity_type == EntityType.PROTEIN:
            chain["molecule_type"] = "protein"
            chain["sequence"] = entity.value
            if msa_path is not None and msa_staging_dir is not None:
                chain_msa_dir = msa_staging_dir / f"chain_{entity.chain_id}"
                chain_msa_dir.mkdir(exist_ok=True)
                staged = chain_msa_dir / f"{OPENFOLD3_MSA_BASENAME}{msa_ext}"
                if staged.is_symlink() or staged.exists():
                    staged.unlink()
                _stage_msa_sanitized(msa_source, staged)
                # Keep the staged basename -- OpenFold infers MSA type from it,
                # so we must not resolve back to the user's original filename.
                chain["main_msa_file_paths"] = [str(staged.absolute())]
        elif entity.entity_type == EntityType.DNA:
            chain["molecule_type"] = "dna"
            chain["sequence"] = entity.value
        elif entity.entity_type == EntityType.RNA:
            chain["molecule_type"] = "rna"
            chain["sequence"] = entity.value
        elif entity.entity_type == EntityType.LIGAND:
            chain["molecule_type"] = "ligand"
            chain["ccd_codes"] = [entity.value]
        elif entity.entity_type == EntityType.SMILES:
            chain["molecule_type"] = "ligand"
            chain["smiles"] = entity.value

        chains.append(chain)

    query_entry: dict = {
        "chains": chains,
        "use_msas": use_msas,
    }

    query = {
        "queries": {
            query_name: query_entry,
        }
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(query, indent=2))

    logger.info("Wrote OpenFold 3 JSON with %d chain(s) to %s", len(chains), output_path)
    return output_path
