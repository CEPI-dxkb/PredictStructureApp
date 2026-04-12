# Acceptance Testing Plan

Systematic acceptance testing for PredictStructureApp and its production
containers. Three phases test the stack bottom-up: native tools, unified CLI,
and the BV-BRC Perl service script with real workspace integration.

## Containers Under Test

| Label | Path | Size | Notes |
|-------|------|------|-------|
| prod | `/scout/containers/folding_prod.sif` | ~22 GB | Current production (symlink) |
| all | `/scout/containers/all-2026-0410.01.sif` | ~27 GB | New all-in-one build |

By default both containers are tested. Override with `PREDICT_STRUCTURE_SIF`
or `--sif`/`--container-label`.

## Technology: pytest

Extends the existing 237-test pytest suite with parametrized acceptance tests.

**Why pytest:** already in place, `parametrize` handles the tool x input matrix
naturally, `pytest-xdist` supports parallel GPU workers, and Perl integration
works via subprocess.

### Dependencies (in `[dev]`)

```
pytest-timeout     pytest-xdist     filelock
pytest-json-report jsonschema
```

## Directory Layout

```
tests/acceptance/
    conftest.py                        # ApptainerRunner, GPU pinning, container fixture
    validators.py                      # Output directory validation (Python)
    matrix.py                          # ToolTestCase, TOOL_INPUT_MATRIX, PARAM_VARIATIONS
    timing.py                          # Wall-clock baseline comparison
    schemas/
        confidence.schema.json
        metadata.schema.json
    test_phase1_native_tools.py        # Phase 1
    test_phase2_cli_integration.py     # Phase 2
    test_phase2_output_normalization.py
    test_phase2_auto_selection.py
    test_phase3_preflight.py           # Phase 3
    test_phase3_service_script.py
    test_phase3_workspace.py

test_data/acceptance/
    params_chai.json  params_alphafold.json  params_openfold.json
    timing_baselines.json
```

## Markers

```ini
phase1, phase2, phase3     # select by phase
gpu, slow, container       # hardware / resource gates
workspace                  # requires .patric_token
```

---

## Run Commands

```bash
# Quick smoke -- ESMFold only (~30 s)
pytest tests/acceptance/ -m phase1 -k esmfold --gpu-id 0 --timeout 120

# Phase 1 on prod container, pinned to GPU 2
pytest tests/acceptance/ -m phase1 --sif /scout/containers/folding_prod.sif \
  --gpu-id 2 --timeout 3600

# Phase 2
pytest tests/acceptance/ -m phase2 --gpu-id 0 --timeout 3600

# Phase 3 (requires .patric_token)
pytest tests/acceptance/ -m phase3 --gpu-id 0 --timeout 3600

# Full suite, specific container, JSON report
PREDICT_STRUCTURE_SIF=/scout/containers/all-2026-0410.01.sif \
  pytest tests/acceptance/ --gpu-id 0 --timeout 7200 \
  --json-report --json-report-file=results.json

# Both containers in parallel (separate terminals / GPUs)
pytest tests/acceptance/ --sif /scout/containers/folding_prod.sif \
  --gpu-id 0 --timeout 7200 &
pytest tests/acceptance/ --sif /scout/containers/all-2026-0410.01.sif \
  --gpu-id 1 --timeout 7200 &
```

---

## GPU Pinning

AlphaFold (JAX) and other tools will grab **all visible GPUs** unless
restricted. The `ApptainerRunner` injects `CUDA_VISIBLE_DEVICES=<N>` into
every GPU-enabled `apptainer exec` call.

Configure via:
- `--gpu-id <N>` pytest flag
- `CUDA_VISIBLE_DEVICES` environment variable
- Default: `0`

This is required when running multiple test suites in parallel on a
multi-GPU node.

## Bind Mounts

Every `predict` call automatically binds:

| Host path | Container path | Mode | Contents |
|-----------|---------------|------|----------|
| `test_data/` | `/data` | rw | FASTA, MSA, job specs |
| `<tmp>/output` | `/output` | rw | Prediction output |
| `/local_databases` | `/local_databases` | **ro** | Model weights and databases |

`/local_databases` contains:

```
/local_databases/
    boltz/          # boltz2_aff.ckpt, boltz2_conf.ckpt, ccd.pkl, mols/
    chai/           # conformers_v1.apkl, esm/, models_v2/
    openfold/       # of3-p2-155k.pt, ckpt_root/
    alphafold/
        databases/  # bfd/, mgnify/, params/, pdb70/, pdb_mmcif/, ...
```

AlphaFold `--af2-data-dir` points to `/local_databases/alphafold/databases`.

---

## Testing Matrix

### Tool x Input Type

```
                  protein  multimer  prot+DNA  prot+RNA  prot+ligand  prot+SMILES
  boltz             *        *         *         *          *            *
  openfold          *        *         *         *          *            *
  chai              *        *         *         *          *            *
  alphafold         *        *         *         -          *            -
  esmfold         */cpu      *         *         -          *            -
```

`*` = expected pass, `-` = not in matrix (tool ignores unsupported entity types gracefully).

The CLI does **not** reject unsupported entity types; it runs with whatever
entities the tool supports and silently skips the rest.

### Parameter Variations

| Parameter | Values | Tools |
|-----------|--------|-------|
| `num_samples` | 1, 3 | boltz, chai, openfold |
| `num_recycles` | 3, 8 | boltz, chai, esmfold |
| `sampling_steps` | 50, 200 | boltz, chai |
| `seed` | 42 (fixed) | all |
| `device` | gpu, cpu | esmfold only for cpu |
| `msa_mode` | none, file | boltz, chai, openfold |
| `output_format` | pdb, mmcif | all |
| `fp16` | true | esmfold |

