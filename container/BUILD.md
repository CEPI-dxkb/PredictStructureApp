# Building the predict-structure Container Images

> **Target audience:** Claude Code session on an **amd64 Linux host** with Docker
> and/or Apptainer installed. This document contains everything needed to build,
> verify, and troubleshoot the container images.

## Overview

There are three container images (build in order):

| # | Image | Dockerfile | Purpose |
|---|-------|-----------|---------|
| 1 | `dxkb/predict-structure:latest` | `Dockerfile.predict-structure` | Lightweight CLI-only dispatcher (~2 GB) |
| 2 | `dxkb/predict-structure-all:latest-gpu` | `Dockerfile.predict-structure-all` | All-in-one with all 4 tools (~20 GB) |
| 3 | `dxkb/predict-structure-bvbrc:latest-gpu` | `Dockerfile.predict-structure-bvbrc` | BV-BRC AppService layer on top of #2 |

Alternatively, the all-in-one image can be built directly as an Apptainer `.sif`:
- `predict-structure-all.def` — standalone Apptainer recipe

There is also a simpler Apptainer recipe that layers predict-structure onto an
**existing** BV-BRC all-in-one `.sif` (the one used in production today):
- `predict-structure.def` — layers CLI onto existing base `.sif`

## Prerequisites

- **Architecture:** amd64 (x86_64) Linux host. ARM/macOS cross-compilation
  fails on the large ML packages (torch, jax) due to QEMU OOM.
- **Docker:** 24.0+ with BuildKit enabled (default since Docker 23).
- **Disk:** ~50 GB free for build cache and final images.
- **Memory:** 16 GB+ RAM recommended (torch compilation is memory-intensive).
- **Network:** Unrestricted access to PyPI, conda-forge, pytorch.org, GitHub.
- **Apptainer** (optional): 1.2+ for building `.sif` files directly.

## Build Instructions

All commands run from the **repository root** (`PredictStructureApp/`).

### Image 1: Lightweight Dispatcher

```bash
docker build -t dxkb/predict-structure:latest \
  -f container/Dockerfile.predict-structure .
```

**Verification:**
```bash
docker run --rm dxkb/predict-structure:latest --help
docker run --rm dxkb/predict-structure:latest --version
docker run --rm dxkb/predict-structure:latest boltz --help
docker run --rm dxkb/predict-structure:latest chai --help
```

This image contains only the `predict-structure` Python CLI. It does NOT
include prediction tools. Use with `--backend docker` (delegates to per-tool
containers) or `--backend cwl`.

### Image 2: All-in-One GPU

```bash
docker build -t dxkb/predict-structure-all:latest-gpu \
  -f container/Dockerfile.predict-structure-all .
```

**Expected build time:** 30–60 minutes on a fast amd64 host.

**Verification:**
```bash
# CLI works
docker run --rm dxkb/predict-structure-all:latest-gpu --help
docker run --rm dxkb/predict-structure-all:latest-gpu --version

# Each tool executable exists
docker run --rm dxkb/predict-structure-all:latest-gpu \
  /opt/conda-boltz/bin/boltz --help
docker run --rm dxkb/predict-structure-all:latest-gpu \
  /opt/conda-chai/bin/chai-lab fold --help
docker run --rm dxkb/predict-structure-all:latest-gpu \
  /opt/conda-esmfold/bin/esm-fold-hf --help
docker run --rm dxkb/predict-structure-all:latest-gpu \
  /opt/conda-alphafold/bin/python -c "import alphafold; print('OK')"

# Debug mode (shows generated native commands)
docker run --rm dxkb/predict-structure-all:latest-gpu \
  boltz /app/predict-structure/test_data/simple_protein.fasta \
  -o /tmp/out --debug

docker run --rm dxkb/predict-structure-all:latest-gpu \
  esmfold /app/predict-structure/test_data/simple_protein.fasta \
  -o /tmp/out --debug

# Auto-discovery
docker run --rm dxkb/predict-structure-all:latest-gpu \
  auto /app/predict-structure/test_data/simple_protein.fasta \
  -o /tmp/out --debug
```

