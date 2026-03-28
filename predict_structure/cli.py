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
import logging
import shutil
import sys
import time
from pathlib import Path

import click
import yaml
from click_option_group import optgroup

logger = logging.getLogger(__name__)

from predict_structure import __version__
from predict_structure.adapters import get_adapter
from predict_structure.backends import get_backend
from predict_structure.entities import (
    EntityList,
    EntityType,
    is_boltz_yaml,
    parse_fasta_entities,
)
from predict_structure.normalizers import write_metadata_json


# ---------------------------------------------------------------------------
# Tool auto-discovery
# ---------------------------------------------------------------------------

from predict_structure.config import get_command, get_data_dir, get_data_root, get_tools

# Default AlphaFold database directory — resolved from config/env.
# Guard against config FileNotFoundError at import time so Click can
# still start and report configuration issues gracefully.
try:
    AF2_DEFAULT_DATA_DIR = get_data_dir("alphafold")
except (FileNotFoundError, KeyError):
    AF2_DEFAULT_DATA_DIR = Path("/databases")


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


def _auto_select_tool(entity_list: EntityList, device: str = "gpu") -> str:
    """Auto-select the best available prediction tool based on entity types.

    Selection rules:
      - Non-protein entities exclude AlphaFold and ESMFold.
      - ``device=cpu`` prefers ESMFold (others are impractical on CPU).
      - Otherwise pick first available in accuracy-priority order:
        Boltz > Chai > AlphaFold > ESMFold.

    Raises:
        click.UsageError: If no suitable tool is found.
    """
    has_non_protein = entity_list.entity_types - {EntityType.PROTEIN}

    # CPU → strongly prefer ESMFold (if protein-only)
    if device == "cpu" and not has_non_protein:
        if _is_tool_available("esmfold"):
            return "esmfold"

    # Accuracy-priority order
    for tool in ("boltz", "chai", "alphafold", "esmfold"):
        # Skip tools that don't support the entity types
        if tool in ("alphafold", "esmfold") and has_non_protein:
            continue

        if tool == "alphafold":
            if _is_tool_available(tool) and AF2_DEFAULT_DATA_DIR.is_dir():
                return tool
        elif _is_tool_available(tool):
            return tool

    raise click.UsageError(
        "No prediction tool found on PATH. "
        "Install one of: boltz, chai-lab, run_alphafold.py, esm-fold-hf"
    )


