# CWL Workflow Execution

How to run the PredictStructureApp CWL workflows with the two
supported runners.

## Workflows in the repo

| File | Class | Purpose |
|------|-------|---------|
| `cwl/tools/predict-structure.cwl` | CommandLineTool | Single prediction; dispatches to one of Boltz / OpenFold / Chai / AlphaFold / ESMFold |
| `cwl/tools/protein-compare.cwl` | CommandLineTool | Run `protein_compare characterize` on a single structure |
| `cwl/tools/protein-compare-batch.cwl` | CommandLineTool | Run `protein_compare batch` across multiple structures |
| `cwl/tools/aggregate-results.cwl` | CommandLineTool | Combine per-tool `results.json` into one multi-tool summary |
| `cwl/tools/rename-structure.cwl` | CommandLineTool | Rename a structure file (used by multi-tool workflow) |
| `cwl/tools/select-structure.cwl` | ExpressionTool | Pick the first structure file from a list |
| **`cwl/workflows/protein-structure-prediction.cwl`** | Workflow | Predict → extract structure → characterize report |
| **`cwl/workflows/multi-tool-comparison.cwl`** | Workflow | Run 4 tools in parallel → rename → batch compare → aggregate results |

## Container requirements

Both workflows reference `/scout/containers/folding_prod.sif` via:

```yaml
DockerRequirement:
  dockerPull: folding_prod.sif
  dockerImageId: /scout/containers/folding_prod.sif
```

`folding_prod.sif` is a symlink that points at the current production
build (`folding_260427.1.sif` at the time of writing). For a SIF in a
different location, override at runtime per-runner (see below).

## Runtime requirements

The SIF must be able to read **and write** `/local_databases/cache/`
during execution -- HuggingFace / PyTorch model caches live there. By
default both runners launch singularity in a confined, read-only mode
that breaks this. Each runner has a different way to fix it:

- **cwltool**: use the `SINGULARITY_BINDPATH` + `SINGULARITYENV_*` env
  vars before invoking. The pytest harness does this in
  `_cwltool_env()` in `tests/acceptance/test_cwl_workflow_execution.py`.
- **GoWe**: same env vars work; additionally pass
  `--image-dir /scout/containers` so GoWe resolves the relative
  `dockerPull: folding_prod.sif` correctly.

Cache + bind + GPU environment template (works for both runners):

```bash
# GPU passthrough -- without this both runners launch apptainer
# without --nv, so the SIF can't see the host's NVIDIA driver and
# every prediction silently falls back to CPU.
export APPTAINER_NV=1

# /local_databases bind (model weights + writable HF cache).
# APPTAINER_BINDPATH is the modern name; SINGULARITY_BINDPATH still
# works but apptainer >=1.x prints a deprecation INFO line.
export APPTAINER_BINDPATH="/local_databases:/local_databases"

# Cache redirection inside the SIF. APPTAINERENV_* survives
# `--cleanenv`; the SINGULARITYENV_* prefix is the legacy alias.
export APPTAINERENV_HF_HOME=/local_databases/cache
export APPTAINERENV_HF_DATASETS_CACHE=/local_databases/cache
export APPTAINERENV_TRANSFORMERS_CACHE=/local_databases/cache
export APPTAINERENV_TORCH_HOME=/local_databases/cache
export APPTAINERENV_XDG_CACHE_HOME=/local_databases/cache/tmp
export APPTAINERENV_TRITON_CACHE_DIR=/local_databases/cache/tmp
export APPTAINERENV_NUMBA_CACHE_DIR=/local_databases/cache/tmp
```

> **Note:** cwltool's `--singularity` mode honors the
> `cwltool:CUDARequirement` hint and passes `--nv` automatically; GoWe
> ignores that hint and needs the explicit `APPTAINER_NV=1` env var.
> Setting it on both runners is harmless and idempotent.

## Job file template

```yaml
# job-workflow-esmfold.yml
tool: esmfold
protein:
  - class: File
    path: /abs/path/to/test_data/simple_protein.fasta
output_dir: predictions
seed: 42
num_recycles: 3
device: gpu
fp16: true
output_format: pdb
```

For GPU tools that need an MSA, add:

```yaml
msa:
  class: File
  path: /abs/path/to/test_data/msa/crambin.a3m
```

For multi-entity inputs, populate `dna`, `rna`, `ligand`, `smiles`,
or `glycan` arrays the same way as `protein`.

## Running

### Via `cwltool`

```bash
# Set the cache + bind env vars from the template above first.
cwltool \
  --singularity \
  --outdir /tmp/cwltool_out \
  cwl/workflows/protein-structure-prediction.cwl \
  job-workflow-esmfold.yml
```

`cwltool --singularity` reads the absolute `dockerImageId` directly,
so no `--image-dir` is needed.

### Via GoWe (`/scout/Experiments/GoWe/bin/cwl-runner`)

