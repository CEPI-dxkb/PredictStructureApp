# Acceptance Testing Guide

## Overview

The acceptance test suite validates PredictStructureApp across three phases:

- **Phase 1 -- Native tools**: Calls tool binaries directly inside the
  container (no `predict-structure` involved). Establishes ground truth
  -- what each tool can do on its own.
- **Phase 2 -- predict-structure CLI**: Tests through
  `predict-structure <tool> --backend subprocess`. Validates adapters,
  entity flags, auto-selection, output normalization, batch mode, and
  the **T1-T5 tier ladder** in `--debug` mode.
- **Phase 3 -- Perl service script + workspace**: Tests
  `App-PredictStructure.pl` with params JSON, preflight resource
  estimation, real BV-BRC workspace integration, and the full T1-T5
  tier ladder end-to-end through the BV-BRC AppScript framework.

Plus several cross-cutting suites:

- **`test_layout_parity.py`** -- proves the BV-BRC app-script and CWL
  workflow produce the identical output tree.
- **`test_provenance_cli.py`** -- exercises `finalize-results` and
  `aggregate-results` standalone.
- **`test_provenance_validation.py`** -- validates `ro-crate-metadata.json`
  against the Process Run Crate spec.
- **`test_cwl_workflow_execution.py`** -- runs the CWL workflow
  end-to-end via `cwltool`.
- **`test_failure_modes.py`** -- fault-injects to verify graceful
  failure handling.

**Currently 175 acceptance tests collected.** See
`docs/TEST_COVERAGE.md` for the full per-tier validation matrix.

## Prerequisites

- **Apptainer** installed and on `PATH`
- **GPU(s)** available (verify with `nvidia-smi`)
- **Production container**: `/scout/containers/folding_260425.1.sif`
  (most-recently-validated build) or a newer SIF
- **Model weights** at `/local_databases/`:
  - `boltz/` -- Boltz-2 weights (~50 GB)
  - `chai/` -- Chai-1 weights (~30 GB)
  - `openfold/` -- OpenFold 3 weights + `runner.yml` for H200 DeepSpeed workaround
  - `alphafold/databases/` -- AlphaFold 2 genetic databases (~2 TB for full_dbs)
  - `cache/hub/` -- HuggingFace model cache (ESMFold weights)
- **Python dev env**:
  ```bash
  conda activate predict-structure
  pip install -e ".[all]"   # includes [dev] + [provenance] + [cwl] + [esmfold]
  ```
- **Phase 3 workspace tests**: Valid `.patric_token` at `~/.patric_token`
  (or set `PATRIC_TOKEN_PATH`).

## Container Requirements

| Path | Purpose |
|------|---------|
| `/opt/conda-boltz/bin/boltz` | Boltz binary |
| `/opt/conda-openfold/bin/run_openfold` | OpenFold binary |
| `/opt/conda-chai/bin/chai-lab` | Chai binary |
| `/opt/conda-alphafold/bin/python` + `/app/alphafold/run_alphafold.py` | AlphaFold |
| `/opt/conda-esmfold/bin/esm-fold-hf` | ESMFold binary |
| `/opt/conda-predict/bin/predict-structure` | Unified CLI (must include `finalize-results` subcommand) |
| `/opt/conda-predict/bin/python` with `rocrate` | RO-Crate provenance |
| `/kb/module/service-scripts/App-PredictStructure.pl` | BV-BRC service (Phase 3 only) |
| `/opt/patric-common/runtime` + `/opt/patric-common/deployment` | BV-BRC Perl runtime (Phase 3) |

For container build instructions see [`docs/CONTAINER_BUILD.md`](CONTAINER_BUILD.md).
For invoking the CWL workflows directly (cwltool / GoWe) see
[`docs/CWL_WORKFLOWS.md`](CWL_WORKFLOWS.md).

## Configuration

### Container selection

Pick the SIF via one of:

1. `--sif` flag: full path to the `.sif`
2. `PREDICT_STRUCTURE_SIF` env var
3. `--container-label prod` to use `/scout/containers/folding_prod.sif`

### GPU pinning

Use `--gpu-id` or `CUDA_VISIBLE_DEVICES`. **Critical for AlphaFold** --
JAX claims all visible GPUs unless explicitly constrained.

Single (`--gpu-id 0`) or multiple (`--gpu-id 0,1,2,3`).

### Dev code overlay

The framework mounts the local `predict_structure/` package at
`/mnt/predict-structure` and prepends to `PYTHONPATH`. Lets you test
source changes without rebuilding the container.

