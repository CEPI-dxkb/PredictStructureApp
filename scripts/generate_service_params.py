#!/usr/bin/env python3
"""Generate Phase 3 service-script params JSON files for the tier ladder.

Emits `test_data/service_params/{tier}_{tool}.json` for every (tier, tool)
combination supported by the BV-BRC service script (App-PredictStructure.pl).

Usage:
    python scripts/generate_service_params.py [--check]

  --check  diff against the on-disk files; exit non-zero if drift.
           CI runs this after pulling, to catch hand-edited drift.

The generator is the single source of truth for params files. Hand-edit
this script, not the JSON, then re-run to regenerate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARAMS_DIR = REPO / "test_data" / "service_params"

# Container-side paths -- must match tests/acceptance/matrix.py.
T1_FASTA = "/data/simple_protein.fasta"
T2_FASTA = "/data/medium_protein.fasta"
T4_FASTA = "/data/multimer.fasta"
T5_FASTA = "/data/large_protein.fasta"

T1_MSA = "/data/msa/crambin.a3m"
T2_MSA = "/data/msa/medium_protein.a3m"
T5_MSA = "/data/msa/large_protein.a3m"

# T3 multi-entity uses text_input (protein + DNA) since the service
# script's params surface accepts protein/dna/rna types but not ligand.
# Ligand-multi-entity coverage lives in Phase 2 (adapter layer) instead.
T3_PROTEIN_SEQ = (
    "MKMTSKEELKQLSEAKKALEEKALKAREEKKAESLENRKEEAEAQAKEALKQELEAEARAEEALQDA"
)
T3_DNA_SEQ = "ATGCGTACGTAGCTAGCTAGCGT"


def _common(tool: str, output_file: str, **extras) -> dict:
    base = {
        "tool": tool,
        "output_path": "/output",
        "output_file": output_file,
        "num_recycles": 3,
        "output_format": "pdb",
        "msa_mode": "none",
        "seed": 42,
    }
    base.update(extras)
    return base


def _with_msa_upload(params: dict, msa_path: str) -> dict:
    """Switch a params dict to msa_mode=upload with the given path."""
    params["msa_mode"] = "upload"
    params["msa_file"] = msa_path
    return params


# Per-tool MSA policy mirrors tests/acceptance/matrix.py::msa_args_for.
NEEDS_MSA_FILE = {"boltz", "chai", "openfold"}    # for non-AF/ESM tools

# AlphaFold needs af2-data-dir but the service params don't expose that
# directly -- it's set by the service script via env or CLI default.
# Skip AlphaFold for tier params here; Phase 1/2 cover AF.

TOOLS_PER_TIER: dict[str, tuple[str, ...]] = {
    "tier1": ("boltz", "chai", "openfold", "esmfold"),
    "tier2": ("boltz", "chai", "openfold", "esmfold"),
    "tier3": ("boltz", "chai", "openfold"),
    "tier4": ("boltz", "chai", "openfold", "esmfold"),
    "tier5": ("boltz", "chai", "openfold"),  # esmfold doable but slow; skip
}


def build_params() -> dict[str, dict]:
    """Return {filename: params_dict} for every supported (tier, tool)."""
    out: dict[str, dict] = {}

    # T1 -- input_file, crambin
    for tool in TOOLS_PER_TIER["tier1"]:
        p = _common(tool, f"tier1_{tool}_test", input_file=T1_FASTA)
        if tool in NEEDS_MSA_FILE:
            _with_msa_upload(p, T1_MSA)
        if tool in {"boltz", "chai"}:
            p["sampling_steps"] = 200
            p["num_samples"] = 1
        if tool == "esmfold":
            p["fp16"] = True
        out[f"tier1_{tool}.json"] = p

    # T2 -- input_file, 1AKE 214 aa
    for tool in TOOLS_PER_TIER["tier2"]:
        p = _common(tool, f"tier2_{tool}_test", input_file=T2_FASTA)
        if tool in NEEDS_MSA_FILE:
            _with_msa_upload(p, T2_MSA)
        if tool in {"boltz", "chai"}:
            p["sampling_steps"] = 200
            p["num_samples"] = 1
        if tool == "esmfold":
            p["fp16"] = True
        out[f"tier2_{tool}.json"] = p

    # T3 -- text_input (multi-entity, protein + DNA)
    for tool in TOOLS_PER_TIER["tier3"]:
        p = _common(tool, f"tier3_{tool}_test")
        p["text_input"] = [
            {"type": "protein", "sequence": T3_PROTEIN_SEQ},
            {"type": "dna",     "sequence": T3_DNA_SEQ},
        ]
        if tool in {"boltz", "chai"}:
            p["sampling_steps"] = 200
            p["num_samples"] = 1
        out[f"tier3_{tool}.json"] = p

    # T4 -- multimer (single FASTA with 2 chains)
    for tool in TOOLS_PER_TIER["tier4"]:
        p = _common(tool, f"tier4_{tool}_test", input_file=T4_FASTA)
        if tool in {"boltz", "chai"}:
            p["sampling_steps"] = 200
            p["num_samples"] = 1
        if tool == "esmfold":
            p["fp16"] = True
        out[f"tier4_{tool}.json"] = p

    # T5 -- large protein (input_file, 434 aa). Slow.
    for tool in TOOLS_PER_TIER["tier5"]:
        p = _common(tool, f"tier5_{tool}_test", input_file=T5_FASTA)
        if tool in NEEDS_MSA_FILE:
            _with_msa_upload(p, T5_MSA)
        if tool in {"boltz", "chai"}:
            p["sampling_steps"] = 200
            p["num_samples"] = 1
        out[f"tier5_{tool}.json"] = p

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--check", action="store_true",
        help="Diff against on-disk files; exit non-zero on drift.",
    )
    args = parser.parse_args()

    PARAMS_DIR.mkdir(exist_ok=True)
    expected = build_params()
    drift = []

    for filename, params in expected.items():
        target = PARAMS_DIR / filename
        text = json.dumps(params, indent=2) + "\n"
        if args.check:
            current = target.read_text() if target.is_file() else ""
            if current != text:
                drift.append(filename)
            continue
        target.write_text(text)
        print(f"  wrote {filename}")

    if args.check:
        if drift:
            print(f"DRIFT in {len(drift)} files: {drift}", file=sys.stderr)
            return 1
        print("All service params files match generator output.")
    else:
        print(f"Generated {len(expected)} files in {PARAMS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
