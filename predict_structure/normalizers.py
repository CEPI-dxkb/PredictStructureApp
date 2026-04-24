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
    per_atom_plddt: list[float] | None = None,
) -> Path:
    """Write standardized confidence metrics.

    Args:
        output_dir: Target directory.
        plddt_mean: Average per-residue confidence (0-100 scale).
        ptm: Predicted TM-score (None if unavailable).
        per_residue_plddt: Per-residue pLDDT array (0-100 scale).
        per_atom_plddt: Optional per-atom pLDDT array, ordered to match
            ATOM records in model_1.pdb. Length >= per_residue_plddt length.
            For AF3-style tools (Boltz, Chai, OpenFold) this has true per-atom
            values; for AF2/ESMFold the residue value is replicated across
            each residue's atoms.

    Returns:
        Path to confidence.json.
    """
    path = output_dir / "confidence.json"
    data = {
        "plddt_mean": round(plddt_mean, 2),
        "ptm": round(ptm, 4) if ptm is not None else None,
        "per_residue_plddt": [round(v, 2) for v in per_residue_plddt],
    }
    if per_atom_plddt is not None:
        if len(per_atom_plddt) < len(per_residue_plddt):
            raise ValueError(
                f"per_atom_plddt ({len(per_atom_plddt)}) shorter than "
                f"per_residue_plddt ({len(per_residue_plddt)})"
            )
        data["per_atom_plddt"] = [round(v, 2) for v in per_atom_plddt]
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


def _extract_bfactors(pdb_path: Path) -> tuple[list[float], list[float]]:
    """Extract per-residue and per-atom B-factors from a PDB file in one pass.

    Hetatms (ligands, waters) are excluded from both lists. Only the first
    model is read.

    Per-residue convention:
      - Protein residues: CA atom's B-factor (standard pLDDT convention).
      - DNA/RNA residues: C1' (sugar carbon; standard backbone reference).
      - Fallback (no CA or C1'): first atom in the residue.

    Returns:
        (per_residue_bfactors, per_atom_bfactors)
    """
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", str(pdb_path))
    per_residue: list[float] = []
    all_atom: list[float] = []
    for model in structure:
        for chain in model:
            for residue in chain:
                # Biopython residue.id is (hetflag, resseq, icode);
                # " " means a standard residue, anything else is a hetatm.
                if residue.id[0] != " ":
                    continue
                residue_atoms = list(residue)
                if not residue_atoms:
                    continue
                all_atom.extend(a.get_bfactor() for a in residue_atoms)
                # Pick a representative atom: CA for protein, C1' for
                # nucleic acids, else first atom.
                if "CA" in residue:
                    rep = residue["CA"]
                elif "C1'" in residue:
                    rep = residue["C1'"]
                else:
                    rep = residue_atoms[0]
                per_residue.append(rep.get_bfactor())
        break  # first model only
    return per_residue, all_atom


def _extract_ca_bfactors(pdb_path: Path) -> list[float]:
    """Return per-residue pLDDT (thin wrapper for back-compat)."""
    return _extract_bfactors(pdb_path)[0]


def _extract_all_atom_bfactors(pdb_path: Path) -> list[float]:
    """Return per-atom pLDDT (thin wrapper for back-compat)."""
    return _extract_bfactors(pdb_path)[1]


def _copy_raw(raw_dir: Path, output_dir: Path) -> None:
    """Copy raw output to output_dir/raw/."""
    dest = output_dir / "raw"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(str(raw_dir), str(dest))


