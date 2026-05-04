"""Results.json (v2.0) + RO-Crate provenance writers.

Produces two post-normalization files alongside ``metadata/metadata.json``:

- ``results.json`` (v2.0) -- a CWL-style outputs map with a small
  UI-summary header. UIs and pipelines read this; per-residue arrays
  stay in ``predictions/confidence.json``; the full run trace lives in
  ``metadata/metadata.json``.
- ``metadata/ro-crate-metadata.json`` -- an RO-Crate 1.1 Process Run
  Crate. Derived from both ``metadata.json`` (run trace + inputs) and
  ``results.json`` (outputs). Best-effort: skipped with a warning if
  the ``rocrate`` package is missing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from predict_structure.normalizers import (
    METADATA_SUBDIR,
    PREDICTIONS_SUBDIR,
    metadata_dir,
)

logger = logging.getLogger(__name__)

RESULTS_SCHEMA_VERSION = "2.0"

# results.state values; mirrors metadata.status.
_STATE_FROM_STATUS = {
    "success": "COMPLETED",
    "partial": "PARTIAL",
    "failed": "FAILED",
}

# Maps our status enum to the schema.org ActionStatus types used in the
# RO-Crate CreateAction.
_SCHEMA_STATUS = {
    "success": "CompletedActionStatus",
    "partial": "CompletedActionStatus",
    "failed": "FailedActionStatus",
}


# ---------------------------------------------------------------------------
# CWL File / Directory entry helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path, buf_size: int = 64 * 1024) -> str:
    """Stream the sha256 of a file (raw hex, no prefix)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(buf_size):
            h.update(chunk)
    return h.hexdigest()


def _make_file_entry(file_path: Path, output_dir: Path) -> dict:
    """Build a CWL-style File entry for ``file_path``.

    Drops the CWL ``path`` and ``dirname`` (local-fs noise); ``location``
    is a POSIX-relative path from ``output_dir`` and gets rewritten to
    a workspace URL post-upload by the Perl service script.
    """
    rel = file_path.relative_to(output_dir).as_posix()
    return {
        "class": "File",
        "basename": file_path.name,
        "nameroot": file_path.stem,
        "nameext": file_path.suffix,
        "checksum": f"sha256${_sha256_file(file_path)}",
        "size": file_path.stat().st_size,
        "location": rel,
    }


def _make_dir_entry(
    dir_path: Path,
    output_dir: Path,
    *,
    opaque: bool = False,
) -> dict:
    """Build a CWL-style Directory entry for ``dir_path``.

    ``opaque=True`` skips ``listing[]`` (used for ``raw/`` so we don't
    descend into thousands of tool-native files).
    """
    rel = dir_path.relative_to(output_dir).as_posix()
    entry = {
        "class": "Directory",
        "basename": dir_path.name,
        "location": rel,
    }
    if opaque:
        entry["opaque"] = True
        return entry
    listing: list[dict] = []
    for child in sorted(dir_path.iterdir()):
        if child.is_dir():
            listing.append(_make_dir_entry(child, output_dir))
        elif child.is_file():
            listing.append(_make_file_entry(child, output_dir))
    entry["listing"] = listing
    return entry


# ---------------------------------------------------------------------------
# results.json
# ---------------------------------------------------------------------------


def write_results_json(output_dir: Path) -> Path:
    """Write ``results.json`` v2.0 (UI summary header + CWL outputs map).

    Reads ``metadata/metadata.json`` (run trace) and
    ``predictions/confidence.json`` (metrics) for the header; walks the
    output directory for the outputs map.

    Returns:
        Path to results.json.

    Raises:
        FileNotFoundError: if metadata.json is missing.
    """
    metadata_path = output_dir / METADATA_SUBDIR / "metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"metadata.json missing in {output_dir}")
    metadata = json.loads(metadata_path.read_text())

    # Confidence may live at the canonical predictions/ location or
    # (legacy) at the top level. Either is acceptable; metrics are skipped
    # if neither exists (e.g. early-failure runs).
    confidence_path = output_dir / PREDICTIONS_SUBDIR / "confidence.json"
    if not confidence_path.is_file():
        confidence_path = output_dir / "confidence.json"
    metrics: dict = {}
    if confidence_path.is_file():
        confidence = json.loads(confidence_path.read_text())
        per_residue = confidence.get("per_residue_plddt") or []
        per_atom = confidence.get("per_atom_plddt") or []
        metrics = {
            "plddt_mean": confidence.get("plddt_mean"),
            "ptm": confidence.get("ptm"),
            "num_residues": len(per_residue),
            "num_atoms": len(per_atom) if per_atom else None,
        }

    state = _STATE_FROM_STATUS.get(metadata.get("status", "success"), "COMPLETED")

    outputs = _build_outputs_map(output_dir)

    data = {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "state": state,
        "tool": metadata.get("tool"),
        "completed_at": metadata.get("completed_at") or metadata.get("timestamp")
            or datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": metadata.get("runtime_seconds"),
        "metrics": metrics,
        "outputs": outputs,
    }

    path = output_dir / "results.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def _build_outputs_map(output_dir: Path) -> dict:
    """Build the named CWL outputs map from on-disk state.

    Only includes ports whose backing path exists — single-sample runs
    without reports skip ``report``/``reports``; raw CLI runs without
    staged inputs skip ``inputs``.
    """
    outputs: dict = {}

    # Top-level user-facing files
    best_pdb = output_dir / "model_1.pdb"
    if best_pdb.is_file():
        outputs["best_model"] = _make_file_entry(best_pdb, output_dir)
    report_html = output_dir / "report.html"
    if report_html.is_file():
        outputs["report"] = _make_file_entry(report_html, output_dir)

    for name in ("predictions", "reports", "inputs", "metadata"):
        d = output_dir / name
        if d.is_dir():
            outputs[name] = _make_dir_entry(d, output_dir)

    raw = output_dir / "raw"
    if raw.is_dir():
        outputs["raw"] = _make_dir_entry(raw, output_dir, opaque=True)

    return outputs


