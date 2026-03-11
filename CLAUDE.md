# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PredictStructureApp is a unified BV-BRC (Bacterial and Viral Bioinformatics Resource Center) module that provides a single interface for protein structure prediction using four tools: Boltz-2, Chai-1, AlphaFold 2, and ESMFold. It wraps per-tool containers behind a unified AppService interface and Python CLI with automatic parameter mapping and format conversion.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Unified CLI (predict-structure)                        │
│  click-based, unified parameters                        │
├─────────────────────────────────────────────────────────┤
│  Adapter Layer                                          │
│  BoltzAdapter | ChaiAdapter | AlphaFoldAdapter | ESMFold│
│  Input conversion  │  Param mapping  │  Output normalize│
├─────────────────────────────────────────────────────────┤
│  Execution Backends                                     │
│  Docker (direct)  │  CWL (GoWe/cwltool)  │  BV-BRC     │
├─────────────────────────────────────────────────────────┤
│  Native Tool Containers                                 │
│  dxkb/boltz  │  dxkb/chai  │  alphafold  │  dxkb/esmfold│
└─────────────────────────────────────────────────────────┘
```

### Delegation Pattern

PredictStructureApp does NOT bundle all tools into a single Docker image. Instead, the BV-BRC service script (`App-PredictStructure.pl`) dispatches to the appropriate per-tool container. This keeps images small and independently updatable.

## Key Components

- **predict_structure/**: Python package with unified CLI, adapters, converters, and backends
  - `cli.py`: click-based CLI entry point (`predict-structure <tool> <input>`)
  - `adapters/base.py`: Abstract adapter class (prepare_input, build_command, run, normalize_output)
  - `adapters/boltz.py`: FASTA→YAML conversion, --diffusion_samples mapping, mmCIF→PDB
  - `adapters/chai.py`: FASTA pass-through, A3M→Parquet MSA conversion
  - `adapters/alphafold.py`: FASTA pass-through, precomputed MSA directory structure
  - `adapters/esmfold.py`: HuggingFace transformers-based (not legacy esm-fold)
  - `converters.py`: FASTA→YAML, A3M→Parquet, mmCIF→PDB format conversions
  - `normalizers.py`: Unified output directory layout and confidence JSON schema
  - `backends/docker.py`: Docker execution (subprocess + volume mounts)
  - `backends/cwl.py`: CWL execution via GoWe or cwltool
- **service-scripts/App-PredictStructure.pl**: BV-BRC AppService entry point
- **app_specs/PredictStructure.json**: Service parameter definitions
- **cwl/**: CWL tool and workflow definitions
- **container/**: Dockerfile for BV-BRC integration layer

## Unified Parameter Mapping

| Unified CLI Flag | Boltz-2 | Chai-1 | AlphaFold 2 | ESMFold (HF) |
|------------------|---------|--------|-------------|---------------|
| `<tool>` | `boltz predict` | `chai fold` | `run_alphafold.py` | `esm-fold-hf` |
| `<input>` | INPUT_PATH (.yaml) | `--fasta` | `--fasta_paths` | `-i` (.fasta) |
| `--output-dir` | `--out_dir` | `output_dir` | `--output_dir` | `-o` |
| `--num-samples` | `--diffusion_samples` | `--num-diffn-samples` | N/A | N/A |
| `--num-recycles` | `--recycling_steps` | `--num-trunk-recycles` | implicit | `--num-recycles` |
| `--seed` | N/A | `--seed` | `--random_seed` | N/A |
| `--device` | `--accelerator` | `--device` | implicit | `--cpu-only` |
| `--msa` | inject into YAML | `--msa-file` (a3m→pqt) | `--msa_dir` | ignored |
| `--boltz-*` | pass-through | - | - | - |
| `--chai-*` | - | pass-through | - | - |
| `--af2-*` | - | - | pass-through | - |
| `--esm-*` | - | - | - | pass-through |

## Building and Running

### Python CLI

```bash
# Install
pip install -e .

# Run prediction
predict-structure boltz input.fasta -o output/ --num-samples 5
predict-structure esmfold input.fasta -o output/ --num-recycles 4
predict-structure chai input.fasta -o output/ --msa alignment.a3m

# Pass-through tool-specific flags
predict-structure boltz input.yaml -o output/ --boltz-use-potentials
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
| Chai-1 | 8 | 64GB | A100/H100/H200 | 2-3h |
| AlphaFold 2 | 8 | 64GB | A100/H100/H200 | 2-8h |
| ESMFold | 8 | 32GB | Optional | 5-15m |

GPU constraint: `A100|H100|H200` on `gpu2` partition.
ESMFold can run on CPU (no GPU policy needed in preflight).

## Related Repositories

- **dxkb** (project workspace): Per-tool apps (boltzApp, ChaiApp, AlphaFoldApp, ESMFoldApp, stabiliNNatorApp) — each is an independent repo
- **ProteinFoldingApp**: Experiment framework for tool comparison and MSA impact analysis (different scope)
- **CEPI**: BV-BRC infrastructure, automated service generator, container build chain

## Key Conventions

- **BV-BRC AppScript pattern**: `Bio::KBase::AppService::AppScript->new(\&run_app, \&preflight)`
- **Adapter pattern**: Each tool adapter inherits from `BaseAdapter` with 4 methods
- **ESMFold uses HuggingFace**: `transformers` + `torch`, NOT legacy OpenFold-based `esm-fold`
- **Output B-factors**: 0-1 range (not crystallographic 0-100)
- **A3M is MSA lingua franca**: Auto-converted to Parquet for Chai, injected into YAML for Boltz
- **Pass-through flags**: `--boltz-*`, `--chai-*`, `--af2-*`, `--esm-*` forwarded to native tools
