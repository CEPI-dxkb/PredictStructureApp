# Acceptance Testing Matrix

Test protein: crambin (46 residues, `test_data/simple_protein.fasta`)
Test date: 2026-03-28
Hardware: NVIDIA H200 NVL (GPUs 2-7)

## Container Inventory

| Container | Date | Size | predict-structure | boltz torch | esmfold torch |
|-----------|------|------|-------------------|-------------|---------------|
| `all-2026-0224b.sif` | 2026-02-24 | 37 GB | old (missing tools.yml) | 2.10.0+cu128 | n/a |
| `folding_260527.1.sif` | 2026-03-26 | 38 GB | old (missing tools.yml) | 2.10.0+cu128 | n/a |
| `folding_260327.3.sif` | 2026-03-27 | 21 GB | current (has tools.yml) | 2.11.0+cu130 | 2.6.0+cu124 |
| `folding_260328.2.sif` | 2026-03-28 | 21 GB | missing tools.yml | 2.11.0+cu130 | 2.6.0+cu124 |
| `folding_260328.3.sif` | 2026-03-28 | 21 GB | missing tools.yml | 2.11.0+cu130 | 2.6.0+cu124 |

Symlinks: `folding_prod.sif` / `folding_dev.sif` / `folding_latest.sif` → `folding_260527.1.sif`

Note: `tools.yml` is on the `cwl/tools` branch but not yet merged to `main`. Containers install from `main`, so predict-structure subcommands fail in containers built after `tools.yml` was added as a dependency.

## Test Results

### Summary

D = direct tool CLI, P = via predict-structure (host, apptainer backend)

```
              all-2026-0224b  folding_260527.1  folding_260327.3  folding_260328.2  folding_260328.3
─────────     ──────────────  ────────────────  ────────────────  ────────────────  ────────────────
Boltz    D    PASS            PASS              FAIL (cu130)      FAIL (cu130)      PASS
Boltz    P    n/a             n/a               n/a               n/a               PASS
Chai     D    PASS            PASS              PASS              PASS              PASS
Chai     P    n/a             n/a               n/a               n/a               PASS
AlphaFold D   PASS            PASS              PASS              PASS              PASS
ESMFold  D    n/a             n/a               PASS              PASS              PASS
ESMFold  P    n/a             n/a               PASS              n/a               PASS
Auto     P    n/a             n/a               FAIL (boltz)      n/a               pending
```

### Boltz

| Container | Method | GPU | Result | Time | Notes |
|-----------|--------|-----|--------|------|-------|
| `all-2026-0224b.sif` | direct | GPU 2 | **PASS** | 10s | torch 2.10+cu128, MSA server, 0 failed |
| `folding_260527.1.sif` | direct | GPU 2 | **PASS** | 10s | torch 2.10+cu128, MSA server, 0 failed |
| `folding_260327.3.sif` | direct | GPU 2 | **FAIL** | - | torch 2.11+cu130: `libnvrtc-builtins.so.13.0` not on LD_LIBRARY_PATH |
| `folding_260328.2.sif` | direct | GPU 2 | **FAIL** | - | Same cu130 issue — built before LD_LIBRARY_PATH fix |
| `folding_260328.3.sif` | direct | GPU 2 | **PASS** | 14s | torch 2.11+cu130, LD_LIBRARY_PATH fix applied |
| `folding_260328.3.sif` | predict-structure | GPU 2 | **PASS** | 57.6s | host CLI, apptainer backend, full normalize |

### Chai

| Container | Method | GPU | Result | Score | Notes |
|-----------|--------|-----|--------|-------|-------|
| `all-2026-0224b.sif` | direct | GPU 3 | **PASS** | 0.189 | MSA server, 199 diffusion steps, 3 recycles |
| `folding_260527.1.sif` | direct | GPU 3 | **PASS** | 0.189 | MSA server, 199 diffusion steps, 3 recycles |
| `folding_260327.3.sif` | direct | GPU 3 | **PASS** | 0.189 | MSA server, 199 diffusion steps, 3 recycles |
| `folding_260328.2.sif` | direct | GPU 3 | **PASS** | 0.189 | MSA server, 199 diffusion steps, 3 recycles |
| `folding_260328.3.sif` | direct | GPU 3 | **PASS** | 0.189 | MSA server, 199 diffusion steps, 3 recycles |
| `folding_260328.3.sif` | predict-structure | GPU 3 | **PASS** | 0.189 | host CLI, apptainer backend, 67.3s total |

### AlphaFold

| Container | Method | GPU | Result | Time | Notes |
|-----------|--------|-----|--------|------|-------|
| `all-2026-0224b.sif` | direct | GPU 4 | **PASS** | ~25m | 5 ranked models, monomer, reduced_dbs |
| `folding_260527.1.sif` | direct | GPU 5 | **PASS** | ~25m | 5 ranked models, monomer, reduced_dbs |
| `folding_260327.3.sif` | direct | GPU 6 | **PASS** | ~28m | 5 ranked models, monomer, reduced_dbs |
| `folding_260328.2.sif` | direct | GPU 4 | **PASS** | ~25m | 5 ranked models, monomer, reduced_dbs |
| `folding_260328.3.sif` | direct | GPU 4 | **PASS** | ~25m | 5 ranked models, monomer, reduced_dbs |

