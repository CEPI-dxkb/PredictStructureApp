# Acceptance Testing Guide

## Overview

The acceptance test suite validates PredictStructureApp across three phases:

- **Phase 1 -- Native tools**: Calls tool binaries directly inside the container (no predict-structure involved). Establishes ground truth -- what each tool can do on its own.
- **Phase 2 -- predict-structure CLI**: Tests through `predict-structure <tool> --backend subprocess`. Validates adapters, entity flags, auto-selection, output normalization, and batch mode.
- **Phase 3 -- Perl service script + workspace**: Tests `App-PredictStructure.pl` with params JSON, preflight resource estimation, and real BV-BRC workspace integration.

**Total: 113 tests** (13 Phase 1 + 64 Phase 2 + 36 Phase 3)

The framework uses pytest with parametrized tests. All tests run inside Apptainer containers with GPU passthrough.

## Prerequisites

- **Apptainer** installed and available on PATH
- **GPU(s)** available (verify with `nvidia-smi`)
- **Production container** at `/scout/containers/folding_prod.sif` (symlink to latest build)
- **Model weights** at `/local_databases/`:
  - `boltz/` -- Boltz-2 weights (~50 GB)
  - `chai/` -- Chai-1 weights (~30 GB)
  - `openfold/` -- OpenFold 3 weights + `runner.yml` for H200 DeepSpeed workaround
  - `alphafold/databases/` -- AlphaFold 2 genetic databases (~2 TB for full_dbs)
  - `cache/hub/` -- HuggingFace model cache (ESMFold weights)
- **Python dev dependencies** in a conda env:
  ```bash
  conda activate predict-structure
  pip install -e ".[dev]"
  ```
- **Phase 3 workspace tests**: Valid `.patric_token` file at `~/.patric_token` (or set `PATRIC_TOKEN_PATH`)

## Container Requirements

The container must have:

| Path | Purpose |
|------|---------|
| `/opt/conda-boltz/bin/boltz` | Boltz binary |
| `/opt/conda-openfold/bin/run_openfold` | OpenFold binary |
| `/opt/conda-chai/bin/chai-lab` | Chai binary |
| `/opt/conda-alphafold/bin/python` + `/app/alphafold/run_alphafold.py` | AlphaFold |
| `/opt/conda-esmfold/bin/esm-fold-hf` | ESMFold binary |
| `/opt/conda-predict/bin/predict-structure` | Unified CLI |
| `/kb/module/service-scripts/App-PredictStructure.pl` | BV-BRC service (Phase 3 only) |
| `/opt/patric-common/runtime` + `/opt/patric-common/deployment` | BV-BRC Perl runtime (Phase 3) |

## Configuration

### Container Selection

Choose which container to test using one of these methods:

1. `--sif` flag: full path to the `.sif` file
2. `PREDICT_STRUCTURE_SIF` environment variable
3. `--container-label prod` to use `/scout/containers/folding_prod.sif`

### GPU Pinning

Use `--gpu-id` flag or `CUDA_VISIBLE_DEVICES` environment variable.
**Critical for AlphaFold** -- JAX will claim all visible GPUs unless explicitly constrained.

Accepts single GPU (`--gpu-id 0`) or multiple (`--gpu-id 0,1,2,3`).

### Dev Code Overlay

The test framework mounts the local `predict_structure/` package at `/mnt/predict-structure` inside the container and prepends it to `PYTHONPATH`. This lets you test code changes without rebuilding the container.

**Note:** We previously bind-mounted directly over `/opt/conda-predict/lib/python3.12/site-packages/predict_structure/`, but that broke JIT compilation in other conda envs (numba/Boltz, triton/OpenFold). The PYTHONPATH approach avoids that interference.

## Running Tests

### Quick Smoke (~30 s)

```bash
PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest \
  tests/acceptance/test_phase1_native_tools.py::TestESMFoldNative::test_protein \
  --gpu-id 0 --timeout 120 -v
```

### Phase 1 -- Native Tools (~40 min)

Tests all 5 tools directly. AlphaFold alone takes ~26 min.

```bash
CUDA_VISIBLE_DEVICES=0,1,2,3 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/test_phase1_native_tools.py \
  --gpu-id 0,1,2,3 --timeout 3600 -v \
  --json-report --json-report-file=output/phase1.json
```

