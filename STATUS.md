# Project Status

**Last updated:** 2026-08-21
**Current version:** v0.17.0 (HEAD: ef0914b)
**Production (alpha) container:** `folding_260825.2.sif` — PredictStructure + StabiliNNator, both verified

## Next action

Steady state. `folding_260825.2.sif` is deployed and registered for both
PredictStructure and StabiliNNator. The whole StabiliNNator chain is closed:
dispatch, walltime, result delivery, report.

Open items, all outside this container:

1. **The alpha JS bundle predates BV-BRC-Web#1403.** `/js/3.59.9/bundle/bundle.js`
   contains neither `ViewPredictStructureReport` nor `ViewStabiliNNatorReport`,
   though both are in alpha's source. The REPORT eye icon is therefore inert on
   alpha for **both** apps until BV-BRC rebuilds the bundle. It works against a
   local p3-web instance, which serves source rather than the bundle.
2. **BV-BRC-Web#1407** — StabiliNNator submission form (the service is
   otherwise API-only; CEPI-dxkb/stabiliNNatorApp#20).
3. **#116** — Jobs-page REPORT action, review 2026-08-27.
4. The preflight host's container cache still has no eviction, and a failed
   image pull still surfaces as an empty "Error submitting job". Worth an
   upstream issue to BV-BRC infra.

## What's done

### Session 2026-08-25: StabiliNNator end to end, on compute nodes

- **`folding_260825.2.sif`** (predict_structure `ef0914b`, stabiliNNatorApp
  `5ed9b23`) deployed and registered for both apps.
- **StabiliNNator runs end to end for the first time.** S01-S03 pass on
  hosts **alder** and **fir** — compute-partition nodes, never seen before
  in this project; every prior job ran on coconut/mango/peach. 6
  `output_files` including `stabilinnator_report.html`, delivered into the
  job result folder.