# Keep for backward compat with tests that mock discover_tool
def discover_tool(input_file: Path, device: str = "gpu") -> str:
    """Auto-discover the best available prediction tool (legacy interface).

    Selection rules:
      - ``.yaml`` / ``.yml`` input forces Boltz (only tool supporting YAML).
      - ``device=cpu`` prefers ESMFold (others are impractical on CPU).
      - Otherwise pick first available in accuracy-priority order:
        Boltz > Chai > AlphaFold > ESMFold.

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

    # Accuracy-priority order
    for tool in ("boltz", "chai", "alphafold", "esmfold"):
        if tool == "alphafold":
            if _is_tool_available(tool) and AF2_DEFAULT_DATA_DIR.is_dir():
                return tool
        elif _is_tool_available(tool):
            return tool

    raise click.UsageError(
        "No prediction tool found on PATH. "
        "Install one of: boltz, chai-lab, run_alphafold.py, esm-fold-hf"
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
    glycan: tuple[str, ...],
) -> EntityList:
    """Build an EntityList from CLI option tuples.

    FASTA files (--protein, --dna, --rna) are parsed and each sequence
    becomes a separate entity. Inline values (--ligand, --smiles, --glycan)
    become one entity each.

    Also handles Boltz YAML pass-through: if a single --protein path points
    to a .yaml/.yml file, it's treated as a YAML entity for Boltz.

    Raises:
        click.UsageError: If no entities are provided.
    """
    entities = EntityList()

    for fasta_path in protein:
        path = Path(fasta_path)
        # Boltz YAML pass-through: single .yaml file passed as --protein
        if is_boltz_yaml(path):
            entities.add(EntityType.PROTEIN, str(path), name=path.stem)
            continue
        for ent in parse_fasta_entities(path, explicit_type=EntityType.PROTEIN):
            entities.add(ent.entity_type, ent.value, name=ent.name)

    for fasta_path in dna:
        for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.DNA):
            entities.add(ent.entity_type, ent.value, name=ent.name)

    for fasta_path in rna:
        for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.RNA):
            entities.add(ent.entity_type, ent.value, name=ent.name)

    for code in ligand:
        entities.add(EntityType.LIGAND, code, name=code)

    for smi in smiles:
        entities.add(EntityType.SMILES, smi, name="smiles")

    for gly in glycan:
        entities.add(EntityType.GLYCAN, gly, name="glycan")

    if not entities:
        raise click.UsageError(
            "No input entities provided. Use --protein, --dna, --rna, "
            "--ligand, --smiles, or --glycan to specify input."
        )

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
    @optgroup.option("--ligand", multiple=True, type=str,
                     help="Ligand CCD code (repeatable)")
    @optgroup.option("--smiles", multiple=True, type=str,
                     help="SMILES string (repeatable)")
    @optgroup.option("--glycan", multiple=True, type=str,
                     help="Glycan specification (repeatable)")
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
    @click.option("--debug", is_flag=True, default=False, help="Print the command instead of executing it")
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
    logger.info("Tool: %s", tool_name)
    logger.info("Entities: %s", [(e.entity_type.value, e.name) for e in entity_list])
    logger.info("Backend: %s | Device: %s", shared.get("backend"), shared.get("device"))

    output_path = Path(shared["output_dir"])
    output_path.mkdir(parents=True, exist_ok=True)
    raw_dir = output_path / "raw_output"
    raw_dir.mkdir(parents=True, exist_ok=True)

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
    adapter.validate_entities(entity_list)
    logger.info("Entity validation passed")

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

        adapter.normalize_output(raw_dir, output_path)
        params_dict = {
            "num_samples": shared["num_samples"],
            "num_recycles": shared["num_recycles"],
            "seed": shared.get("seed"),
            "device": shared["device"],
        }
        write_metadata_json(output_path, tool_name, params_dict, elapsed, __version__)
        click.echo(f"Prediction complete: {output_path}")
        return

    # -----------------------------------------------------------------
    # Standard path: subprocess / docker / apptainer / legacy CWL
    # -----------------------------------------------------------------

    # 3. Prepare input (entity list → tool-native format, MSA conversion)
    msa_path = Path(shared["msa"]) if shared.get("msa") else None
    prepared = adapter.prepare_input(entity_list, output_path, msa_path=msa_path)
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

    start = time.time()
    rc = execution_backend.run(cmd, **run_kwargs)
    elapsed = time.time() - start

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
            click.echo(f"Prediction failed with exit code {rc}", err=True)
            sys.exit(rc)

    # 7. Normalize output
    # CWL places tool output inside raw_dir/output/ (the CWL output_dir name)
    normalize_dir = cwl_output_subdir if backend == "cwl" else raw_dir
    adapter.normalize_output(normalize_dir, output_path)

    params_dict = {
        "num_samples": shared["num_samples"],
        "num_recycles": shared["num_recycles"],
        "seed": shared.get("seed"),
        "device": shared["device"],
    }
    write_metadata_json(output_path, tool_name, params_dict, elapsed, __version__)

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
                entities.add(ent.entity_type, ent.value, name=ent.name)
        for fasta_path in job.get("dna", []):
            for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.DNA):
                entities.add(ent.entity_type, ent.value, name=ent.name)
        for fasta_path in job.get("rna", []):
            for ent in parse_fasta_entities(Path(fasta_path), explicit_type=EntityType.RNA):
                entities.add(ent.entity_type, ent.value, name=ent.name)
        for code in job.get("ligands", []):
            entities.add(EntityType.LIGAND, code, name=code)
        for smi in job.get("smiles", []):
            entities.add(EntityType.SMILES, smi, name="smiles")
        for gly in job.get("glycans", []):
            entities.add(EntityType.GLYCAN, gly, name="glycan")

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
        }

        entity_inputs = {
            "protein": job.get("protein", []),
            "dna": job.get("dna", []),
            "rna": job.get("rna", []),
            "ligand": job.get("ligands", []),
            "smiles": job.get("smiles", []),
            "glycan": job.get("glycans", []),
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
    """Predict protein structure using Boltz-2, Chai-1, AlphaFold 2, or ESMFold.

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
def boltz(protein, dna, rna, ligand, smiles, glycan,
          sampling_steps, use_msa_server, msa_server_url, use_potentials, **shared):
    """Predict structure with Boltz-2 (diffusion-based, proteins/DNA/RNA/ligands)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, glycan)
    extra = {
        "sampling_steps": sampling_steps,
        "use_msa_server": use_msa_server or (msa_server_url is not None),
        "msa_server_url": msa_server_url,
        "boltz_use_potentials": use_potentials,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles, "glycan": glycan,
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
def chai(protein, dna, rna, ligand, smiles, glycan,
         sampling_steps, use_msa_server, msa_server_url,
         no_esm_embeddings, use_templates_server, constraint_path,
         template_hits_path, num_trunk_samples, recycle_msa_subsample,
         no_low_memory, **shared):
    """Predict structure with Chai-1 (diffusion-based protein prediction)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, glycan)
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
        "ligand": ligand, "smiles": smiles, "glycan": glycan,
    }
    run_prediction("chai", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# alphafold subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("AlphaFold 2 options")
@optgroup.option("--af2-data-dir", type=click.Path(), required=True, help="AlphaFold database directory (~2TB)")
@optgroup.option("--af2-model-preset", default="monomer", help="Model preset (monomer, monomer_casp14, multimer)")
@optgroup.option("--af2-db-preset", default="reduced_dbs", help="DB preset (reduced_dbs, full_dbs)")
@optgroup.option("--af2-max-template-date", default="2022-01-01", help="Max template date (YYYY-MM-DD)")
@backend_options
def alphafold(protein, dna, rna, ligand, smiles, glycan,
              af2_data_dir, af2_model_preset, af2_db_preset, af2_max_template_date, **shared):
    """Predict structure with AlphaFold 2 (MSA-based, high accuracy)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, glycan)
    extra = {
        "af2_data_dir": af2_data_dir,
        "af2_model_preset": af2_model_preset,
        "af2_db_preset": af2_db_preset,
        "af2_max_template_date": af2_max_template_date,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles, "glycan": glycan,
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
def esmfold(protein, dna, rna, ligand, smiles, glycan,
            fp16, chunk_size, max_tokens_per_batch, **shared):
    """Predict structure with ESMFold (single-sequence, no MSA needed, CPU-capable)."""
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, glycan)
    extra = {
        "esm_fp16": fp16,
        "esm_chunk_size": chunk_size,
        "esm_max_tokens": max_tokens_per_batch,
    }
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles, "glycan": glycan,
    }
    run_prediction("esmfold", extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


# ---------------------------------------------------------------------------
# auto subcommand
# ---------------------------------------------------------------------------

# Sensible defaults applied when auto-discovery selects a tool.
# These match the per-tool subcommand defaults so the user doesn't need
# to provide tool-specific flags.
_AUTO_DEFAULTS: dict[str, dict] = {
    "boltz": {},
    "chai": {},
    "alphafold": {
        "af2_data_dir": str(AF2_DEFAULT_DATA_DIR),
        "af2_model_preset": "monomer",
        "af2_db_preset": "reduced_dbs",
        "af2_max_template_date": "2022-01-01",
    },
    "esmfold": {},
}


@main.command()
@shared_options
@backend_options
def auto(protein, dna, rna, ligand, smiles, glycan, **shared):
    """Auto-discover the best available tool and predict structure.

    Checks which prediction tools are installed and selects the best
    one based on entity types, device, and availability.

    \b
    Priority order (GPU):  Boltz > Chai > AlphaFold > ESMFold
    Priority order (CPU):  ESMFold > Boltz > Chai > AlphaFold
    Non-protein entities:  AlphaFold and ESMFold excluded
    """
    entity_list = _build_entity_list(protein, dna, rna, ligand, smiles, glycan)
    tool_name = _auto_select_tool(entity_list, device=shared.get("device", "gpu"))
    click.echo(f"Auto-selected: {tool_name}")

    extra = dict(_AUTO_DEFAULTS.get(tool_name, {}))
    entity_inputs = {
        "protein": protein, "dna": dna, "rna": rna,
        "ligand": ligand, "smiles": smiles, "glycan": glycan,
    }
    run_prediction(tool_name, extra, entity_list=entity_list,
                   entity_inputs=entity_inputs, **shared)


if __name__ == "__main__":
    main()