```bash
# Set the cache + bind env vars from the template above first.
/scout/Experiments/GoWe/bin/cwl-runner \
  --apptainer \
  --image-dir /scout/containers \
  --outdir /tmp/gowe_out \
  --metrics \
  cwl/workflows/protein-structure-prediction.cwl \
  job-workflow-esmfold.yml
```

`--image-dir` tells GoWe where to resolve the relative `dockerPull:
folding_prod.sif`. Without it, GoWe looks in the current working
directory and fails with `lstat ...: no such file or directory`.

GoWe writes per-step subdirectories (`work_1/`, `work_2/`, ...)
alongside the workflow's declared outputs. cwltool stages outputs
flat into `--outdir`.

### Print the resolved commands without executing

```bash
# cwltool
cwltool --print-commandline \
  cwl/workflows/protein-structure-prediction.cwl \
  job-workflow-esmfold.yml

# GoWe
/scout/Experiments/GoWe/bin/cwl-runner print-command \
  cwl/workflows/protein-structure-prediction.cwl \
  job-workflow-esmfold.yml
```

## Expected output (single-tool workflow)

`protein-structure-prediction.cwl` declares these outputs:

```
predictions/                          ← the full normalized output dir
├── model_1.pdb, model_1.cif          ← structure
├── confidence.json, metadata.json    ← scores + run metadata
├── results.json                      ← summary + sha256 manifest
├── ro-crate-metadata.json            ← Process Run Crate provenance
├── raw/, raw_output/                 ← tool-native output (kept)
structure (model_1.pdb)               ← extracted top-level pointer
characterization_report (report.html)
characterization_json (report.json)
```

The full layout matches `docs/OUTPUT_NORMALIZATION.md` §1.

## Multi-tool comparison workflow

`cwl/workflows/multi-tool-comparison.cwl` runs Boltz + OpenFold + Chai
+ ESMFold in parallel against the same input, renames each
structure (`model_1.<tool>.pdb`), runs `protein_compare batch` over
the four, and emits an aggregated `results.json` via the
`aggregate_results` step.

```yaml
# job-multi-tool.yml
protein:
  - class: File
    path: /abs/path/to/test_data/simple_protein.fasta
output_dir: workflow_output
seed: 42
device: gpu
output_format: pdb
report_name: comparison
confidence_weighted: true
```

```bash
/scout/Experiments/GoWe/bin/cwl-runner \
  --apptainer --image-dir /scout/containers --parallel \
  --outdir /tmp/gowe_multi_out \
  cwl/workflows/multi-tool-comparison.cwl \
  job-multi-tool.yml
```

`--parallel` lets GoWe fan out the four prediction steps concurrently;
without it they run sequentially.

## Validating the workflow definitions

Both runners can validate without executing:

```bash
cwltool --validate cwl/workflows/protein-structure-prediction.cwl
/scout/Experiments/GoWe/bin/cwl-runner validate cwl/workflows/protein-structure-prediction.cwl
```

The pytest suite covers these and more:

- `tests/test_cwl_tool.py` -- syntax validation of every CWL file in the repo
- `tests/test_cwl_acceptance.py` -- the predict-structure CWL backend unit tests
- `tests/acceptance/test_cwl_workflow_execution.py` -- end-to-end
  cwltool runs against the SIF (gated `slow` + `tier1`)

## Troubleshooting

### `OSError: [Errno 30] Read-only file system: '/local_databases'`

The cache env vars and `/local_databases` bind aren't applied. Set the
`SINGULARITY_BINDPATH` + `SINGULARITYENV_*` template above before
invoking the runner.

### `FATAL: ... could not open image .../folding_prod.sif: ... no such file or directory`

GoWe-specific: `--image-dir` not set. Pass
`--image-dir /scout/containers` so the relative `dockerPull` resolves
correctly.

### `predict-structure: error: No such command 'finalize-results'`

The SIF's bundled `predict-structure` package is older than the latest
source. Verify with:

```bash
apptainer exec /scout/containers/folding_prod.sif \
  /opt/conda-predict/bin/predict-structure --help \
  | grep -E "finalize-results|aggregate-results"
```

If missing, the SIF needs to be rebuilt from current `main` (see
`docs/CONTAINER_BUILD.md`).

### `WARNING: No GPU available, falling back to CPU` (or `--fp16 ignored`)

Apptainer launched without `--nv`, so the SIF can't see the host
NVIDIA driver. Set `APPTAINER_NV=1` before invoking the runner. This
is automatically set by cwltool when the CWL declares
`cwltool:CUDARequirement`, but GoWe doesn't honor that hint -- pass
the env var explicitly.

### Workflow validates but predict-structure exits with no error message

Likely a downstream tool failure (e.g. ESMFold can't reach
HuggingFace, AlphaFold can't find databases). Inspect
`<outdir>/work_1/predict-structure.err` for the actual stack trace --
the runners only surface "permanentFail" at the workflow level.
