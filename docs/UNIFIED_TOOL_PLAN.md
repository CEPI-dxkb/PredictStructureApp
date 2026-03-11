# Unified Protein Structure Prediction Tool — Design Plan

## 1. CLI Parameter Inventory

### 1.1 Boltz-2 (`boltz predict`)

| Parameter | Type | Default | Semantic Category |
|-----------|------|---------|-------------------|
| `INPUT_PATH` | file/dir | required | **input** |
| `--out_dir` | path | `./` | **output** |
| `--cache` | path | `~/.boltz` | infra |
| `--checkpoint` | path | None | infra |
| `--override` | flag | false | infra |
| `--use_msa_server` | flag | false | **msa** |
| `--max_msa_seqs` | int | 8192 | **msa** |
| `--msa_pairing_strategy` | enum | greedy | msa |
| `--diffusion_samples` | int | 1 | **sampling** |
| `--sampling_steps` | int | 200 | **sampling** |
| `--max_parallel_samples` | int | 5 | infra |
| `--step_scale` | float | 1.638 | sampling |
| `--recycling_steps` | int | 3 | **recycling** |
| `--use_potentials` | flag | false | refinement |
| `--output_format` | enum | mmcif | **output_format** |
| `--write_full_pae` | flag | false | output |
| `--write_full_pde` | flag | false | output |
| `--accelerator` | enum | gpu | **device** |
| `--devices` | int | 1 | device |
| `--num_workers` | int | 2 | infra |
| `--predict_affinity` | flag | false | boltz-specific |

### 1.2 Chai-1 (`chai-lab fold`)

| Parameter | Type | Default | Semantic Category |
|-----------|------|---------|-------------------|
| `fasta_file` | file | required | **input** |
| `output_dir` | path | required | **output** |
| `--use-msa-server` | flag | false | **msa** |
| `--msa-server-url` | string | colabfold | msa |
| `--msa-directory` | path | None | **msa** |
| `--msa-file` | path | None | **msa** |
| `--use-templates-server` | flag | false | templates |
| `--num-diffn-samples` | int | 5 | **sampling** |
| `--num-trunk-recycles` | int | 3 | **recycling** |
| `--num-diffn-timesteps` | int | 200 | **sampling** |
| `--seed` | int | random | **seed** |
| `--device` | string | auto | **device** |
| `--low-memory` | flag | true | infra |
| `--use-esm-embeddings` | flag | true | chai-specific |
| `--constraint-path` | path | None | chai-specific |

### 1.3 AlphaFold2 (`run_alphafold.py`)

| Parameter | Type | Default | Semantic Category |
|-----------|------|---------|-------------------|
| `--fasta_paths` | file(s) | required | **input** |
| `--output_dir` | path | required | **output** |
| `--data_dir` | path | required | **infra** |
| `--model_preset` | enum | monomer | **model** |
| `--db_preset` | enum | full_dbs | **msa** |
| `--max_template_date` | string | 2022-01-01 | templates |
| `--use_precomputed_msas` | flag | false | **msa** |
| `--models_to_relax` | enum | best | refinement |
| `--use_gpu_relax` | flag | true | device |
| `--num_multimer_predictions_per_model` | int | 5 | **sampling** |
| `--random_seed` | int | random | **seed** |
| `--benchmark` | flag | false | infra |
| (many database paths) | path | required | infra |

### 1.4 ESMFold (HuggingFace: `esm-fold-hf`)

| Parameter | Type | Default | Semantic Category |
|-----------|------|---------|-------------------|
| `-i, --fasta` | file | required | **input** |
| `-o, --pdb` | path | required | **output** |
| `-m, --model-name` | string | facebook/esmfold_v1 | infra |
| `--max-tokens-per-batch` | int | 1024 | infra |
| `--chunk-size` | int | None | infra |
| `--num-recycles` | int | 4 | **recycling** |
| `--cpu-only` | flag | false | **device** |
| `--fp16` | flag | false | infra |
| `--use-tf32` | flag | false | infra |

---

## 2. Semantic Parameter Overlap Matrix

### 2.1 Exact Semantic Equivalences

These parameters mean the same thing across tools, just with different names and flag styles:

