# Container Build

How to build the production folding SIFs (`folding_YYMMDD.N.sif`) used
for acceptance testing and BV-BRC deployment.

## Overview

The folding container is built in stages using apptainer definition
files from the `runtime_build` repository. Set `RUNTIME_BUILD` to its
`gpu-builds/cuda-12.2-cudnn-8.9.6/` directory (layout identical across
checkouts):

```bash
export RUNTIME_BUILD=<path-to-runtime_build>/gpu-builds/cuda-12.2-cudnn-8.9.6
```

## Stages

1. `base-build.def` -- CUDA + cuDNN + miniforge
2. `reqts-boltz.def` -- Boltz 2
3. `reqts-chai.def` -- Chai 1
4. `reqts-alphafold.def` -- AlphaFold 2
5. `reqts-openfold.def` -- OpenFold 3
6. `reqts-esmfold.def` -- ESMFold
7. `reqts-predict-structure.def` -- predict-structure CLI (from GitHub)
8. `reqts-bvbrc-service.def` -- BV-BRC AppService layer (final production SIF)

## Build flags

Two flags are required when the build user is **not** in `/etc/subuid` /
`/etc/subgid`:

```bash
--fakeroot                      # required for %post script
APPTAINER_TMPDIR=<big-scratch>  # /tmp is often a small tmpfs (~50GB) and
                                # can't hold a 30GB+ SIF extraction
```

Pick `APPTAINER_TMPDIR` to point at a filesystem with at least ~1.5x the
base SIF size free.

## Build command template

```bash
APPTAINER_TMPDIR=$APPTAINER_TMPDIR apptainer build --fakeroot \
  --build-arg base=<previous_stage>.sif \
  <output>.sif \
  $RUNTIME_BUILD/reqts-<tool>.def
```

For the BV-BRC service layer (final stage), add `app_repo`:

```bash
APPTAINER_TMPDIR=$APPTAINER_TMPDIR apptainer build --fakeroot \
  --build-arg base=<containers-dir>/base-gpu.YYYY-MM-DD.NNN.sif \
  --build-arg app_repo=https://github.com/CEPI-dxkb/PredictStructureApp.git \
  <containers-dir>/folding_YYMMDD.N.sif \
  $RUNTIME_BUILD/reqts-bvbrc-service.def
```

## Example: `folding_260425.1.sif`

Built from `base-gpu.2026-04-25.001.sif` via `reqts-bvbrc-service.def`:

```bash
APPTAINER_TMPDIR=$APPTAINER_TMPDIR apptainer build --fakeroot \
  --build-arg base=<containers-dir>/base-gpu.2026-04-25.001.sif \
  --build-arg app_repo=https://github.com/CEPI-dxkb/PredictStructureApp.git \
  <containers-dir>/folding_260425.1.sif \
  $RUNTIME_BUILD/reqts-bvbrc-service.def
```

The `app_repo` arg installs predict-structure from GitHub **main**. To
pick up fixes from a feature branch, modify
`reqts-predict-structure.def` and `reqts-bvbrc-service.def` to use:

```
pip install "predict-structure[all] @ git+https://github.com/CEPI-dxkb/PredictStructureApp.git@<branch>"
```

Or install from a local path during build by bind-mounting the repo.

## Known build issue: `/etc/subuid`

Without a `/etc/subuid` entry for the build user, apptainer falls back
to "root-mapped namespace" and cannot handle files owned by non-root
UIDs in the base SIF, producing errors like:

```
INFO:    User not listed in /etc/subuid, trying root-mapped namespace
set_attributes: failed to change uid and gids on ...because Invalid argument
ERROR:   unpackSIF failed: root filesystem extraction failed
FATAL:   While performing build: packer failed to pack
```

Workarounds:

- Have sysadmin add user to `/etc/subuid` and `/etc/subgid`
- Use `--fakeroot` explicitly (does not fully resolve, but helps in some cases)
- Use a writable overlay: `apptainer overlay create --size 50000 overlay.img`
  then `apptainer exec --overlay overlay.img base.sif <install commands>`

## Verifying a build

After building, sanity-check the resulting SIF:

```bash
SIF=<containers-dir>/folding_YYMMDD.N.sif

# All five tool CLIs present?
apptainer exec $SIF /opt/conda-boltz/bin/boltz --version
apptainer exec $SIF /opt/conda-chai/bin/chai-lab --help | head -5
apptainer exec $SIF /opt/conda-openfold/bin/run_openfold --help | head -5
apptainer exec $SIF /opt/conda-esmfold/bin/esm-fold-hf --version
apptainer exec $SIF /opt/conda-alphafold/bin/python -c "import alphafold"

# Unified CLI + provenance dep present?
apptainer exec $SIF /opt/conda-predict/bin/predict-structure --version
apptainer exec $SIF /opt/conda-predict/bin/predict-structure finalize-results --help
apptainer exec $SIF /opt/conda-predict/bin/python -c "import rocrate; print(rocrate.__version__)"

# Service script + Perl runtime present?
apptainer exec $SIF perl -c /kb/module/service-scripts/App-PredictStructure.pl
```

If `finalize-results` is missing or `rocrate` import fails, the SIF is
behind on the `predict-structure` package -- rebuild with the latest
`main`.

Then run the full T1-T5 acceptance sweep against it
(see `docs/ACCEPTANCE_TESTING.md`).