# ---------------------------------------------------------------------------
# RO-Crate (Process Run Crate)
# ---------------------------------------------------------------------------


def _iter_outputs(node: dict, base: Path):
    """Yield every File-leaf under a CWL outputs node (File or Directory)."""
    if node.get("class") == "File":
        # Skip the crate file itself if it ever appears.
        loc = node.get("location", node.get("basename", ""))
        if loc.endswith("ro-crate-metadata.json"):
            return
        yield base, node
    elif node.get("class") == "Directory":
        if node.get("opaque"):
            return
        for child in node.get("listing") or []:
            yield from _iter_outputs(child, base)


def write_ro_crate(output_dir: Path) -> Path | None:
    """Write an RO-Crate 1.1 Process Run Crate.

    Reads ``metadata/metadata.json`` (run trace + inputs) and
    ``results.json`` (outputs map + metrics). Best-effort: returns None
    (logs a warning) if the ``rocrate`` package is not installed.
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

    metadata_path = output_dir / METADATA_SUBDIR / "metadata.json"
    results_path = output_dir / "results.json"
    if not metadata_path.is_file() or not results_path.is_file():
        logger.warning(
            "RO-Crate skipped: metadata.json or results.json missing in %s",
            output_dir,
        )
        return None

    metadata = json.loads(metadata_path.read_text())
    results = json.loads(results_path.read_text())

    crate = ROCrate()
    tool = metadata.get("tool", "predict-structure")
    crate.name = f"{tool} prediction"
    crate.description = (
        f"Structure prediction run via {tool} "
        f"(predict-structure {metadata.get('version')})"
    )
    crate.datePublished = (
        metadata.get("completed_at")
        or results.get("completed_at")
        or datetime.now(timezone.utc).isoformat()
    )

    ps_app = crate.add(ContextEntity(crate, "#predict-structure", properties={
        "@type": "SoftwareApplication",
        "name": "predict-structure",
        "softwareVersion": metadata.get("version"),
        "url": "https://github.com/CEPI-dxkb/PredictStructureApp",
    }))

    tool_app = crate.add(ContextEntity(crate, f"#tool-{tool}", properties={
        "@type": "SoftwareApplication",
        "name": tool,
        "softwareVersion": metadata.get("tool_version"),
    }))

    # Input entities -- file-backed inputs become CWL File entities,
    # inline entities become PropertyValue context entities.
    object_refs: list[dict] = []
    for inp in metadata.get("inputs") or []:
        if inp.get("staged"):
            staged_rel = inp["staged"]
            staged_abs = output_dir / staged_rel
            if not staged_abs.is_file():
                continue
            props = {
                "@type": "File",
                "name": staged_rel,
                "contentSize": inp.get("size"),
                "encodingFormat": inp.get("format"),
                "additionalType": inp.get("kind"),
            }
            if inp.get("checksum"):
                props["sha256"] = inp["checksum"].split("$", 1)[-1]
            ent = crate.add_file(staged_abs, dest_path=staged_rel, properties=props)
            object_refs.append({"@id": ent["@id"]})
        elif inp.get("value") is not None:
            ent_id = f"#input-{inp.get('kind')}-{len(object_refs)}"
            ent = crate.add(ContextEntity(crate, ent_id, properties={
                "@type": "PropertyValue",
                "name": inp.get("name") or inp.get("kind"),
                "value": inp["value"],
                "additionalType": inp.get("kind"),
                "encodingFormat": inp.get("format"),
            }))
            object_refs.append({"@id": ent["@id"]})

    # Output entities -- walk the CWL outputs map and emit a File for every leaf.
    result_refs: list[dict] = []
    for _, leaf in _iter_outputs(
        {"class": "Directory", "listing": list(results.get("outputs", {}).values())},
        output_dir,
    ):
        rel = leaf.get("location") or leaf["basename"]
        abs_path = output_dir / rel
        if not abs_path.is_file():
            continue
        props = {"@type": "File", "name": rel}
        if leaf.get("size") is not None:
            props["contentSize"] = leaf["size"]
        if leaf.get("checksum"):
            props["sha256"] = leaf["checksum"].split("$", 1)[-1]
        ent = crate.add_file(abs_path, dest_path=rel, properties=props)
        result_refs.append({"@id": ent["@id"]})

    action_props = {
        "@type": "CreateAction",
        "name": f"Run {tool} prediction",
        "instrument": {"@id": tool_app["@id"]},
        "agent": {"@id": ps_app["@id"]},
        "actionStatus": {
            "@id": "http://schema.org/"
                   + _SCHEMA_STATUS.get(metadata.get("status", "success"),
                                        "CompletedActionStatus")
        },
        "description": " ".join(metadata.get("command") or []),
        "object": object_refs,
        "result": result_refs,
    }
    if metadata.get("container_image"):
        action_props["containerImage"] = metadata["container_image"]
    if metadata.get("started_at"):
        action_props["startTime"] = metadata["started_at"]
    if metadata.get("completed_at"):
        action_props["endTime"] = metadata["completed_at"]

    crate.add(ContextEntity(crate, "#run", properties=action_props))

    meta_dir = metadata_dir(output_dir)
    path = meta_dir / "ro-crate-metadata.json"
    try:
        crate.metadata.write(meta_dir)
    except Exception as exc:
        logger.warning("RO-Crate write failed: %s; skipping", exc)
        return None
    return path
