# Project Status

**Last updated:** 2026-08-17
**Current version:** v0.17.0 (HEAD: c350a68)
**Production container:** `folding_260815.1.sif` (predict_structure 42d6171)

## Next action

Steady state — nothing is blocked on us. The two open work fronts:

1. **Next container rebuild** picks up the protein_compare report fixes
   (#79 zero-count histogram bins, #80 report TOC — merged to
   wilke/protein_structure_analysis main, `7105946`). protein_compare is
   pip-installed from that repo's main in runtime_build's
   `reqts-predict-structure.def`, so no code change here is needed — just
   batch the rebuild with whatever lands next.
2. **Upstream PRs await BV-BRC maintainers:** BV-BRC-Web#1400 (retire
   AlphaFold from UI, add ESMFold2, runtime hints — closes #90's UI half)
   and BV-BRC-Docs#283 (docs sweep — close #52 when it merges). Both were
   consolidated fork-first: reviewed, fixed, and merged in wilke's forks,
   then opened as single upstream PRs.

New issues #104–#109 (filed 2026-08-17, see below) are all small and
unscheduled; #106 (raw output uploaded twice) is the one with real user
impact — GBs of duplicate workspace bytes per Boltz/Chai job.

## What's done

### Session 2026-08-17: reviewer queue emptied + housekeeping

- **#79 fixed** (wilke/protein_structure_analysis#12) — empty histogram
  bins rendered as blank canvas; now a thin colored baseline sliver,
  capped below the smallest populated bar. Reproduction corrected the
  premise: zero-*count* bins, not zero-value data.
- **#80 fixed** (wilke/protein_structure_analysis#13) — Contents nav from
  pre-rendered sections (dead links impossible by construction),
  per-residue profile now precedes the distribution histogram. First
  tests in that repo (5, container-passing).
- **#51 closed** — decision: per-tool runtime expectation hints (live in
  BV-BRC-Web#1400) suffice; the AppService API exposes no within-job
  progress to build a real progress bar from.
- **#103 merged** (c350a68) — README multi-chain wording, corrected during
  review: the 26-record limit is per FASTA file, only the 10,000-residue
  limit counts chains combined. That review surfaced #108.
- **Follow-up issues filed:** #104 (boltz-report-msa.cwl byte-identical
  copy), #105 (select-pae.cwl validate-only coverage), #106 (raw_output/
  + raw/ both uploaded), #107 (test_config.py env restore), #108 (chain
  IDs silently wrap past 26 combined entities), #109 (upstream
  dev_container PYTHONPATH trailing colon — tracking).
- **/local_databases cleanup:** 66 GB reclaimed. Deleted transitional
  ESMC-6B/ESMFold2 copies from `cache/hub` and `esmfold/hub`, plus a
  third `esmfold_v1` copy in `cache/hub`. Canonical layout now:
  `esmfold2/hub` (25 G, ESMFold2 + ESMC-6B), `esmfold/hub` (16 G,
  esmfold_v1 only). Verified before deleting: refs/main → snapshots with
  config.json, no broken symlinks; probe prefers per-tool dirs.

### Session 2026-08-14/15: ESMFold2 end-to-end + PAE in production

Full arc from "ESMFold2 has never completed a BV-BRC job" to verified in
production. Three nested causes, each hidden by the previous:

- **#94/#95/#97** — anchored regex missed esmfold2 in the
  `--use-msa-server` exclusion; A3M upload enabled (esm ships no MSA
  server client — #96 tracks pulling from our ColabFold server).
- **#98/#102** (42d6171) — the runner executed a stale June copy via
  `-m` from conda-esmfold2's site-packages. Now invoked by file path via
  a `{runner:...}` placeholder; conda-esmfold2 no longer installs
  predict-structure at all (runtime_build repacked, single-install
  assertion in the def + 22-check env suite).
- **#99** — writability-based HF cache probe picked a dir lacking
  ESMC-6B. Now content-based (`%REPOS_FOR_TOOL`, refs/main + snapshot
  config.json), per-tool dir preferred, dies fast when nothing
  qualifies. ESMFold2 weights staged canonically at
  `/local_databases/esmfold2` (both repos: ESMFold2 1.3 G + ESMC-6B 24 G).
- **#48/#100** — CCD codes: 1–3 **or exactly 5** alphanumeric (wwPDB
  5-char era; zero 4-char codes exist). Validated in `EntityList.add`
  (Python) and the Perl ligand loop; glycan-specific message on `(`.
- **#50/#101** — Boltz `pae_*.npz` → `predictions/pae.json` (PAELoader
  Format 1, max_pae = 31.75 colormap ceiling, iptm gated on multichain).
  **Verified end-to-end in production**: B01 (task 23425749) produced a
  46×46 pae.json and a report rendering Mean PAE/pTM — first time ever.
