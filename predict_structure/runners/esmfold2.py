"""Runner for ESMFold2 (``biohub/ESMFold2``).

ESMFold2 ships only as a Python API, so the :class:`ESMFold2Adapter` writes a
JSON spec and delegates execution here (wired through ``tools.yml``). This
module loads that spec, drives the upstream ``fold()`` API, and writes the raw
artifacts the adapter's ``normalize_output`` consumes:

    <output-dir>/model_1.cif        # result.complex.to_mmcif()
    <output-dir>/confidence.json    # {plddt, per_residue_plddt, ptm, iptm}

Upstream API (per the model card)::

    from esm.models.esmfold2 import (
        DNAInput, ESMFold2InputBuilder, LigandInput, Modification,
        ProteinInput, RNAInput, StructurePredictionInput,
    )
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

    model = ESMFold2Model.from_pretrained("biohub/ESMFold2").cuda().eval()
    spi = StructurePredictionInput(sequences=[ProteinInput(id="A", sequence=...)])
    result = ESMFold2InputBuilder().fold(
        model, spi, num_loops=3, num_sampling_steps=50,
        num_diffusion_samples=1, seed=0,
    )
    # result.plddt, result.ptm, result.iptm, result.complex.to_mmcif()

The runner is intentionally defensive about optional pieces of the API
(``RNAInput``, ``Modification`` keyword names, scalar-vs-array confidence
fields) so a minor upstream signature change degrades gracefully instead of
crashing the whole prediction.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("predict_structure.runners.esmfold2")


def _build_inputs(spec: dict[str, Any]) -> list[Any]:
    """Map JSON spec records to ``esm.models.esmfold2`` input objects."""
    from esm.models import esmfold2 as ef2

    ProteinInput = ef2.ProteinInput
    DNAInput = ef2.DNAInput
    LigandInput = ef2.LigandInput
    RNAInput = getattr(ef2, "RNAInput", None)
    Modification = getattr(ef2, "Modification", None)
    MSA = getattr(ef2, "MSA", None)

    def _msa(record: dict[str, Any]) -> Any:
        """Load a chain's A3M, if the spec carries one.

        ESMFold2 wants the query as row 0 with insertions stripped; the adapter
        already verified that row matches this chain's sequence. Failing loudly
        beats folding single-sequence behind the user's back — silently dropping
        the MSA is the bug this path exists to fix (#95).
        """
        path = record.get("msa")
        if not path:
            return None
        if MSA is None:
            raise ValueError(
                "esm.models.esmfold2 exposes no MSA type; this build of esm "
                "cannot accept MSA input"
            )
        logger.info("Loading MSA for chain %s from %s", record.get("id"), path)
        try:
            msa = MSA.from_a3m(path, remove_insertions=True)
        except Exception as exc:
            # Name the chain and the file: a bare FileNotFoundError from deep in
            # the loader tells the user nothing about which input was at fault.
            raise ValueError(
                f"Failed to load the MSA for chain {record.get('id')!r} from "
                f"{path}: {exc}"
            ) from exc
        logger.info("MSA depth %d for chain %s", len(msa.sequences), record.get("id"))
        return msa

    def _mods(record: dict[str, Any]) -> list[Any]:
        raw = record.get("modifications") or []
        if not raw or Modification is None:
            if raw and Modification is None:
                logger.warning("esm.models.esmfold2.Modification unavailable; "
                               "ignoring %d modification(s)", len(raw))
            return []
        out = []
        for m in raw:
            try:
                out.append(Modification(position=int(m["position"]), ccd=str(m["ccd"])))
            except Exception as exc:  # pragma: no cover - upstream signature drift
                logger.warning("Skipping modification %r: %s", m, exc)
        return out

    inputs: list[Any] = []
    for rec in spec.get("sequences", []):
        etype = rec.get("type")
        cid = rec.get("id")
        if etype == "protein":
            # Pass msa= only when there is one. This module is deliberately
            # defensive about optional parts of the upstream API, and an esm
            # build whose ProteinInput lacks the field (ESMFold2-Fast is
            # single-sequence) would otherwise reject the kwarg and break every
            # job, including ones with no MSA at all.
            kwargs: dict[str, Any] = {
                "id": cid, "sequence": rec["sequence"], "modifications": _mods(rec),
            }
            msa = _msa(rec)
            if msa is not None:
                kwargs["msa"] = msa
            inputs.append(ProteinInput(**kwargs))
        elif etype == "dna":
            inputs.append(DNAInput(id=cid, sequence=rec["sequence"], modifications=_mods(rec)))
        elif etype == "rna":
            if RNAInput is None:
                raise ValueError("esm.models.esmfold2 has no RNAInput; RNA entity unsupported")
            inputs.append(RNAInput(id=cid, sequence=rec["sequence"], modifications=_mods(rec)))
        elif etype == "ligand":
            if "ccd" in rec:
                inputs.append(LigandInput(id=cid, ccd=rec["ccd"]))
            elif "smiles" in rec:
                inputs.append(LigandInput(id=cid, smiles=rec["smiles"]))
            else:
                raise ValueError(f"Ligand entity {cid!r} has neither 'ccd' nor 'smiles'")
        else:
            raise ValueError(f"Unsupported ESMFold2 entity type: {etype!r}")
    if not inputs:
        raise ValueError("ESMFold2 spec contains no sequences")
    return inputs


def _to_float_list(value: Any) -> list[float]:
    """Coerce a scalar / list / numpy / torch confidence value to a float list."""
    if value is None:
        return []
    if hasattr(value, "detach"):  # torch tensor
        value = value.detach().cpu()
    if hasattr(value, "tolist"):  # numpy array or torch tensor
        value = value.tolist()
    if isinstance(value, (int, float)):
        return [float(value)]
    try:
        flat: list[float] = []
        for v in value:
            flat.extend(_to_float_list(v))
        return flat
    except TypeError:
        return [float(value)]


def _to_scalar(value: Any) -> float | None:
    vals = _to_float_list(value)
    if not vals:
        return None
    return sum(vals) / len(vals) if len(vals) > 1 else vals[0]


def _write_confidence(result: Any, out_dir: Path) -> None:
    per_residue = _to_float_list(getattr(result, "plddt", None))
    plddt_mean = (sum(per_residue) / len(per_residue)) if per_residue else 0.0
    conf = {
        "plddt": plddt_mean,
        "per_residue_plddt": per_residue,
        "ptm": _to_scalar(getattr(result, "ptm", None)),
        "iptm": _to_scalar(getattr(result, "iptm", None)),
    }
    (out_dir / "confidence.json").write_text(json.dumps(conf, indent=2))
    logger.info("Wrote confidence.json (mean pLDDT=%.4f, %d residues)",
                plddt_mean, len(per_residue))


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = json.loads(Path(args.spec).read_text())
    inputs = _build_inputs(spec)

    import torch
    from esm.models.esmfold2 import ESMFold2InputBuilder, StructurePredictionInput
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

    use_cuda = not args.cpu_only and torch.cuda.is_available()
    if use_cuda:
        torch.cuda.reset_peak_memory_stats()

    logger.info("Loading ESMFold2 checkpoint %s", args.checkpoint)
    t0 = time.perf_counter()
    model = ESMFold2Model.from_pretrained(args.checkpoint)
    if use_cuda:
        model = model.cuda().eval()
    else:
        # The checkpoint loads in bf16, but CPU kernels mix fp32/bf16 and raise
        # "expected m1 and m2 to have the same dtype". Force fp32 for CPU.
        model = model.cpu().float().eval()
    load_secs = time.perf_counter() - t0
    logger.info("Model loaded in %.1fs (device=%s)", load_secs, "cuda" if use_cuda else "cpu")

    spi = StructurePredictionInput(sequences=inputs)

    fold_kwargs: dict[str, Any] = {
        "num_loops": args.num_loops,
        "num_sampling_steps": args.num_sampling_steps,
        "num_diffusion_samples": args.num_diffusion_samples,
    }
    if args.seed is not None:
        fold_kwargs["seed"] = args.seed

    logger.info("Folding %d entit(ies) with %s", len(inputs), fold_kwargs)
    t1 = time.perf_counter()
    result = ESMFold2InputBuilder().fold(model, spi, **fold_kwargs)
    fold_secs = time.perf_counter() - t1
    if isinstance(result, (list, tuple)):  # multiple diffusion samples → best first
        result = result[0]

    if use_cuda:
        peak_gb = torch.cuda.max_memory_allocated() / 1e9
        reserved_gb = torch.cuda.max_memory_reserved() / 1e9
        logger.info("PERF load=%.1fs fold=%.1fs peak_gpu=%.2fGB reserved_gpu=%.2fGB",
                    load_secs, fold_secs, peak_gb, reserved_gb)
    else:
        logger.info("PERF load=%.1fs fold=%.1fs device=cpu", load_secs, fold_secs)

    mmcif = result.complex.to_mmcif()
    (out_dir / "model_1.cif").write_text(mmcif)
    logger.info("Wrote model_1.cif (%d bytes)", len(mmcif))

    _write_confidence(result, out_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="predict_structure.runners.esmfold2",
        description="Run ESMFold2 from a JSON spec (invoked by ESMFold2Adapter).",
    )
    p.add_argument("--spec", required=True, help="Path to the ESMFold2 input JSON spec")
    p.add_argument("--output-dir", required=True, help="Directory for model_1.cif + confidence.json")
    p.add_argument("--num-loops", type=int, default=3, help="ESMFold2 num_loops (recycling)")
    p.add_argument("--num-sampling-steps", type=int, default=50, help="Diffusion sampling steps")
    p.add_argument("--num-diffusion-samples", type=int, default=1, help="Diffusion samples")
    p.add_argument("--checkpoint", default="biohub/ESMFold2", help="HF checkpoint id or path")
    p.add_argument("--seed", type=int, default=None, help="Random seed")
    p.add_argument("--cpu-only", action="store_true", help="Run on CPU instead of CUDA")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        logger.error("ESMFold2 runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