### ESMFold

| Container | Method | GPU | Result | Time | pLDDT | Notes |
|-----------|--------|-----|--------|------|-------|-------|
| `folding_260327.3.sif` | predict-structure (in container) | GPU 7 | **PASS** | 5.6s | 43.6 | fp16, 4 recycles |
| `folding_260327.3.sif` | predict-structure (in container) | CPU | **PASS** | 25.9s | 43.6 | Same results, 3x slower |
| `folding_260328.2.sif` | direct | GPU 7 | **PASS** | 6.9s | 43.6 | fp16, 4 recycles |
| `folding_260328.3.sif` | direct | GPU 7 | **PASS** | 6.4s | 43.6 | fp16, 4 recycles |
| `folding_260328.3.sif` | predict-structure | GPU 7 | **PASS** | 28.8s | 43.6 | host CLI, apptainer backend |

### Auto (predict-structure auto)

| Container | Method | GPU | Result | Notes |
|-----------|--------|-----|--------|-------|
| `folding_260327.3.sif` | in container | GPU 7 | **FAIL** | Selects boltz → fails (cu130 issue) |

## Exact Command Lines

All commands assume: `source /scout/wf/gowe/secrets.env`

### Direct Tool CLI

```bash
# Boltz (direct) — requires typed YAML input
CUDA_VISIBLE_DEVICES=2 apptainer exec --nv \
  --bind /scout --bind /tmp --bind /local_databases \
  /scout/containers/folding_260328.3.sif \
  /opt/conda-boltz/bin/boltz predict \
  /home/wilke/Development/PredictStructureApp/test_data/crambin-boltz.yaml \
  --out_dir /tmp/test-boltz-direct \
  --diffusion_samples 1 --use_msa_server --accelerator gpu

# Chai (direct) — requires typed FASTA (>protein|name)
CUDA_VISIBLE_DEVICES=3 apptainer exec --nv \
  --bind /scout --bind /tmp --bind /local_databases \
  /scout/containers/folding_260328.3.sif \
  /opt/conda-chai/bin/chai-lab fold \
  /home/wilke/Development/PredictStructureApp/test_data/crambin-chai.fasta \
  /tmp/test-chai-direct \
  --num-diffn-samples 1 --use-msa-server

# ESMFold (direct) — standard FASTA input
CUDA_VISIBLE_DEVICES=7 apptainer exec --nv \
  --bind /scout --bind /tmp --bind /local_databases \
  /scout/containers/folding_260328.3.sif \
  /opt/conda-esmfold/bin/esm-fold-hf \
  -i /home/wilke/Development/PredictStructureApp/test_data/simple_protein.fasta \
  -o /tmp/test-esm-direct \
  --num-recycles 4 --fp16

# AlphaFold (direct) — requires database paths
CUDA_VISIBLE_DEVICES=4 apptainer exec --nv \
  --bind /scout --bind /tmp --bind /local_databases \
  /scout/containers/folding_260328.3.sif \
  /opt/conda-alphafold/bin/python /app/alphafold/run_alphafold.py \
  --fasta_paths=/home/wilke/Development/PredictStructureApp/test_data/simple_protein.fasta \
  --output_dir=/tmp/test-af-direct \
  --data_dir=/local_databases/alphafold/databases \
  --model_preset=monomer \
  --db_preset=reduced_dbs \
  --max_template_date=2022-01-01 \
  --nouse_gpu_relax \
  --uniref90_database_path=/local_databases/alphafold/databases/uniref90/uniref90.fasta \
  --mgnify_database_path=/local_databases/alphafold/databases/mgnify/mgy_clusters_2022_05.fa \
  --template_mmcif_dir=/local_databases/alphafold/databases/pdb_mmcif/mmcif_files \
  --obsolete_pdbs_path=/local_databases/alphafold/databases/pdb_mmcif/obsolete.dat \
  --small_bfd_database_path=/local_databases/alphafold/databases/small_bfd/bfd-first_non_consensus_sequences.fasta \
  --pdb70_database_path=/local_databases/alphafold/databases/pdb70/pdb70
```

### Via predict-structure (host CLI, apptainer backend)

```bash
# Boltz via predict-structure
CUDA_VISIBLE_DEVICES=2 conda run -n predict-structure \
  predict-structure boltz \
  --protein test_data/simple_protein.fasta \
  -o /tmp/test-boltz-ps \
  --num-samples 1 --use-msa-server \
  --backend apptainer --sif /scout/containers/folding_260328.3.sif

# Chai via predict-structure
CUDA_VISIBLE_DEVICES=3 conda run -n predict-structure \
  predict-structure chai \
  --protein test_data/simple_protein.fasta \
  -o /tmp/test-chai-ps \
  --num-samples 1 --use-msa-server \
  --backend apptainer --sif /scout/containers/folding_260328.3.sif

# ESMFold via predict-structure
CUDA_VISIBLE_DEVICES=7 conda run -n predict-structure \
  predict-structure esmfold \
  --protein test_data/simple_protein.fasta \
  -o /tmp/test-esm-ps \
  --num-recycles 4 --fp16 \
  --backend apptainer --sif /scout/containers/folding_260328.3.sif

# Auto via predict-structure
CUDA_VISIBLE_DEVICES=7 conda run -n predict-structure \
  predict-structure auto \
  --protein test_data/simple_protein.fasta \
  -o /tmp/test-auto-ps \
  --backend apptainer --sif /scout/containers/folding_260328.3.sif
```

