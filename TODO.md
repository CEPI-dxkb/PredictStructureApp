# TODO

Tactical checklist — derived from current PLAN phase. Check off as you go.

## Blocked

- [ ] **BV-BRC submission returns HTTP 500 for every job.** Affects valid jobs
      too (E01, plain ESMFold), so it is not the new preflight validation.
      Preflight verified healthy standalone and via the deployed Perl.
      Container cache has 554 GB free but `/disks/patric-common/container-cache/`
      still holds only `folding_260622.3.sif` — `folding_260813.2.sif` was never
      staged. Needs scheduler admin: check the app→container registration and
      the scheduler-side error log. Blocks everything below it.
- [ ] Run the API test matrix against `folding_260813.2.sif` (all 3 GPU hosts)
- [ ] Run AlphaFold in the matrix — still not covered since the 260622 run
      (may be moot if #85 lands first)

## Active

- [x] Fix #67: strip NUL bytes from ColabFold MSA files (83e4c17)
- [x] Fix #81: Boltz normalizer crash with SMILES ligands (a00dc8a)
- [x] Fix #82: reject CCD ligands for Chai instead of dropping them (8ac583f)
- [x] Fix #84: validate tool/entity compatibility in preflight (abda889)
- [x] Add branching rule to CLAUDE.md (e653c5a)
- [x] Commit container def env-var fixes (cbc9ab0)
- [x] Build + deploy folding_260813.1.sif and folding_260813.2.sif
- [x] Fix ESMFold2 HF cache permissions on /local_databases/esmfold
- [ ] Verify the #84 rejection message survives BV-BRC's HTTP 500 and actually
      reaches the user — the runner now captures the response body, so the
      first successful matrix run answers this
- [ ] Confirm the OpenFold cache change works in a real job: `OPENFOLD_CACHE`
      was inert before 2026-08-13, so OpenFold had been falling back to
      `~/.openfold3/`
- [ ] GoWe: test CWL tool submission through CPU workers
- [ ] GoWe: test predict-structure CWL tool through GPU workers

## Issue queue

- [ ] #85 — Decommission AlphaFold 2, replace with ESMFold2 (blocked by #75)
- [ ] #75 — ESMFold2 in UI but not functional (cache permissions fixed; recheck)
- [ ] #77 — Per-model protein length limits (CLI + UI)
- [ ] #76 — DSSP as post-prediction step
- [ ] #48 — CCD ligand input rejects glycans containing parentheses
- [ ] #50 — Add PAE score to the report
- [ ] #79 — B-factor distribution bars invisible when value is zero
- [ ] #80 — Report TOC/index + section reorder
- [ ] #72 — Workspace file upload not immediately visible (UI)
- [ ] #73 — File browser cannot re-highlight another file (UI)
- [ ] #51 — Job progress indicator (UI)
- [ ] #52 — Docs: multi-chain applies to DNA and RNA too
- [ ] #18 — Nucleic acid secondary structure (DSSR integration)

## Inbox

Items captured mid-work — triage into the queue or MEMORY/PLAN later.

- `tests/acceptance/` shells out to real 32 GB containers and dominates suite
  runtime; use `--ignore=tests/acceptance` for the normal loop
- The container carries TWO copies of `App-PredictStructure.pl`; production
  runs `/opt/p3/deployment/plbin/`, not the git checkout under
  `/build/dev_container/`. A rebuild must redeploy the plbin copy or the Perl
  silently stays stale while labels report the new commit
- Scheduler error log is NOT at `~/var/services/app_service/error.log-*` on
  coconut — that path does not exist; find the real location
- There is no `v0.17.0` git tag; newest tag is `v0.16.1` while pyproject has
  been on 0.17.0 since June. Tags are not a usable release marker right now
- 9 approved PRs from the batch review were merged; verify no regressions in
  the next container build