### Phase 2 -- predict-structure CLI (~2 h with AlphaFold, ~10 min without)

```bash
# Skip slow tests (AlphaFold multimer) for faster iteration
CUDA_VISIBLE_DEVICES=0 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/ -m "phase2 and not slow" \
  --gpu-id 0 --timeout 3600 -v \
  --json-report --json-report-file=output/phase2.json

# Full Phase 2 including slow tests
CUDA_VISIBLE_DEVICES=0,1,2,3 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/ -m phase2 \
  --gpu-id 0,1,2,3 --timeout 7200 -v \
  --json-report --json-report-file=output/phase2.json
```

### Phase 3 -- Service Script + Workspace

Requires `.patric_token` for workspace tests. Tests without a token will skip gracefully.

```bash
CUDA_VISIBLE_DEVICES=0 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/ -m phase3 \
  --gpu-id 0 --timeout 3600 -v \
  --json-report --json-report-file=output/phase3.json
```

**Two modes for `test_phase3_workspace.py`:**

| Mode | When to use | How |
|------|-------------|-----|
| **Baked-in** (default) | Acceptance / regression testing a new container build before release -- exercises the Perl and app_spec frozen into the SIF | no env var |
| **Dev overlay** | Iterating on `service-scripts/App-PredictStructure.pl` or `app_specs/PredictStructure.json` without rebuilding the SIF | `PREDICT_STRUCTURE_DEV_SERVICE=1` |

```bash
# Dev iteration: overlay the host's service-scripts/ and app_specs/
PREDICT_STRUCTURE_DEV_SERVICE=1 \
CUDA_VISIBLE_DEVICES=0 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/test_phase3_workspace.py -v
```

If a Phase 3 test passes only with the overlay, the fix still needs to land
in the container image before the build is release-ready.

**Workspace layout.** Tests write under
`<user-home>/AppTests/<tool>/<testname>-<YYYYMMDD-HHMMSS>/` -- the timestamped
leaf is the "versioned output_path" the service script uploads into. Tests
clean up their own sub-folder on completion.

```
<user-home>/AppTests/
├── _inputs/                              ← staging for test input FASTAs
│   └── <testname>-<ts>-simple_protein.fasta
├── misc/    upload_and_verify-<ts>/      ← raw upload test scratch
├── esmfold/ workspace_roundtrip-<ts>/    ← service-script output
│   └── model_1.pdb, model_1.cif, confidence.json, metadata.json, ...
└── chai/    report_workspace_roundtrip-<ts>/
    └── model_1.pdb, model_1.cif, confidence.json, metadata.json,
        report.html, report.json, report.pdf, raw/, raw_output/
```

Test inputs are staged in `_inputs/` (sibling folder) rather than inside the
output dir. This keeps the output dir fresh so `p3-cp -r` lands files at the
top level instead of nesting under `output/` (p3-cp's behavior when the
target already exists).

**Two file layouts in Phase 3:**

| File | Scope |
|------|-------|
| `test_phase3_workspace.py` | Pure workspace ops (`p3-whoami`, `p3-ls`, `p3-cp`) |
| `test_phase3_appscript_workspace.py` | Service script + workspace end-to-end roundtrips |
| `test_phase3_service_script.py` | Service script offline (no workspace I/O) |

**Phase-3 env var toggles:**

| Env var | Effect |
|---------|--------|
| `PREDICT_STRUCTURE_DEV_SERVICE=1` | Overlay host's `service-scripts/` + `app_specs/` into the SIF (see table above) |
| `PREDICT_STRUCTURE_KEEP_WORKSPACE=1` | Skip post-test `p3-rm`; each test prints the kept path |
| `P3_DEBUG_RUN_SUBFOLDER=1` | (service script) Nest results under a per-run subfolder `predict_structure_result_<ts>_<task_id>/`. Default is flat -- results land directly in `output_path`. Useful when multiple runs share one `output_path`. |

Example -- investigate artifacts after a failing Chai run:

```bash
PREDICT_STRUCTURE_DEV_SERVICE=1 PREDICT_STRUCTURE_KEEP_WORKSPACE=1 \
CUDA_VISIBLE_DEVICES=0 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest \
  tests/acceptance/test_phase3_appscript_workspace.py -v -s
# Then:
# p3-ls -l /<user>@bvbrc/home/AppTests/chai/report_workspace_roundtrip-<ts>/
```

