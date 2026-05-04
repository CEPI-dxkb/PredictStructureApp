# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Always use the `predict-structure` conda environment for this project:

```bash
conda activate predict-structure
```

When running Python, pytest, or pip commands, prefix with `conda run -n predict-structure` if the environment is not already active.

## Project Overview

PredictStructureApp is a unified BV-BRC (Bacterial and Viral Bioinformatics Resource Center) module that provides a single interface for protein structure prediction using five tools: Boltz-2, OpenFold 3, Chai-1, AlphaFold 2, and ESMFold. It wraps per-tool containers behind a unified AppService interface and Python CLI with automatic parameter mapping and format conversion.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Unified CLI (predict-structure)                        │
│  click-based, unified parameters                        │
├─────────────────────────────────────────────────────────┤
│  Adapter Layer                                          │
│  Boltz | OpenFold | Chai | AlphaFold | ESMFold Adapters │
│  Input conversion  │  Param mapping  │  Output normalize│
├─────────────────────────────────────────────────────────┤
│  Execution Backends                                     │
│  Docker (direct)  │  CWL (GoWe/cwltool)  │  BV-BRC     │
├─────────────────────────────────────────────────────────┤
│  Native Tool Containers                                 │
│  dxkb/boltz │ openfold3 │ dxkb/chai │ alphafold │ esmfold│
└─────────────────────────────────────────────────────────┘
```

### Delegation Pattern

PredictStructureApp does NOT bundle all tools into a single Docker image. Instead, the BV-BRC service script (`App-PredictStructure.pl`) dispatches to the appropriate per-tool container. This keeps images small and independently updatable.

## Key Components

- **predict_structure/**: Python package with unified CLI, adapters, converters, and backends
  - `cli.py`: click-based CLI entry point (`predict-structure <tool> <input> [OPTIONS]`), uses click.group() with per-tool subcommands
  - `adapters/base.py`: Abstract adapter class (prepare_input, build_command, run, normalize_output)
  - `adapters/boltz.py`: FASTA→YAML conversion, --diffusion_samples mapping, mmCIF→PDB
  - `adapters/chai.py`: FASTA pass-through, A3M→Parquet MSA conversion
  - `adapters/alphafold.py`: FASTA pass-through, precomputed MSA directory structure
  - `adapters/openfold.py`: OpenFold 3 (AF3-class), JSON input format, rich confidence metrics
  - `adapters/esmfold.py`: HuggingFace transformers-based (not legacy esm-fold)
  - `converters.py`: FASTA→YAML, A3M→Parquet, mmCIF→PDB format conversions
  - `normalizers.py`: Unified output directory layout and confidence JSON schema
  - `backends/docker.py`: Docker execution (subprocess + volume mounts)
  - `backends/cwl.py`: CWL execution via GoWe or cwltool
- **service-scripts/App-PredictStructure.pl**: BV-BRC AppService entry point
- **app_specs/PredictStructure.json**: Service parameter definitions
- **cwl/**: CWL tool and workflow definitions
- **container/**: Dockerfile for BV-BRC integration layer

## CLI Structure

The CLI uses `click.group()` with per-tool subcommands. Each subcommand has shared options (common to all tools) plus tool-specific options.

### Shared Options (all subcommands)

| Flag | Type | Description |
|------|------|-------------|
| `<input>` | file | FASTA file (or Boltz YAML) |
| `--output-dir, -o` | path | Output directory (required) |
| `--num-samples, -n` | int | Number of structure samples |
| `--num-recycles` | int | Recycling iterations |
| `--seed` | int | Random seed |
| `--device` | enum | `gpu` or `cpu` |
| `--msa` | path | MSA file (.a3m, .sto, .pqt) |
| `--output-format` | enum | `pdb` or `mmcif` |
| `--backend` | enum | `subprocess`, `docker`, or `cwl` |
| `--image` | str | Override Docker image (docker backend only) |
| `--cwl-runner` | str | CWL runner command (cwl backend only) |
| `--cwl-tool` | str | CWL tool definition path (cwl backend only) |
| `--debug` | flag | Print command instead of executing |

### Tool-Specific Options

| Subcommand | Option | Description |
|------------|--------|-------------|
| `boltz` | `--sampling-steps` | Diffusion sampling steps |
| `boltz` | `--use-msa-server` | Use remote MSA server |
| `boltz` | `--use-potentials` | Enable potential terms |
| `openfold` | `--num-diffusion-samples` | Diffusion samples per query |
| `openfold` | `--num-model-seeds` | Independent model seeds |
| `openfold` | `--use-msa-server/--no-msa-server` | ColabFold MSA server (default: True) |
| `openfold` | `--use-templates/--no-templates` | Template structures (default: True) |
| `openfold` | `--checkpoint` | Model checkpoint name |
| `chai` | `--sampling-steps` | Diffusion sampling steps |
| `chai` | `--use-msa-server` | Use remote MSA server |
| `alphafold` | `--af2-data-dir` | Database directory (required) |
| `alphafold` | `--af2-model-preset` | Model preset |
| `alphafold` | `--af2-db-preset` | DB preset |
| `alphafold` | `--af2-max-template-date` | Max template date |
| `esmfold` | `--fp16` | Half-precision inference |
| `esmfold` | `--chunk-size` | Chunk size for long sequences |
| `esmfold` | `--max-tokens-per-batch` | Max tokens per batch |

### Parameter Mapping (shared → native)

| Shared Flag | Boltz-2 | OpenFold 3 | Chai-1 | AlphaFold 2 | ESMFold (HF) |
|-------------|---------|-----------|--------|-------------|---------------|
| `--output-dir` | `--out_dir` | `--output-dir` | `output_dir` | `--output_dir` | `-o` |
| `--num-samples` | `--diffusion_samples` | `--num-diffusion-samples` | `--num-diffn-samples` | N/A | N/A |
| `--num-recycles` | `--recycling_steps` | N/A (runner YAML) | `--num-trunk-recycles` | implicit | `--num-recycles` |
| `--seed` | N/A | `--num-model-seeds` | `--seed` | `--random_seed` | N/A |
| `--device` | `--accelerator` | implicit (GPU) | `--device` | implicit | `--cpu-only` |
| `--msa` | inject into YAML | JSON `main_msa_file_paths` | `--msa-file` (a3m→pqt) | `--msa_dir` | ignored |

## Building and Running

### Python CLI

```bash
# Install
pip install -e .