| Unified Name | Boltz-2 | Chai-1 | AlphaFold2 | ESMFold |
|-------------|---------|--------|------------|---------|
| **input** | `INPUT_PATH` (.yaml) | `fasta_file` (.fasta) | `--fasta_paths` (.fasta) | `-i` (.fasta) |
| **output_dir** | `--out_dir` | `output_dir` | `--output_dir` | `-o` |
| **recycling** | `--recycling_steps` (def: 3) | `--num-trunk-recycles` (def: 3) | implicit (3) | `--num-recycles` (def: 4) |
| **num_samples** | `--diffusion_samples` (def: 1) | `--num-diffn-samples` (def: 5) | `--num_multimer_predictions_per_model` (def: 5) | N/A (deterministic) |
| **sampling_steps** | `--sampling_steps` (def: 200) | `--num-diffn-timesteps` (def: 200) | N/A | N/A |
| **seed** | (not exposed in CLI) | `--seed` | `--random_seed` | N/A (deterministic) |
| **use_msa_server** | `--use_msa_server` | `--use-msa-server` | N/A (has own pipeline) | N/A |
| **device** | `--accelerator` (gpu/cpu) | `--device` (cuda:N) | implicit | `--cpu-only` (flag) |

### 2.2 Input Format Divergence (Critical Design Decision)

| Tool | Native Input | MSA Input | MSA Format |
|------|-------------|-----------|------------|
| Boltz-2 | YAML manifest | embedded in YAML `msa:` field | A3M |
| Chai-1 | FASTA | `--msa-file` / `--msa-directory` | Parquet (.aligned.pqt) |
| AlphaFold2 | FASTA | precomputed in directory structure | A3M/Stockholm |
| ESMFold | FASTA | not supported | N/A |

**Key insight**: FASTA is the common denominator for sequence input. Only Boltz requires YAML (for multi-entity complexes, ligands, constraints). MSA formats diverge — A3M is the lingua franca but Chai needs Parquet conversion.

### 2.3 Output Format Divergence

| Tool | Primary Output | Confidence Output |
|------|---------------|-------------------|
| Boltz-2 | mmCIF (.cif) | JSON + NPZ (pLDDT, pTM, PAE) |
| Chai-1 | mmCIF (.cif) | NPZ (scores) |
| AlphaFold2 | PDB (.pdb) | JSON (ranking_debug) |
| ESMFold | PDB (.pdb) | pLDDT in B-factor column |

### 2.4 Parameters Unique to One Tool

| Tool | Unique Parameters | Notes |
|------|------------------|-------|
| Boltz-2 | `--predict_affinity`, `--use_potentials`, `--step_scale`, `--write_full_pae/pde` | Affinity & potentials are Boltz-only features |
| Chai-1 | `--constraint-path`, `--use-esm-embeddings`, `--use-templates-server` | Constraints & template server |
| AlphaFold2 | `--model_preset`, `--db_preset`, `--models_to_relax`, all database paths | Complex DB infrastructure |
| ESMFold | `--chunk-size`, `--fp16`, `--max-tokens-per-batch` | Memory optimization (no MSA) |

---

## 3. ProteinFoldingApp as Backbone

The existing `ProteinFoldingApp/` already provides significant infrastructure:

### 3.1 What Already Exists

- **CWL tool definitions** for all 4 tools (`cwl/tools/{boltz,chai,alphafold,esmfold}-predict.cwl`)
- **Unified experiment workflows** orchestrating all tools with standardized metrics
- **MSA generation pipeline** (MMseqs2 + JackHMMER with format conversion)
- **Structure comparison framework** (`protein_compare` → JSON → CSV → plots)
- **Target configuration system** (`configs/targets_pilot.yaml`)
- **Statistical analysis** (Wilcoxon, bootstrap CIs, effect sizes)
- **GoWe workflow engine integration** for CWL execution

### 3.2 What's Missing for a Unified CLI

1. **No single entry point** — each tool is invoked separately through CWL
2. **No parameter normalization** — each CWL tool exposes native flags
3. **No input format abstraction** — caller must prepare tool-specific inputs (YAML for Boltz, FASTA for others, Parquet for Chai MSAs)
4. **No output normalization** — outputs are mmCIF/PDB depending on tool
5. **No interactive CLI** — orchestration is through CWL submission, not a user-facing command
6. **ESMFold uses legacy `esm-fold`** — should switch to HuggingFace `esm-fold-hf`

### 3.3 Architecture Recommendation

Evolve ProteinFoldingApp into the unified tool by adding a CLI layer on top of the existing CWL infrastructure:

```
┌─────────────────────────────────────────────┐
│  Unified CLI  (predict-structure)           │
│  - Normalizes input (FASTA → per-tool fmt)  │
│  - Normalizes parameters                     │
│  - Normalizes output (→ PDB + JSON)          │
├─────────────────────────────────────────────┤
│  Adapter Layer  (per-tool)                  │
│  - boltz_adapter.py                          │
│  - chai_adapter.py                           │
│  - alphafold_adapter.py                      │
│  - esmfold_adapter.py (HuggingFace)          │
├─────────────────────────────────────────────┤
│  Execution Backends                         │
│  - Direct CLI  (subprocess / Docker)         │
│  - CWL workflows (GoWe / cwltool)            │
│  - BV-BRC AppService (SLURM)                 │
├─────────────────────────────────────────────┤
│  Native Tools                               │
│  boltz predict | chai fold | run_alphafold   │
│  esm-fold-hf (HuggingFace)                  │
└─────────────────────────────────────────────┘
```

---

## 4. Unified CLI Design

### 4.1 Proposed Command Structure

```bash
predict-structure <tool> <input.fasta> [options]

# Or with auto-selection:
predict-structure --auto <input.fasta> [options]
```

### 4.2 Unified Parameter Set

#### Required Parameters

| Unified Flag | Type | Description | Maps To |
|-------------|------|-------------|---------|
| `<tool>` | enum | `boltz`, `chai`, `alphafold`, `esmfold`, `auto` | tool selection |
| `<input>` | file | FASTA file (or Boltz YAML if tool=boltz) | per-tool input |
| `--output-dir, -o` | path | Output directory | `--out_dir` / `output_dir` / `--output_dir` / `-o` |

#### Common Optional Parameters (cross-tool)

| Unified Flag | Type | Default | Boltz | Chai | AF2 | ESMFold |
|-------------|------|---------|-------|------|-----|---------|
| `--num-samples, -n` | int | 1 | `--diffusion_samples` | `--num-diffn-samples` | `--num_multimer_predictions_per_model` | ignored |
| `--num-recycles` | int | tool default | `--recycling_steps` (3) | `--num-trunk-recycles` (3) | implicit (3) | `--num-recycles` (4) |
| `--sampling-steps` | int | 200 | `--sampling_steps` | `--num-diffn-timesteps` | N/A | N/A |
| `--seed` | int | random | N/A | `--seed` | `--random_seed` | N/A |
| `--device` | string | auto | `--accelerator` | `--device` | implicit | `--cpu-only` |
| `--output-format` | enum | pdb | `--output_format` + convert | convert from cif | native pdb | native pdb |

#### MSA Parameters

| Unified Flag | Type | Default | Boltz | Chai | AF2 | ESMFold |
|-------------|------|---------|-------|------|-----|---------|
| `--msa` | file/dir | None | inject into YAML | `--msa-file` (after a3m→pqt) | `--msa_dir` (precomputed) | ignored |
| `--use-msa-server` | flag | false | `--use_msa_server` | `--use-msa-server` | N/A | ignored |
| `--no-msa` | flag | false | omit msa field | omit msa arg | single-seq A3M | always |

#### Tool-Specific Pass-Through

| Unified Flag | Type | Description |
|-------------|------|-------------|
| `--boltz-*` | any | Pass-through to Boltz (e.g. `--boltz-use-potentials`, `--boltz-predict-affinity`) |
| `--chai-*` | any | Pass-through to Chai (e.g. `--chai-constraint-path`, `--chai-use-templates-server`) |
| `--af2-*` | any | Pass-through to AF2 (e.g. `--af2-model-preset`, `--af2-db-preset`) |
| `--esm-*` | any | Pass-through to ESMFold (e.g. `--esm-chunk-size`, `--esm-fp16`) |

### 4.3 Unified Output Structure

Regardless of tool, all outputs are normalized to:

```
output_dir/
├── predicted.pdb              # Best structure (always PDB)
├── predicted.cif              # Best structure (always mmCIF)
├── confidence.json            # Normalized: { plddt_mean, ptm, per_residue_plddt[] }
├── pae.json                   # PAE matrix (if available)
├── metadata.json              # Tool, params, runtime, versions
└── native/                    # Original tool output (unmodified)
    └── ...
```

---