### Full Suite on Both Containers in Parallel

Each container on separate GPUs (requires enough GPUs):

```bash
# Container 1 on GPUs 0-3
CUDA_VISIBLE_DEVICES=0,1,2,3 PREDICT_STRUCTURE_SIF=/scout/containers/folding_prod.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/ \
  --gpu-id 0,1,2,3 --timeout 7200 -v \
  --json-report --json-report-file=output/full_prod.json &

# Container 2 on GPUs 4-7
CUDA_VISIBLE_DEVICES=4,5,6,7 PREDICT_STRUCTURE_SIF=/scout/containers/all-2026-0410.01.sif \
  conda run -n predict-structure python -m pytest tests/acceptance/ \
  --gpu-id 4,5,6,7 --timeout 7200 -v \
  --json-report --json-report-file=output/full_all.json &
```

## Test Structure

### Phase 1 -- Native Tools (`test_phase1_native_tools.py`)

Calls tool binaries directly -- no `predict-structure` CLI. Tests the
tool x [protein | dna] x [msa | no-msa] matrix.

13 tests: Boltz (4), Chai (3), OpenFold (3), AlphaFold (1), ESMFold (2).

### Phase 2 -- predict-structure CLI (`test_phase2_*.py`)

Tests through `predict-structure <tool> --backend subprocess`:

- Tool x input type matrix (from `matrix.py`)
- `--debug` mode (prints command without executing)
- Entity flags (`--protein`, `--dna`, `--ligand`, `--smiles`)
- Auto-selection logic with real tools
- Output normalization (standardized directory layout, confidence JSON)
- Batch mode (`--job spec.yaml`)
- Parameter variations (sampling steps, num samples, recycles)

### Phase 3 -- Perl Service Script (`test_phase3_*.py`)

Tests the BV-BRC service integration:

- `App-PredictStructure.pl` with `params_*.json` files
- `predict-structure preflight` resource estimation
- Real workspace upload/download via `p3-cp` (requires token)

## Bind Mounts

Tests automatically configure these Apptainer bind mounts:

| Host Path | Container Path | Mode | Purpose |
|-----------|----------------|------|---------|
| `test_data/` | `/data` | rw | Test input files |
| Per-test tmp dir | `/output` | rw | Isolated output |
| `/local_databases` | `/local_databases` | rw | Model weights + cache (cache dir needs writes) |
| Repo root | `/mnt/predict-structure` | rw | Dev code via PYTHONPATH |

### Cache Environment Variables

Set inside the container to direct all writable caches to the shared location:

```
HF_HOME=/local_databases/cache
HF_DATASETS_CACHE=/local_databases/cache
TRANSFORMERS_CACHE=/local_databases/cache
TORCH_HOME=/local_databases/cache
XDG_CACHE_HOME=/local_databases/cache/tmp
TRITON_CACHE_DIR=/local_databases/cache/tmp
NUMBA_CACHE_DIR=/local_databases/cache/tmp
PYTHONPATH=/mnt/predict-structure
```

## Results

Results are written to `tests/acceptance/RESULTS.md`. JSON reports go to `output/*.json`.

Latest results (2026-04-17): 101/113 pass on `folding_260412.1.sif`.
Remaining failures:
- 4x OpenFold normalizer (per-atom vs per-residue pLDDT count)
- 1x OpenFold precomputed MSA input format
- 2x workspace minor issues (UTF-8 decode, upload listing)

## Adding New Tests

### Phase 1 (Native Tool Tests)

Call tool binaries directly -- do not use `predict-structure`. Prepare input
in the tool's native format (YAML for Boltz, FASTA for Chai/ESMFold, JSON for
OpenFold), then use `ApptainerRunner.exec()` to run it. Verify output files.

### Phase 2 (CLI Integration Tests)

Use the test matrix in `tests/acceptance/matrix.py` and `ApptainerRunner.predict()`.
To add a new test case:

1. Add a `ToolTestCase` to the matrix in `matrix.py`
2. Mark expected failures with `xfail_reason`
3. Use `validators.assert_valid_output()` to check normalized output

## Markers

| Marker | Description |
|--------|-------------|
| `phase1` | Native tool tests (no predict-structure) |
| `phase2` | predict-structure CLI tests |
| `phase3` | Perl service script + workspace tests |
| `gpu` | Requires GPU |
| `slow` | Long-running test (>5 min, e.g. AlphaFold multimer) |
| `container` | Requires Apptainer container |
| `workspace` | Requires BV-BRC workspace access |

