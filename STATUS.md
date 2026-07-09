# Project Status

**Last updated:** 2026-07-08
**Current version:** v0.17.0 (HEAD: e653c5a)
**Production container:** `folding_260622.3.sif`

## What's done

### Bug fixes (2026-07-08, on main)

- **Fix #67: MSA NUL byte stripping** (83e4c17) — ColabFold MSA servers append trailing `\x00` that crashes OpenFold 3's parser and corrupts Chai A3M→Parquet conversion. Added `_stage_msa_sanitized()` in converters.py; applied in OpenFold JSON builder, A3M parser, and Chai Parquet converter.
- **Fix #81: Boltz normalizer crash with SMILES ligands** (a00dc8a) — Boltz CIF with SMILES ligands labels all atoms as HETATM, causing `_extract_bfactors()` to return empty arrays and `write_confidence_json()` to crash. Fixed: HETATM fallback in extractor + graceful omission of per_atom_plddt when empty/short.
- **CLAUDE.md branching rule** (e653c5a) — Added convention: never commit fixes/features directly to main, always use feature branches.

### New issues created (2026-07-08)

| # | Title | Type |
|---|---|---|
| 72 | Workspace file upload not immediately visible | UI bug |
| 73 | File browser: cannot re-highlight a different file | UI bug |
| 74 | 3Dmol.js viewer not showing secondary structures in cartoon mode | Report bug |
| 75 | Add ESMFold2 to UI tool selector | Enhancement |
| 76 | Add DSSP as post-prediction step | Enhancement |
| 77 | Per-model protein length limits with clear error messages | Enhancement |
| 78 | Report viewer: Reset View / Spin button issues | Report bug |
| 79 | B-factor distribution bars invisible when value is zero | Report bug |
| 80 | Report: add TOC/index, reorder B-factor sections | Report enhancement |
| 81 | Boltz normalizer crash with SMILES ligands | Bug (fixed) |

### v0.17.0 — ESMFold2 adapter + report provenance (2026-06-09 → 2026-06-22)

- **ESMFold2 adapter** (PR #44, merged) — new diffusion-based tool, multi-entity support
- **Report provenance** (PR #70 + protein_compare PR #7) — HTML reports now include Job Provenance section showing tool, version, status, runtime, container, parameters, and inputs from `metadata.json`
- **Version bump** — predict-structure 0.17.0, pyproject.toml synced
- **11 PRs merged** (#57-68) — preflight fixes, container boltz CUDA-13 libs, alphafold multimer preset, chai token validation, openfold MSA server URL, ESMFold2 tests, CI container build, app_spec text_input, HF_HUB_OFFLINE, Phase1 test tiers

### Test results (folding_260622.3.sif, 2026-06-23)

| Category | Cases | Pass | Fail | Notes |
|---|---|---|---|---|
| Tool × entity | 24 | 24 | 0 | Boltz, OpenFold, Chai, ESMFold, auto |
| Parameter variations | 14 | 14 | 0 | samples, recycles, mmcif, debug, seed |
| **Total** | **38** | **38** | **0** | All 3 GPU hosts exercised |

### Host coverage (folding_260622.3.sif)

| Host | Jobs | Tools |
|---|---|---|
| coconut (H200) | 23 | Boltz, ESMFold, auto, some OpenFold/Chai |
| mango (H100) | 11 | OpenFold (MSA/DNA/RNA/SMILES), Chai, param variants |
| peach (V100) | 4 | Chai (MSA/RNA/2samples) |

### Unit test results (2026-07-08)

457 passed, 10 skipped (full suite including #67 and #81 regression tests)

## What's pending

### Uncommitted local changes

| Item | Status | Notes |
|---|---|---|
| Container def fixes | Uncommitted | Dockerfile.predict-structure-all, folding-from-base.def, predict-structure-all.def |

### Open issues (by priority)

| # | Issue | Priority | Notes |
|---|---|---|---|
| 81 | Boltz normalizer crash with SMILES | **Fixed** | a00dc8a — needs next container build |
| 67 | MSA NUL bytes crash OpenFold/Chai | **Fixed** | 83e4c17 — needs next container build |
| 38 | Boltz only works on coconut | Medium | torch+cu130 needs CUDA 13.0; rebuild with cu124 for mango/peach |
| 77 | Per-model protein length limits | Medium | CLI + UI validation with tool-specific error messages |
| 75 | Add ESMFold2 to UI tool selector | Medium | app_spec + service script registration |
| 76 | DSSP as post-prediction step | Medium | Secondary structure assignment for reports |
| 74 | 3Dmol.js cartoon mode missing secondary structures | Low | protein_compare report template |
| 78 | Report viewer Reset View / Spin buttons | Low | protein_compare report template |
| 79 | B-factor distribution zero-height bars | Low | protein_compare report template |
| 80 | Report TOC/index + section reorder | Low | protein_compare report template |
| 72 | Workspace file upload not immediately visible | Low | BV-BRC UI |
| 73 | File browser re-highlight broken | Low | BV-BRC UI |

### Host coverage gaps

| Tool | Host | Why |
|---|---|---|
| ESMFold | mango, peach | No GPU constraint; scheduler always picks coconut |
| OpenFold | peach | H100\|H200 constraint excludes V100 |
| AlphaFold | Not tested | Not included in 260622 matrix run |

## Infrastructure

### Folding tools (production SIF: folding_260622.3.sif)

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
| folding_260622.3.sif | 2026-06-22 | **Production** | v0.17.0 + report provenance; 38/38 tests pass |
| folding_260622.2.sif | 2026-06-22 | Previous prod | v0.17.0 + report provenance (PR #70); 38/38 tests pass |
| folding_260622.1.sif | 2026-06-22 | Retired | v0.17.0, ESMFold2 adapter, 11 PRs merged; 38/38 tests pass |
| folding_260602.1.sif | 2026-06-02 | Previous prod | v0.16.1, GPU precheck, MSA validation, run log; 47/47 tests pass |
| folding_260601.1.sif | 2026-06-01 | Bad build | Broken on mango (CUDA 12.6); all OF/Chai/AF jobs failed in ~9s |
| folding_260522.1.sif | 2026-05-22 | Retired | Fixed 90-environment.sh, env vars; 48/49 tests pass |
| folding_260515.2.sif | 2026-05-15 | Retired | v0.16.1, 101/101 tests pass; broken 90-environment.sh |

### Key paths

| Path | Purpose |
|---|---|
| /scout/containers/folding_prod.sif | Production symlink → folding_260622.3.sif |
| /scout/containers/folding_260622.3.sif | Current production SIF (34 GB) |
| /vol/patric3/production/containers/folding_260622.3.sif | BV-BRC production copy |
| /disks/patric-common/container-cache/ | BV-BRC scheduler container cache |
| /local_databases/ | All tool weights + caches (bind-mounted) |
| ~/.patric_token | BV-BRC auth token |

### Repos

| Repo | Version | Branch | Last commit | Pushed? |
|---|---|---|---|---|
| PredictStructureApp | v0.17.0 | main | e653c5a (branching rule + #67 + #81 fixes) | YES |
| protein_compare | v0.2.1 | main | c7cd9c6 (PR #7 merged) | YES |

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
