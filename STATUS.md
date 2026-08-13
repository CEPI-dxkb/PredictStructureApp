# Project Status

**Last updated:** 2026-08-13
**Current version:** v0.17.0 (HEAD: abda889)
**Production container:** `folding_260813.2.sif`

## Next action

`folding_260813.2.sif` is deployed and the full API matrix passes **48/48**.
Open PRs to land: #87 (this branch), #89 (test-runner cold-start fix).

Then: decide #85 (retire AlphaFold 2) — it is the only thing keeping AlphaFold
cases out of the matrix — and pick up #50, whose report side is already built
and only needs the Boltz PAE npz converted to `predictions/pae.json`.

### Resolved 2026-08-13: submission failure after the container switch

Every `start_app2` call returned HTTP 500 with an empty detail
(`"Error submitting job: \n"`). Root cause: the **ApplicationDefaultContainer**
row for PredictStructure pointed at `folding_260513.1`, whose SIF no longer
exists anywhere. The scheduler runs preflight *inside* the registered
container, so a missing container produces no output and hence an empty error.
Repointing the row at `folding_260813.2` fixed it.

Diagnostic order that worked, for next time:
1. Submit the trivial `Date` app — it succeeded, proving the scheduler, auth,
   and workspace paths were fine and the fault was app-specific.
2. Run preflight the way the scheduler does (`--preflight` + `--user-error-file`
   against the deployed `plbin` copy) — exit 0 and valid JSON exonerated the
   app code.
3. Check `p3x-show-container-config` on `gum` and confirm the app's container
   filename actually exists.

Do **not** use `AppService.enumerate_apps` to check whether an app is
registered: it returns a curated 39-app list that never includes
PredictStructure, on production, www, and alpha alike. That misled this
investigation.

After repointing, the first submission still took **464 s** while a 32 GB SIF
was staged into the container cache — the runner's flat 120 s timeout turned
that routine cold start into three more spurious failures. Fixed in #89.

## What's done

### Preflight validation + container rebuild (2026-08-13)

- **Fix #84: reject tool/entity mismatches at submit** (abda889, PR #86) —
  jobs whose inputs a tool cannot handle were scheduled on a GPU node and only
  then failed with a traceback; prod job 23403506 held an 8h GPU reservation
  before dying in 8s. Preflight cannot read workspace files, so validation now
  runs off declared kinds (`--has-protein/--has-dna/--has-rna/--has-ligand/
  --has-smiles`). Rejections travel as exit 3 + a JSON error payload, which the
  Perl converts into a clean `die`. Also fixed a pre-existing bug where
  `return` inside a `Try::Tiny` catch was dead code, silently scheduling GPU
  tools with no GPU constraint.
- **Fix #82: Chai CCD ligands** (8ac583f, PR #83) — Chai's FASTA needs SMILES,
  so a CCD code was silently dropped and it folded protein-only, exit 0.
- **Container env vars corrected** (cbc9ab0) — `OPENFOLD_CACHE` (the variable
  openfold3 actually reads; the old one was inert), `TORCH_HOME` pointed at a
  nonexistent directory, `DISABLE_PANDERA_IMPORT_WARNING` kept after verifying
  pandera does read it.