### MSA Modes (local only)

| Mode | Flag | Tools |
|------|------|-------|
| none | _(no flag)_ | all 5 |
| file | `--msa /data/msa/crambin.a3m` | boltz, chai, openfold |

MSA server (`--use-msa-server`) is **excluded** -- all testing is local.

### Test Counts

| Phase | Tests per container | Runtime estimate |
|-------|-------------------|-----------------|
| Phase 1: Native tools | 37 | 2-6 h |
| Phase 2: CLI integration | 32 | 2-4 h |
| Phase 3: Service + workspace | 36 | 1-2 h |
| **Total** | **105** | **5-12 h** |

Both containers: 210 tests.

---

## Phase 1: Native Tool Execution

**File:** `test_phase1_native_tools.py`

Runs each tool directly inside the container via
`apptainer exec --nv <sif> predict-structure <tool> ... --backend subprocess`.

Tests are parametrized from `matrix.TOOL_INPUT_MATRIX` (tool x input type)
and `matrix.PARAM_VARIATIONS` (parameter sweeps).

**Validation per test:**
1. Exit code 0
2. `validators.assert_valid_output()` -- PDB ATOM records, confidence.json
   schema, metadata.json schema, raw_output/ directory
3. Timing baseline comparison (warn, not fail)

**Quick smoke:** `TestESMFoldQuickSmoke` -- single crambin + fp16 (~30 s).

## Phase 2: predict-structure CLI

All tests run inside the container with `--backend subprocess`.

### test_phase2_cli_integration.py

- Each subcommand with real execution
- `--debug` mode (prints command, no execution, no output files)
- Entity flags: `--protein`, `--dna`, `--rna`, `--ligand`, `--smiles`, `--sequence`
- `--msa <file>` (local .a3m, no server)
- `--job spec.yaml` batch execution

### test_phase2_output_normalization.py

- confidence.json: pLDDT 0-100, per_residue_plddt length = sequence length
- metadata.json: correct tool name, positive runtime
- model_1.pdb: ATOM records present
- `--output-format pdb` vs `--output-format mmcif`

### test_phase2_auto_selection.py

- `auto --protein` (GPU, no MSA) -> openfold
- `auto --protein --msa file` (GPU) -> boltz
- `auto --protein --device cpu` -> esmfold
- `auto --protein --ligand ATP` -> boltz/openfold/chai (not alphafold/esmfold)

## Phase 3: Perl Service Script + Workspace

### test_phase3_preflight.py

- `predict-structure preflight --tool <tool>` for each tool
- JSON output: `resolved_tool`, `needs_gpu`, `cpu`, `memory`, `runtime`
- GPU policy_data for GPU tools, absent for esmfold
- `--tool auto` resolves to concrete tool name

### test_phase3_service_script.py

- `perl -c` syntax check
- `App-PredictStructure.pl` with `params_<tool>.json` for each tool
- `text_input` mode (inline sequences) vs `input_file` mode
- MSA modes: none, file upload (no server)

### test_phase3_workspace.py

Requires `.patric_token` (real BV-BRC workspace).

- `p3-whoami` / `p3-ls` connectivity
- Upload file, verify in workspace, clean up
- Full service script roundtrip with workspace output

---

## Output Validation

`validators.py` checks:

| Check | File | Criteria |
|-------|------|----------|
| Structure | `model_1.pdb` | Exists, >100 bytes, has ATOM records |
| Structure | `model_1.cif` | Exists, >100 bytes |
| Confidence | `confidence.json` | JSON Schema: plddt_mean 0-100, per_residue_plddt array |
| Metadata | `metadata.json` | JSON Schema: tool name, runtime_seconds > 0 |
| Raw output | `raw_output/` | Directory exists, non-empty |
| Report | `report.html` | (optional) >10 KB, contains `<html>` |

JSON Schemas are in `tests/acceptance/schemas/`.

## Timing Baselines

`test_data/acceptance/timing_baselines.json` defines expected runtime ranges.
Tests **warn** (not fail) if wall-clock time exceeds 3x typical.

```json
{
  "esmfold_protein_gpu":  {"min_s": 3,  "max_s": 45,   "typical_s": 7},
  "boltz_protein_gpu":    {"min_s": 30, "max_s": 1800, "typical_s": 120},
  "alphafold_protein_gpu":{"min_s": 600,"max_s": 7200, "typical_s": 1500}
}
```

## Reproducibility

- **Fixed seed:** `--seed 42` on all tests
- **Test protein:** crambin (46 residues) -- fast inference
- **Precomputed MSA:** `test_data/msa/crambin.a3m` -- no server dependency

## Lessons Learned (from initial test runs)

1. **Bind mounts matter:** All non-ESMFold tools fail without `/local_databases`
   mounted. This was the #1 failure mode in the first run.

2. **GPU pinning is required:** AlphaFold/JAX pre-allocates memory on every
   visible GPU. Without `CUDA_VISIBLE_DEVICES`, a single AlphaFold test grabs
   all 8 GPUs and blocks parallel runs.

3. **CLI accepts unsupported entities gracefully:** The CLI does not reject
   `--dna` or `--ligand` flags for tools that don't support them. It runs the
   tool with whatever entities it can handle. Tests should not use `xfail` for
   these cases.

4. **AlphaFold data path:** `--af2-data-dir` must point to
   `/local_databases/alphafold/databases` (not `/databases`).

5. **OpenFold interactive prompt:** Without pre-cached weights, OpenFold prompts
   for download confirmation. The `/local_databases/openfold/` bind provides
   the checkpoint so the adapter resolves it automatically.