# Run prediction (each tool is a subcommand with its own options)
predict-structure boltz input.fasta -o output/ --num-samples 5 --use-potentials
predict-structure esmfold input.fasta -o output/ --num-recycles 4 --fp16
predict-structure chai input.fasta -o output/ --msa alignment.a3m
predict-structure openfold --protein input.fasta -o output/ --num-diffusion-samples 5
predict-structure alphafold input.fasta -o output/ --af2-data-dir /data/alphafold

# Debug mode (print command without executing)
predict-structure esmfold input.fasta -o output/ --debug

# Per-tool help
predict-structure boltz --help
predict-structure esmfold --help
```

### BV-BRC Service

```bash
# Run as BV-BRC service (inside container)
App-PredictStructure params.json

# Test with sample params
docker run --gpus all -v $(pwd)/test_data:/data \
  dxkb/predict-structure-bvbrc:latest-gpu App-PredictStructure /data/params.json
```

### Docker Images

```bash
# Build BV-BRC integration layer (delegates to per-tool containers)
cd container
docker build -t dxkb/predict-structure-bvbrc:latest-gpu -f Dockerfile.PredictStructure-bvbrc .

# Build Apptainer for HPC
singularity build predict-structure-bvbrc.sif docker://dxkb/predict-structure-bvbrc:latest-gpu
```

### CWL Workflows

```bash
# Validate CWL
cwltool --validate cwl/tools/predict-structure.cwl

# Run via CWL
cwltool cwl/tools/predict-structure.cwl test_data/job.yml
```

## Testing

```bash
# Unit tests (adapters, converters, normalizers)
pytest tests/ -v

# Integration test (requires GPU)
pytest tests/test_integration.py -v --gpu

# BV-BRC Makefile tests
make test-client
make test-server

