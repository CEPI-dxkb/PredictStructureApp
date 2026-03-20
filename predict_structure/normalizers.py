"""Output normalization for structure prediction tools.

Transforms raw, tool-specific output directories into a standardized layout:
    output_dir/
    ├── model_1.pdb
    ├── model_1.cif
    ├── confidence.json   # {plddt_mean, ptm, per_residue_plddt[]}
    ├── metadata.json     # {tool, params, runtime, version}
    └── raw/              # Original tool output (unmodified)

All pLDDT values are normalized to 0-100 scale.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from Bio.PDB import PDBParser

from predict_structure.converters import mmcif_to_pdb, pdb_to_mmcif

logger = logging.getLogger(__name__)


def write_confidence_json(
    output_dir: Path,
    plddt_mean: float,
    ptm: float | None,
    per_residue_plddt: list[float],
) -> Path:
    """Write standardized confidence metrics.

    Args:
        output_dir: Target directory.
        plddt_mean: Average per-residue confidence (0-100 scale).
        ptm: Predicted TM-score (None if unavailable).
        per_residue_plddt: Per-residue pLDDT array (0-100 scale).

    Returns:
        Path to confidence.json.
    """
    path = output_dir / "confidence.json"
    data = {
        "plddt_mean": round(plddt_mean, 2),
        "ptm": round(ptm, 4) if ptm is not None else None,
        "per_residue_plddt": [round(v, 2) for v in per_residue_plddt],
    }
    path.write_text(json.dumps(data, indent=2))
    return path


def write_metadata_json(
    output_dir: Path,
    tool: str,
    params: dict,
    runtime_seconds: float,
    version: str,
) -> Path:
    """Write prediction provenance metadata.

    Args:
        output_dir: Target directory.
        tool: Tool name.
        params: Unified parameters used.
        runtime_seconds: Wall-clock time for the prediction.
        version: predict-structure package version.

    Returns:
        Path to metadata.json.
    """
    path = output_dir / "metadata.json"
    data = {
        "tool": tool,
        "params": params,
        "runtime_seconds": round(runtime_seconds, 1),
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))
    return path


def _extract_ca_bfactors(pdb_path: Path) -> list[float]:
    """Extract B-factors from CA atoms in a PDB file."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", str(pdb_path))
    bfactors = []
    for model in structure:
        for chain in model:
            for residue in chain:
                if "CA" in residue:
                    bfactors.append(residue["CA"].get_bfactor())
        break  # first model only
    return bfactors


def _copy_raw(raw_dir: Path, output_dir: Path) -> None:
    """Copy raw output to output_dir/raw/."""
    dest = output_dir / "raw"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(str(raw_dir), str(dest))


