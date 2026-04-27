"""Summary manifest + RO-Crate provenance writers.

Produces two post-normalization files in the output directory:

- ``results.json``    -- a denormalized summary + file manifest (sha256,
  size, role) that re-reads ``metadata.json`` and ``confidence.json`` so
  there is a single source of truth.
- ``ro-crate-metadata.json`` -- an RO-Crate 1.1 Process Run Crate
  describing inputs, the exact command line, outputs, runtime, and
  container image. Written best-effort: if the ``rocrate`` package is
  missing, a warning is logged and the file is simply skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from predict_structure import __version__

logger = logging.getLogger(__name__)

RESULTS_SCHEMA_VERSION = "1.0"

Status = Literal["success", "partial", "failed"]

# Maps our status enum to the schema.org ActionStatus types used in the
# RO-Crate CreateAction.
_SCHEMA_STATUS = {
    "success": "CompletedActionStatus",
    "partial": "CompletedActionStatus",
    "failed": "FailedActionStatus",
}

# Maps a file basename (or suffix) to a role label used by downstream
# consumers to find specific artifacts without hard-coding paths.
_ROLE_MAP = {
    "model_1.pdb": "structure",
    "model_1.cif": "structure",
    "confidence.json": "confidence",
    "metadata.json": "metadata",
    "results.json": "summary",
    "ro-crate-metadata.json": "provenance",
    "report.html": "report",
    "report.json": "report",
    "report.pdf": "report",
}


def _sha256_file(path: Path, buf_size: int = 64 * 1024) -> str:
    """Stream the sha256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(buf_size):
            h.update(chunk)
    return h.hexdigest()


def _role_for(rel_path: str) -> str:
    """Map a relative path to a role label, defaulting to 'auxiliary'."""
    name = rel_path.rsplit("/", 1)[-1]
    return _ROLE_MAP.get(name, "auxiliary")


def _collect_outputs(output_dir: Path) -> list[dict]:
    """Build the outputs manifest.

    Enumerates files directly under ``output_dir`` and one level into
    ``report/``; ``raw/`` is listed as a single opaque directory entry so
    we don't descend into (and hash) the tool-native payload, which can
    be thousands of files for Boltz/OpenFold/AlphaFold.
    """
    entries: list[dict] = []

    def _add_file(item: Path, rel: str) -> None:
        entries.append({
            "path": rel,
            "size": item.stat().st_size,
            "sha256": _sha256_file(item),
            "role": _role_for(rel),
        })

    for item in sorted(output_dir.iterdir()):
        name = item.name
        if name == "raw":
            continue
        # Skip files that are written AFTER results.json (their size +
        # sha256 would be stale by the time the manifest lands on disk):
        # - results.json itself (self-reference)
        # - ro-crate-metadata.json (write_ro_crate runs after write_results_json
        #   and would rewrite this file)
        if name in ("results.json", "ro-crate-metadata.json"):
            continue
        if item.is_file():
            _add_file(item, name)
        elif name == "report" and item.is_dir():
            for sub in sorted(item.iterdir()):
                if sub.is_file():
                    _add_file(sub, f"report/{sub.name}")

    raw_dir = output_dir / "raw"
    if raw_dir.is_dir():
        entries.append({
            "path": "raw",
            "size": None,
            "sha256": None,
            "role": "raw_dir",
        })

    return sorted(entries, key=lambda e: e["path"])


def _infer_inputs(metadata: dict) -> list[dict]:
    """Derive input descriptors from metadata params (best-effort).

    metadata["params"] is the unified parameter dict passed to the CLI.
    We don't have FASTA sequences here (they're in the tool's raw/ dir),
    so we record only what metadata provides -- caller can enrich later.
    """
    params = metadata.get("params", {})
    inputs = []
    for kind in ("protein", "dna", "rna"):
        for src in params.get(kind, []) or []:
            inputs.append({"kind": kind, "source": str(src)})
    return inputs


