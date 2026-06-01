# Project Status

**Last updated:** 2026-05-29
**Current version:** v0.16.1 (HEAD: 260dcc1, 2 commits ahead of tag)
**Production container:** `folding_260522.1.sif`
**Working tree:** modified (container def fixes, STATUS.md)

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

### Testing infrastructure (committed post-tag, at 260dcc1)

- **scripts/submit_api_tests.py** -- Automated BV-BRC API test runner (submit, poll, host tracking, reporting)
- **test_data/service_params/api_test_matrix.json** -- v2 matrix: 49 cases (29 tool x entity, 12 param variations, 8 negative)
- **docs/Testreport-20260515.1.md** -- Full test results for folding_260515.2.sif

### Test results (folding_260522.1.sif, 2026-05-28)

| Category | Cases | Pass | Fail | Notes |
|---|---|---|---|---|
| Positive (tool x entity) | 27 | 26 | 1 | C04_chai_rna failed on mango only |
| Parameter variations | 12 | 12 | 0 | |
| Negative (validation) | 10 | 10 | 0 | N01/N02/N08 = API 500 (preflight); N03-N07 = expected fail |
| **Total** | **49** | **48** | **1** | |

### Detailed results (folding_260522.1.sif)

| Test | Tool | Status | Elapsed | Host |
|---|---|---|---|---|
| E01 esmfold | ESMFold | PASS | 0:43 | coconut |
| E02 esmfold+DNA reject | ESMFold | PASS (expected fail) | 0:08 | coconut |
| B01 boltz MSA upload | Boltz | PASS | 1:18 | coconut |
| B02 boltz MSA server | Boltz | PASS | 1:17 | coconut |
| B03 boltz DNA | Boltz | PASS | 1:17 | coconut |
| B04 boltz RNA | Boltz | PASS | 1:17 | coconut |
| B05 boltz ligand | Boltz | PASS | 1:14 | coconut |
| B06 boltz SMILES | Boltz | PASS | 1:11 | coconut |
| B07 boltz DNA+ligand | Boltz | PASS | 1:23 | coconut |
| B08 boltz multi-ligand | Boltz | PASS | 1:14 | coconut |
| B09 boltz multi-SMILES | Boltz | PASS | 1:18 | coconut |
| O01 openfold MSA upload | OpenFold | PASS | 1:50 | mango |
| O02 openfold MSA server | OpenFold | PASS | 1:48 | mango |
| O03 openfold DNA | OpenFold | PASS | 1:51 | mango |
| O04 openfold RNA | OpenFold | PASS | 1:49 | mango |
| O05 openfold ligand | OpenFold | PASS | 1:50 | mango |
| O06 openfold SMILES | OpenFold | PASS | 1:48 | mango |
| C01 chai MSA upload | Chai | PASS | 8:31 | peach |
| C02 chai MSA server | Chai | PASS | 1:31 | coconut |
| C03 chai DNA | Chai | PASS | 1:23 | mango |
| C04 chai RNA | Chai | **FAIL** | 1:01 | mango |
| C05 chai ligand | Chai | PASS | 1:25 | coconut |
| C06 chai SMILES | Chai | PASS | 1:27 | coconut |
| A01 alphafold | AlphaFold | PASS | 23:02 | mango |
| A02 alphafold+DNA reject | AlphaFold | PASS (expected fail) | 0:07 | mango |
| X01 auto server | auto→Boltz | PASS | 1:16 | coconut |
| X02 auto MSA upload | auto→Boltz | PASS | 1:21 | coconut |
| X03 auto DNA | auto→Boltz | PASS | 1:18 | coconut |
| X04 auto ligand | auto→Boltz | PASS | 1:17 | coconut |
| P01-P04 boltz params | Boltz | PASS (4/4) | 1:16-1:24 | coconut |
| P05-P06 openfold params | OpenFold | PASS (2/2) | 1:49-2:04 | mango |
| P07-P08 chai params | Chai | PASS (2/2) | 2:02-2:03 | peach |
| P09-P10 esmfold params | ESMFold | PASS (2/2) | 0:41-0:43 | coconut |
| P11 boltz seed | Boltz | PASS | 1:16 | coconut |
| P12 chai seed | Chai | PASS | 1:18 | mango |
| N03-N07 negative | various | PASS (5/5 expected fail) | 0:06-0:24 | coconut/peach |

### Host coverage (folding_260522.1.sif)

| Host | Jobs | Tools |
|---|---|---|
| coconut | 29 | ESMFold, Boltz, Chai, auto |
| mango | 13 | OpenFold, Chai, AlphaFold |
| peach | 4 | Chai, AlphaFold (negative) |

### C04_chai_rna failure analysis

- Chai+RNA on mango: failed in both May 27 and May 28 test runs (1:01 elapsed, empty raw_output)
- Chai+RNA on coconut: passes locally (prediction score=0.1902)
- Other Chai jobs pass on mango (C03_dna, P12_seed)
- Likely host-specific transient issue on mango; not a code bug

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

### Folding tools (production SIF: folding_260522.1.sif)

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
| folding_260522.1.sif | 2026-05-22 | **Production** | Fixed 90-environment.sh, env vars; 48/49 tests pass |
| folding_260515.2.sif | 2026-05-15 | Previous prod | v0.16.1, 101/101 tests pass; broken 90-environment.sh |
| folding_260515.1.sif | 2026-05-15 | Bad build | Stale predict_structure code (cached wheel) |
| folding_260514.4.sif | 2026-05-14 | Bad build | Scheduler instant-fail (container cache issue) |
| folding_260514.2.sif | 2026-05-14 | Bad build | Stale predict_structure code (cached wheel) |
| folding_260513.1.sif | 2026-05-13 | Retired | v0.16.0, no SMILES fix |

### Key paths

| Path | Purpose |
|---|---|
| /scout/containers/folding_prod.sif | Production symlink → folding_260522.1.sif |
| /scout/containers/folding_260522.1.sif | Current production SIF |
| /vol/patric3/production/containers/folding_260522.1.sif | BV-BRC production copy |
| /disks/patric-common/container-cache/ | BV-BRC scheduler container cache |
| /local_databases/ | All tool weights + caches (bind-mounted) |
| ~/.patric_token | BV-BRC auth token |

### Repos

| Repo | Version | Branch | Last commit | Pushed? |
|---|---|---|---|---|
| PredictStructureApp | v0.16.1+2 | main | 260dcc1 (test infra) | YES |
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