We previously bind-mounted directly over `/opt/conda-predict/lib/...`,
but that broke JIT compilation in other conda envs (numba/Boltz,
triton/OpenFold). The PYTHONPATH approach avoids that.

**To validate the SIF as-shipped** (no overlay) -- useful for release
acceptance to catch staleness in the bundled `predict-structure`
package -- set `PREDICT_STRUCTURE_NO_DEV_OVERLAY=1`:

```bash
# Test the SIF exactly as it will run in production
PREDICT_STRUCTURE_NO_DEV_OVERLAY=1 \
  pytest tests/acceptance/ -m tier1 --sif $SIF
```

Same shape as `PREDICT_STRUCTURE_DEV_SERVICE` (Perl + app_specs
overlay). Default is overlay-on, matching the dev-iteration workflow.

## Running tests

### Quick smoke (~30 s)

```bash
PREDICT_STRUCTURE_SIF=/scout/containers/folding_260425.1.sif \
  conda run -n predict-structure python -m pytest \
  tests/acceptance/test_phase1_native_tools.py::TestESMFoldNative::test_protein \
  --gpu-id 0 --timeout 120 -v
```

### Tier ladder (recommended primary entry point)

```bash
SIF=/scout/containers/folding_260425.1.sif

# Smoke -- small protein, fast feedback (~6 min)
pytest tests/acceptance/ -m "tier1 and not slow" --sif $SIF -v

# Functional medium protein (~5 min)
pytest tests/acceptance/ -m tier2 --sif $SIF --timeout 3600

# Multi-entity coverage (protein + DNA via text_input) (~4 min)
pytest tests/acceptance/ -m tier3 --sif $SIF --timeout 3600

# Multimer (~5 min)
pytest tests/acceptance/ -m tier4 --sif $SIF --timeout 3600

# Large scaling check (~5 min on H200)
pytest tests/acceptance/ -m tier5 --sif $SIF --timeout 7200

# Full T1-T5 sweep (~25 min total)
pytest tests/acceptance/ -m "tier1 or tier2 or tier3 or tier4 or tier5" --sif $SIF
```

### Phase-scoped runs

```bash
SIF=/scout/containers/folding_260425.1.sif

# Phase 1 native tools (~40 min, includes AlphaFold)
pytest tests/acceptance/test_phase1_native_tools.py --sif $SIF \
  --gpu-id 0,1,2,3 --timeout 3600 -v

# Phase 2 CLI integration (skip slow AlphaFold for fast iteration)
pytest tests/acceptance/ -m "phase2 and not slow" --sif $SIF --gpu-id 0 -v

# Phase 3 service script + workspace (requires .patric_token)
pytest tests/acceptance/ -m phase3 --sif $SIF --gpu-id 0 --timeout 3600 -v
```

### Phase 3 modes (baked-in vs dev overlay)

| Mode | When to use | How |
|------|-------------|-----|
| **Baked-in** (default) | Acceptance / regression-testing a new SIF before release -- exercises the Perl + app_spec frozen into the SIF | no env var |
| **Dev overlay** | Iterating on `service-scripts/App-PredictStructure.pl` or `app_specs/PredictStructure.json` without rebuilding the SIF | `PREDICT_STRUCTURE_DEV_SERVICE=1` |

```bash
# Dev iteration -- overlay host's service-scripts/ and app_specs/
PREDICT_STRUCTURE_DEV_SERVICE=1 \
  pytest tests/acceptance/test_phase3_appscript_workspace.py --sif $SIF -v
```

If a Phase 3 test passes only with the overlay, the fix still needs to
land in the container before the build is release-ready.

### Test runtime extraction

The suite records every test's call-phase duration in
`output/test_runtimes.json` (default; override with `--runtime-out` or
`PREDICT_STRUCTURE_RUNTIME_OUT`). The JSON has per-test entries plus
per-tier aggregates (count, total, mean, p50, p95, max).

```bash
pytest tests/acceptance/ -m tier1 --sif $SIF --runtime-out output/tier1.json
python scripts/runtime_summary.py --in output/tier1.json --top 10

# Built-in pytest "top-N" alternative
pytest tests/acceptance/ -m tier1 --sif $SIF --durations=20

# Full per-test JSON via pytest-json-report (in dev extras)
pytest tests/acceptance/ -m tier1 --sif $SIF \
  --json-report --json-report-file=output/tier1.full.json
```

### Observed wall-clock (folding_260425.1.sif, H200 NVL)