def move_reports_to_subdir(output_dir: Path) -> Path | None:
    """Relocate protein_compare report files into output_dir/report/.

    `protein_compare characterize -o <prefix>` writes `<prefix>.html`,
    `<prefix>.json`, `<prefix>.pdf` at the top level. For a unified layout
    we move any `report.{html,json,pdf}` into a `report/` subdir so the
    top level stays uniformly machine-readable and `report.json` doesn't
    collide with `results.json`.

    No-op if no report files are present. Safe to call multiple times.

    Returns:
        Path to the `report/` directory if any reports were moved, else None.
    """
    report_names = ("report.html", "report.json", "report.pdf")
    moved = False
    dest = output_dir / "report"
    for name in report_names:
        src = output_dir / name
        if src.is_file():
            dest.mkdir(exist_ok=True)
            shutil.move(str(src), str(dest / name))
            moved = True
    return dest if moved else None


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
        _, per_atom = _extract_bfactors(output_dir / "model_1.pdb")
        # Apply the same 0-1 -> 0-100 heuristic as per-residue so both
        # arrays share the same scale.
        if per_atom and max(per_atom) <= 1.0:
            per_atom = [v * 100 for v in per_atom]
        write_confidence_json(output_dir, plddt_mean, ptm, plddt_array,
                              per_atom_plddt=per_atom)
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

    # Per-residue (CA) and per-atom pLDDT from PDB B-factors (Chai stores 0-100)
    per_residue, per_atom = _extract_bfactors(pdb_dst)
    plddt_mean = sum(per_residue) / len(per_residue) if per_residue else 0.0

    write_confidence_json(output_dir, plddt_mean, ptm, per_residue,
                          per_atom_plddt=per_atom)

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

    # AF2 stores per-residue pLDDT (0-100) in B-factors, duplicated across atoms.
    per_residue, per_atom = _extract_bfactors(pdb_dst)
    plddt_mean = sum(per_residue) / len(per_residue) if per_residue else 0.0

    # Prefer ranking_debug.json's mean pLDDT over the simple average (it uses
    # the model-selection score, which may differ from raw CA B-factor mean).
    ptm = None
    if ranking_json and ranking_json.exists():
        rdata = json.loads(ranking_json.read_text())
        plddts = rdata.get("plddts", {})
        order = rdata.get("order", [])
        if plddts and order:
            plddt_mean = plddts.get(order[0], plddt_mean)

    write_confidence_json(output_dir, plddt_mean, ptm, per_residue,
                          per_atom_plddt=per_atom)
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

    # ESMFold writes pLDDT as PDB B-factors, sometimes on 0-1 and sometimes
    # on 0-100 scale depending on version. Detect from CA values and scale.
    per_residue, per_atom = _extract_bfactors(pdb_dst)
    if per_residue and max(per_residue) <= 1.0:
        per_residue = [b * 100 for b in per_residue]
        per_atom = [b * 100 for b in per_atom]
    plddt_mean = sum(per_residue) / len(per_residue) if per_residue else 0.0

    # pTM not available in PDB output (logged to stdout by hf_fold.py)
    write_confidence_json(output_dir, plddt_mean, None, per_residue,
                          per_atom_plddt=per_atom)
    _copy_raw(raw_dir, output_dir)
    return output_dir


def normalize_openfold_output(raw_dir: Path, output_dir: Path) -> Path:
    """Normalize OpenFold 3 output to standardized layout.

    Raw structure (OF3 nests under query_name/seed_N/):
        raw_dir/<query_name>/seed_<N>/<query>_seed_<N>_sample_<M>_model.cif
        raw_dir/<query_name>/seed_<N>/<query>_seed_<N>_sample_<M>_confidences.json
        raw_dir/<query_name>/seed_<N>/<query>_seed_<N>_sample_<M>_confidences_aggregated.json
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find the first query subdirectory
    query_dirs = [d for d in raw_dir.iterdir() if d.is_dir() and d.name != "raw"]
    if not query_dirs:
        raise FileNotFoundError(f"No query output directories in {raw_dir}")
    query_dir = query_dirs[0]

    # Find the first seed subdirectory
    seed_dirs = sorted(d for d in query_dir.iterdir() if d.is_dir() and d.name.startswith("seed_"))
    if not seed_dirs:
        raise FileNotFoundError(f"No seed_* directories in {query_dir}")
    seed_dir = seed_dirs[0]

    # Find model CIF files and select the best sample by ranking score
    model_files = sorted(seed_dir.glob("*_model.cif"))
    if not model_files:
        raise FileNotFoundError(f"No *_model.cif files in {seed_dir}")

    best_cif = model_files[0]
    best_score = -float("inf")

    for cif in model_files:
        # Derive aggregated confidences filename from model filename
        # e.g. prediction_seed_42_sample_1_model.cif
        #    → prediction_seed_42_sample_1_confidences_aggregated.json
        agg_path = cif.parent / cif.name.replace("_model.cif", "_confidences_aggregated.json")
        if agg_path.exists():
            agg_data = json.loads(agg_path.read_text())
            score = agg_data.get("sample_ranking_score", -float("inf"))
            if score > best_score:
                best_score = score
                best_cif = cif

    # Copy best CIF → model_1.cif
    cif_dst = output_dir / "model_1.cif"
    shutil.copy2(str(best_cif), str(cif_dst))

    # Convert CIF → PDB
    mmcif_to_pdb(cif_dst, output_dir / "model_1.pdb")

    # Extract confidence from aggregated JSON
    stem = best_cif.name.replace("_model.cif", "")
    agg_path = best_cif.parent / f"{stem}_confidences_aggregated.json"
    conf_path = best_cif.parent / f"{stem}_confidences.json"

    plddt_mean = 0.0
    ptm = None
    per_residue: list[float] = []

    if agg_path.exists():
        agg_data = json.loads(agg_path.read_text())
        plddt_mean = float(agg_data.get("avg_plddt", 0.0))
        ptm = agg_data.get("ptm")
        if ptm is not None:
            ptm = float(ptm)

    # OpenFold 3's confidences.json has per-ATOM pLDDT by design (AF3 atomization
    # convention -- see docs/OUTPUT_NORMALIZATION.md). Use CA B-factors for the
    # per-residue convention consumers expect.
    per_residue, per_atom = _extract_bfactors(output_dir / "model_1.pdb")
    if per_residue and not plddt_mean:
        plddt_mean = sum(per_residue) / len(per_residue)

    write_confidence_json(output_dir, plddt_mean, ptm, per_residue,
                          per_atom_plddt=per_atom)
    _copy_raw(raw_dir, output_dir)
    return output_dir