- **Two containers built** — `folding_260813.1.sif` (#67/#81/#82) and
  `folding_260813.2.sif` (adds #84). Both deployed to
  `/vol/patric3/production/containers/`.
- **ESMFold2 cache unblocked** — weights were already at
  `/local_databases/esmfold/hub/models--biohub--ESMFold2` but the directory was
  not group-writable, so the Perl's `-w` probe rejected it, fell through to
  `/local_databases/cache` (which lacks ESMFold2), and forced
  `HF_HUB_OFFLINE=1`. Permissions fixed; both ESMFold and ESMFold2 now resolve
  offline from the same cache. Likely the mechanism behind #75.
- **Issues filed** — #84 (preflight validation, fixed), #85 (decommission
  AlphaFold 2 in favour of ESMFold2, blocked by #75).

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

### Unit test results (2026-08-13)

473 passed, 10 skipped. Run with
`python -m pytest tests/ -q --ignore=tests/acceptance` — `tests/acceptance/`
shells out to real 32 GB containers via `apptainer exec` and takes far longer
than the rest of the suite combined.

### API test matrix (folding_260813.2.sif, 2026-08-13)

`docs/test-reports/matrix_20260813_160754.json` — **48 pass, 0 fail.**

| Category | Cases | Result |
|---|---|---|
| Boltz | 9 | all pass (coconut only — cu130 needs H200) |
| OpenFold | 6 | all pass (mango) |
| Chai | 5 | all pass (peach, mango, coconut) |
| ESMFold / auto / parameter variations | 20 | all pass |
| **Submit-time rejections** | **8** | **all refused before scheduling** |
| Worker-side failures (N03, N07) | 2 | scheduled, then failed as expected |

Hosts: coconut 25, mango 10, peach 5.

**#84 verified in production.** E02, C05, R02, N04, N06 were refused at submit
with no task created and no GPU allocated, and the messages reach the client
intact inside the JSON-RPC error body, e.g.:

> Error submitting job: Error running preflight checks: Chai-1 cannot accept
> CCD-coded ligands; its FASTA format requires SMILES strings. Supply the
> ligand as SMILES via --smiles, or use Boltz-2 or OpenFold 3 …

R03 also passes: `auto` + DNA + CCD ligand resolves to a tool that accepts
them, confirming auto no longer routes CCD ligands to Chai.

Not covered: R01/A01/A02 (AlphaFold), excluded by default — revisit with #85.

Known wart: the older `_validate_params` rejections (N01, N02, N08) still leak
a Perl backtrace into the user-visible message. The #84 path suppresses it via
`local $SIG{__DIE__} = 'DEFAULT'`; the same one-liner would clean these up.

## What's pending

### Open issues (by priority)

| # | Issue | Priority | Notes |
|---|---|---|---|
| 85 | Decommission AlphaFold 2, replace with ESMFold2 | High | Blocked by #75 |
| 75 | ESMFold2 in UI but not functional | High | Cache permissions fixed 2026-08-13; recheck |
| 77 | Per-model protein length limits | Medium | CLI + UI validation with tool-specific error messages |
| 76 | DSSP as post-prediction step | Medium | Secondary structure assignment for reports |
| 48 | CCD ligand input rejects glycans with parentheses | Medium | Validation regex |
| 50 | Add PAE score to the report | Low | protein_compare |
| 51 | Job progress indicator | Low | BV-BRC UI |
| 52 | Docs: multi-chain applies to DNA/RNA too | Low | Docs |
| 79 | B-factor distribution zero-height bars | Low | protein_compare report template |
| 80 | Report TOC/index + section reorder | Low | protein_compare report template |
| 72 | Workspace file upload not immediately visible | Low | BV-BRC UI |
| 73 | File browser re-highlight broken | Low | BV-BRC UI |
| 18 | Nucleic acid secondary structure (DSSR) | Low | Enhancement |

Closed since last update: #67, #74, #78, #81, #82, #84 (plus #8, #11, #12, #15,
#45 triaged closed).

### Host coverage gaps

| Tool | Host | Why |
|---|---|---|
| ESMFold | mango, peach | No GPU constraint; scheduler always picks coconut |
| OpenFold | peach | H100\|H200 constraint excludes V100 |
| AlphaFold | Not tested | Not included in 260622 matrix run |

## Infrastructure

### Folding tools (production SIF: folding_260813.2.sif)

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
| folding_260813.2.sif | 2026-08-13 | **Production** | +#84 preflight validation; predict_structure abda889. API matrix not yet run (blocked) |
| folding_260813.1.sif | 2026-08-13 | Superseded | #67 + #81 + #82, corrected cache env vars; predict_structure 8ac583f |
| folding_260622.3.sif | 2026-06-22 | Previous prod | v0.17.0 + report provenance; 38/38 tests pass |
| folding_260622.2.sif | 2026-06-22 | Previous prod | v0.17.0 + report provenance (PR #70); 38/38 tests pass |
| folding_260622.1.sif | 2026-06-22 | Retired | v0.17.0, ESMFold2 adapter, 11 PRs merged; 38/38 tests pass |
| folding_260602.1.sif | 2026-06-02 | Previous prod | v0.16.1, GPU precheck, MSA validation, run log; 47/47 tests pass |
| folding_260601.1.sif | 2026-06-01 | Bad build | Broken on mango (CUDA 12.6); all OF/Chai/AF jobs failed in ~9s |
| folding_260522.1.sif | 2026-05-22 | Retired | Fixed 90-environment.sh, env vars; 48/49 tests pass |
| folding_260515.2.sif | 2026-05-15 | Retired | v0.16.1, 101/101 tests pass; broken 90-environment.sh |

### Key paths

| Path | Purpose |
|---|---|
| /scout/containers/folding_prod.sif | Local testing symlink → folding_260813.2.sif |
| /scout/containers/folding_260813.2.sif | Current SIF, local build (32 GB) |
| /vol/patric3/production/containers/folding_260813.2.sif | BV-BRC copy — promotion step: `cp` here |
| /disks/patric-common/container-cache/ | BV-BRC scheduler container cache |
| /local_databases/ | All tool weights + caches (bind-mounted) |
| ~/.patric_token | BV-BRC auth token |

### Repos

| Repo | Version | Branch | Last commit | Pushed? |
|---|---|---|---|---|
| PredictStructureApp | v0.17.0 | main | abda889 (#84 preflight validation) | YES |
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