def normalize_boltz_output(raw_dir: Path, output_dir: Path) -> Path:
    """Normalize Boltz-2 output to standardized layout.

    Raw structure (Boltz-2 nests under boltz_results_{input_stem}/):
        raw_dir/boltz_results_{stem}/predictions/{name}/{name}_model_0.cif
        raw_dir/boltz_results_{stem}/predictions/{name}/confidence_{name}_model_0.json

    Also handles the flat layout for backward compatibility:
        raw_dir/predictions/{name}/...
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find the predictions subdirectory — check flat first, then boltz_results_*
    pred_dir = raw_dir / "predictions"
    if not pred_dir.exists():
        # Boltz-2 nests output under boltz_results_{input_stem}/
        results_dirs = sorted(raw_dir.glob("boltz_results_*/predictions"))
        if results_dirs:
            pred_dir = results_dirs[0]
        else:
            raise FileNotFoundError(
                f"No predictions/ directory in {raw_dir} "
                f"(also checked boltz_results_*/predictions)"
            )

    # Get first (usually only) prediction subdirectory
    subdirs = [d for d in pred_dir.iterdir() if d.is_dir()]
    if not subdirs:
        raise FileNotFoundError(f"No prediction subdirectories in {pred_dir}")
    pred_subdir = subdirs[0]
    name = pred_subdir.name

    # Copy CIF → model_1.cif
    cif_files = list(pred_subdir.glob(f"{name}_model_0.cif"))
    if not cif_files:
        cif_files = list(pred_subdir.glob("*.cif"))
    if not cif_files:
        raise FileNotFoundError(f"No CIF files in {pred_subdir}")
    cif_src = cif_files[0]
    cif_dst = output_dir / "model_1.cif"
    shutil.copy2(str(cif_src), str(cif_dst))

    # Convert CIF → PDB
    mmcif_to_pdb(cif_dst, output_dir / "model_1.pdb")

    # Extract confidence from JSON + per-residue pLDDT from NPZ
    conf_files = list(pred_subdir.glob(f"confidence_{name}_model_0.json"))
    if not conf_files:
        conf_files = list(pred_subdir.glob("confidence_*.json"))

    plddt_array: list[float] = []
    plddt_mean = 0.0
    ptm = None

    # Per-residue pLDDT from NPZ (Boltz-2 writes plddt_{name}_model_0.npz)
    plddt_npz = list(pred_subdir.glob(f"plddt_{name}_model_0.npz"))
    if not plddt_npz:
        plddt_npz = list(pred_subdir.glob("plddt_*.npz"))
    if plddt_npz:
        plddt_data = np.load(str(plddt_npz[0]))
        plddt_array = plddt_data["plddt"].flatten().tolist()
        # Scale 0-1 → 0-100 if needed
        if plddt_array and max(plddt_array) <= 1.0:
            plddt_array = [v * 100 for v in plddt_array]
        plddt_mean = sum(plddt_array) / len(plddt_array) if plddt_array else 0.0

    if conf_files:
        conf_data = json.loads(conf_files[0].read_text())
        ptm = conf_data.get("ptm")
        # Use complex_plddt as mean if per-residue not available
        if not plddt_array:
            cplddt = conf_data.get("complex_plddt", conf_data.get("plddt"))
            if isinstance(cplddt, list):
                plddt_array = cplddt
                if plddt_array and max(plddt_array) <= 1.0:
                    plddt_array = [v * 100 for v in plddt_array]
                plddt_mean = sum(plddt_array) / len(plddt_array) if plddt_array else 0.0
            elif isinstance(cplddt, (int, float)):
                plddt_mean = cplddt * 100 if cplddt <= 1.0 else cplddt

    if plddt_array or ptm is not None:
        write_confidence_json(output_dir, plddt_mean, ptm, plddt_array)
    else:
        logger.warning("No confidence data found in %s", pred_subdir)

    _copy_raw(raw_dir, output_dir)
    return output_dir


def normalize_chai_output(raw_dir: Path, output_dir: Path) -> Path:
    """Normalize Chai-1 output to standardized layout.

    Raw structure:
        raw_dir/pred.model_idx_0.cif
        raw_dir/scores.model_idx_0.npz
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find best model CIF
    cif_files = sorted(raw_dir.glob("pred.model_idx_*.cif"))
    if not cif_files:
        raise FileNotFoundError(f"No pred.model_idx_*.cif files in {raw_dir}")
    cif_src = cif_files[0]  # model_idx_0 = best
    cif_dst = output_dir / "model_1.cif"
    shutil.copy2(str(cif_src), str(cif_dst))

    # Convert CIF → PDB
    pdb_dst = output_dir / "model_1.pdb"
    mmcif_to_pdb(cif_dst, pdb_dst)

    # Extract confidence from NPZ + PDB B-factors
    ptm = None
    score_files = sorted(raw_dir.glob("scores.model_idx_*.npz"))
    if score_files:
        data = np.load(str(score_files[0]))
        ptm = float(data["ptm"].item()) if "ptm" in data else None

    # Per-residue pLDDT from PDB B-factors (Chai stores 0-100 scale)
    per_residue = _extract_ca_bfactors(pdb_dst)
    # Chai B-factors are already 0-100
    plddt_mean = sum(per_residue) / len(per_residue) if per_residue else 0.0

    write_confidence_json(output_dir, plddt_mean, ptm, per_residue)

    _copy_raw(raw_dir, output_dir)
    return output_dir