- **PYTHONPATH sanitizer** in 90-environment.sh — dev_container's
  user-env.sh leaves a trailing colon = cwd on sys.path for every python
  in the container (the enabler of #98's stale-copy hazard). Upstream
  report tracked as #109.

Containers: `folding_260814.1.sif` (full matrix) → `folding_260815.1.sif`
(adds #48+#50+#98+sanitizer; current production, B01-verified after
repoint).

### Session 2026-08-13: retirement, preflight, matrix (see git history)

#90 AlphaFold retired from auto (56b1e5a); #84 submit-time tool/entity
validation via declared kinds (abda889); #82 Chai CCD rejection; matrix
48/48 on folding_260813.2. Details in the git log and closed issues.

## Test results

### Unit tests (2026-08-17, HEAD c350a68)

**589 passed, 10 skipped** —
`python -m pytest tests/ -q --timeout=60 --ignore=tests/acceptance`
(`tests/acceptance/` shells out to real 32 GB containers; run it
deliberately, not in the normal loop).

### API test matrix (folding_260814.1.sif, 2026-08-14)

`docs/test-reports/matrix_20260814_205320.json` — **56/56 as expected:**
43 completed, 11 refused at submit by design (submit-time rejections,
no task created), 2 worker-side failures that were expected failures
(N03 bad format, N07 bad SMILES).

Highlights: **F01–F04 ESMFold2 pass** (first ever through BV-BRC);
**A01 AlphaFold pass** (26:05 on coconut — first run since June);
X01 confirms no-MSA auto → Boltz with a server-side ColabFold MSA (the
docs/UI claim that auto picks ESMFold was false and has been corrected
everywhere).

### B01 re-verification (folding_260815.1.sif, 2026-08-17)

`docs/test-reports/matrix_20260817_084004.json` — B01 completed in 1:40
on coconut against the repointed production container; PAE JSON and
report rendering confirmed in the output (task 23425749).

## What's pending

### Open issues

| # | Issue | Notes |
|---|---|---|
| 106 | raw_output/ + raw/ both uploaded | Real user impact: duplicate GBs per job |
| 108 | Chain IDs wrap past 26 combined entities | Silent duplicate chains; hard-stop in `EntityList.add` |
| 104 | boltz-report-msa.cwl byte-identical to boltz-report.cwl | Rename/implement/delete |
| 105 | select-pae.cwl has no executable coverage | Validate-only today |
| 107 | test_config.py deletes env var instead of restoring | Use monkeypatch |
| 109 | Upstream dev_container PYTHONPATH trailing colon | We're sanitized; report upstream, then close |
| 96 | ESMFold2 MSA from our ColabFold server | Needs server address; reuse `scripts/_colabfold_api_msa.py`, follow the openfold interface pattern |
| 90 | Retire AlphaFold — UI half | Closes when BV-BRC-Web#1400 merges |
| 52 | Docs: multi-chain applies to DNA/RNA | Repo half done (#103); closes when BV-BRC-Docs#283 merges |
| 88 | Eye-icon REPORT action | BV-BRC-Web; candidate for next consolidated fork PR |
| 85 | Decommission AlphaFold 2 | Deferred — review 2026-11-13 |
| 77 | Per-model length limits | CLI + UI |
| 76 | DSSP post-prediction step | Enhancement |
| 72, 73 | Workspace upload visibility / re-highlight | BV-BRC UI |
| 18 | Nucleic acid secondary structure (DSSR) | Enhancement |

Closed since 2026-08-13: #48, #50, #51, #75, #79, #80, #82, #84, #91–#95,
#97–#103 (fix PRs and their issues).

## Infrastructure

### Folding tools (production SIF: folding_260815.1.sif)

| Tool | Package | Version | PyTorch / Framework | Weights |
|---|---|---|---|---|
| Boltz | `boltz[cuda]` | 2.2.1 | torch 2.11.0 (cu130) | `$BOLTZ_CACHE` |
| OpenFold | `openfold3` | 0.4.1 | torch 2.5.1+cu121 | `of3-p2-155k.pt` |
| Chai | `chai-lab` | 0.6.1 | torch 2.5.1+cu121 | `$CHAI_DOWNLOADS_DIR` |
| AlphaFold (retired) | `wilke/alphafold` fork | git HEAD | JAX 0.4.26 | `$AF2_DATA_DIR` (~2 TB) |
| ESMFold | `transformers` | 5.8.0 | torch 2.6.0+cu124 | `/local_databases/esmfold/hub` |
| ESMFold2 | `esm` (biohub) | — | torch cu130 (driver ≥ 580 → H200 only) | `/local_databases/esmfold2/hub` (ESMFold2 + ESMC-6B) |

- ESMFold2: subprocess backend only, `min_gpu_memory_mb` 18000, runner
  invoked by file path (never `-m`), own env `/opt/conda-esmfold2` that
  does **not** contain predict-structure.
- Boltz + ESMFold2 (cu130) run only on coconut (H200); OF/Chai (cu121)
  run on all three hosts.

### GPU hosts

| Host | GPU | VRAM | CUDA | cu130 (Boltz, ESMFold2) | cu121 (OF/Chai) |
|---|---|---|---|---|---|
| coconut | 8× H200 NVL | 141 GB | 13.0 | YES | YES |
| mango | 8× H100 NVL | 95 GB | 12.6 | NO | YES |
| peach | 2× V100 | 32 GB | 12.2 | NO | YES |

### Container history (recent)

| SIF | Date | Status | Notes |
|---|---|---|---|
| folding_260815.1.sif | 2026-08-15 | **Production** | +#48 +#50 +#98 + PYTHONPATH sanitizer; 42d6171; B01 verified after repoint |
| folding_260814.1.sif | 2026-08-14 | Superseded | ESMFold2 arc (#94–#99); 56/56 matrix incl. A01 |
| folding_260813.3.sif | 2026-08-13 | Superseded | #90 + #75 blockers |
| folding_260813.2.sif | 2026-08-13 | Superseded | +#84 preflight validation; 48/48 matrix |
| folding_260813.1.sif | 2026-08-13 | Superseded | #67 + #81 + #82 |

Older history: see git log of this file.

### Key paths

| Path | Purpose |
|---|---|
| /scout/containers/folding_prod.sif | Local testing symlink → folding_260815.1.sif |
| /vol/patric3/production/containers/ | Promotion target — `cp` the SIF here (needs user) |
| /disks/patric-common/container-cache/ | BV-BRC scheduler container cache |
| /local_databases/esmfold2/hub | Canonical ESMFold2 + ESMC-6B cache (svcbvbrc) |
| /local_databases/esmfold/hub | esmfold_v1 cache |
| ~/.patric_token | BV-BRC auth token |
| ~/Development/runtime_build/gpu-builds/cuda-12.2-cudnn-8.9.6/ | Container build defs + BUILD-SOP.md |

### Repos

| Repo | Branch | HEAD | Notes |
|---|---|---|---|
| PredictStructureApp | main | c350a68 | pushed |
| protein_structure_analysis (wilke) | main | 7105946 | #79 + #80 merged; feeds next container build |
| BV-BRC-Web (wilke fork) | alpha | 10c90676d | consolidated UI changes; upstream PR #1400 open |
| BV-BRC-Docs (wilke fork) | master | — | docs sweep merged; upstream PR #283 open |

## Operational notes (validated the hard way)

- **After a container repoint, verify with a probe job's stderr
  "Container path:" line** — the repoint silently failed to take twice.
  `enumerate_apps` never lists PredictStructure; don't use it.
- First submission after a container switch takes ~8 min of SIF staging;
  the test runner allows 900 s.
- If `start_app2` returns an empty "Error submitting job:", check
  `p3x-show-container-config` (on gum, as p3) for a pointer at a deleted
  SIF; the scheduler runs preflight *inside* the registered container.
- Production Perl runs from `/opt/p3/deployment/plbin/`, not the git
  checkout — a rebuild must refresh both copies.
- Task stderr: `https://p3.theseed.org/services/app_service/task_info/<id>/stderr`;
  Shock downloads need `Authorization: OAuth $(cat ~/.patric_token)`.

## How to resume

### Re-run the full test matrix
```bash
python3 scripts/submit_api_tests.py matrix --include-alphafold
```

### Test a new SIF locally before handing over for deployment
Acceptance harness (17 checks incl. single-install, path-invocation,
service-script preflight): see session scratchpad `acceptance/run.sh`
pattern, or run the Boltz+SMILES case:
```bash
WORKDIR=$(mktemp -d)
apptainer exec --nv \
    --bind $WORKDIR:/work --bind /local_databases:/local_databases \
    --bind $PWD/test_data:/data \
    --env P3_WORKDIR=/work \
    /scout/containers/<new>.sif \
    perl /opt/p3/deployment/plbin/App-PredictStructure.pl \
        "" /build/dev_container/modules/PredictStructureApp/app_specs/PredictStructure.json \
        /tmp/test_boltz_smiles.json
ls $WORKDIR/output/{model_1.pdb,report.html,results.json,predictions/pae.json}
```

### Verify a SIF carries the intended commit
```bash
apptainer inspect /scout/containers/<new>.sif | grep predict_structure_commit
apptainer exec <sif> /opt/conda-predict/bin/python -c "import predict_structure as p; print(p.__version__)"
```

### After a BV-BRC image switch
1. Submit one ESMFold job (`matrix --tests E01`) — expect a slow first call
2. Pull its stderr and confirm the "Container path:" line names the new SIF
3. Then submit the full matrix