- **Three bugs, found only because S01-S03 exist** (added this session):
  1. `partition => 'normal'` — not a valid partition. Jobs logged
     "Submitted" then were silently refused: no start_time, no hostname,
     zero-byte logs, no task_status dir (23450684, 23450690).
  2. **Walltime, misdiagnosed by me as a staging limit.** With
     `partition => compute` and `runtime => 120`, jobs died at ~1.1x their
     OWN requested walltime (S01 120s->132s, S02/S03 60s->69s/65s). I
     reported this as "compute nodes do not carry the 27 GB image" and
     switched to gpu2. Wrong: a peer session retried compute with
     runtime 600 and the jobs staged the image cold in ~3:12-3:24 and
     succeeded. The nodes were always capable; they never had the time.
     Lesson: two variables changed together (partition AND runtime), and
     the confounded result was reported as a finding.
  3. Results uploaded flat into `output_path`, leaving the job result
     folder empty and `output_files: []` — so the REPORT icon had nothing
     to find (stabiliNNatorApp#18, fixed in `486e037`).
- **Both test suites now assert effects, not exit codes.** Acceptance
  check 17 asserted only `rc=0` while printing the bad partition as a
  label; it now asserts the partition value and that the app spec agrees
  with the Perl preflight. Matrix `judge()` now fails a completed job with
  empty `output_files` and can require an output suffix (S01-S03 require
  `*_report.html`). Both were verified red against the broken images
  before being trusted.
- **#88 closed** — BV-BRC-Web#1403 merged to alpha (`b0e97e13d`), adding
  REPORT icons for both apps, opening in a new tab.

### Session 2026-08-24: 260821.3 clean, all tool installs pinned

- **`folding_260821.3.sif` → 59/59** (`matrix_20260824_111704.json`): 44
  completed, 13 refused at submit by design, 2 expected worker-side failures
  (N03/N07). Hosts coconut 29, mango 12, peach 5. Registered for
  PredictStructure **and** StabiliNNator.
- **#114 confirmed fixed in production** — O04 (RNA) failing → passing;
  O01–O06 now 6/6.
- **260821.2 was broken and rolled past, not deployed long:** the def
  installed `openfold3` **unpinned**, 0.5.0 released between the .1 and .2
  builds, its diffusion-transformer architecture no longer matches
  `of3-p2-155k.pt`, and every OpenFold case died with
  `Checkpoint state_dict keys do not match`. Only openfold3 had drifted.
- **All five floating installs now pinned** to the versions 260821.1 verified
  (runtime_build `ad709be`): `openfold3==0.4.5`, `boltz[cuda]==2.2.1`,
  `chai-lab==0.6.1`, `esm@1b52073`, `ESMFoldApp@7cae913`. Rule added to the
  build skill: a reproducible build with a floating install is not
  reproducible; bumping a tool is a deliberate pin change plus that tool's
  matrix.
- **O02 transient:** openfold3's ColabFold path fetches template chain-ID
  mappings from RCSB and treats failure as fatal. Failed once for 31
  entries, passed on retry; RCSB answers fine from coconut.

### Session 2026-08-21: reproducible container in production + #114

- **`folding_260821.1.sif` deployed to alpha** — first from-scratch
  reproducible build in production (`all-build.def`, digest-pinned bases,
  27 G vs 32 G; the 5 G is the pruned KB runtime, 15 G → 75 M, plus 92 other
  apps' plbin scripts that never belonged in our image). Every BV-BRC
  tool/lib the service uses verified present; host constraints byte-identical
  to 260815.1.
- **Deployment war story:** five submit failures with the blank
  `"Error submitting job: \n"` — the preflight host's cache could not write
  more than 22.0 GB (`curl: (23)` at 82% every time). Diagnosis wandered
  (registry table → mango → gum) before the fix landed: user cleared the
  right cache. Rolled back to 260815.1 in between (verified in 43 s — the
  probe-first discipline paid for itself). `p3x-run-preflight` inside the
  image was clean the whole time.
- **Matrix vs 260821.1** (`matrix_20260821_162056.json`): **42/44 as
  expected**, all hosts exercised (coconut 28, mango 13, peach 3), A01
  AlphaFold 23:54. First production runs of #106 prune, #79/#80 report
  fixes, stabiliNNator.
- **#114 found by that matrix** — O02/O04 failed: openfold3 0.4.5 (bumped in
  the reproducible build; 0.4.1 before) writes `msas/` into the output dir,
  and `normalize_openfold_output` picked its query dir as the first entry of
  an **unordered** `iterdir()`. Fixed (ef0914b, PR #115): selection by
  content (must contain `seed_*`), deterministic regression test (msas/
  distractor that sorts first, verified failing on old code). 612 tests.
- **Closed:** #90 (UI half = BV-BRC-Web#1400, merged 2026-08-18), #52
  (BV-BRC-Docs#283, merged 2026-08-18), #110 (SOP Step 4b unconditional +
  cross-copy gate, verified in 260821.1's 41/41), #114.
- **BUILD-SOP rewritten** (2026-08-20 session): incremental path documented,
  Step 4b unconditional, Step 4 matched to the def (it never installed
  protein_compare!), Step 8 split local/promotion/verify. Acceptance harness
  committed as `test-container-acceptance.sh` (was session-scratch only).
  Env suite grew cross-copy checks (mutation-tested).
- **`test-folding` skill** added (`.claude/skills/test-folding/` — note
  `.claude/` is gitignored, machine-local only): local three-layer gate
  (structural 41 / behavioural 26 / real prediction) then alpha
  (container-path proof, then matrix, and how to read the results JSON —
  submit-time rejections carry no `status` key).


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

### Unit tests (2026-08-21, HEAD ef0914b)

**612 passed, 10 skipped** —
`python -m pytest tests/ -q --timeout=60 --ignore=tests/acceptance`
(`tests/acceptance/` shells out to real 32 GB containers; run it
deliberately, not in the normal loop).

### API test matrix (folding_260825.2.sif, 2026-08-25)

`docs/test-reports/matrix_20260825_213954.json` — **62/62 as expected** with
`--include-alphafold --include-negative`: 47 completed, 13 refused at submit
(no task created — the pass condition for those), 2 expected worker-side
failures (N03 bad format, N07 bad SMILES). Hosts: coconut 29, mango 12,
peach 5, **alder 3** — the compute-partition node, first time StabiliNNator
has appeared in a matrix run at all.

### API test matrix (folding_260821.3.sif, 2026-08-24)

`docs/test-reports/matrix_20260824_111704.json` — **59/59 as expected** with
`--include-alphafold --include-negative`: 44 completed, 13 refused at submit
(no task created — the pass condition for those), 2 expected worker-side
failures (N03 bad format, N07 bad SMILES). Hosts: coconut 29, mango 12,
peach 5.

### API test matrix (folding_260821.1.sif, 2026-08-21)

`docs/test-reports/matrix_20260821_162056.json` — **42/44 as expected** with
`--include-alphafold`. The 2 unexpected failures are #114 (O02/O04, openfold3
0.4.5 `msas/` dir vs normalizer), fixed in ef0914b / folding_260821.2. Hosts:
coconut 28, mango 13, peach 3. A01 AlphaFold 23:54. First production runs of
the #106 prune, #79/#80 report fixes, ESMFold2 F01–F04 on this build, and
stabiliNNator in the image.

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
| 96 | ESMFold2 MSA from our ColabFold server | Blocked on server address; reuse `scripts/_colabfold_api_msa.py`, openfold pattern |
| 88 | Eye-icon REPORT action | BV-BRC-Web; next consolidated fork PR |
| 85 | Decommission AlphaFold 2 | Deferred — review 2026-11-13 |
| 77 | Per-model length limits | CLI + UI |
| 76 | DSSP post-prediction step | Enhancement |
| 72, 73 | Workspace upload visibility / re-highlight | BV-BRC UI |
| 18 | Nucleic acid secondary structure (DSSR) | Enhancement |

No open defects. Closed since 2026-08-17: #51, #52, #90, #103–#110, #114.
Upstream: BV-BRC/dev_container#20 open (PYTHONPATH trailing colon, reported
with fix; we ship a sanitizer and are unaffected).

## Infrastructure

### Folding tools (production SIF: folding_260821.3.sif — all installs pinned)

| Tool | Package | Version | PyTorch / Framework | Weights |
|---|---|---|---|---|
| Boltz | `boltz[cuda]` | 2.2.1 | torch 2.11.0 (cu130) | `$BOLTZ_CACHE` |
| OpenFold | `openfold3` | 0.4.5 (pinned) | torch 2.5.1+cu121 | `of3-p2-155k.pt` |
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
| folding_260825.2.sif | 2026-08-25 | **Production (alpha)** | stabiliNNatorApp 5ed9b23: compute partition, 600s runtime, result-folder upload. S01-S03 pass on alder/fir |
| folding_260825.1.sif | 2026-08-25 | Superseded | 486e037 upload fix; gpu2 |
| folding_260824.2.sif | 2026-08-24 | Superseded | gpu2 + 600s runtime |
| folding_260824.1.sif | 2026-08-24 | Superseded | compute + 120s — jobs killed at walltime |
| folding_260821.3.sif | 2026-08-21 | Superseded | 260821.2 + every tool install pinned; **59/59**; PredictStructure + StabiliNNator |
| folding_260821.2.sif | 2026-08-21 | **Broken — do not use** | +#114 fix but openfold3 0.5.0 drift: OpenFold 0/6 |
| folding_260821.1.sif | 2026-08-21 | **Production (alpha)** | First reproducible def build; 27 G; +#104–#108, #79/#80, stabiliNNator; known O02/O04 regression (#114) |
| folding_260815.1.sif | 2026-08-15 | Rollback standby | +#48 +#50 +#98 + PYTHONPATH sanitizer; 42d6171; B01 verified after repoint |
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
