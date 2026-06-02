# Project Status

**Last updated:** 2026-06-02
**Current version:** v0.16.1 (HEAD: a1a853c, merged PR #42)
**Production container:** `folding_260602.1.sif`

## What's done

### v0.16.1 bug fixes (committed, pushed, tagged)

- **SMILES normalizer crash** -- Boltz PDB output for ligand-containing structures has corrupted line layout that crashes BioPython's PDB parser (upstream Boltz #298, #630). Fixed by preferring mmCIF over PDB in `_extract_bfactors()` and `promote_best_model()`.
- **protein_compare report crash** -- Same root cause. Fixed in protein_compare v0.2.1: `StructureLoader.load()` prefers `.cif` sibling when loading `.pdb` files.
- **Boltz GPU constraint** -- Changed preflight constraint from `V100|H100|H200` to `H200` only (cu130 needs CUDA 13.0+).
- **AlphaFold DB path** -- Fixed `/databases` to `/local_databases/alphafold/databases`.
- **CIF promotion** -- `promote_best_model()` copies `model_1.cif` alongside `.pdb` to top-level output.

### folding_260522.1.sif container fixes

- **90-environment.sh crash** -- `[[ ]]` bash syntax in `#!/bin/sh` script with empty if-block bodies crashed the env script, preventing `source /opt/p3/deployment/user-env.sh` from running. `p3x-app-shepherd` and `p3x-run-preflight` were not on `$PATH`. Fixed by replacing conditional if-blocks with unconditional exports in `predict-structure-all.def` and `folding-from-base.def`.
- **Wrong env var names** -- `OPENFOLD3_CACHE_DIR` renamed to `OPENFOLD_CACHE` (what OpenFold 3 actually reads). Removed `DISABLE_PANDERA_IMPORT_WARNING` (not read by Pandera).
- **Wrong HF_HOME path** -- Changed from `/local_databases/huggingface` (or `/local_databases/cache`) to `/local_databases/esmfold` (actual location on disk). Fixed in all three container defs.
- **Singularity CE 3.10 on gum** -- Initial deploy failed with `bad superblock for squashfs`. Fixed by deleting corrupt cache entry on gum and re-pulling.
- **Boltz weights missing** -- `/local_databases` moved to separate 4TB volume; Boltz cache was empty. Re-downloaded mols.tar + boltz2_conf.ckpt + boltz2_aff.ckpt (5.8 GB).

### PR #42: GPU VRAM precheck, MSA validation, run logging (merged 2026-06-01)

- **GPU VRAM precheck** (`gpu_check.py`) -- queries `nvidia-smi` before tool launch, fails fast when GPU VRAM is consumed by non-slurm processes. Per-tool thresholds on each adapter.
- **MSA format validation** (`msa_check.py`) -- sniffs first 4 KiB to detect format mismatches before expensive tool execution.
- **Run log** -- writes `predict_structure.log` to output dir with host, CUDA device, slurm job ID, command, exit code, and post-mortem VRAM state on failure.

### Testing infrastructure (committed post-tag, at 260dcc1)

- **scripts/submit_api_tests.py** -- Automated BV-BRC API test runner (submit, poll, host tracking, reporting)
- **test_data/service_params/api_test_matrix.json** -- v2 matrix: 49 cases (29 tool x entity, 12 param variations, 8 negative)
- **docs/Testreport-20260515.1.md** -- Full test results for folding_260515.2.sif

### Test results (folding_260602.1.sif, 2026-06-02)

| Category | Cases | Pass | Fail | Notes |
|---|---|---|---|---|
| Positive (tool x entity) | 29 | 29 | 0 | All tools pass on both hosts |
| Parameter variations | 12 | 12 | 0 | |
| Negative (validation) | 5 | 5 | 0 | N03-N07 expected fail |
| AlphaFold | 1 | 1 | 0 | A01 on mango, 21:46 |
| **Total** | **47** | **47** | **0** | |

### Host coverage (folding_260602.1.sif)

| Host | Jobs | Tools |
|---|---|---|
| coconut | 27 | ESMFold, Boltz, OpenFold, Chai, auto |
| mango | 12 | OpenFold, Chai, AlphaFold |

### folding_260601.1.sif — broken build (2026-06-01)

- All OpenFold, Chai, and AlphaFold jobs failed on mango in ~9 seconds
- Boltz and ESMFold on coconut passed (coconut-only tools unaffected)
- Root cause: container-level breakage on CUDA 12.6 hosts
- Fixed in folding_260602.1.sif

### Previous test results (folding_260522.1.sif, 2026-05-28)

| Category | Cases | Pass | Fail | Notes |
|---|---|---|---|---|
| Positive (tool x entity) | 27 | 26 | 1 | C04_chai_rna failed on mango only |
| Parameter variations | 12 | 12 | 0 | |
| Negative (validation) | 10 | 10 | 0 | N01/N02/N08 = API 500 (preflight); N03-N07 = expected fail |
| **Total** | **49** | **48** | **1** | |

### Previous test results (folding_260515.2.sif, 2026-05-15/16)

| Category | Cases | Pass | Fail |
|---|---|---|---|
| Positive (tool x entity) | 29 | 29 | 0 |
| Parameter variations | 12 | 12 | 0 |
| Negative (validation) | 10 | 10 | 0 |
| Saturation (10 per tool x 5) | 50 | 50 | 0 |
| **Total** | **101** | **101** | **0** |

## What's pending

### Immediate (before next release)

| Item | Status | Notes |
|---|---|---|
| Push protein_compare v0.2.1 | Blocked | SSH key issue with git@github.com:wilke/protein_structure_analysis.git |

### Open issues

| # | Issue | Status | Notes |
|---|---|---|---|
| 38 | Boltz only works on coconut | Open | torch+cu130 needs CUDA 13.0; rebuild with cu124 for mango/peach |
| 39 | Add prediction provenance to report | Open | protein_compare enhancement |
| 40 | ESMFold contacts HuggingFace Hub on every run | Open | Set HF_HUB_OFFLINE=1 in SIF %environment |
| 41 | Boltz PDB ligand lines crash BioPython | **Fixed** | v0.16.1 + protein_compare v0.2.1 |

### Host coverage gaps

| Tool | Host | Why |
|---|---|---|
| ESMFold | mango, peach | No GPU constraint; scheduler always picks coconut |
| OpenFold | peach | H100\|H200 constraint excludes V100 |

### Future work

- Run negative test matrix via API (N01-N08 partially tested; N01/N02/N08 cause API 500 at preflight)
- Phase 4 submission script improvements: retry logic, workspace output verification
- Issue #38: evaluate torch+cu124 rebuild for Boltz
- Issue #40: HF_HUB_OFFLINE=1 for ESMFold

## Infrastructure

### Folding tools (production SIF: folding_260602.1.sif)

| Tool | Package | Version | PyTorch / Framework | ML Model | Checkpoint / Weights |
|---|---|---|---|---|---|
| Boltz | `boltz[cuda]` | 2.2.1 | torch 2.11.0 (cu130) | Boltz-2 | Auto-downloaded to `$BOLTZ_CACHE` |
| OpenFold | `openfold3` | 0.4.1 | torch 2.5.1+cu121 | OpenFold 3 (AF3-class) | `of3-p2-155k.pt` |
| Chai | `chai-lab` | 0.6.1 | torch 2.5.1+cu121 | Chai-1 | Auto-downloaded to `$CHAI_DOWNLOADS_DIR` |
| AlphaFold | `wilke/alphafold` (fork) | git HEAD | JAX 0.4.26 + jaxlib 0.4.26+cuda12.cudnn89 | AlphaFold 2 | Genetic DBs (~2TB) in `$AF2_DATA_DIR` |
| ESMFold | `transformers` | 5.8.0 | torch 2.6.0+cu124 | ESMFold v1 (ESM-2 3B backbone) | HuggingFace Hub → `$HF_HOME` |

- Boltz torch+cu130 requires CUDA 13.0+ — only runs on coconut (H200)
- OpenFold/Chai share torch+cu121 — run on all three hosts
- ESMFold uses HuggingFace `transformers` (`EsmForProteinFolding`), not legacy fair-esm
- AlphaFold uses a custom fork with JAX (not PyTorch), no pinned version

### GPU hosts

| Host | GPU | Count | VRAM | CUDA | Boltz (cu130) | OF/Chai (cu121) | ESMFold (cu124) |
|---|---|---|---|---|---|---|---|
| coconut | H200 NVL | 8x | 141 GB | 13.0 | YES | YES | YES |
| mango | H100 NVL | 8x | 95 GB | 12.6 | NO | YES | YES |
| peach | V100 PCIE | 2x | 32 GB | 12.2 | NO | YES | YES |

### Container history

| SIF | Date | Status | Notes |
|---|---|---|---|
| folding_260602.1.sif | 2026-06-02 | **Production** | GPU precheck, MSA validation, run log; 47/47 tests pass |
| folding_260601.1.sif | 2026-06-01 | Bad build | Broken on mango (CUDA 12.6); all OF/Chai/AF jobs failed in ~9s |
| folding_260522.1.sif | 2026-05-22 | Previous prod | Fixed 90-environment.sh, env vars; 48/49 tests pass |
| folding_260515.2.sif | 2026-05-15 | Retired | v0.16.1, 101/101 tests pass; broken 90-environment.sh |
| folding_260515.1.sif | 2026-05-15 | Bad build | Stale predict_structure code (cached wheel) |
| folding_260514.4.sif | 2026-05-14 | Bad build | Scheduler instant-fail (container cache issue) |
| folding_260514.2.sif | 2026-05-14 | Bad build | Stale predict_structure code (cached wheel) |
| folding_260513.1.sif | 2026-05-13 | Retired | v0.16.0, no SMILES fix |

### Key paths

| Path | Purpose |
|---|---|
| /scout/containers/folding_prod.sif | Production symlink → folding_260602.1.sif |
| /scout/containers/folding_260602.1.sif | Current production SIF |
| /vol/patric3/production/containers/folding_260602.1.sif | BV-BRC production copy |
| /disks/patric-common/container-cache/ | BV-BRC scheduler container cache |
| /local_databases/ | All tool weights + caches (bind-mounted) |
| ~/.patric_token | BV-BRC auth token |

### Repos

| Repo | Version | Branch | Last commit | Pushed? |
|---|---|---|---|---|
| PredictStructureApp | v0.16.1+ | main | a1a853c (PR #42 merged) | YES |
| protein_compare | v0.2.1 | main | 3918cbd (comment fix) | NO (SSH) |

## How to resume

### Re-run the full test matrix
```bash
python3 scripts/submit_api_tests.py matrix --include-alphafold
```

### Re-run saturation for a single tool
```bash
python3 scripts/submit_api_tests.py saturate <tool> -n 10
```

### Test a new SIF locally (Boltz+SMILES, hardest case)
```bash
WORKDIR=$(mktemp -d)
apptainer exec --nv \
    --bind $WORKDIR:/work --bind /local_databases:/local_databases \
    --bind $PWD/test_data:/data \
    --env P3_WORKDIR=/work --env HF_HOME=/local_databases/cache \
    /scout/containers/<new>.sif \
    perl /build/dev_container/modules/PredictStructureApp/service-scripts/App-PredictStructure.pl \
        "" /build/dev_container/modules/PredictStructureApp/app_specs/PredictStructure.json \
        /tmp/test_boltz_smiles.json
ls $WORKDIR/output/{model_1.pdb,model_1.cif,report.html,results.json}
```

### Verify SIF has correct code (don't trust version alone)
```bash
SIF=/scout/containers/<new>.sif
apptainer exec $SIF /opt/conda-predict/bin/python -c "import predict_structure; print(predict_structure.__version__)"
apptainer exec $SIF grep "constraint" /opt/conda-predict/lib/python3.12/site-packages/predict_structure/adapters/boltz.py
apptainer exec $SIF grep "MMCIFParser" /opt/conda-predict/lib/python3.12/site-packages/predict_structure/normalizers.py
apptainer exec $SIF grep -A3 "cif_src = src.with_suffix" /opt/conda-predict/lib/python3.12/site-packages/predict_structure/normalizers.py
apptainer exec $SIF grep "Boltz PDB" /opt/conda-predict/lib/python3.12/site-packages/protein_compare/io/parser.py
```

### After BV-BRC image switch
1. Wait 60s for scheduler to cache SIF
2. Submit one ESMFold job first (`python3 scripts/submit_api_tests.py matrix --tests E01`)
3. If instant-fail: check container cache disk space on compute nodes
4. If API hangs: preflight is mounting SIF for first time, retry with patience
5. Once ESMFold passes, submit full matrix
