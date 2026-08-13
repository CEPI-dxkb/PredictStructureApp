# TODO

Tactical checklist — derived from current PLAN phase. Check off as you go.

## Next up

- [x] Merge #87 (container env vars + STATUS/TODO) and #89 (runner cold start)
- [x] Fix #90: retire AlphaFold from auto selection (PR #91, 56b1e5a)
- [x] Fix #75 blockers: ESMFold2 H200 pin + VRAM floor + F01-F03 (PR #92, 160dc09)
- [x] Build folding_260813.3.sif with #90 + #75
- [ ] **Repoint ApplicationDefaultContainer at folding_260813.3** (needs scheduler
      admin) — everything below is blocked on it
- [ ] Run the matrix against 260813.3, including F01-F03 — the first ESMFold2
      cases ever submitted through BV-BRC; closes #75
- [ ] Apply docs/bvbrc-web-90-retire-alphafold.patch in BV-BRC-Web to finish #90
      (this account has READ only on that repo)
- [ ] #88 — eye-icon REPORT action, also BV-BRC-Web
- [ ] Decide #85 (full AlphaFold decommission) — #90 already removed it from auto,
      so the urgency is lower; still the reason A01/A02/R01 are excluded
- [ ] #50: convert the Boltz PAE npz to `predictions/pae.json` — the report side
      is already built and shipped, only the data path is missing
- [ ] #48: the Python CLI does no CCD validation at all while the Perl enforces
      `^[A-Za-z0-9]{1,3}$`; junk reaches the tool and fails opaquely
- [ ] Suppress the Carp backtrace on `_validate_params` dies, as the #84 path
      already does (`local $SIG{__DIE__} = 'DEFAULT'`)
- [ ] GoWe: test CWL tool submission through CPU workers
- [ ] GoWe: test predict-structure CWL tool through GPU workers

## Active

- [x] Fix #67: strip NUL bytes from ColabFold MSA files (83e4c17)
- [x] Fix #81: Boltz normalizer crash with SMILES ligands (a00dc8a)
- [x] Fix #82: reject CCD ligands for Chai instead of dropping them (8ac583f)
- [x] Fix #84: validate tool/entity compatibility in preflight (abda889)
- [x] Add branching rule to CLAUDE.md (e653c5a)
- [x] Commit container def env-var fixes (cbc9ab0)
- [x] Build + deploy folding_260813.1.sif and folding_260813.2.sif
- [x] Fix ESMFold2 HF cache permissions on /local_databases/esmfold
- [x] Run the API test matrix against folding_260813.2 — 48 pass, 0 fail
- [x] Fix the app->container registration (was pointing at a deleted SIF)
- [x] Verify the #84 rejection message reaches the user — confirmed, it arrives
      intact in the JSON-RPC error body (matrix run 2026-08-13)
- [x] Confirm the OpenFold cache change works in a real job — all 6 OpenFold
      matrix cases pass on mango with `OPENFOLD_CACHE` live
- [ ] GoWe: test CWL tool submission through CPU workers
- [ ] GoWe: test predict-structure CWL tool through GPU workers

## Issue queue

- [ ] #85 — Decommission AlphaFold 2, replace with ESMFold2 (blocked by #75)
- [ ] #88 — Eye-icon REPORT action for PredictStructure in the workspace browser (fix lands in BV-BRC-Web)
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
