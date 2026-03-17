"""Unified CLI entry point for protein structure prediction.

Usage:
    predict-structure <tool> <input> [OPTIONS]

Examples:
    predict-structure boltz input.fasta -o output/ --num-samples 5 --use-potentials
    predict-structure esmfold input.fasta -o output/ --num-recycles 4 --fp16
    predict-structure chai input.fasta -o output/ --msa alignment.a3m
    predict-structure alphafold input.fasta -o output/ --af2-data-dir /data
"""

from __future__ import annotations

import functools
import sys
import time
from pathlib import Path

import click
from click_option_group import optgroup

from predict_structure import __version__
from predict_structure.adapters import get_adapter
from predict_structure.backends import get_backend
from predict_structure.normalizers import write_metadata_json


# ---------------------------------------------------------------------------
# Shared options applied to every tool subcommand
# ---------------------------------------------------------------------------

def shared_options(func):
    """Decorator that applies options common to all prediction tools."""
    @click.argument("input_file", type=click.Path(exists=True))
    @optgroup.group("Prediction options")
    @optgroup.option("-o", "--output-dir", type=click.Path(), required=True, help="Output directory")
    @optgroup.option("--num-samples", "-n", type=int, default=1, help="Number of structure samples")
    @optgroup.option("--num-recycles", type=int, default=3, help="Recycling iterations")
    @optgroup.option("--seed", type=int, default=None, help="Random seed")
    @optgroup.option("--device", type=click.Choice(["gpu", "cpu"]), default="gpu", help="Compute device")
    @optgroup.option("--msa", type=click.Path(), default=None, help="MSA file (.a3m, .sto, .pqt)")
    @optgroup.option("--output-format", type=click.Choice(["pdb", "mmcif"]), default="pdb")
    @optgroup.group("Backend options")
    @optgroup.option(
        "--backend",
        type=click.Choice(["docker", "subprocess", "cwl"]),
        default="subprocess",
        help="Execution backend",
    )
    @optgroup.option("--image", default=None, help="Override Docker image (docker backend only)")
    @optgroup.option("--cwl-runner", default=None, help="CWL runner command (default: cwltool)")
    @optgroup.option("--cwl-tool", default=None, help="Path to CWL tool definition")
    @click.option("--debug", is_flag=True, default=False, help="Print the command instead of executing it")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Shared prediction logic
# ---------------------------------------------------------------------------

def run_prediction(tool_name: str, extra_kwargs: dict, **shared):
    """Core prediction logic shared by all tool subcommands.

    Args:
        tool_name: Adapter key (boltz, chai, alphafold, esmfold).
        extra_kwargs: Tool-specific keyword arguments for build_command.
        **shared: Shared CLI options (input_file, output_dir, backend, etc.).
    """
    output_path = Path(shared["output_dir"])
    output_path.mkdir(parents=True, exist_ok=True)
    raw_dir = output_path / "raw_output"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve adapter and backend
    adapter = get_adapter(tool_name)
    backend = shared["backend"]
    backend_kwargs = {}
    if backend == "docker" and shared.get("image"):
        backend_kwargs["default_image"] = shared["image"]
    if backend == "cwl":
        if shared.get("cwl_runner"):
            backend_kwargs["runner"] = shared["cwl_runner"]
        if shared.get("cwl_tool"):
            backend_kwargs["cwl_tool"] = shared["cwl_tool"]
    execution_backend = get_backend(backend, **backend_kwargs)

    # 2. Prepare input (FASTA → tool-native format, MSA conversion)
    msa_path = Path(shared["msa"]) if shared.get("msa") else None
    prepared = adapter.prepare_input(
        Path(shared["input_file"]), output_path, msa_path=msa_path
    )

    # 3. Build tool-specific command
    cmd = adapter.build_command(
        prepared,
        raw_dir,
        num_samples=shared["num_samples"],
        num_recycles=shared["num_recycles"],
        seed=shared.get("seed"),
        device=shared["device"],
        **extra_kwargs,
    )

    # 4. Execute prediction (or print command in debug mode)
    if shared.get("debug"):
        click.echo(" ".join(str(c) for c in cmd))
        return

    start = time.time()
    rc = execution_backend.run(
        cmd,
        tool_name=adapter.tool_name,
        gpu=adapter.requires_gpu and shared["device"] != "cpu",
    )
    elapsed = time.time() - start

    if rc != 0:
        click.echo(f"Prediction failed with exit code {rc}", err=True)
        sys.exit(rc)

    # 5. Normalize output
    adapter.normalize_output(raw_dir, output_path)

    params_dict = {
        "num_samples": shared["num_samples"],
        "num_recycles": shared["num_recycles"],
        "seed": shared.get("seed"),
        "device": shared["device"],
    }
    write_metadata_json(output_path, tool_name, params_dict, elapsed, __version__)

    click.echo(f"Prediction complete: {output_path}")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__)