# Validate output structure
./tests/validate_output.sh /path/to/output
```

## Input/Output Formats

### Input
- **FASTA** (.fasta, .fa): Universal input, converted to tool-specific formats by adapters
- **Boltz YAML** (.yaml): Passed directly to Boltz for full feature support (ligands, constraints)
- **MSA files** (.a3m, .sto, .pqt): Optional alignment files, auto-converted per tool

### Output (Normalized)
Every prediction produces a standardized output directory:
```
output/
├── model_1.pdb          # Structure (always PDB)
├── model_1.cif          # Structure (always mmCIF)
├── confidence.json      # {plddt_mean, ptm, per_residue_plddt[]}
├── metadata.json        # {tool, params, runtime, version}
└── raw/                 # Original tool output (unmodified)
```

## Resource Requirements

| Tool | CPU | Memory | GPU | Runtime |
|------|-----|--------|-----|---------|
| Boltz-2 | 8 | 64-96GB | A100/H100/H200 | 2-4h |
| OpenFold 3 | 8 | 96GB | A100/H100/H200 (32GB+ VRAM) | 2-4h |
| Chai-1 | 8 | 64GB | A100/H100/H200 | 2-3h |
| AlphaFold 2 | 8 | 64GB | A100/H100/H200 | 2-8h |
| ESMFold | 8 | 32GB | Optional | 5-15m |

GPU constraint: `A100|H100|H200` on `gpu2` partition.
ESMFold can run on CPU (no GPU policy needed in preflight).

## BV-BRC Service Script

`service-scripts/App-PredictStructure.pl` bridges BV-BRC AppService to the Python CLI:

```
BV-BRC → App-PredictStructure.pl → predict-structure <tool> --protein ... → Python adapters → native tool
```

### Flow
1. **preflight()** — calls `predict-structure preflight --tool <tool>` for resource estimates
2. **run_app()** — downloads workspace files, runs prediction, generates report, uploads results

### Key Details
- Preflight delegates tool resolution + GPU decision to Python CLI `preflight` subcommand
- MSA mode mapping: `none` → no flag, `server` → `--use-msa-server`, `upload` → `--msa <file>`
- Binary path: `/opt/conda-predict/bin/predict-structure`
- Backend: always `--backend subprocess` (inside container)
- Report: `python -m protein_compare characterize output/model_1.pdb -o report --format all`
- Upload: `p3-cp -r` with `--map-suffix` for file type mapping
- Runtime in SECONDS (14400 = 4h)
- `policy_data` for GPU scheduling (not deprecated `gpu => 1`)
- No filesystem validation in preflight (volumes not mounted yet)

### Preflight CLI
```bash
predict-structure preflight --tool esmfold --protein input.fasta
# {"resolved_tool": "esmfold", "needs_gpu": false, "cpu": 8, "memory": "32G", "runtime": 3600}

predict-structure preflight --tool boltz
# {"resolved_tool": "boltz", "needs_gpu": true, "cpu": 8, "memory": "96G", ...}
```

## Related Repositories

- **dxkb** (project workspace): Per-tool apps (boltzApp, ChaiApp, AlphaFoldApp, ESMFoldApp, stabiliNNatorApp) — each is an independent repo
- **ProteinFoldingApp**: Experiment framework for tool comparison and MSA impact analysis (different scope)
- **CEPI**: BV-BRC infrastructure, automated service generator, container build chain

## Key Conventions

- **BV-BRC AppScript pattern**: `Bio::KBase::AppService::AppScript->new(\&run_app, \&preflight)`
- **Adapter pattern**: Each tool adapter inherits from `BaseAdapter` with 4 methods
- **OpenFold 3 uses JSON input**: `entities_to_openfold_json()` converts EntityList → OF3 JSON query format (not FASTA). Built-in ColabFold MSA server. Requires 32GB+ GPU VRAM.
- **ESMFold uses HuggingFace**: `transformers` + `torch`, NOT legacy OpenFold-based `esm-fold`
- **Output B-factors**: 0-1 range (not crystallographic 0-100)
- **A3M is MSA lingua franca**: Auto-converted to Parquet for Chai, injected into YAML for Boltz
- **Subcommand pattern**: CLI uses click.group() — tool-specific options are explicit on each subcommand, not generic pass-through
