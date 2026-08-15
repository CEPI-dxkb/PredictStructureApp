"""Unified CLI entry point for protein structure prediction.

Usage:
    predict-structure <tool> --protein input.fasta [OPTIONS]
    predict-structure --job jobs.yaml -o output/

Examples:
    predict-structure boltz --protein input.fasta -o output/ --num-samples 5 --use-potentials
    predict-structure esmfold --protein input.fasta -o output/ --num-recycles 4 --fp16
    predict-structure chai --protein input.fasta -o output/ --msa alignment.a3m
    predict-structure alphafold --protein input.fasta -o output/ --af2-data-dir /data
    predict-structure boltz --protein input.fasta --ligand ATP -o output/
    predict-structure --job jobs.yaml -o output/
"""

from __future__ import annotations

import functools
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml
from click_option_group import optgroup

logger = logging.getLogger(__name__)

from predict_structure import __version__
from predict_structure.adapters import get_adapter
from predict_structure.adapters.base import join_names
from predict_structure.backends import get_backend
from predict_structure.entities import (
    EntityList,
    EntityType,
    is_boltz_yaml,
    parse_fasta_entities,
)
from predict_structure.gpu_check import check_gpu_memory
from predict_structure.msa_check import MsaFormatError, check_msa_input
from predict_structure.normalizers import stage_inputs, write_metadata_json
from predict_structure.results import write_results_json, write_ro_crate


# Wrapper-side log written into output_dir so failures aren't silent
# when the tool subprocess exits non-zero. Slurm captures full tool
# stderr separately; this file is the wrapper's view and travels with
# the output directory on workspace upload.
RUN_LOG_NAME = "predict_structure.log"