**Convert to Apptainer for HPC:**
```bash
singularity build predict-structure-all.sif \
  docker://dxkb/predict-structure-all:latest-gpu
```

### Image 3: BV-BRC Service Layer

Requires Image 2 to be built first.

```bash
docker build -t dxkb/predict-structure-bvbrc:latest-gpu \
  -f container/Dockerfile.predict-structure-bvbrc .
```

**Verification:**
```bash
# CLI entrypoint
docker run --rm dxkb/predict-structure-bvbrc:latest-gpu \
  predict-structure --help

# BV-BRC Perl runtime
docker run --rm dxkb/predict-structure-bvbrc:latest-gpu \
  perl -MBio::KBase::AppService::AppScript -e 'print "OK\n"'
```

### Alternative: Apptainer Direct Build

If you have an existing BV-BRC all-in-one `.sif` (e.g. from
`runtime_build/gpu-builds/cuda-12.2-cudnn-8.9.6/`), use the simpler recipe:

```bash
# This layers predict-structure CLI onto the existing .sif
# Edit predict-structure.def to set the correct base image path
apptainer build predict-structure.sif container/predict-structure.def
```

Or build the full all-in-one from scratch:

```bash
# Requires a base .sif from runtime_build
apptainer build predict-structure-all.sif \
  --build-arg base=/path/to/base.sif \
  --build-arg runtime=/path/to/runtime.tgz \
  --build-arg packages=/path/to/packages.txt \
  container/predict-structure-all.def
```

### Dev Workflow (bind-mount, no rebuild)

For iterating on the Python code without rebuilding the image:

```bash
# One-time: build deps into container/deps/
export PREDICT_STRUCTURE_SIF=/path/to/all-in-one.sif
./container/build-deps.sh

# Run with live code
./container/dev-run.sh --help
./container/dev-run.sh boltz input.fasta -o output/ --debug
```

## Container Layout

The all-in-one image has this structure:

```
/opt/conda-boltz/bin/boltz          # Boltz-2 (Python 3.11)
/opt/conda-chai/bin/chai-lab        # Chai-1 (Python 3.10)
/opt/conda-alphafold/bin/python     # AlphaFold 2 (Python 3.11)
/opt/conda-esmfold/bin/esm-fold-hf  # ESMFold (Python 3.11)
/opt/conda-predict/bin/predict-structure  # Unified CLI (Python 3.12)
/usr/local/bin/predict-structure    # Symlink → /opt/conda-predict/bin/
/opt/miniforge/                     # Miniforge base (conda)
/opt/hhsuite/                       # HHsuite for AlphaFold templates
/app/alphafold/                     # AlphaFold source + stereo_chemical_props
/app/predict-structure/             # predict-structure source + app_specs + CWL
```

### Runtime bind mounts

Models and databases are NOT baked into the image. Bind-mount at runtime:

```
/local_databases/boltz/      → Boltz model weights (BOLTZ_CACHE)
/local_databases/chai/       → Chai model weights (CHAI_DOWNLOADS_DIR)
/local_databases/alphafold/  → AlphaFold genetic databases (~2TB)
/local_databases/huggingface/ → HuggingFace model cache (HF_HOME)
```

Docker example:
```bash
docker run --gpus all \
  -v /data/databases:/local_databases \
  -v /data/input:/input \
  -v /data/output:/output \
  dxkb/predict-structure-all:latest-gpu \
  boltz /input/protein.fasta -o /output --use-msa-server
```

Apptainer example:
```bash
apptainer run --nv \
  --bind /data/databases:/local_databases \
  predict-structure-all.sif \
  boltz /input/protein.fasta -o /output --use-msa-server
```

## Tool Configuration

The file `predict_structure/tools.yml` maps tool names to executables, images,
and CWL definitions. The container paths match these entries:

