"""Unified CLI entry point for protein structure prediction.

Usage:
    predict-structure <tool> <input> [OPTIONS]

Examples:
    predict-structure boltz input.fasta -o output/ --num-samples 5
    predict-structure esmfold input.fasta -o output/ --num-recycles 4
    predict-structure chai input.fasta -o output/ --msa alignment.a3m
"""

import click


TOOLS = ["boltz", "chai", "alphafold", "esmfold"]


@click.command()
@click.argument("tool", type=click.Choice(TOOLS, case_sensitive=False))
@click.argument("input_file", type=click.Path(exists=True))
@click.option("-o", "--output-dir", type=click.Path(), required=True, help="Output directory")
@click.option("--num-samples", type=int, default=1, help="Number of structure samples")
@click.option("--num-recycles", type=int, default=3, help="Recycling iterations")
@click.option("--seed", type=int, default=None, help="Random seed")
@click.option("--device", type=click.Choice(["gpu", "cpu"]), default="gpu", help="Compute device")
@click.option("--msa", type=click.Path(), default=None, help="MSA file (.a3m, .sto, .pqt)")
@click.option("--output-format", type=click.Choice(["pdb", "mmcif"]), default="pdb")
def main(tool, input_file, output_dir, num_samples, num_recycles, seed, device, msa, output_format):
    """Predict protein structure using TOOL on INPUT_FILE."""
    click.echo(f"predict-structure {tool} {input_file} → {output_dir}")
    click.echo("(stub — adapter dispatch not yet implemented)")


if __name__ == "__main__":
    main()