def _attach_run_log(output_dir: Path) -> logging.FileHandler:
    """Add a FileHandler at output_dir/predict_structure.log to the root logger.

    Logs at INFO and above regardless of the CLI verbosity flag, so a
    failed run always leaves a useful trace even when ``--verbose`` was
    not passed. Caller is responsible for ``logging.getLogger().removeHandler``
    if the handler needs to be detached (we leave it attached for the
    lifetime of the run).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(output_dir / RUN_LOG_NAME, mode="a", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    root = logging.getLogger()
    # Ensure root level lets INFO through to the FileHandler even when
    # the console handler is at WARNING.
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)
    return handler


# ---------------------------------------------------------------------------
# Tool auto-discovery
# ---------------------------------------------------------------------------

from predict_structure.config import get_command, get_data_root, get_tools


def _is_tool_available(tool: str) -> bool:
    """Check if a prediction tool is installed and accessible.

    Checks the first element of the tool's ``command`` list from
    ``tools.yml`` — either on PATH (via ``shutil.which``) or as an
    absolute filesystem path.
    """
    try:
        cmd = get_command(tool)
    except KeyError:
        return False
    if not cmd:
        return False
    exe = cmd[0]
    # Absolute path — check if file exists
    if exe.startswith("/"):
        return Path(exe).exists()
    # Relative — check PATH
    return shutil.which(exe) is not None


class UnsupportedInputError(click.ClickException, ValueError):
    """The job's inputs cannot be served by any tool — a user-fixable problem.

    Distinct from ``click.UsageError`` (which means the deployment is broken,
    e.g. nothing on PATH) so preflight can reject the former at submit time
    while still falling back to default resources for the latter.

    Inherits from both parents deliberately: ``ValueError`` so preflight catches
    it alongside adapter validation errors, and ``ClickException`` so the other
    call sites (the ``auto`` subcommand, the job-file runner) print
    ``Error: <message>`` instead of dumping a traceback — the whole point of
    #84. ``exit_code`` matches the ``click.UsageError`` this replaced.
    """

    exit_code = 2


def _auto_select_tool(
    entity_list: EntityList,
    device: str = "gpu",
    *,
    has_msa: bool = False,
    use_msa_server: bool = False,
) -> str:
    """Auto-select the best available prediction tool based on entity types.

    Selection rules:
      - Non-protein entities exclude ESMFold.
      - ``device=cpu`` prefers ESMFold (others are impractical on CPU).
      - Boltz, OpenFold, and Chai require an MSA source (``--msa`` file
        or ``--use-msa-server``).  Without one they are skipped --
        running them with a dummy single-sequence MSA produces unusable
        predictions, so we exclude them rather than silently degrade.
      - ESMFold is single-sequence by design and never uses MSA.
      - AlphaFold 2 is retired from auto selection (#90).  It stays
        runnable when named explicitly (API ``tool: "alphafold"``, CLI
        ``predict-structure alphafold``, CWL), but auto never picks it.
      - Otherwise pick first available in priority order:
        Boltz > OpenFold > Chai > ESMFold.

    Raises:
        click.UsageError: If no suitable tool is found.
    """
    requested_types = frozenset(entity_list.entity_types)
    has_non_protein = requested_types - {EntityType.PROTEIN}
    msa_available = has_msa or use_msa_server

    # CPU → strongly prefer ESMFold (if protein-only)
    if device == "cpu" and not has_non_protein:
        if _is_tool_available("esmfold"):
            return "esmfold"

    # Why each candidate was passed over, so the failure below can name the
    # actual cause instead of always blaming PATH (issue #84).
    excluded_by_input = False
    excluded_by_msa: list[str] = []

    # Priority order: diffusion tools first (need MSA), then ESMFold
    # (fast single-sequence) as the no-MSA fallback. AlphaFold 2 is
    # deliberately absent: it is retired from auto selection (#90) because
    # its local-DB MSA pipeline takes hours where ESMFold takes minutes,
    # and it is no longer offered in the UI. Explicit `--tool alphafold`
    # still runs it.
    has_protein = EntityType.PROTEIN in requested_types
    for tool in ("boltz", "openfold", "chai", "esmfold"):
        # Installed-ness first. A tool that isn't deployed was never a
        # candidate, so it must not be reported as an input or MSA problem —
        # otherwise "nothing is installed" masquerades as a user error.
        if not _is_tool_available(tool):
            continue

        # Ask the adapter rather than hardcoding which tools take what. Keeps
        # this in step with supported_entities and honours Chai's SMILES-only
        # ligand rule, so auto never resolves to a tool that would reject the
        # job seconds later (#82, #84).
        if not get_adapter(tool).supports_entity_types(requested_types):
            excluded_by_input = True
            continue

        # Boltz/OpenFold/Chai need MSA for protein chains. Skip them
        # when none is available to avoid the silent dummy-MSA fallback
        # (catastrophic quality regression).
        if tool in ("boltz", "openfold", "chai") and has_protein and not msa_available:
            excluded_by_msa.append(get_adapter(tool).display_name or tool)
            continue

        return tool

    # Nothing matched. Separate a user-input problem (fixable by changing the
    # job, so preflight should reject it at submit) from a deployment problem
    # (nothing installed, so preflight should fall back to defaults) — #84.
    if excluded_by_msa:
        # Name only the tools actually skipped for this reason. Suggesting a
        # fallback here would be false advice: every other tool has already
        # been tried and rejected by the time we reach this line.
        verb = "needs" if len(excluded_by_msa) == 1 else "need"
        raise UnsupportedInputError(
            f"{join_names(excluded_by_msa)} {verb} an MSA for protein chains, "
            f"but no MSA file was supplied and the MSA server was not enabled. "
            f"Upload an MSA or enable the MSA server."
        )
    if excluded_by_input:
        kinds = ", ".join(sorted(e.value for e in requested_types))
        raise UnsupportedInputError(
            f"No available prediction tool supports this combination of inputs "
            f"({kinds})."
        )
    # AlphaFold is retired from auto (#90) but still runnable by name. Saying
    # "no tool found" when it is sitting there installed is simply false, and
    # UsageError would exit 2 — which App-PredictStructure.pl reads as "the
    # preflight binary broke" and answers by scheduling the job anyway (#84).
    # Classify it as bad input so preflight rejects it properly.
    if _is_tool_available("alphafold"):
        raise UnsupportedInputError(
            "AlphaFold 2 is the only prediction tool installed, and it is "
            "retired from automatic selection. Run it explicitly with "
            "`predict-structure alphafold`, or install one of: boltz, "
            "run_openfold, chai-lab, esm-fold-hf."
        )
    raise click.UsageError(
        "No prediction tool found on PATH. "
        "Install one of: boltz, run_openfold, chai-lab, esm-fold-hf"
    )


# Keep for backward compat with tests that mock discover_tool
def discover_tool(input_file: Path, device: str = "gpu") -> str:
    """Auto-discover the best available prediction tool (legacy interface).

    Selection rules:
      - ``.yaml`` / ``.yml`` input forces Boltz (only tool supporting YAML).
      - ``device=cpu`` prefers ESMFold (others are impractical on CPU).
      - Otherwise pick first available in accuracy-priority order:
        Boltz > OpenFold > Chai > ESMFold.  AlphaFold 2 is retired from
        auto selection (#90) and is only reachable by naming it.

    Raises:
        click.UsageError: If no suitable tool is found.
    """
    suffix = input_file.suffix.lower()

    # YAML input → must be Boltz
    if suffix in (".yaml", ".yml"):
        if _is_tool_available("boltz"):
            return "boltz"
        raise click.UsageError(
            "YAML input requires Boltz, but 'boltz' is not found on PATH."
        )

    # CPU → strongly prefer ESMFold (others are impractical without GPU)
    if device == "cpu":
        if _is_tool_available("esmfold"):
            return "esmfold"
        # Fall through to general priority

    # Same priority order as _auto_select_tool, AlphaFold excluded (#90).
    for tool in ("boltz", "openfold", "chai", "esmfold"):
        if _is_tool_available(tool):
            return tool

    raise click.UsageError(
        "No prediction tool found on PATH. "
        "Install one of: boltz, run_openfold, chai-lab, esm-fold-hf"
    )


# ---------------------------------------------------------------------------
# Entity list construction from CLI flags
# ---------------------------------------------------------------------------

def _build_entity_list(
    protein: tuple[str, ...],
    dna: tuple[str, ...],
    rna: tuple[str, ...],
    ligand: tuple[str, ...],
    smiles: tuple[str, ...],
    *,
    sequence_files: tuple[str, ...] = (),
    force: bool = False,
) -> EntityList:
    """Build an EntityList from CLI option tuples.

    FASTA files (--protein, --dna, --rna) are parsed and each sequence
    becomes a separate entity. Inline values (--ligand, --smiles) become
    one entity each. ``--ligand`` accepts a CCD code (1-3 or exactly 5
    alphanumeric chars; e.g. ``ATP``, ``A1H1F``); ``--smiles`` accepts a
    SMILES string for arbitrary small molecules. Glycans are submitted as
    CCD-coded ligands, one ``--ligand <CCD>`` per monosaccharide; the
    upstream tools have no separate glycan type and linked glycan strings
    such as ``NAG(4-1 NAG)`` are rejected.

    Also handles Boltz YAML pass-through: if a single --protein path points
    to a .yaml/.yml file, it's treated as a YAML entity for Boltz.

    Raises:
        click.UsageError: If no entities are provided.
    """
    from predict_structure.entities import MAX_SEQUENCES, MAX_TOTAL_RESIDUES

    max_seq = None if force else MAX_SEQUENCES
    max_res = None if force else MAX_TOTAL_RESIDUES
    entities = EntityList()

    for fasta_path in protein:
        path = Path(fasta_path)
        # Boltz YAML pass-through: single .yaml file passed as --protein.
        # Known uncovered path (#48): the YAML is typed as PROTEIN and handed
        # to Boltz verbatim, so a user-authored `ccd:` entry inside it never
        # reaches the CCD check in EntityList.add. Deliberate — parsing and
        # rewriting a hand-written Boltz YAML is a separate concern.
        if is_boltz_yaml(path):
            entities.add(
                EntityType.PROTEIN, str(path), name=path.stem,
                source_path=path, format="boltz-yaml",
            )
            continue
        for ent in parse_fasta_entities(
            path, explicit_type=EntityType.PROTEIN, max_sequences=max_seq,
        ):
            entities.add(
                ent.entity_type, ent.value, name=ent.name,
                source_path=ent.source_path, format=ent.format,
            )

    for fasta_path in dna:
        for ent in parse_fasta_entities(
            Path(fasta_path), explicit_type=EntityType.DNA, max_sequences=max_seq,
        ):
            entities.add(
                ent.entity_type, ent.value, name=ent.name,
                source_path=ent.source_path, format=ent.format,
            )

    for fasta_path in rna:
        for ent in parse_fasta_entities(
            Path(fasta_path), explicit_type=EntityType.RNA, max_sequences=max_seq,
        ):
            entities.add(
                ent.entity_type, ent.value, name=ent.name,
                source_path=ent.source_path, format=ent.format,
            )

    # Auto-detect sequence type (no explicit_type — uses detect_sequence_type)
    for fasta_path in sequence_files:
        for ent in parse_fasta_entities(
            Path(fasta_path), explicit_type=None, max_sequences=max_seq,
        ):
            entities.add(
                ent.entity_type, ent.value, name=ent.name,
                source_path=ent.source_path, format=ent.format,
            )

    for code in ligand:
        try:
            entities.add(EntityType.LIGAND, code, name=code, format="ccd")
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc

    for smi in smiles:
        entities.add(EntityType.SMILES, smi, name="smiles", format="smiles")

    if not entities:
        raise click.UsageError(
            "No input entities provided. Use --protein, --dna, --rna, "
            "--sequence, --ligand, or --smiles to specify input."
        )

    # Validate total size
    try:
        entities.validate_size(max_residues=max_res)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    return entities


# ---------------------------------------------------------------------------
# Shared options applied to every tool subcommand
# ---------------------------------------------------------------------------

def entity_options(func):
    """Decorator that applies entity input options."""
    @optgroup.group("Entity input")
    @optgroup.option("--protein", multiple=True, type=click.Path(exists=True),
                     help="Protein FASTA file (repeatable for multi-chain)")
    @optgroup.option("--dna", multiple=True, type=click.Path(exists=True),
                     help="DNA FASTA file (repeatable)")
    @optgroup.option("--rna", multiple=True, type=click.Path(exists=True),
                     help="RNA FASTA file (repeatable)")
    @optgroup.option("--sequence", "sequence_files", multiple=True, type=click.Path(exists=True),
                     help="FASTA file with auto-detected sequence type (repeatable)")
    @optgroup.option("--ligand", multiple=True, type=str,
                     help="Ligand CCD code: 1-3 or exactly 5 alphanumeric "
                          "chars (e.g. ATP, A1H1F). Use this for any "
                          "CCD-coded compound including glycans (e.g. NAG, "
                          "MAN) — one code per monosaccharide. Repeatable.")
    @optgroup.option("--smiles", multiple=True, type=str,
                     help="SMILES string for an arbitrary small molecule. "
                          "Use --ligand for CCD-coded compounds. Repeatable.")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


def shared_options(func):
    """Decorator that applies options common to all prediction tools.

    Help order (top to bottom): Entity input, Global options, [Tool options], Execution options.
    Click decorators stack bottom-up, so Execution is applied last (via backend_options).
    """
    @entity_options
    @optgroup.group("Global options")
    @optgroup.option("-o", "--output-dir", type=click.Path(), required=True, help="Output directory")
    @optgroup.option("--num-samples", "-n", type=int, default=1, help="Number of structure samples")
    @optgroup.option("--num-recycles", type=int, default=3, help="Recycling iterations")
    @optgroup.option("--seed", type=int, default=None, help="Random seed")
    @optgroup.option("--msa", type=click.Path(), default=None, help="MSA file (.a3m, .sto, .pqt)")
    @optgroup.option("--output-format", type=click.Choice(["pdb", "mmcif"]), default="pdb")
    @optgroup.option(
        "--emit-rocrate/--no-emit-rocrate",
        default=True,
        help="Emit ro-crate-metadata.json provenance alongside results.json [default: emit]",
    )
    @click.option("--debug", is_flag=True, default=False, help="Print the command instead of executing it")
    @click.option("--force", is_flag=True, default=False, help="Bypass input size limits")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


def backend_options(func):
    """Decorator that applies execution/backend options (shown last in help)."""
    @optgroup.group("Execution options")
    @optgroup.option(
        "--backend",
        type=click.Choice(["docker", "subprocess", "cwl", "apptainer"]),
        default="subprocess",
        help="Execution backend",
    )
    @optgroup.option("--device", type=click.Choice(["gpu", "cpu"]), default="gpu", help="Compute device")
    @optgroup.option("--image", default=None, help="Override Docker image (docker backend only)")
    @optgroup.option("--sif", default=None, help="Apptainer SIF image path (apptainer/cwl backend)")
    @optgroup.option("--cwl-runner", default=None, help="CWL runner command (default: cwltool)")
    @optgroup.option("--cwl-tool", default=None, help="Path to CWL tool definition")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Shared prediction logic
# ---------------------------------------------------------------------------

def _build_params_dict(shared: dict) -> dict:
    """Extract the canonical per-run params saved in metadata.json."""
    return {
        "num_samples": shared["num_samples"],
        "num_recycles": shared["num_recycles"],
        "seed": shared.get("seed"),
        "device": shared["device"],
    }


def _finalize_output(
    output_path: Path,
    tool_name: str,
    shared: dict,
    elapsed: float,
    *,
    entity_list: EntityList | None = None,
    started_at: str | None = None,
) -> None:
    """Post-normalization: stage inputs, write metadata.json + results.json + ro-crate.

    Runs in this exact order so later writers can read earlier ones:
      1. stage_inputs                -- copy user inputs into output_dir/inputs/
      2. write_metadata_json         -- canonical run trace (incl. inputs[])
      3. write_results_json          -- v2.0 outputs map + UI summary
      4. write_ro_crate              -- best-effort Process Run Crate

    ``write_results_json`` requires ``metadata.json`` to be present. If
    missing we let the exception propagate -- it signals a normalizer
    contract violation and should fail loudly, matching the standalone
    `finalize-results` path.
    """
    import os
    from datetime import datetime, timezone

    msa_path = Path(shared["msa"]) if shared.get("msa") else None
    inputs_descriptors = stage_inputs(entity_list, msa_path, output_path)

    completed_at = datetime.now(timezone.utc).isoformat()
    write_metadata_json(
        output_path,
        tool=tool_name,
        version=__version__,
        tool_version=None,
        status="success",
        started_at=started_at,
        completed_at=completed_at,
        runtime_seconds=elapsed,
        command=sys.argv,
        container_image=os.environ.get("PREDICT_STRUCTURE_IMAGE"),
        backend=shared["backend"],
        params=_build_params_dict(shared),
        inputs=inputs_descriptors,
    )
    write_results_json(output_path)
    if shared.get("emit_rocrate", True):
        write_ro_crate(output_path)


def _docker_volumes_and_rewrite(
    cmd: list[str],
    *,
    input_path: Path,
    output_dir: Path,
    data_dir: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Build Docker volume mounts and rewrite host paths in the command.

    Returns:
        (volumes, rewritten_cmd) where *volumes* is ``{host: container}``
        and *rewritten_cmd* has host paths replaced with container paths.
    """
    from predict_structure.backends.docker import (
        CONTAINER_INPUT, CONTAINER_OUTPUT, CONTAINER_DATA,
    )

    volumes: dict[str, str] = {}
    input_host = str(input_path.resolve().parent)
    output_host = str(output_dir.resolve())

    volumes[input_host] = CONTAINER_INPUT
    volumes[output_host] = CONTAINER_OUTPUT

    if data_dir:
        data_host = str(Path(data_dir).resolve())
        volumes[data_host] = CONTAINER_DATA

    # Build replacement map sorted longest-prefix-first so
    # /databases/uniref90 is not matched before /databases.
    replacements = sorted(volumes.items(), key=lambda kv: -len(kv[0]))

    rewritten: list[str] = []
    for arg in cmd:
        new_arg = arg
        # Only rewrite if arg contains a path-like string
        if "/" in arg or Path(arg).is_absolute():
            # Always resolve symlinks (e.g. /tmp → /private/tmp on macOS)
            resolved = str(Path(arg).resolve())
            for host_dir, container_dir in replacements:
                if resolved.startswith(host_dir + "/") or resolved == host_dir:
                    new_arg = container_dir + resolved[len(host_dir):]
                    break
        rewritten.append(new_arg)

    return volumes, rewritten


def run_prediction(
    tool_name: str,
    extra_kwargs: dict,
    *,
    entity_list: EntityList,
    entity_inputs: dict | None = None,
    **shared,
):
    """Core prediction logic shared by all tool subcommands.

    Args:
        tool_name: Adapter key (boltz, chai, alphafold, esmfold).
        extra_kwargs: Tool-specific keyword arguments for build_command.
        entity_list: Entities to predict.
        entity_inputs: Raw CLI entity options for CWL backend
            (e.g. ``{"protein": ("/path/to/file.fasta",), ...}``).
        **shared: Shared CLI options (output_dir, backend, etc.).
    """
    output_path = Path(shared["output_dir"])
    output_path.mkdir(parents=True, exist_ok=True)
    raw_dir = output_path / "raw_output"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Attach the run log file as early as possible so the wrapper's
    # decisions (GPU precheck, command, exit code) are persisted even
    # when the tool subprocess exits silently. CUDA_VISIBLE_DEVICES is
    # the slurm-assigned GPU(s) — useful when debugging mango-style
    # contention.
    _attach_run_log(output_path)
    logger.info("predict-structure %s starting", __version__)
    logger.info("Tool: %s", tool_name)
    logger.info("Entities: %s", [(e.entity_type.value, e.name) for e in entity_list])
    logger.info("Backend: %s | Device: %s", shared.get("backend"), shared.get("device"))
    import os as _os
    logger.info("HOST=%s CUDA_VISIBLE_DEVICES=%s SLURM_JOB_ID=%s",
                _os.uname().nodename,
                _os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>"),
                _os.environ.get("SLURM_JOB_ID", "<unset>"))

    # 1. Resolve adapter and backend
    adapter = get_adapter(tool_name)
    logger.info("Supported entities: %s", sorted(e.value for e in adapter.supported_entities))
    backend = shared["backend"]
    backend_kwargs = {}
    if backend == "docker" and shared.get("image"):
        backend_kwargs["default_image"] = shared["image"]
    if backend == "apptainer" and shared.get("sif"):
        backend_kwargs["sif_path"] = shared["sif"]
    if backend == "cwl":
        if shared.get("cwl_runner"):
            backend_kwargs["runner"] = shared["cwl_runner"]
        if shared.get("cwl_tool"):
            backend_kwargs["cwl_tool"] = shared["cwl_tool"]
        # Auto-enable Singularity when a SIF is configured
        from predict_structure.config import get_shared_sif
        if shared.get("sif") or get_shared_sif():
            backend_kwargs["use_singularity"] = True
    execution_backend = get_backend(backend, **backend_kwargs)

    # 2. Validate entity types against adapter capabilities
    # Surface as a plain message, not a traceback: this reaches BV-BRC users
    # in the job error stream, where a click/AppScript stack is noise (#84).
    try:
        adapter.validate_entities(entity_list)
    except ValueError as exc:
        logger.error("Entity validation failed: %s", exc)
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    adapter.validate_sequences(entity_list)
    logger.info("Entity validation passed")

    # Validate MSA format before any expensive work. Catches wrong-format
    # files (single-seq FASTA, Stockholm for a tool that wants A3M, empty,
    # binary). Cheap — sniffs the first 4 KiB and the suffix.
    msa_input_path = Path(shared["msa"]) if shared.get("msa") else None
    try:
        check_msa_input(msa_input_path, tool_name)
    except MsaFormatError as exc:
        logger.error("MSA validation failed: %s", exc)
        click.echo(f"Invalid MSA input: {exc}", err=True)
        sys.exit(2)

    # -----------------------------------------------------------------
    # CWL unified path: bypass adapter.build_command() and build the
    # CWL job directly from entity inputs and CLI options.
    # Only activated when --cwl-tool explicitly specifies the unified
    # predict-structure.cwl tool.  Default --backend cwl uses per-tool
    # CWL definitions via the standard adapter path below.
    # -----------------------------------------------------------------
    if backend == "cwl" and entity_inputs is not None and shared.get("cwl_tool"):
        job = execution_backend.build_unified_job(
            tool_name,
            entity_inputs,
            output_dir=str(raw_dir),
            num_samples=shared["num_samples"],
            num_recycles=shared["num_recycles"],
            seed=shared.get("seed"),
            device=shared["device"],
            msa=shared.get("msa"),
            output_format=shared.get("output_format", "pdb"),
            **extra_kwargs,
        )

        if shared.get("debug"):
            debug_lines = execution_backend.format_unified_command(
                job, tool_name=tool_name, output_dir=str(output_path),
            )
            click.echo("\n".join(str(l) for l in debug_lines))
            return

        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc).isoformat()
        start = time.time()
        rc = execution_backend.run_unified(
            job, tool_name=tool_name, output_dir=str(output_path),
        )
        elapsed = time.time() - start

        if rc != 0:
            has_output = any(raw_dir.glob("**/*.pdb")) or any(raw_dir.glob("**/*.cif"))
            if has_output:
                logger.warning(
                    "Tool exited with code %d but produced output — "
                    "attempting normalization", rc
                )
            else:
                click.echo(f"Prediction failed with exit code {rc}", err=True)
                sys.exit(rc)

        try:
            adapter.normalize_output(raw_dir, output_path)
        except FileNotFoundError as exc:
            click.echo(
                f"Prediction produced no output to normalize: {exc}\n"
                f"Check raw output in {raw_dir}",
                err=True,
            )
            sys.exit(1)
        _finalize_output(
            output_path, tool_name, shared, elapsed,
            entity_list=entity_list, started_at=started_at,
        )
        click.echo(f"Prediction complete: {output_path}")
        return

    # -----------------------------------------------------------------
    # Standard path: subprocess / docker / apptainer / legacy CWL
    # -----------------------------------------------------------------

    # 3. Prepare input (entity list → tool-native format, MSA conversion)
    # Adapters reject unusable input here too (Chai CCD ligands, token limits);
    # same treatment as entity validation — a message, not a stack trace (#84).
    msa_path = Path(shared["msa"]) if shared.get("msa") else None
    try:
        prepared = adapter.prepare_input(entity_list, output_path, msa_path=msa_path)
    except ValueError as exc:
        logger.error("Input preparation failed: %s", exc)
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    logger.info("Prepared input: %s", prepared)

    # 4. Build tool-specific command
    cmd = adapter.build_command(
        prepared,
        raw_dir,
        num_samples=shared["num_samples"],
        num_recycles=shared["num_recycles"],
        seed=shared.get("seed"),
        device=shared["device"],
        **extra_kwargs,
    )

    # 5. For docker backend: build volume mounts and rewrite host paths
    run_kwargs: dict = {
        "tool_name": adapter.tool_name,
        "gpu": shared["device"] != "cpu",
    }

    if backend == "docker":
        data_dir = extra_kwargs.get("af2_data_dir")
        volumes, cmd = _docker_volumes_and_rewrite(
            cmd,
            input_path=prepared,
            output_dir=raw_dir,
            data_dir=data_dir,
        )
        run_kwargs["volumes"] = volumes

    if backend == "apptainer":
        from predict_structure.config import get_data_dir, get_data_root
        binds = {}
        # Bind data root so tools can access/write model weights and caches
        data_root = get_data_root()
        if data_root.exists():
            binds[str(data_root)] = str(data_root)
        # Bind tool-specific data dir if it's outside data_root (absolute path)
        try:
            tool_data = get_data_dir(tool_name)
            if tool_data.exists() and not str(tool_data).startswith(str(data_root)):
                binds[str(tool_data)] = str(tool_data)
        except (FileNotFoundError, KeyError):
            pass
        # Bind the output directory so the container can read/write it
        output_resolved = str(output_path.resolve())
        binds[output_resolved] = output_resolved
        run_kwargs["binds"] = binds

    cwl_output_subdir = raw_dir
    if backend == "cwl":
        run_kwargs["output_dir"] = str(raw_dir)
        # CWL outputs go into raw_dir/<output_dir_name>/
        cwl_output_subdir = raw_dir / "output"

    logger.info("Command: %s", " ".join(cmd))

    # 6. Execute prediction (or print command in debug mode)
    if shared.get("debug"):
        debug_lines = execution_backend.format_command(cmd, **run_kwargs)
        click.echo("\n".join(str(l) for l in debug_lines))
        return

    # VRAM precheck: catch GPUs whose VRAM is already pinned by another
    # process (e.g. external inference servers slurm GRES doesn't track).
    # Only runs on host-local backends — the cwl/gowe path executes on a
    # different host and does its own checks downstream.
    if (adapter.requires_gpu
            and shared.get("device") != "cpu"
            and backend in ("subprocess", "apptainer", "docker")):
        result = check_gpu_memory(adapter.min_gpu_memory_mb)
        if result.ok:
            logger.info("GPU precheck: %s", result.message)
        else:
            logger.error("GPU precheck failed:\n%s", result.message)
            click.echo(
                "Prediction aborted: insufficient GPU VRAM before launch.\n"
                f"{result.message}\n"
                f"Run log: {output_path / RUN_LOG_NAME}",
                err=True,
            )
            sys.exit(2)

    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.time()
    rc = execution_backend.run(cmd, **run_kwargs)
    elapsed = time.time() - start
    logger.info("Tool subprocess exited rc=%d after %.1fs", rc, elapsed)

    if rc != 0:
        # Check if the tool produced output despite the error (e.g. AF2
        # relaxation failure after successful prediction).
        has_output = any(raw_dir.glob("**/*.pdb")) or any(raw_dir.glob("**/*.cif"))
        if has_output:
            logger.warning(
                "Tool exited with code %d but produced output — "
                "attempting normalization", rc
            )
        else:
            # Build a diagnostic block: post-mortem VRAM + likely cause hint.
            # Helps when the upstream slurm stderr isn't accessible
            # (e.g. workspace only shows JobFailed.txt).
            diag_lines = [
                f"Tool exited with code {rc} after {elapsed:.1f}s with no output.",
            ]
            if (adapter.requires_gpu
                    and shared.get("device") != "cpu"
                    and backend in ("subprocess", "apptainer", "docker")):
                post = check_gpu_memory(adapter.min_gpu_memory_mb)
                diag_lines.append(f"Post-mortem GPU state: {post.message}")
                if not post.ok:
                    diag_lines.append(
                        "Likely CUDA OOM during tool execution — VRAM "
                        "below threshold at exit."
                    )
            for line in diag_lines:
                logger.error(line)
            click.echo("\n".join(diag_lines), err=True)
            click.echo(f"Run log: {output_path / RUN_LOG_NAME}", err=True)
            sys.exit(rc)

    # 7. Normalize output
    # CWL places tool output inside raw_dir/output/ (the CWL output_dir name)
    normalize_dir = cwl_output_subdir if backend == "cwl" else raw_dir
    try:
        adapter.normalize_output(normalize_dir, output_path)
    except FileNotFoundError as exc:
        click.echo(
            f"Prediction produced no output to normalize: {exc}\n"
            f"Check raw output in {raw_dir}",
            err=True,
        )
        sys.exit(1)

    _finalize_output(
        output_path, tool_name, shared, elapsed,
        entity_list=entity_list, started_at=started_at,
    )

    click.echo(f"Prediction complete: {output_path}")


# ---------------------------------------------------------------------------
# Job file execution
# ---------------------------------------------------------------------------

def _run_job_file(job_path: Path, base_output_dir: Path | None) -> None:
    """Execute a batch of predictions from a YAML job spec.

    Each entry in the YAML list defines one prediction with entity inputs,
    optional tool selection, and tool-specific options.

    Args:
        job_path: Path to YAML job spec file.
        base_output_dir: Base output directory; each job gets a subdirectory.
    """
    if base_output_dir is None:
        raise click.UsageError("--output-dir / -o is required with --job")

    data = yaml.safe_load(job_path.read_text())
    if not isinstance(data, list):
        raise click.UsageError(f"Job file must be a YAML list, got {type(data).__name__}")

    base_output_dir = Path(base_output_dir)
    base_output_dir.mkdir(parents=True, exist_ok=True)

    for idx, job in enumerate(data):
        job_dir = base_output_dir / f"job_{idx:03d}"

        # Build entity list from job entry
        entities = EntityList()
        for fasta_path in job.get("protein", []):
            for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.PROTEIN):
                entities.add(
                    ent.entity_type, ent.value, name=ent.name,
                    source_path=ent.source_path, format=ent.format,
                )
        for fasta_path in job.get("dna", []):
            for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.DNA):
                entities.add(
                    ent.entity_type, ent.value, name=ent.name,
                    source_path=ent.source_path, format=ent.format,
                )
        for fasta_path in job.get("rna", []):
            for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.RNA):
                entities.add(
                    ent.entity_type, ent.value, name=ent.name,
                    source_path=ent.source_path, format=ent.format,
                )
        for code in job.get("ligands", []):
            try:
                entities.add(EntityType.LIGAND, code, name=code, format="ccd")
            except ValueError as exc:
                raise click.UsageError(f"Job {idx:03d}: {exc}") from exc
        for smi in job.get("smiles", []):
            entities.add(EntityType.SMILES, smi, name="smiles", format="smiles")

        if not entities:
            click.echo(f"Warning: job {idx} has no entities, skipping", err=True)
            continue

        # Select tool
        options = job.get("options", {})
        tool_name = job.get("tool")
        if tool_name is None:
            tool_name = _auto_select_tool(entities, device=options.get("device", "gpu"))

        click.echo(f"Job {idx:03d}: {tool_name} → {job_dir}")

        shared = {
            "output_dir": str(job_dir),
            "num_samples": options.get("num_samples", 1),
            "num_recycles": options.get("num_recycles", 3),
            "seed": options.get("seed"),
            "msa": options.get("msa"),
            "output_format": options.get("output_format", "pdb"),
            "backend": options.get("backend", "subprocess"),
            "device": options.get("device", "gpu"),
            "image": options.get("image"),
            "sif": options.get("sif"),
            "cwl_runner": options.get("cwl_runner"),
            "cwl_tool": options.get("cwl_tool"),
            "debug": options.get("debug", False),
            "emit_rocrate": options.get("emit_rocrate", True),
        }

        entity_inputs = {
            "protein": job.get("protein", []),
            "dna": job.get("dna", []),
            "rna": job.get("rna", []),
            "ligand": job.get("ligands", []),
            "smiles": job.get("smiles", []),
            "sequence": job.get("sequence", []),
        }

        extra = {k: v for k, v in options.items() if k not in shared}
        run_prediction(tool_name, extra, entity_list=entities,
                       entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.option("--job", type=click.Path(exists=True), default=None,
              help="YAML job spec for batch predictions")
@click.option("-o", "--output-dir", "job_output_dir", type=click.Path(), default=None,
              help="Output directory (used with --job)")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Enable verbose logging (DEBUG level)")
@click.pass_context
def main(ctx, job, job_output_dir, verbose):
    """Predict protein structure using Boltz-2, OpenFold 3, Chai-1, AlphaFold 2, or ESMFold.

    Each subcommand dispatches to the appropriate prediction tool with
    automatic parameter mapping, input format conversion, and output
    normalization.

    Use --job for batch predictions from a YAML spec file.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if job is not None:
        if ctx.invoked_subcommand is not None:
            raise click.UsageError("--job is exclusive with subcommands")
        _run_job_file(Path(job), Path(job_output_dir) if job_output_dir else None)
        ctx.exit()
    elif ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# boltz subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("Boltz-2 options")
@optgroup.option("--sampling-steps", type=int, default=200, help="Number of diffusion sampling steps [default: 200]")
@optgroup.option("--use-msa-server", is_flag=True, default=False, help="Use remote MSA server")
@optgroup.option("--msa-server-url", default=None, help="Custom MSA server URL (implies --use-msa-server)")
@optgroup.option("--use-potentials", is_flag=True, default=False, help="Enable potential terms")
@backend_options
def boltz(protein, dna, rna, ligand, smiles,
          sampling_steps, use_msa_server, msa_server_url, use_potentials, **shared):
    """Predict structure with Boltz-2 (diffusion-based, proteins/DNA/RNA/ligands)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    extra = {
        "sampling_steps": sampling_steps,
        "use_msa_server": use_msa_server or (msa_server_url is not None),
        "msa_server_url": msa_server_url,
        "boltz_use_potentials": use_potentials,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction("boltz", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# chai subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("Chai-1 options")
@optgroup.option("--sampling-steps", type=int, default=200, help="Diffusion timesteps [default: 200]")
@optgroup.option("--use-msa-server", is_flag=True, default=False, help="Use remote MSA server")
@optgroup.option("--msa-server-url", default=None, help="Custom MSA server URL (implies --use-msa-server)")
@optgroup.option("--no-esm-embeddings", is_flag=True, default=False, help="Disable ESM2 language model embeddings")
@optgroup.option("--use-templates-server", is_flag=True, default=False, help="Use PDB template server")
@optgroup.option("--constraint-path", type=click.Path(), default=None, help="Constraint JSON file")
@optgroup.option("--template-hits-path", type=click.Path(), default=None, help="Pre-computed template hits file")
@optgroup.option("--num-trunk-samples", type=int, default=1, help="Trunk samples per prediction [default: 1]")
@optgroup.option("--recycle-msa-subsample", type=int, default=0, help="MSA subsample per recycle [default: 0 = all]")
@optgroup.option("--no-low-memory", is_flag=True, default=False, help="Disable low-memory mode")
@backend_options
def chai(protein, dna, rna, ligand, smiles,
         sampling_steps, use_msa_server, msa_server_url,
         no_esm_embeddings, use_templates_server, constraint_path,
         template_hits_path, num_trunk_samples, recycle_msa_subsample,
         no_low_memory, **shared):
    """Predict structure with Chai-1 (diffusion-based protein prediction)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    extra = {
        "sampling_steps": sampling_steps,
        "use_msa_server": use_msa_server or (msa_server_url is not None),
        "msa_server_url": msa_server_url,
        "use_esm_embeddings": False if no_esm_embeddings else True,
        "use_templates_server": use_templates_server,
        "constraint_path": constraint_path,
        "template_hits_path": template_hits_path,
        "num_trunk_samples": num_trunk_samples,
        "recycle_msa_subsample": recycle_msa_subsample,
        "low_memory": False if no_low_memory else True,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction("chai", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# alphafold subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("AlphaFold 2 options")
@optgroup.option("--af2-data-dir", type=click.Path(), default=None, help="AlphaFold database directory [default: from tools.yml]")
@optgroup.option("--af2-model-preset", default="monomer", help="Model preset (monomer, monomer_casp14, multimer)")
@optgroup.option("--af2-db-preset", default="reduced_dbs", help="DB preset (reduced_dbs, full_dbs)")
@optgroup.option("--af2-max-template-date", default="2022-01-01", help="Max template date (YYYY-MM-DD)")
@backend_options
def alphafold(protein, dna, rna, ligand, smiles,
              af2_data_dir, af2_model_preset, af2_db_preset, af2_max_template_date, **shared):
    """Predict structure with AlphaFold 2 (MSA-based, high accuracy).

    Retired from auto selection and from the BV-BRC UI (#90), but kept
    fully runnable here and via the API/CWL for reproducing older jobs.
    """
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    extra = {
        "af2_data_dir": af2_data_dir,
        "af2_model_preset": af2_model_preset,
        "af2_db_preset": af2_db_preset,
        "af2_max_template_date": af2_max_template_date,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction("alphafold", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# esmfold subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("ESMFold options")
@optgroup.option("--fp16", is_flag=True, default=False, help="Use half-precision (FP16) inference")
@optgroup.option("--chunk-size", type=int, default=None, help="Chunk size for long sequences")
@optgroup.option("--max-tokens-per-batch", type=int, default=None, help="Max tokens per batch")
@backend_options
def esmfold(protein, dna, rna, ligand, smiles,
            fp16, chunk_size, max_tokens_per_batch, **shared):
    """Predict structure with ESMFold (single-sequence, no MSA needed, CPU-capable)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    extra = {
        "esm_fp16": fp16,
        "esm_chunk_size": chunk_size,
        "esm_max_tokens": max_tokens_per_batch,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction("esmfold", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# esmfold2 subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("ESMFold2 options")
@optgroup.option("--sampling-steps", type=int, default=50, help="Diffusion sampling steps [default: 50]")
@optgroup.option("--checkpoint", default="biohub/ESMFold2", help="HF checkpoint id or path [default: biohub/ESMFold2]")
@backend_options
def esmfold2(protein, dna, rna, ligand, smiles,
             sampling_steps, checkpoint, **shared):
    """Predict structure with ESMFold2 (diffusion, no MSA; protein/DNA/RNA/ligand complexes)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    extra = {
        "sampling_steps": sampling_steps,
        "checkpoint": checkpoint,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction("esmfold2", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# openfold subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("OpenFold 3 options")
@optgroup.option("--num-diffusion-samples", type=int, default=5, help="Diffusion samples per query [default: 5]")
@optgroup.option("--num-model-seeds", type=int, default=1, help="Independent model seeds [default: 1]")
@optgroup.option("--use-msa-server/--no-msa-server", default=False, help="Use ColabFold MSA server [default: False]")
@optgroup.option("--msa-server-url", default=None, help="Custom MSA server URL (implies --use-msa-server)")
@optgroup.option("--use-templates/--no-templates", default=False, help="Use template structures [default: False]")
@optgroup.option("--checkpoint", default=None, help="Model checkpoint name (e.g. openfold3_p2_v1)")
@optgroup.option("--runner-yaml", type=click.Path(exists=True), default=None,
                 help="Runner YAML for advanced config (e.g. disable DeepSpeed for H200)")
@backend_options
def openfold(protein, dna, rna, ligand, smiles,
             num_diffusion_samples, num_model_seeds,
             use_msa_server, msa_server_url, use_templates, checkpoint, runner_yaml, **shared):
    """Predict structure with OpenFold 3 (AF3-class, protein/DNA/RNA/ligands)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    extra = {
        "num_diffusion_samples": num_diffusion_samples,
        "num_model_seeds": num_model_seeds,
        "use_msa_server": use_msa_server or (msa_server_url is not None),
        "msa_server_url": msa_server_url,
        "use_templates": use_templates,
        "checkpoint": checkpoint,
        "runner_yaml": runner_yaml,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction("openfold", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# auto subcommand
# ---------------------------------------------------------------------------

# Sensible defaults applied when auto-discovery selects a tool.
# These match the per-tool subcommand defaults so the user doesn't need
# to provide tool-specific flags. No "alphafold" entry: auto can no
# longer resolve to it (#90); the alphafold subcommand carries its own
# defaults.
_AUTO_DEFAULTS: dict[str, dict] = {
    "boltz": {},
    "openfold": {},
    "chai": {},
    "esmfold": {},
    "esmfold2": {},
}


@main.command()
@shared_options
@click.option("--use-msa-server", is_flag=True, default=False,
              help="Use remote MSA server (enables Boltz/Chai selection)")
@backend_options
def auto(protein, dna, rna, ligand, smiles, use_msa_server, **shared):
    """Auto-discover the best available tool and predict structure.

    Checks which prediction tools are installed and selects the best
    one based on entity types, device, and availability.

    Boltz, OpenFold, and Chai are only selected when an MSA source is
    available (--msa file or --use-msa-server).  Without one, they are
    skipped in favor of ESMFold (single-sequence).

    AlphaFold 2 is never auto-selected; run `predict-structure alphafold`
    to use it.

    \b
    Priority order (GPU, MSA available):  Boltz > OpenFold > Chai > ESMFold
    Priority order (GPU, no MSA):         ESMFold
    Priority order (CPU):                 ESMFold > others
    Non-protein entities:                 ESMFold excluded
    """
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, sequence_files=shared.get("sequence_files", ()), force=shared.get("force", False))
    tool_name = _auto_select_tool(
        entity_list,
        device=shared.get("device", "gpu"),
        has_msa=shared.get("msa") is not None,
        use_msa_server=use_msa_server,
    )
    click.echo(f"Auto-selected: {tool_name}")

    extra = dict(_AUTO_DEFAULTS.get(tool_name, {}))
    if use_msa_server and tool_name in ("boltz", "openfold", "chai"):
        extra["use_msa_server"] = True
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles,
        "sequence": shared.get("sequence_files", ()),
    }
    run_prediction(tool_name, extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# preflight subcommand
# ---------------------------------------------------------------------------

@main.command()
@click.option("--tool", type=click.Choice(["auto", "boltz", "openfold", "chai", "alphafold", "esmfold", "esmfold2"]),
              default="auto", help="Prediction tool (or 'auto' to resolve)")
@click.option("--protein", type=click.Path(), default=None,
              help="Protein FASTA file (used for auto-resolution)")
@click.option("--msa", type=click.Path(), default=None,
              help="MSA file (influences auto tool selection)")
@click.option("--use-msa-server", is_flag=True, default=False,
              help="MSA server available (influences auto tool selection)")
@click.option("--device", type=click.Choice(["gpu", "cpu"]), default="gpu",
              help="Compute device")
@click.option("--has-protein", is_flag=True, default=False,
              help="A protein input was supplied (declaration only, no file read)")
@click.option("--has-dna", is_flag=True, default=False,
              help="A DNA input was supplied (declaration only, no file read)")
@click.option("--has-rna", is_flag=True, default=False,
              help="An RNA input was supplied (declaration only, no file read)")
@click.option("--has-ligand", is_flag=True, default=False,
              help="A CCD-coded ligand was supplied (declaration only)")
@click.option("--has-smiles", is_flag=True, default=False,
              help="A SMILES ligand was supplied (declaration only)")
def preflight(tool, protein, msa, use_msa_server, device,
              has_protein, has_dna, has_rna, has_ligand, has_smiles):
    """Return resource requirements as JSON for BV-BRC preflight.

    Resolves 'auto' to a concrete tool and returns CPU, memory, runtime,
    and GPU requirements. Does NOT run any prediction.

    The ``--has-*`` flags declare which kinds of input the job carries, without
    naming or reading any file. Preflight runs on the scheduler node where
    workspace files are not mounted, so this is the only entity information
    available — and it is enough to reject a tool/input mismatch before SLURM
    allocates a GPU (issue #84).

    Exit codes:
        0  resources emitted as JSON on stdout
        3  input is invalid for the tool; stdout carries {"error": {...}} and
           the caller should fail the job rather than fall back to defaults
           (3, not 2 — click already uses 2 for its own usage errors)

    \b
    Example:
        predict-structure preflight --tool esmfold --has-protein
        predict-structure preflight --tool auto --has-protein --has-dna --use-msa-server
    """
    declared: set[EntityType] = set()
    for flag, entity_type in (
        (has_protein, EntityType.PROTEIN),
        (has_dna, EntityType.DNA),
        (has_rna, EntityType.RNA),
        (has_ligand, EntityType.LIGAND),
        (has_smiles, EntityType.SMILES),
    ):
        if flag:
            declared.add(entity_type)

    # Resolve tool
    if tool == "auto":
        if protein:
            entity_list = _build_entity_list(
                protein=(protein,), dna=(), rna=(), ligand=(), smiles=(),
            )
        else:
            # No file access here — synthesize one placeholder entity per
            # declared kind so _auto_select_tool sees the real entity mix.
            # Falls back to protein-only when nothing was declared.
            entity_list = EntityList()
            for entity_type in sorted(declared or {EntityType.PROTEIN},
                                      key=lambda e: e.value):
                entity_list.add(entity_type, "X", name="preflight_declared")
        try:
            resolved = _auto_select_tool(
                entity_list,
                device=device,
                has_msa=msa is not None,
                use_msa_server=use_msa_server,
            )
        except UnsupportedInputError as exc:
            # click.UsageError is deliberately not caught: it means nothing is
            # installed, which is a deployment fault, not the user's input.
            _preflight_reject(str(exc))
    else:
        resolved = tool

    # Get resource requirements from the adapter
    adapter = get_adapter(resolved)

    # Reject tool/input mismatches now, while rejecting is still cheap. The
    # same check runs again in run_prediction; this one saves the allocation.
    if declared:
        try:
            adapter.validate_entity_types(declared)
        except ValueError as exc:
            _preflight_reject(str(exc), resolved_tool=resolved)

    resources = adapter.preflight()

    # Build output with resolved tool and GPU info
    output = {
        "resolved_tool": resolved,
        "needs_gpu": adapter.requires_gpu,
    }
    output.update(resources)

    click.echo(json.dumps(output))


def _preflight_reject(message: str, resolved_tool: str | None = None) -> None:
    """Emit a structured preflight rejection on stdout and exit 3.

    App-PredictStructure.pl treats a generic non-zero exit as "the preflight
    binary broke" and silently falls back to default resources — which would
    schedule the very job we are rejecting. The caller therefore keys off the
    ``error`` payload rather than the exit status, since click already exits 2
    for its own usage errors and the two must not be confused.
    """
    payload: dict[str, Any] = {"error": {"code": "invalid_input", "message": message}}
    if resolved_tool:
        payload["error"]["resolved_tool"] = resolved_tool
    click.echo(json.dumps(payload))
    sys.exit(3)


# ---------------------------------------------------------------------------
# Provenance post-processing subcommands
# ---------------------------------------------------------------------------


@main.command("finalize-results")
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option(
    "--emit-rocrate/--no-emit-rocrate",
    default=True,
    help="Emit ro-crate-metadata.json alongside results.json [default: emit]",
)
def finalize_results(output_dir, emit_rocrate):
    """(Re)generate results.json + ro-crate-metadata.json in an existing output dir.

    Reads the canonical ``metadata/metadata.json`` (which already carries
    inputs, command, container, backend) and rebuilds the v2.0 outputs map
    in ``results.json`` + the derived ``metadata/ro-crate-metadata.json``.

    Used by the BV-BRC service script after running protein_compare so the
    manifest includes the freshly generated report files.
    """
    out = Path(output_dir)
    try:
        results_path = write_results_json(out)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Wrote {results_path}")
    if emit_rocrate:
        crate_path = write_ro_crate(out)
        if crate_path is not None:
            click.echo(f"Wrote {crate_path}")


@main.command("rewrite-locations")
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option(
    "--base", required=True,
    help="Base location (e.g. ws:///user@bvbrc/home/job123) to prepend to each "
         "relative POSIX path. Trailing slash is normalized.",
)
def rewrite_locations(output_dir, base):
    """Rewrite ``location`` fields in results.json + metadata.json from
    relative POSIX paths to absolute URLs (typically ``ws://...`` after
    BV-BRC workspace upload).

    Walks ``results.json``'s ``outputs`` map recursively (CWL File +
    Directory entries) and ``metadata.json``'s ``inputs[].staged`` field.
    Locations that are already absolute (contain ``://``) are left alone.
    """
    out = Path(output_dir)
    base_url = base.rstrip("/")

    def _rewrite(loc: str) -> str:
        if "://" in loc:
            return loc
        return f"{base_url}/{loc.lstrip('/')}"

    def _walk_outputs(node):
        if isinstance(node, dict):
            if "location" in node and isinstance(node["location"], str):
                node["location"] = _rewrite(node["location"])
            for child in node.get("listing", []) or []:
                _walk_outputs(child)

    results_path = out / "results.json"
    if results_path.is_file():
        results = json.loads(results_path.read_text())
        for entry in (results.get("outputs") or {}).values():
            _walk_outputs(entry)
        results_path.write_text(json.dumps(results, indent=2))
        click.echo(f"Rewrote locations in {results_path}")

    metadata_path = out / "metadata" / "metadata.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text())
        for inp in metadata.get("inputs") or []:
            staged = inp.get("staged")
            if staged and "://" not in staged:
                inp["location"] = _rewrite(staged)
        metadata_path.write_text(json.dumps(metadata, indent=2))
        click.echo(f"Rewrote locations in {metadata_path}")


@main.command("aggregate-results")
@click.option(
    "--in", "inputs", type=click.Path(exists=True), multiple=True, required=True,
    help="Per-tool results.json files to aggregate",
)
@click.option(
    "-o", "--output", type=click.Path(), required=True,
    help="Path for the aggregated results.json",
)
def aggregate_results(inputs, output):
    """Aggregate multiple per-tool results.json files into a combined summary.

    Produces a top-level results.json with a "runs" array, where each entry
    is a full per-tool results.json. Used by the multi-tool CWL workflow.
    """
    runs = [json.loads(Path(p).read_text()) for p in inputs]
    aggregate = {
        "schema_version": "1.0",
        "kind": "multi-tool",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
    }
    Path(output).write_text(json.dumps(aggregate, indent=2))
    click.echo(f"Wrote {output}")


if __name__ == "__main__":
    main()
