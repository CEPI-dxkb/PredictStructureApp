# TODO

Tactical checklist — derived from current PLAN phase. Check off as you go.

## Active (Phase 2 + 3)

- [x] Push protein_compare v0.2.1 (fixed: switched remote to HTTPS)
- [x] Set HF_HUB_OFFLINE=1 in SIF %environment for ESMFold (Issue #40, PR #58 merged)
- [x] Add job provenance to HTML report (Issue #69, PR #70 + protein_compare PR #7 merged)
- [x] Commit test reports (folding_260622.2: 38/38 pass, all hosts)
- [x] Commit test reports (folding_260622.3: 38/38 pass, all hosts)
- [x] Fix #67: strip NUL bytes from ColabFold MSA files (83e4c17)
- [x] Fix #81: Boltz normalizer crash with SMILES ligands (a00dc8a)
- [x] Add branching rule to CLAUDE.md (e653c5a)
- [ ] Commit container def fixes (predict-structure-all.def, folding-from-base.def, Dockerfile)
- [ ] Evaluate torch+cu124 rebuild for Boltz on mango/peach (Issue #38)
- [ ] GoWe: test CWL tool submission through CPU workers
- [ ] GoWe: test predict-structure CWL tool through GPU workers
- [ ] Run AlphaFold in next API test matrix run (not covered in 260622 run)

## Issues filed (2026-07-08)

- [ ] #72 — Workspace file upload not immediately visible (UI)
- [ ] #73 — File browser cannot re-highlight another file (UI)
- [ ] #74 — 3Dmol.js viewer not showing secondary structures in cartoon mode (report)
- [ ] #75 — Add ESMFold2 to UI tool selector (enhancement)
- [ ] #76 — Add DSSP as post-prediction step (enhancement)
- [ ] #77 — Per-model protein length limits with clear error messages (CLI + UI)
- [ ] #78 — Report viewer Reset View / Spin button issues (report)
- [ ] #79 — B-factor distribution bars invisible when value is zero (report)
- [ ] #80 — Report TOC/index + section reorder (report)

## Inbox

Items captured mid-work — triage into the queue or MEMORY/PLAN later.

- Editable install shadow bug: change `pip install -e` to `pip install` in container defs for next build
- 9 approved PRs from batch review were merged; verify no regressions in next container build
- protein_compare remote switched from SSH to HTTPS (push URL) — SSH key still broken
- Fixes #67 and #81 need next container build to reach production
