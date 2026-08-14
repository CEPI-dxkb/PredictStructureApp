"""ESMFold2 adapter for biomolecular structure prediction.

ESMFold2 (``biohub/ESMFold2``) is a diffusion-based model exposed only as a
Python API:

    from esm.models.esmfold2 import (
        DNAInput, ESMFold2InputBuilder, LigandInput, Modification,
        ProteinInput, StructurePredictionInput,
    )
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

    model = ESMFold2Model.from_pretrained("biohub/ESMFold2").cuda().eval()
    spi = StructurePredictionInput(sequences=[
        ProteinInput(id="A", sequence=...),
        DNAInput(id="B", sequence=..., modifications=[Modification(...)]),
        LigandInput(id="L", ccd=["SAH"]),
    ])
    result = ESMFold2InputBuilder().fold(
        model, spi, num_loops=3, num_sampling_steps=50,
        num_diffusion_samples=1, seed=0,
    )
    # result.plddt, result.ptm, result.iptm, result.complex.to_mmcif()

Because there is no upstream CLI, this adapter writes the prediction spec to
a JSON file and delegates execution to the project's runner module
(``predict_structure.runners.esmfold2``), configured via ``tools.yml``. The
runner is expected to load the JSON, call the API shown above, and write
``model_1.cif`` plus ``confidence.json`` (with ``plddt``, ``per_residue_plddt``,
``ptm``, ``iptm``) into the output directory.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from predict_structure.adapters.base import BaseAdapter
from predict_structure.converters import mmcif_to_pdb
from predict_structure.entities import Entity, EntityList, EntityType
from predict_structure.normalizers import (
    predictions_dir,
    promote_best_model,
    write_confidence_json,
    _copy_raw,
)

logger = logging.getLogger(__name__)


def _entity_to_esmfold2_spec(entity: Entity) -> dict[str, Any]:
    """Render a single entity as a JSON-serialisable ESMFold2 input record.

    The schema mirrors the keyword arguments of ``ProteinInput`` / ``DNAInput``
    / ``RNAInput`` / ``LigandInput`` in ``esm.models.esmfold2`` so the runner
    can map each record to its constructor without a separate adapter table.
    """
    spec: dict[str, Any] = {"id": entity.chain_id}

    if entity.entity_type == EntityType.PROTEIN:
        spec["type"] = "protein"
        spec["sequence"] = entity.value
    elif entity.entity_type == EntityType.DNA:
        spec["type"] = "dna"
        spec["sequence"] = entity.value
    elif entity.entity_type == EntityType.RNA:
        spec["type"] = "rna"
        spec["sequence"] = entity.value
    elif entity.entity_type == EntityType.LIGAND:
        spec["type"] = "ligand"
        spec["ccd"] = [entity.value]
    elif entity.entity_type == EntityType.SMILES:
        spec["type"] = "ligand"
        spec["smiles"] = entity.value
    else:
        raise ValueError(f"ESMFold2 does not support entity type {entity.entity_type}")

    # Modifications are carried on the Entity metadata when present.
    mods = getattr(entity, "modifications", None)
    if mods:
        spec["modifications"] = [
            {"position": int(m["position"]), "ccd": str(m["ccd"])} for m in mods
        ]

    return spec


def _a3m_query_sequence(msa_path: Path) -> str:
    """Return the query (first) sequence of an A3M, insertions stripped.

    ESMFold2 requires the MSA's first row to be the query and to match the
    chain's sequence exactly, so this is what we match chains against. A3M
    lowercase letters mark insertions relative to the query and are removed.
    """
    seq_lines: list[str] = []
    with msa_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(">"):
                if seq_lines:
                    break          # hit the second record — query is complete
                continue
            seq_lines.append(line)
    query = "".join(seq_lines)
    # Drop A3M lowercase insertions, then every gap and terminator character.
    # '.' is a2m-style gap padding and '*' a translated stop codon; both are
    # common in real files and neither is part of the chain, so leaving them in
    # would fail the match and kill a job over formatting.
    query = "".join(c for c in query if not c.islower())
    return query.translate(str.maketrans("", "", "-.*~ ")).upper()


def _attach_msa(specs: list[dict[str, Any]], msa_path: Path) -> None:
    """Attach ``msa_path`` to the protein chain whose sequence it describes.

    ESMFold2 takes one MSA per chain (``ProteinInput.msa``). We are given a
    single uploaded file, so it belongs to whichever protein chain the A3M's
    query row matches. Guessing wrong is worse than refusing: a mismatched MSA
    is rejected deep inside the tool, and silently folding without it is the
    exact failure this feature exists to remove (#95).
    """
    proteins = [s for s in specs if s.get("type") == "protein"]
    if not proteins:
        raise ValueError(
            f"--msa {msa_path} was supplied but the job has no protein chain "
            f"to attach it to."
        )

    query = _a3m_query_sequence(msa_path)
    matches = [s for s in proteins if s["sequence"].upper() == query]
    if not matches:
        def _describe(label: str, seq: str) -> str:
            head = seq[:24] + ("…" if len(seq) > 24 else "")
            return f"{label} {len(seq)} aa ({head})"

        raise ValueError(
            f"The MSA in {msa_path} does not match any protein chain in this "
            f"job. ESMFold2 requires the first sequence of the A3M to be the "
            f"query and to match the chain exactly. "
            + _describe("A3M query:", query)
            + "; chains: "
            + ", ".join(_describe(f"{s['id']}=", s["sequence"]) for s in proteins)
            + ". Supply the MSA built for this sequence, or drop --msa to fold "
            + "single-sequence."
        )
    if len(matches) > 1:
        logger.info(
            "MSA matches %d identical protein chains; attaching to all of them",
            len(matches),
        )
    for spec in matches:
        spec["msa"] = str(msa_path)


def entities_to_esmfold2_json(
    entity_list: EntityList,
    output_path: Path,
    msa_path: Path | None = None,
) -> Path:
    """Write an EntityList as an ESMFold2 ``StructurePredictionInput`` spec."""
    specs = [_entity_to_esmfold2_spec(e) for e in entity_list]
    if msa_path is not None:
        _attach_msa(specs, Path(msa_path))
    spec = {"sequences": specs}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2))
    logger.info("Wrote ESMFold2 spec with %d entries to %s", len(spec["sequences"]), output_path)
    return output_path


class ESMFold2Adapter(BaseAdapter):
    """Adapter for ESMFold2 multi-entity structure prediction.

    Accepts proteins, DNA, RNA, and CCD ligands in one input, with optional
    residue modifications. Produces an mmCIF complex and pLDDT / pTM / ipTM
    scores.

    The ``biohub/ESMFold2`` checkpoint we default to accepts an optional
    per-chain MSA (``ProteinInput.msa``, built via ``MSA.from_a3m``); upstream
    reports ipTM 0.19 -> 0.85 on PDB 7YTU with one. An uploaded ``--msa`` is
    wired through (#95). Fetching one from a server is not — ``esm`` ships no
    MSA-server client, so that work is ours to do (#96).

    ``ESMFold2-Fast`` is the genuinely single-sequence variant; if the default
    checkpoint ever changes to it, MSA support must go back off.
    """

    tool_name: str = "esmfold2"
    display_name: str = "ESMFold2"
    supports_msa: bool = True
    requires_gpu: bool = True
    #: Measured peak on H200: 13.9-14.0 GB allocated, 14.1-14.3 GB reserved
    #: (crambin 46aa through ubiquitin+ATP 107 tokens). Without this the
    #: adapter inherited BaseAdapter's 8000 MiB, so the GPU precheck would wave
    #: through a host with 8-14 GB free and the run would then OOM.
    min_gpu_memory_mb: int = 18000
    supported_entities: frozenset[EntityType] = frozenset({
        EntityType.PROTEIN, EntityType.DNA, EntityType.RNA,
        EntityType.LIGAND, EntityType.SMILES,
    })

    def prepare_input(
        self,
        entity_list: EntityList,
        output_dir: Path,
        *,
        msa_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Convert entity list to an ESMFold2 JSON spec, attaching any MSA.

        The MSA is recorded per protein chain in the spec; the runner loads it
        with ``MSA.from_a3m`` and hands it to ``ProteinInput``.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        if msa_path is not None:
            logger.info("Attaching MSA %s to the ESMFold2 spec", msa_path)
        return entities_to_esmfold2_json(
            entity_list, output_dir / "input.json", msa_path=msa_path,
        )

    def build_command(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        num_samples: int = 5,
        num_recycles: int = 3,
        seed: int | None = None,
        device: str = "gpu",
        **kwargs: Any,
    ) -> list[str]:
        """Construct the ESMFold2 runner invocation.

        Parameter mapping (shared → ESMFold2 ``fold()`` kwargs):
          --num-samples    → ``num_diffusion_samples``
          --num-recycles   → ``num_loops``
          --seed           → ``seed``
          sampling_steps   → ``num_sampling_steps``  (default 50, per upstream)
        """
        from predict_structure.config import get_command

        num_sampling_steps = kwargs.get("sampling_steps", 50)
        checkpoint = kwargs.get("checkpoint", "biohub/ESMFold2")

        cmd = [
            *get_command("esmfold2"),
            "--spec", str(input_path),
            "--output-dir", str(output_dir),
            "--num-loops", str(num_recycles),
            "--num-sampling-steps", str(num_sampling_steps),
            "--num-diffusion-samples", str(num_samples),
            "--checkpoint", str(checkpoint),
        ]
        if seed is not None:
            cmd.extend(["--seed", str(seed)])
        if device == "cpu":
            cmd.append("--cpu-only")

        return cmd

    def run(self, command: list[str], **kwargs: Any) -> int:
        """Execute prediction via the configured backend."""
        backend = kwargs.get("backend")
        if backend is None:
            from predict_structure.backends.subprocess import SubprocessBackend
            backend = SubprocessBackend()
        return backend.run(command, tool_name=self.tool_name, **kwargs)

    def normalize_output(self, raw_output_dir: Path, output_dir: Path) -> Path:
        """Normalize ESMFold2 output to the standard layout.

        Expected raw layout (produced by the runner):
            raw_output_dir/
                model_1.cif       (from ``result.complex.to_mmcif()``)
                confidence.json   {plddt: float, per_residue_plddt: [...],
                                   ptm: float, iptm: float}
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        pred = predictions_dir(output_dir)

        cif_candidates = sorted(raw_output_dir.glob("*.cif"))
        if not cif_candidates:
            raise FileNotFoundError(f"No .cif files in {raw_output_dir}")
        cif_src = cif_candidates[0]

        cif_dst = pred / "model_1.cif"
        shutil.copy2(str(cif_src), str(cif_dst))
        mmcif_to_pdb(cif_dst, pred / "model_1.pdb")

        # Confidence: the runner is expected to write a small JSON summary.
        conf_src = raw_output_dir / "confidence.json"
        plddt_mean = 0.0
        ptm: float | None = None
        iptm: float | None = None
        per_residue: list[float] = []
        if conf_src.exists():
            data = json.loads(conf_src.read_text())
            per_residue = [float(v) for v in data.get("per_residue_plddt", [])]
            plddt_mean = float(data.get("plddt", sum(per_residue) / len(per_residue) if per_residue else 0.0))
            ptm = float(data["ptm"]) if data.get("ptm") is not None else None
            iptm = float(data["iptm"]) if data.get("iptm") is not None else None
            # ESMFold2 reports pLDDT on 0-1; normalize to 0-100 to match the rest of the app.
            if per_residue and max(per_residue) <= 1.0:
                per_residue = [v * 100 for v in per_residue]
                if plddt_mean <= 1.0:
                    plddt_mean *= 100
        else:
            logger.warning("ESMFold2 confidence.json not found in %s", raw_output_dir)

        conf_path = write_confidence_json(output_dir, plddt_mean, ptm, per_residue)
        # Persist ipTM next to the standard confidence file when available.
        if iptm is not None:
            extra = json.loads(conf_path.read_text())
            extra["iptm"] = round(iptm, 4)
            conf_path.write_text(json.dumps(extra, indent=2))

        _copy_raw(raw_output_dir, output_dir)
        promote_best_model(output_dir)
        return output_dir

    def preflight(self) -> dict[str, Any]:
        # Sizing from benchmarks (docs/esmfold2-benchmarks.md): peak host RSS
        # ~16G GPU / ~28G CPU-fp32; VRAM <=17G; warm runs <60s. Values give
        # headroom for far larger inputs than the <=450-residue cases tested.
        return {
            "cpu": 8,
            "memory": "32G",
            "runtime": 3600,
            "storage": "50G",
            "policy_data": {
                "gpu_count": 1,
                "partition": "gpu2",
                # H200 only. /opt/conda-esmfold2 ships torch 2.12.0+cu130, and
                # CUDA 13 binaries need driver >= 580 — coconut (H200) has it,
                # mango (H100, driver 560) and peach (V100, 535) do not. Boltz
                # carries the same torch build and was narrowed to H200 for
                # exactly this reason (#38). "A100" was also a phantom: no A100
                # host exists in the cluster.
                "constraint": "H200",
            },
        }
