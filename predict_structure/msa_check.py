"""Lightweight MSA input-format validation.

Each adapter expects a particular MSA layout (A3M for Boltz/Chai/OpenFold,
a directory of per-database files for AlphaFold, Parquet for Chai when
preconverted, none for ESMFold). When a user passes the wrong format
the failure typically surfaces deep inside a converter or the tool
itself — opaque and slow.

This module sniffs the file (or directory) up front and fails with a
specific message naming the format detected and what the tool actually
wants. Runs in milliseconds; cheap insurance against a 60-second tool
crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Per-tool MSA acceptance.
#
# - file_suffixes: extensions the adapter can consume directly
# - allows_directory: whether a directory of MSA files is also accepted
# - ignored: tool ignores MSA entirely (still warn if one is passed)
@dataclass(frozen=True)
class _ToolMsaSpec:
    file_suffixes: tuple[str, ...]
    allows_directory: bool
    ignored: bool = False


_TOOL_MSA_SPECS: dict[str, _ToolMsaSpec] = {
    "boltz":     _ToolMsaSpec(file_suffixes=(".a3m",), allows_directory=False),
    "chai":      _ToolMsaSpec(file_suffixes=(".a3m", ".pqt"), allows_directory=True),
    "openfold":  _ToolMsaSpec(file_suffixes=(".a3m",), allows_directory=True),
    "alphafold": _ToolMsaSpec(file_suffixes=(".a3m", ".sto"), allows_directory=True),
    "esmfold":   _ToolMsaSpec(file_suffixes=(), allows_directory=False, ignored=True),
}


class MsaFormatError(ValueError):
    """Raised when an MSA file's contents don't match a supported format
    or don't match the tool's expectations."""


def _sniff_format(path: Path) -> str:
    """Return a short format tag based on the file's contents.

    Tags: "a3m", "fasta", "stockholm", "parquet", "empty", "binary",
    "unknown". A3M and FASTA share the ``>`` header convention; A3M is
    distinguished by the presence of lowercase residues (insertions)
    or multiple records.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError as exc:
        raise MsaFormatError(f"Cannot read MSA file {path}: {exc}") from exc

    if not head:
        return "empty"

    # Parquet magic bytes
    if head.startswith(b"PAR1"):
        return "parquet"

    # Detect binary content (non-text bytes early in file)
    sample = head[:512]
    text_bytes = sum(1 for b in sample
                     if b in (9, 10, 13) or 32 <= b < 127)
    if text_bytes / max(1, len(sample)) < 0.85:
        return "binary"

    text = head.decode("utf-8", errors="replace").lstrip()
    first_line = text.splitlines()[0] if text.splitlines() else ""

    if first_line.startswith("# STOCKHOLM"):
        return "stockholm"

    if first_line.startswith(">"):
        # A3M has lowercase insertion characters OR multiple records;
        # plain FASTA has a single record with only uppercase letters.
        lines = text.splitlines()
        records = [ln for ln in lines if ln.startswith(">")]
        seq_lines = [ln for ln in lines if ln and not ln.startswith(">") and not ln.startswith("#")]
        has_lowercase = any(any(c.islower() for c in ln) for ln in seq_lines)
        if len(records) > 1 or has_lowercase:
            return "a3m"
        return "fasta"

    return "unknown"


def check_msa_input(msa_path: Path | None, tool_name: str) -> None:
    """Validate the MSA argument for the given tool.

    Logs a precise message on success (helps confirm what was detected)
    and raises ``MsaFormatError`` on failure with a specific suggestion.
    No-op when ``msa_path`` is None.
    """
    if msa_path is None:
        return

    spec = _TOOL_MSA_SPECS.get(tool_name)
    if spec is None:
        # Unknown tool — don't second-guess; just check existence.
        if not msa_path.exists():
            raise MsaFormatError(f"MSA path does not exist: {msa_path}")
        return

    if spec.ignored:
        logger.warning(
            "%s ignores MSA input — provided --msa %s will be silently dropped",
            tool_name, msa_path,
        )
        return

    if not msa_path.exists():
        raise MsaFormatError(f"MSA path does not exist: {msa_path}")

    if msa_path.is_dir():
        if not spec.allows_directory:
            raise MsaFormatError(
                f"{tool_name} expects an MSA file ({'/'.join(spec.file_suffixes)}), "
                f"not a directory: {msa_path}"
            )
        # For directory inputs, just confirm at least one file with an
        # accepted suffix exists.
        matches = [p for p in msa_path.iterdir()
                   if p.is_file() and p.suffix.lower() in spec.file_suffixes]
        if not matches:
            wanted = "/".join(spec.file_suffixes)
            raise MsaFormatError(
                f"MSA directory {msa_path} contains no {wanted} files "
                f"(found: {sorted(p.name for p in msa_path.iterdir())[:5]}...)"
            )
        logger.info(
            "MSA directory ok for %s: %d matching file(s) in %s",
            tool_name, len(matches), msa_path,
        )
        return

    # File path: check suffix AND content
    suffix = msa_path.suffix.lower()
    fmt = _sniff_format(msa_path)

    if fmt in ("empty", "binary", "unknown"):
        raise MsaFormatError(
            f"MSA file {msa_path} is not a recognized text MSA "
            f"(detected: {fmt}). Expected one of: {', '.join(spec.file_suffixes)}"
        )

    if fmt == "fasta":
        raise MsaFormatError(
            f"MSA file {msa_path} looks like a single-sequence FASTA, "
            f"not an alignment. {tool_name} needs a multi-sequence MSA "
            f"({'/'.join(spec.file_suffixes)})."
        )

    # Suffix–content mismatch is informative but we trust content over suffix.
    if suffix and suffix not in spec.file_suffixes:
        # Special case: .sto content with .a3m extension etc.
        if fmt == "a3m" and ".a3m" in spec.file_suffixes:
            logger.warning(
                "MSA file %s has suffix %s but content is a3m — proceeding",
                msa_path, suffix,
            )
        elif fmt == "stockholm" and ".sto" in spec.file_suffixes:
            logger.warning(
                "MSA file %s has suffix %s but content is Stockholm — proceeding",
                msa_path, suffix,
            )
        else:
            raise MsaFormatError(
                f"MSA file {msa_path} has suffix {suffix} (detected content: "
                f"{fmt}), but {tool_name} accepts only: "
                f"{', '.join(spec.file_suffixes)}"
            )

    # Stockholm passed to a tool that wants A3M, etc.
    accepted_by_format = {
        "a3m": ".a3m" in spec.file_suffixes,
        "stockholm": ".sto" in spec.file_suffixes,
        "parquet": ".pqt" in spec.file_suffixes,
    }
    if not accepted_by_format.get(fmt, False):
        raise MsaFormatError(
            f"MSA file {msa_path} is {fmt} format, but {tool_name} accepts "
            f"only: {', '.join(spec.file_suffixes)}. "
            f"Convert with: hhfilter / reformat.pl / chai a3m-to-pqt as needed."
        )

    logger.info("MSA file ok for %s: %s (format=%s)", tool_name, msa_path, fmt)