def main():
    """Predict protein structure using Boltz-2, Chai-1, AlphaFold 2, or ESMFold.

    Each subcommand dispatches to the appropriate prediction tool with
    automatic parameter mapping, input format conversion, and output
    normalization.
    """


# ---------------------------------------------------------------------------
# boltz subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("Boltz-2 options")
@optgroup.option("--sampling-steps", type=int, default=200, help="Number of diffusion sampling steps")
@optgroup.option("--use-msa-server", is_flag=True, default=False, help="Use remote MSA server")
@optgroup.option("--use-potentials", is_flag=True, default=False, help="Enable potential terms")
def boltz(input_file, sampling_steps, use_msa_server, use_potentials, **shared):
    """Predict structure with Boltz-2 (diffusion-based, proteins/DNA/RNA/ligands)."""
    extra = {
        "sampling_steps": sampling_steps,
        "use_msa_server": use_msa_server,
        "boltz_use_potentials": use_potentials,
    }
    run_prediction("boltz", extra, input_file=input_file, **shared)


# ---------------------------------------------------------------------------
# chai subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("Chai-1 options")
@optgroup.option("--sampling-steps", type=int, default=200, help="Number of diffusion sampling steps")
@optgroup.option("--use-msa-server", is_flag=True, default=False, help="Use remote MSA server")
def chai(input_file, sampling_steps, use_msa_server, **shared):
    """Predict structure with Chai-1 (diffusion-based protein prediction)."""
    extra = {
        "sampling_steps": sampling_steps,
        "use_msa_server": use_msa_server,
    }
    run_prediction("chai", extra, input_file=input_file, **shared)


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
def alphafold(input_file, af2_data_dir, af2_model_preset, af2_db_preset, af2_max_template_date, **shared):
    """Predict structure with AlphaFold 2 (MSA-based, high accuracy)."""
    extra = {
        "af2_data_dir": af2_data_dir,
        "af2_model_preset": af2_model_preset,
        "af2_db_preset": af2_db_preset,
        "af2_max_template_date": af2_max_template_date,
    }
    run_prediction("alphafold", extra, input_file=input_file, **shared)


# ---------------------------------------------------------------------------
# esmfold subcommand
# ---------------------------------------------------------------------------

@main.command()
@shared_options
@optgroup.group("ESMFold options")
@optgroup.option("--fp16", is_flag=True, default=False, help="Use half-precision (FP16) inference")
@optgroup.option("--chunk-size", type=int, default=None, help="Chunk size for long sequences")
@optgroup.option("--max-tokens-per-batch", type=int, default=None, help="Max tokens per batch")
def esmfold(input_file, fp16, chunk_size, max_tokens_per_batch, **shared):
    """Predict structure with ESMFold (single-sequence, no MSA needed, CPU-capable)."""
    extra = {
        "esm_fp16": fp16,
        "esm_chunk_size": chunk_size,
        "esm_max_tokens": max_tokens_per_batch,
    }
    run_prediction("esmfold", extra, input_file=input_file, **shared)


if __name__ == "__main__":
    main()