| Tool | command | conda env |
|------|---------|-----------|
| boltz | `/opt/conda-boltz/bin/boltz predict` | Python 3.11 |
| chai | `/opt/conda-chai/bin/chai-lab fold` | Python 3.10 |
| alphafold | `/opt/conda-alphafold/bin/python /app/alphafold/run_alphafold.py` | Python 3.11 |
| esmfold | `/opt/conda-esmfold/bin/esm-fold-hf` | Python 3.11 |

## Known Issues and Fixes

### 1. Conda TOS acceptance (FIXED)

**Error:**
```
CondaError: ... To accept these channels' Terms of Service, run:
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
```

**Fix:** The Dockerfile uses Miniforge (conda-forge channel by default) instead
of Miniconda. Additionally, `CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes` is set in the
environment. If you still see this, run:
```dockerfile
ENV CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
```

### 2. ARM cross-compilation OOM (NOT FIXABLE)

**Error:** Build fails during `pip install torch` or `pip install boltz[cuda]`
with exit code 1 and no further details.

**Cause:** QEMU amd64 emulation on ARM (macOS Apple Silicon) runs out of
memory when installing large Python packages (torch ~700MB, jax ~500MB).

**Fix:** Build on a native amd64 Linux host. There is no workaround for
cross-compilation of these packages.

### 3. cuDNN symlink issues

**Error:** JAX or TensorFlow cannot find cuDNN libraries at runtime.

**Fix:** The Dockerfile creates symlinks in `/usr/lib/x86_64-linux-gnu/`:
```bash
ln -sf libcudnn.so.8.9.6 libcudnn.so.8
ln -sf libcudnn.so.8.9.6 libcudnn.so
```
This matches the BV-BRC `base-build.def` recipe.

### 4. OpenMM CUDA plugin crashes

**Error:** `import openmm` crashes due to CUDA version mismatch in OpenMM plugins.

**Fix (from BV-BRC recipe):** Remove the CUDA/OpenCL OpenMM plugins:
```bash
rm -f /opt/conda-alphafold/lib/plugins/libOpenMM*CUDA* \
      /opt/conda-alphafold/lib/plugins/libOpenMM*OpenCL*
```
OpenMM is only used for structure relaxation, not prediction.

### 5. PyTorch CUDA version mismatch

**Error:** `RuntimeError: CUDA error: no kernel image is available for execution`

**Fix:** PyTorch is installed from the cu121 index to match CUDA 12.2:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```
Do NOT install the default PyTorch (CPU-only) or cu118 variant.

## Build Ancestry

These Dockerfiles are aligned with the BV-BRC Apptainer recipes at:
https://github.com/BV-BRC/runtime_build/tree/master/gpu-builds/cuda-12.2-cudnn-8.9.6

| BV-BRC recipe | Our equivalent |
|---------------|---------------|
| `base-build.def` | Base layer in `Dockerfile.predict-structure-all` |
| `reqts-boltz.def` | Boltz stage in `Dockerfile.predict-structure-all` |
| `reqts-chai.def` | Chai stage in `Dockerfile.predict-structure-all` |
| `reqts-alphafold.def` | AlphaFold stage in `Dockerfile.predict-structure-all` |
| `all-build.def` | `predict-structure-all.def` |

ESMFold and the predict-structure CLI are additions not in the BV-BRC recipes.

## Quick Reference

```bash
# Build all three images (run in order)
docker build -t dxkb/predict-structure:latest -f container/Dockerfile.predict-structure .
docker build -t dxkb/predict-structure-all:latest-gpu -f container/Dockerfile.predict-structure-all .
docker build -t dxkb/predict-structure-bvbrc:latest-gpu -f container/Dockerfile.predict-structure-bvbrc .

# Convert to Apptainer
singularity build predict-structure-all.sif docker://dxkb/predict-structure-all:latest-gpu

# Run tests inside container
docker run --rm dxkb/predict-structure-all:latest-gpu \
  bash -c "cd /app/predict-structure && /opt/conda-predict/bin/pytest tests/ -q"

# Run debug commands script
docker run --rm dxkb/predict-structure-all:latest-gpu \
  bash /app/predict-structure/test_data/debug_commands.sh
```