## Troubleshooting

### Tests skip with "SIF not found"

Check the container path exists and is readable:
```bash
ls -la $PREDICT_STRUCTURE_SIF
```

### OpenFold fails with "Unable to JIT load the evoformer_attn op"

H200 GPUs don't support the DeepSpeed evo_attention kernel. Ensure
`/local_databases/openfold/runner.yml` exists with:
```yaml
model_update:
  custom:
    settings:
      memory:
        eval:
          use_deepspeed_evo_attention: false
```
The adapter auto-resolves this file when present.

### AlphaFold grabs all 8 GPUs

JAX default behavior. Always pass `--gpu-id <N>` (or `CUDA_VISIBLE_DEVICES=<N>`)
to pin to a specific device. The test framework injects this into the container
via `--env`.

### Container extraction fails with "unpackSIF failed / set_attributes"

Large SIF files with files owned by non-root UIDs hit fakeroot uid/gid
mapping limits. Workaround: use a writable overlay instead of rebuilding:
```bash
apptainer overlay create --size 8192 overlay.img
apptainer exec --overlay overlay.img base.sif bash -c 'pip install ...'
```

### Workspace tests error instead of skip

The fixture uses `pytest.skip` when `~/.patric_token` is missing. If you see
errors instead of skips, check that the fixture is being called (`-rs` flag
shows skip reasons).

### Boltz fails with "Missing MSA's in input"

Protein chains need an explicit `msa` field. Our converter sets `msa: empty`
when no MSA file is provided (single-sequence mode). If testing native Boltz
directly, either provide an MSA file or use `msa: empty` in the YAML.

## Container Build

The folding container is built in stages using apptainer definition files
from the `runtime_build` repository. Set `RUNTIME_BUILD` to its
`gpu-builds/cuda-12.2-cudnn-8.9.6/` directory (layout identical across
checkouts):

```bash
export RUNTIME_BUILD=<path-to-runtime_build>/gpu-builds/cuda-12.2-cudnn-8.9.6
```

Stages:

1. `base-build.def` -- CUDA + cuDNN + miniforge
2. `reqts-boltz.def` -- Boltz 2
3. `reqts-chai.def` -- Chai 1
4. `reqts-alphafold.def` -- AlphaFold 2
5. `reqts-openfold.def` -- OpenFold 3
6. `reqts-esmfold.def` -- ESMFold
7. `reqts-predict-structure.def` -- predict-structure CLI (from GitHub)
8. `reqts-bvbrc-service.def` -- BV-BRC AppService layer (final production SIF)

### Build Flags

Two flags are required when the build user is **not** in `/etc/subuid` /
`/etc/subgid`:

```bash
--fakeroot                      # required for %post script
APPTAINER_TMPDIR=<big-scratch>  # /tmp is often a small tmpfs (e.g. 50GB) and
                                # can't hold a 30GB+ SIF extraction
```

Pick `APPTAINER_TMPDIR` to point at a filesystem with at least ~1.5x the
base SIF size free.

### Build Command Template

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

### Example Build (folding_260422.1.sif)

Built from `base-gpu.2026-04-22.002.sif` via `reqts-bvbrc-service.def`:

```bash
APPTAINER_TMPDIR=$APPTAINER_TMPDIR apptainer build --fakeroot \
  --build-arg base=<containers-dir>/base-gpu.2026-04-22.002.sif \
  --build-arg app_repo=https://github.com/CEPI-dxkb/PredictStructureApp.git \
  <containers-dir>/folding_260422.1.sif \
  $RUNTIME_BUILD/reqts-bvbrc-service.def
```

Note: This installs predict-structure from GitHub **main** branch. To pick up
fixes from the `acceptance-testing` branch, modify `reqts-predict-structure.def`
and `reqts-bvbrc-service.def` to use:

```
pip install "predict-structure[cwl] @ git+https://github.com/CEPI-dxkb/PredictStructureApp.git@acceptance-testing"
```

Or install from a local path during build by bind-mounting the repo.

### Known Build Issue: /etc/subuid

Without a `/etc/subuid` entry for the build user, apptainer falls back to
"root-mapped namespace" and cannot handle files owned by non-root UIDs in
the base SIF, producing errors like:

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