def write_results_json(
    output_dir: Path,
    command: list[str] | None = None,
    backend: str | None = None,
    container_image: str | None = None,
    status: Status = "success",
) -> Path:
    """Write results.json summary + file manifest.

    Reads metadata.json and confidence.json from ``output_dir`` for canonical
    fields, hashes the remaining files, and emits a stable sorted manifest.

    Args:
        output_dir: Normalized prediction output directory.
        command: The exact CLI invocation (sys.argv or equivalent). If
            None, uses an empty list.
        backend: Execution backend name (e.g. 'subprocess', 'docker').
        container_image: Container image / SIF path. None if native.
        status: One of 'success', 'partial', 'failed'.

    Returns:
        Path to results.json.

    Raises:
        FileNotFoundError: if metadata.json or confidence.json is missing.
    """
    metadata_path = output_dir / "metadata.json"
    confidence_path = output_dir / "confidence.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"metadata.json missing in {output_dir}")
    if not confidence_path.is_file():
        raise FileNotFoundError(f"confidence.json missing in {output_dir}")

    metadata = json.loads(metadata_path.read_text())
    confidence = json.loads(confidence_path.read_text())

    per_residue = confidence.get("per_residue_plddt") or []
    per_atom = confidence.get("per_atom_plddt") or []

    data = {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "tool": metadata.get("tool"),
        "version": metadata.get("version") or __version__,
        "tool_version": metadata.get("tool_version"),
        "status": status,
        "timestamp": metadata.get("timestamp")
            or datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": metadata.get("runtime_seconds"),
        "inputs": _infer_inputs(metadata),
        "command": list(command) if command else [],
        "container_image": container_image,
        "backend": backend,
        "metrics": {
            "plddt_mean": confidence.get("plddt_mean"),
            "ptm": confidence.get("ptm"),
            "num_residues": len(per_residue),
            "num_atoms": len(per_atom) if per_atom else None,
        },
        "outputs": _collect_outputs(output_dir),
    }

    path = output_dir / "results.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def write_ro_crate(
    output_dir: Path,
    results: Path | dict,
) -> Path | None:
    """Write an RO-Crate 1.1 Process Run Crate describing the run.

    Best-effort: returns None (logs a warning) if the ``rocrate`` package
    is not installed. The crate is populated entirely from the results
    summary so there's a single source of truth.

    The emitted file is always named ``ro-crate-metadata.json`` per the
    RO-Crate spec.

    Args:
        output_dir: The normalized output directory.
        results: Either a parsed results dict (preferred, avoids a re-read)
            or a path to results.json.

    Returns:
        Path to ro-crate-metadata.json on success, None if rocrate is
        unavailable or an error occurred.
    """
    try:
        from rocrate.rocrate import ROCrate
        from rocrate.model.contextentity import ContextEntity
    except ImportError:
        logger.warning(
            "rocrate package not installed; skipping ro-crate-metadata.json "
            "(install predict-structure[provenance] to enable)"
        )
        return None

    if isinstance(results, Path):
        try:
            results = json.loads(results.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cannot read %s: %s; skipping RO-Crate", results, exc)
            return None

    crate = ROCrate()
    crate.name = f"{results.get('tool', 'predict-structure')} prediction"
    crate.description = (
        f"Structure prediction run via {results.get('tool')} "
        f"(predict-structure {results.get('version')})"
    )
    crate.datePublished = results.get("timestamp") \
        or datetime.now(timezone.utc).isoformat()

    # SoftwareApplication for predict-structure itself
    ps_app = crate.add(ContextEntity(crate, "#predict-structure", properties={
        "@type": "SoftwareApplication",
        "name": "predict-structure",
        "softwareVersion": results.get("version"),
        "url": "https://github.com/CEPI-dxkb/PredictStructureApp",
    }))

    # SoftwareApplication for the underlying tool (best-effort)
    tool_app = crate.add(ContextEntity(crate, f"#tool-{results.get('tool')}", properties={
        "@type": "SoftwareApplication",
        "name": results.get("tool"),
        "softwareVersion": results.get("tool_version"),
    }))

    # File entities for outputs (skip the crate file itself + raw dir entries)
    result_entities = []
    for out in results.get("outputs", []):
        if out["role"] == "raw_dir":
            continue
        if out["path"] == "ro-crate-metadata.json":
            continue
        props = {
            "@type": "File",
            "name": out["path"],
        }
        if out.get("size") is not None:
            props["contentSize"] = out["size"]
        if out.get("sha256"):
            props["sha256"] = out["sha256"]
        file_ent = crate.add_file(
            output_dir / out["path"],
            dest_path=out["path"],
            properties=props,
        )
        result_entities.append(file_ent)

    # CreateAction -- the actual run
    action_props = {
        "@type": "CreateAction",
        "name": f"Run {results.get('tool')} prediction",
        "instrument": {"@id": tool_app["@id"]},
        "agent": {"@id": ps_app["@id"]},
        "actionStatus": {
            "@id": "http://schema.org/"
                   + _SCHEMA_STATUS.get(results.get("status", "success"),
                                        "CompletedActionStatus")
        },
        "description": " ".join(results.get("command", [])),
        "result": [{"@id": e["@id"]} for e in result_entities],
    }
    if results.get("container_image"):
        action_props["containerImage"] = results["container_image"]
    if results.get("runtime_seconds") is not None:
        # Represent runtime as an endTime relative to timestamp if available
        action_props["endTime"] = results.get("timestamp")

    crate.add(ContextEntity(crate, "#run", properties=action_props))

    # Write the crate metadata into output_dir (keeps files in place)
    path = output_dir / "ro-crate-metadata.json"
    try:
        crate.metadata.write(output_dir)
    except Exception as exc:
        logger.warning("RO-Crate write failed: %s; skipping", exc)
        return None
    return path
