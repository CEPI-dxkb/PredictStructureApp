# Acceptance Testing Guide

## Overview

The acceptance test suite validates PredictStructureApp across three phases:

- **Phase 1 -- Native tools**: Calls tool binaries directly inside the container (no predict-structure involved). Confirms each tool works end-to-end.
- **Phase 2 -- predict-structure CLI**: Tests through `predict-structure <tool> --backend subprocess`. Validates adapters, entity flags, auto-selection, output normalization, and batch mode.
- **Phase 3 -- Perl service script + workspace**: Tests `App-PredictStructure.pl` with params JSON, preflight resource estimation, and real BV-BRC workspace integration.

The framework uses pytest with parametrized tests. All tests run inside Apptainer containers with GPU passthrough.

## Prerequisites

- **Apptainer** installed and available on PATH
- **GPU(s)** available (verify with `nvidia-smi`)
- **Production containers** at `/scout/containers/`:
  - `folding_prod.sif` (current production)
  - `all-2026-0410.01.sif` (candidate all-in-one)
- **Model weights** at `/local_databases/`:
  - `boltz/` -- Boltz-2 weights
  - `chai/` -- Chai-1 weights
  - `openfold/` -- OpenFold 3 weights
  - `alphafold/databases/` -- AlphaFold 2 genetic databases
- **HF model cache** at `/local_databases/cache/hub/` (ESMFold model files)
- **Python dev dependencies**:
  ```bash
  pip install -e ".[dev]"
  ```
- **Phase 3 workspace tests**: A valid `.patric_token` file for BV-BRC authentication

## Configuration

### Container Selection

Choose which container to test using one of these methods (in priority order):

1. `--sif` flag: full path to the `.sif` file
2. `--container-label` flag: shorthand (`prod` or `all`)
3. `PREDICT_STRUCTURE_SIF` environment variable

Default behavior: both containers are tested.

### GPU Pinning

Use `--gpu-id` flag or `CUDA_VISIBLE_DEVICES` environment variable to pin tests to specific GPUs. This is critical for AlphaFold, which uses JAX and will claim all visible GPUs unless explicitly constrained.

Default: GPU 0.

### Dev Code Overlay

For Phase 2 and Phase 3 tests, the local `predict_structure/` package is mounted into the container's site-packages directory. This allows testing local code changes without rebuilding the container. Phase 1 native tests do NOT use the overlay -- they test the container's built-in tool binaries directly.

## Running Tests

### Quick Smoke Test (~30s)

Run a single ESMFold test to verify the setup:

```bash
pytest tests/acceptance/test_phase1_native_tools.py::TestESMFoldNative::test_protein \
  --sif /scout/containers/folding_prod.sif \
  --gpu-id 0 \
  --timeout 120
```

### Phase 1: Native Tools (~40 min)

Tests each tool binary directly inside the container across the protein/DNA/MSA matrix:

```bash
CUDA_VISIBLE_DEVICES=1,2,3,4 pytest tests/acceptance/test_phase1_native_tools.py \
  --sif /scout/containers/folding_prod.sif \
  --gpu-id 1,2,3,4 \
  --timeout 3600
```

### Phase 2: predict-structure CLI (~2h)

Tests the full predict-structure CLI with adapters and output normalization:

```bash
pytest tests/acceptance/ -m phase2 \
  --sif /scout/containers/folding_prod.sif \
  --gpu-id 0 \
  --timeout 3600
```

### Phase 3: Service Script + Workspace

Tests the Perl service script end-to-end with workspace upload:

```bash
pytest tests/acceptance/ -m phase3 \
  --sif /scout/containers/folding_prod.sif \
  --gpu-id 0 \
  --timeout 3600
```

### Both Containers in Parallel

Run each container on a separate GPU in separate terminals:

```bash
CUDA_VISIBLE_DEVICES=0 pytest tests/acceptance/ \
  --sif /scout/containers/folding_prod.sif --gpu-id 0 &

CUDA_VISIBLE_DEVICES=1 pytest tests/acceptance/ \
  --sif /scout/containers/all-2026-0410.01.sif --gpu-id 1 &
```

### JSON Report

Generate a machine-readable results file:

```bash
pytest tests/acceptance/ --json-report --json-report-file=results.json
```

## Test Structure

### Phase 1 -- Native Tools (`test_phase1_native_tools.py`)

Calls tool binaries directly inside the container:

- `boltz predict` -- Boltz-2
- `esm-fold-hf` -- ESMFold (HuggingFace)
- `chai-lab fold` -- Chai-1
- `run_openfold predict` -- OpenFold 3
- `run_alphafold.py` -- AlphaFold 2

No `predict-structure` CLI is involved. Tests the tool x [protein | dna] x [msa | no-msa] matrix to confirm each tool works inside the container before testing the adapter layer.

### Phase 2 -- predict-structure CLI (`test_phase2_*.py`)

Tests through `predict-structure <tool> --backend subprocess`. Covers:

- Tool x input type matrix (protein, DNA, protein+ligand, protein+MSA)
- `--debug` mode (prints command without executing)
- Entity flags (`--protein`, `--dna`, `--ligand`)
- Auto-selection logic
- Output normalization (standardized directory layout, confidence JSON)
- Batch mode
- Parameter variations (sampling steps, num samples, recycles)

### Phase 3 -- Perl Service Script (`test_phase3_*.py`)

Tests the BV-BRC service integration:

- `App-PredictStructure.pl` with params JSON files
- Preflight resource estimation (`predict-structure preflight`)
- Real workspace upload and download via `p3-cp`

## Bind Mounts

Tests automatically configure these Apptainer bind mounts:

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `test_data/` | `/data` | Test input files |
| Per-test tmp dir | `/output` | Isolated output |
| `/local_databases` | `/local_databases` | Model weights (rw for cache/) |

### Cache Environment Variables

Set inside the container to direct all caches to the shared location:

```
HF_HOME=/local_databases/cache
TORCH_HOME=/local_databases/cache
NUMBA_CACHE_DIR=/local_databases/cache/tmp
TRITON_CACHE_DIR=/local_databases/cache/tmp
```

## Adding New Tests

### Phase 1 (Native Tool Tests)

Phase 1 tests call tool binaries directly -- do not use `predict-structure`. Create the raw command line as it would be invoked inside the container, then use `ApptainerRunner.exec()` to run it. Verify output files exist and contain valid structure data.

### Phase 2 (CLI Integration Tests)

Phase 2 tests use the test matrix defined in `matrix.py` and the `ApptainerRunner.predict()` method, which invokes `predict-structure <tool>` with the appropriate flags. To add a new test case:

1. Add the input combination to the matrix in `matrix.py`
2. Mark expected failures with `pytest.mark.xfail` and a reason string
3. Use the validators in `validators.py` to check output structure and confidence scores

## Markers

| Marker | Description |
|--------|-------------|
| `phase1` | Native tool tests (no predict-structure) |
| `phase2` | predict-structure CLI tests |
| `phase3` | Perl service script + workspace tests |
| `gpu` | Requires GPU |
| `slow` | Long-running test (>5 min) |
| `container` | Requires Apptainer container |
| `workspace` | Requires BV-BRC workspace access |