### Via predict-structure (inside container, subprocess backend)

```bash
# ESMFold inside container
CUDA_VISIBLE_DEVICES=7 apptainer exec --nv \
  --bind /scout --bind /tmp --bind /local_databases \
  /scout/containers/folding_260327.3.sif \
  /opt/conda-predict/bin/predict-structure esmfold \
  --protein /home/wilke/Development/PredictStructureApp/test_data/simple_protein.fasta \
  -o /tmp/test-esm-inside \
  --num-recycles 4 --fp16

# Auto inside container
CUDA_VISIBLE_DEVICES=7 apptainer exec --nv \
  --bind /scout --bind /tmp --bind /local_databases \
  /scout/containers/folding_260327.3.sif \
  /opt/conda-predict/bin/predict-structure auto \
  --protein /home/wilke/Development/PredictStructureApp/test_data/simple_protein.fasta \
  -o /tmp/test-auto-inside
```

## Blocking Issues

### 1. Boltz cu130 — nvrtc builtins not on LD_LIBRARY_PATH
- **Root cause**: `pip install boltz[cuda]` pulled torch 2.11+cu130; the nvrtc builtins ship at `/opt/conda-boltz/lib/python3.11/site-packages/nvidia/cu13/lib/` but aren't on `LD_LIBRARY_PATH`
- **Two fixes applied**:
  1. `all-build.def` `%environment`: added `LD_LIBRARY_PATH` for cu13 libs (line 46)
  2. `reqts-boltz.def` + `all-build.def`: added `--extra-index-url .../cu121` to prevent cu130 in future builds
- **Status**: RESOLVED in `folding_260328.3.sif`

### 2. `tools.yml` missing from containers
- `tools.yml` exists on `cwl/tools` branch, not merged to `main`
- Container builds install from `main`: `pip install "predict-structure[chai,cwl] @ git+https://github.com/CEPI-dxkb/PredictStructureApp.git"`
- **Fix**: merge `cwl/tools` → `main`, or change build def to install from branch
- **Workaround**: use host predict-structure with `--backend apptainer --sif <SIF>`

### 3. Auto fails when boltz fails
- Auto selects boltz (first choice for protein+GPU), which inherits the cu130 issue
- **Status**: RESOLVED in `folding_260328.3.sif` (boltz works, auto should work)

## Fixes Applied This Session

| Fix | File | Description |
|-----|------|-------------|
| GPU flag for ESMFold | `predict_structure/cli.py:468` | `requires_gpu and device != "cpu"` → `device != "cpu"` |
| Boltz LD_LIBRARY_PATH | `all-build.def` %environment | Added cu13 lib path for nvrtc builtins |
| Boltz cu121 pinning | `reqts-boltz.def`, `all-build.def` | Added `--extra-index-url .../cu121` to `pip install boltz[cuda]` |
| Chai cu121 pinning | `reqts-chai.def`, `all-build.def` | Added `--extra-index-url .../cu121` to `pip install chai-lab` |
| ESMFold torch CVE | `reqts-esmfold.def`, `all-build.def` | `torch>=2.0` → `torch>=2.6` (cu124) |
| ESMFold torch CVE | `Dockerfile.predict-structure-all` | `torch` → `torch>=2.6` |
| CWL namespace | all `cwl/tools/*.cwl` | `gowe.commonwl.org` → `github.com/wilke/GoWe` |
| DockerRequirement | all `cwl/tools/*.cwl` | Moved from requirements to hints |
| SIF image names | all `cwl/tools/*.cwl` | Registry names → `.sif` filenames |
| gowe:Execution | boltz/chai/alphafold CWL | Added `executor: worker` hint |
| model_cache_dir | boltz/chai/esmfold CWL | Unified cache dir input with defaults |
| AlphaFold defaults | `cwl/tools/alphafold.cwl` | `use_gpu_relax: false`, `data_dir` default |

## Build Command

```bash
cd ~/Development/runtime_build/gpu-builds/cuda-12.2-cudnn-8.9.6 && \
sudo apptainer build \
  --build-arg runtime=/home/olson/BV-BRC/runtime_build/gpu-builds/runtime-137-12.tgz \
  --build-arg packages=/home/olson/BV-BRC/runtime_build/gpu-builds/packages-137-12.txt \
  --warn-unused-build-args \
  /scout/containers/folding_<date>.<idx>.sif \
  all-build.def
```