## 5. Implementation Approaches

Your suggested approaches, analyzed:

### 5.1 Shell Script Wrapper

**Pros**: Minimal dependencies, fast to prototype, transparent, easy to debug.
**Cons**: Limited input/output normalization, hard to do format conversion (FASTA→YAML, A3M→Parquet), no proper error handling for complex cases, string manipulation for JSON is fragile.

**Verdict**: Good for v0 prototype. Handles the "dispatch to correct Docker container" use case well. Struggles with format conversion and output normalization.

```bash
#!/bin/bash
# Sketch:
predict-structure() {
    local tool=$1 input=$2; shift 2
    case $tool in
        boltz)    docker run dxkb/boltz boltz predict ... ;;
        chai)     docker run dxkb/chai chai fold ... ;;
        alphafold) docker run wilke/alphafold python /app/... ;;
        esmfold)  docker run dxkb/esmfold esm-fold-hf ... ;;
    esac
}
```

### 5.2 Python Wrapper

**Pros**: Proper argument parsing (argparse/click), format conversion built-in (BioPython for PDB↔mmCIF, pandas for A3M→Parquet), structured output normalization, testable, type-safe configuration.
**Cons**: Adds Python dependency, more code to maintain.

**Verdict**: Best for a production-quality unified tool. Can handle all format conversions natively. Natural fit since all underlying tools are Python-based (except AF2's database tools).

```python
# Sketch:
@click.command()
@click.argument('tool', type=click.Choice(['boltz','chai','alphafold','esmfold','auto']))
@click.argument('input_fasta', type=click.Path(exists=True))
@click.option('--output-dir', '-o', required=True)
@click.option('--num-samples', '-n', default=1)
@click.option('--num-recycles', default=None)  # None = use tool default
@click.option('--seed', default=None)
@click.option('--msa', type=click.Path(), default=None)
@click.option('--device', default='auto')
def predict_structure(tool, input_fasta, output_dir, ...):
    adapter = get_adapter(tool)  # BoltzAdapter, ChaiAdapter, etc.
    adapter.prepare_input(input_fasta, msa=msa)
    adapter.run(output_dir, **normalized_params)
    adapter.normalize_output(output_dir)
```

### 5.3 CWL Workflows (Extend ProteinFoldingApp)

**Pros**: Already exists in ProteinFoldingApp, portable, reproducible, GoWe/cwltool/Toil compatible, HPC-ready (SLURM).
**Cons**: CWL is verbose for CLI ergonomics, not interactive, harder to do conditional logic (e.g., auto tool selection), no runtime format conversion steps built in yet.

**Verdict**: Best for batch/HPC execution and reproducible experiments. Not ideal as a user-facing CLI by itself, but excellent as the execution backend behind a Python or shell wrapper.

### 5.4 Recommended: Hybrid Approach

```
Python CLI (click/argparse)
    ├── Direct mode: subprocess calls to Docker/native tools
    │   └── For interactive use, single predictions
    └── CWL mode: generates CWL job and submits to GoWe
        └── For batch, HPC, reproducible pipelines
```

The Python CLI handles input normalization, parameter mapping, and output normalization. Execution can be either direct (subprocess + Docker) or via CWL (GoWe submission). This builds on ProteinFoldingApp's existing CWL infrastructure while adding the missing CLI layer.

---

## 6. ESMFold Strategy: HuggingFace-First

### 6.1 Why HuggingFace over Legacy ESM

| Aspect | Legacy (`esm-fold`) | HuggingFace (`esm-fold-hf`) |
|--------|---------------------|------------------------------|
| Dependencies | OpenFold (complex build), custom CUDA ops | `transformers`, `torch` (standard) |
| Installation | Compile from source, CUDA toolkit required | `pip install transformers torch` |
| Model loading | Manual download, custom paths | `from_pretrained("facebook/esmfold_v1")` auto-download |
| Memory optimization | `--cpu-offload` | `--fp16`, `--chunk-size`, 8-bit quantization |
| Maintenance | Stale (last update 2023) | Active HuggingFace ecosystem |
| Docker image size | ~15GB (OpenFold + CUDA compile) | ~8GB (standard PyTorch) |
| API compatibility | Custom | Standard HuggingFace `pipeline` interface |

### 6.2 Proposed ESMFold CLI (`esm-fold-hf`)

Already exists in the repo at `ESMFoldApp/esm_hf/scripts/hf_fold.py`. This should be promoted to the primary ESMFold interface and the legacy `esm-fold` deprecated.

Key parameters to expose in unified tool:
- `--num-recycles` (1-48, default 4)
- `--chunk-size` (memory optimization)
- `--fp16` (half-precision)
- `--max-tokens-per-batch` (batching)

### 6.3 Migration Path

1. Update `ESMFoldApp/cwl/tools/esmfold-predict.cwl` baseCommand from `esm-fold` to `esm-fold-hf`
2. Build new Docker image based on `transformers` + `torch` (no OpenFold)
3. Update ProteinFoldingApp CWL tool reference
4. Validate output parity with legacy on pilot targets

---

## 7. Maturity Assessment & Gaps

| Tool | BV-BRC App | CWL Tool | Docker | CLI Direct | Gap |
|------|-----------|----------|--------|-----------|-----|
| Boltz-2 | ✅ mature | ✅ | ✅ | ✅ | None significant |
| Chai-1 | ✅ mature | ✅ | ✅ | ✅ | MSA needs A3M→Parquet conversion |
| AlphaFold2 | ✅ mature | ✅ | ✅ | ✅ | Complex DB setup, heavy infrastructure |
| ESMFold | ⚠️ legacy deps | ✅ | ⚠️ heavy image | ⚠️ legacy | Switch to HuggingFace, rebuild Docker |

### 7.1 Decision: Use App or Original Code?

| Tool | Recommendation | Rationale |
|------|---------------|-----------|
| Boltz-2 | **Original CLI** (`boltz predict`) | Clean, well-documented, direct Docker use. BV-BRC wrapper adds SLURM/workspace overhead not needed for unified tool. |
| Chai-1 | **Original CLI** (`chai fold`) | Same reasoning. Add A3M→Parquet conversion in adapter layer. |
| AlphaFold2 | **Original code** (`run_alphafold.py`) | BV-BRC wrapper mostly passes through. Original gives full control over DB paths and presets. |
| ESMFold | **HuggingFace model** (new CLI) | Avoid legacy OpenFold dependency hell. Lighter Docker image. Better long-term maintenance. |

---

## 8. Implementation Roadmap

### Phase 1: Foundation (ProteinFoldingApp + Python CLI)

1. Create `predict_structure/` Python package in ProteinFoldingApp
2. Implement adapter classes: `BoltzAdapter`, `ChaiAdapter`, `AlphaFoldAdapter`, `ESMFoldAdapter`
3. Implement unified CLI with `click` or `argparse`
4. Add input format conversion (FASTA→Boltz YAML, A3M→Parquet)
5. Add output normalization (mmCIF→PDB, confidence JSON extraction)

### Phase 2: ESMFold Migration

1. Promote `esm_hf/scripts/hf_fold.py` as primary ESMFold CLI
2. Build new lightweight Docker image
3. Validate output parity on pilot targets
4. Update CWL tool definition

### Phase 3: CWL Integration

1. Create `cwl/tools/predict-structure.cwl` that wraps the unified CLI
2. Update experiment workflows to optionally use unified tool
3. Add `--backend cwl` mode for GoWe submission

### Phase 4: BV-BRC Integration

1. Create `App-PredictStructure.pl` unified BV-BRC AppScript
2. Unified app_spec JSON with tool selector and normalized parameters
3. Deploy alongside existing per-tool apps

---

## 9. Open Questions

1. **Auto tool selection**: What heuristic for `--auto`? Sequence length? MSA availability? (ESMFold for quick/no-MSA, Boltz for complexes, AF2 for well-studied proteins?)

2. **Ligand/DNA/RNA support**: Boltz-2 handles these natively via YAML. Chai has some multi-entity support. AF2 and ESMFold are protein-only. Should the unified tool support non-protein entities, and if so, how to handle tools that can't?

3. **Ensemble mode**: Should `predict-structure --ensemble` run all 4 tools and return consensus or best-by-confidence? ProteinFoldingApp already has the comparison infrastructure for this.

4. **stabiliNNator integration**: The ProteinEngineeringWorkflows CWL pipeline already chains structure prediction → stability analysis. Should the unified tool include `--analyze-stability` as a post-processing step?

5. **Version pinning**: Tools evolve rapidly (Boltz-2 was a major update). How to handle version management in the unified wrapper?