def _find_af2_best_pdb(search_dir: Path) -> Path | None:
    """Find the best AlphaFold PDB: ranked_0.pdb > relaxed_model_1 > unrelaxed_model_1."""
    # Prefer ranked (post-relaxation)
    ranked = search_dir / "ranked_0.pdb"
    if ranked.exists():
        return ranked
    # Fall back to relaxed model 1
    relaxed = sorted(search_dir.glob("relaxed_model_*_pred_0.pdb"))
    if relaxed:
        return relaxed[0]
    # Fall back to unrelaxed model 1
    unrelaxed = sorted(search_dir.glob("unrelaxed_model_*_pred_0.pdb"))
    if unrelaxed:
        return unrelaxed[0]
    return None


def normalize_alphafold_output(raw_dir: Path, output_dir: Path) -> Path:
    """Normalize AlphaFold2 output to standardized layout.

    Raw structure (tries ranked > relaxed > unrelaxed):
        raw_dir/{target}/ranked_0.pdb
        raw_dir/{target}/relaxed_model_1_pred_0.pdb
        raw_dir/{target}/unrelaxed_model_1_pred_0.pdb
        raw_dir/{target}/ranking_debug.json
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # AF2 nests under a target subdirectory
    best_pdb = None
    ranking_json = None

    # Check for direct files first, then subdirectories
    best_pdb = _find_af2_best_pdb(raw_dir)
    if best_pdb:
        ranking_json = raw_dir / "ranking_debug.json"
    else:
        for subdir in raw_dir.iterdir():
            if subdir.is_dir():
                best_pdb = _find_af2_best_pdb(subdir)
                if best_pdb:
                    ranking_json = subdir / "ranking_debug.json"
                    break

    if best_pdb is None:
        raise FileNotFoundError(f"No AlphaFold PDB output found in {raw_dir}")

    if best_pdb.name.startswith("unrelaxed"):
        logger.warning("Using unrelaxed model (relaxation failed): %s", best_pdb.name)

    # Copy PDB → model_1.pdb
    pdb_dst = output_dir / "model_1.pdb"
    shutil.copy2(str(best_pdb), str(pdb_dst))

    # Convert PDB → CIF
    pdb_to_mmcif(pdb_dst, output_dir / "model_1.cif")

    # Extract confidence
    # Per-residue pLDDT from CA B-factors (AF2 stores pLDDT in B-factor, 0-100)
    per_residue = _extract_ca_bfactors(pdb_dst)
    plddt_mean = sum(per_residue) / len(per_residue) if per_residue else 0.0

    # Try ranking_debug.json for mean pLDDT (more accurate)
    ptm = None
    if ranking_json and ranking_json.exists():
        rdata = json.loads(ranking_json.read_text())
        plddts = rdata.get("plddts", {})
        if plddts:
            # Use the mean from ranking_debug if available
            order = rdata.get("order", [])
            if order:
                top_model = order[0]
                plddt_mean = plddts.get(top_model, plddt_mean)

    write_confidence_json(output_dir, plddt_mean, ptm, per_residue)
    _copy_raw(raw_dir, output_dir)
    return output_dir


def normalize_esmfold_output(raw_dir: Path, output_dir: Path) -> Path:
    """Normalize ESMFold output to standardized layout.

    Raw structure:
        raw_dir/{header}.pdb  (B-factors = pLDDT at 0-1 scale!)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find the first PDB file
    pdb_files = sorted(raw_dir.glob("*.pdb"))
    if not pdb_files:
        raise FileNotFoundError(f"No PDB files found in {raw_dir}")
    pdb_src = pdb_files[0]

    # Copy PDB → model_1.pdb
    pdb_dst = output_dir / "model_1.pdb"
    shutil.copy2(str(pdb_src), str(pdb_dst))

    # Convert PDB → CIF
    pdb_to_mmcif(pdb_dst, output_dir / "model_1.cif")

    # Extract confidence — ESMFold B-factors are 0-1, scale to 0-100
    raw_bfactors = _extract_ca_bfactors(pdb_dst)
    if raw_bfactors and max(raw_bfactors) <= 1.0:
        per_residue = [b * 100 for b in raw_bfactors]
    else:
        per_residue = raw_bfactors
    plddt_mean = sum(per_residue) / len(per_residue) if per_residue else 0.0

    # pTM not available in PDB output (logged to stdout by hf_fold.py)
    write_confidence_json(output_dir, plddt_mean, None, per_residue)
    _copy_raw(raw_dir, output_dir)
    return output_dir