| Tier slice | Tests | Wall-clock |
|---|---|---|
| `tier1 and not slow` | 21 | 5m54s |
| `tier2` (full) | 9 | 4m57s |
| `tier3` | 6 | 4m07s |
| `tier4` | 9 | 4m55s |
| `tier5` | 8 | 4m57s |
| **Full T1-T5 sweep** | **53** | **~25 min** |

Per-tool service-script runs (the bulk of each tier's time):

| Tier | Fixture | ESMFold | Boltz | Chai | OpenFold |
|---|---|---|---|---|---|
| T1 | crambin (46 aa) | 38s | (slow only) | (slow only) | (slow only) |
| T2 | 1AKE (214 aa + MSA) | 44s | 1m03s | 1m12s | 1m49s |
| T3 | crambin + DNA (text_input) | n/a | 1m07s | 1m09s | 1m45s |
| T4 | multimer (2 chains × 25 aa) | 38s | 1m02s | 1m23s | 1m45s |
| T5 | enolase (434 aa + deep MSA) | n/a | 1m13s | 1m31s | 2m05s |

ESMFold + AlphaFold are excluded from T3/T5 service-script tests by
design (ESMFold has no service-script multi-entity surface; AlphaFold
builds its own MSAs from databases).

### Combine markers

```bash
# Phase 2 tier 1 -- fast adapter-layer regression
pytest tests/acceptance/ -m "phase2 and tier1" --sif $SIF

# Everything except the slowest tier
pytest tests/acceptance/ -m "not tier5" --sif $SIF
```

### Fixtures by tier

| Tier | Fixture | Size | MSA |
|---|---|---|---|
| `tier1` | `simple_protein.fasta` (crambin) | 46 aa | `crambin.a3m` |
| `tier2` | `medium_protein.fasta` (1AKE adenylate kinase) | 214 aa | `medium_protein.a3m` |
| `tier3` | `simple_protein.fasta` + `--ligand ATP` (Phase 2) / `text_input` protein+DNA (Phase 3) | 46+ | `crambin.a3m` (Phase 2) / none (Phase 3) |
| `tier4` | `multimer.fasta` | 2 chains | none |
| `tier5` | `large_protein.fasta` (yeast enolase) | 434 aa | `large_protein.a3m` |

The `medium_protein.a3m` and `large_protein.a3m` fixtures are generated
once via `scripts/generate_test_msas.sh` (uses ColabFold MSA server)
and committed. Phase-3 service-script tier files
(`test_data/service_params/tier{N}_{tool}.json`) and Q/A specs
(`tier{N}_{tool}.expected.json`) are auto-generated by
`scripts/generate_service_params.py`; rerun with `--check` to detect
drift in CI.

### Workspace layout

Phase 3 tests write under
`<user-home>/AppTests/<tool>/<testname>-<YYYYMMDD-HHMMSS>-<uuid8>/` --
the timestamped+random leaf is the "versioned output_path" the service
script uploads into. Tests clean up their own sub-folder on completion.

```
<user-home>/AppTests/
├── _inputs/                              ← staging for test input FASTAs
│   └── <testname>-<ts>-<uuid>-simple_protein.fasta
├── misc/    upload_and_verify-<ts>/      ← raw upload test scratch
├── esmfold/ workspace_roundtrip-<ts>/    ← service-script output
│   └── model_1.pdb, model_1.cif, confidence.json, metadata.json,
│       results.json, ro-crate-metadata.json, raw/
└── chai/    report_workspace_roundtrip-<ts>/
    └── (same as above) + report/{report.html, report.json, report.pdf}
```

Inputs stage in `_inputs/` (sibling folder), NOT inside the output
dir. This keeps the output dir fresh so `p3-cp -r` lands files at the
top level instead of nesting under `output/` (p3-cp's behavior when
the target already exists).

### Phase 3 file layouts

| File | Scope |
|------|-------|
| `test_phase3_workspace.py` | Pure workspace ops (`p3-whoami`, `p3-ls`, `p3-cp`) |
| `test_phase3_appscript_workspace.py` | Service script + workspace end-to-end roundtrips |
| `test_phase3_service_script.py` | Service script offline (no workspace I/O); includes T1-T5 tier coverage |
| `test_phase3_preflight.py` | Preflight resource estimation |

### Phase-3 env var toggles

| Env var | Effect |
|---------|--------|
| `PREDICT_STRUCTURE_DEV_SERVICE=1` | Overlay host's `service-scripts/` + `app_specs/` into the SIF |
| `PREDICT_STRUCTURE_NO_DEV_OVERLAY=1` | Disable the default `predict_structure/` Python overlay -- test the SIF as-shipped (release acceptance mode) |
| `PREDICT_STRUCTURE_KEEP_WORKSPACE=1` | Skip post-test `p3-rm`; each test prints the kept path |
| `P3_DEBUG_RUN_SUBFOLDER=1` | (service script) Nest results under a per-run subfolder. Default is flat -- results land directly in `output_path` |

Example -- investigate artifacts after a failing Chai run:

```bash
PREDICT_STRUCTURE_DEV_SERVICE=1 PREDICT_STRUCTURE_KEEP_WORKSPACE=1 \
CUDA_VISIBLE_DEVICES=0 PREDICT_STRUCTURE_SIF=$SIF \
  pytest tests/acceptance/test_phase3_appscript_workspace.py -v -s
# Then:
# p3-ls -l /<user>@bvbrc/home/AppTests/chai/report_workspace_roundtrip-<ts>-<uuid>/
```

## Bind mounts

Tests automatically configure these Apptainer binds:

| Host path | Container path | Mode | Purpose |
|---|---|---|---|
| `test_data/` | `/data` | rw | Test input files |
| Per-test tmp dir | `/output` | rw | Isolated output |
| `/local_databases` | `/local_databases` | rw | Model weights + cache |
| Repo root | `/mnt/predict-structure` | rw | Dev code via PYTHONPATH |
| `service-scripts/` | `/kb/module/service-scripts` | rw | Only when `PREDICT_STRUCTURE_DEV_SERVICE=1` |

### Cache env vars set in-container

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

## Validation status

See [`docs/TEST_COVERAGE.md`](TEST_COVERAGE.md) for the latest
end-to-end validation matrix and rating.

## Markers

| Marker | Description |
|--------|-------------|
| `phase1` | Native tool tests (no predict-structure) |
| `phase2` | predict-structure CLI tests |
| `phase3` | Perl service script + workspace tests |
| `tier1` | Smoke -- small protein (crambin, 46 aa), every tool, every layer |
| `tier2` | Functional -- medium protein (~214 aa), full pipeline |
| `tier3` | Multi-entity -- protein + ligand/DNA/RNA |
| `tier4` | Multimer -- multi-chain protein |
| `tier5` | Large -- ~434 aa, scaling regression (gated `slow`) |
| `gpu` | Requires GPU |
| `slow` | Long-running test (>5 min, e.g. AlphaFold) |
| `container` | Requires Apptainer container |
| `workspace` | Requires BV-BRC workspace access |
| `cwl` | CWL validation tests |
| `docker` | Requires Docker daemon |

## Troubleshooting

### "SIF not found"

```bash
ls -la $PREDICT_STRUCTURE_SIF
```

### OpenFold "Unable to JIT load the evoformer_attn op"

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

JAX default behavior. Always pass `--gpu-id <N>` (or `CUDA_VISIBLE_DEVICES`)
to pin to a specific device.

### Workspace tests error instead of skip

The fixture uses `pytest.skip` when `~/.patric_token` is missing. If
you see errors instead of skips, run with `-rs` to inspect the skip
reason.

### Boltz "Missing MSA's in input"

Protein chains need an explicit `msa` field. The Boltz adapter sets
`msa: empty` for single-sequence mode. If testing native Boltz
directly, either provide an MSA file or use `msa: empty` in the YAML.

### Tests pass but no real prediction ran

The BV-BRC AppScript framework returns exit 0 even when the Perl
`die`s. The Phase 3 service-script tests defend against this by
asserting `model_1.pdb` exists post-run. If you see a service-script
test pass in <1 second, that's the symptom. Check the `_finalize_output`
contract in the helper.

## Adding new tests

### Phase 1 (native tool tests)

Call tool binaries directly. Prepare input in the tool's native format
(YAML for Boltz, FASTA for Chai/ESMFold, JSON for OpenFold), then use
`ApptainerRunner.exec()`. Verify output files.

### Phase 2 (CLI integration tests)

Use the test matrix in `tests/acceptance/matrix.py` and
`ApptainerRunner.predict()`:

1. Add a `ToolTestCase` to the matrix.
2. Mark expected failures with `xfail_reason`.
3. Use `validators.assert_valid_output()` to check normalized output.

For tier-aware tests, parametrize over `(tool, tier)` using
`ALL_TIERS` + `tier_supported_for_tool` + `msa_args_for` from
`matrix.py` (see `TestTierCoverage` for a template).

### Phase 3 (service script tests)

Add params + expected JSON via `scripts/generate_service_params.py`
(it writes both the input and the Q/A `.expected.json`). External
testing frameworks consume the Q/A files via `scripts/run_qa_case.py`
-- see `test_data/service_params/README.md` for the full format spec.
