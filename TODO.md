# TODO

Tactical checklist — derived from current PLAN phase. Check off as you go.

## Next up

- [ ] Deploy folding_260821.3 (building; = 260821.2 + every tool install
      pinned — 260821.2 is BROKEN for OpenFold, openfold3 0.5.0 drifted in
      from an unpinned PyPI install; roll back to 260821.1 meanwhile): local
      acceptance 26/26 → promote (p3 cp + repoint) → E01 probe with
      Container-path check → re-run O01–O06 → full matrix if desired
- [ ] File upstream (BV-BRC infra): container-cache has no eviction and a
      failed image pull surfaces as an empty "Error submitting job" —
      both bit the 260821.1 deploy (5 failed submits, ~22 GB write ceiling
      on the still-unidentified preflight host)
- [ ] Identify the preflight host (which machine writes the scheduler log?)
      and record it in MEMORY/STATUS — third deploy in a row where this
      unknown cost round trips
- [ ] #96 — ESMFold2 MSA via our ColabFold server; blocked on the server
      address; reuse `scripts/_colabfold_api_msa.py`, follow the openfold
      interface pattern (do not write a new client)
- [ ] #88 — eye-icon REPORT action; fold into the next consolidated
      BV-BRC-Web fork PR
- [ ] #85 — AlphaFold decommission decision, review 2026-11-13
- [ ] GoWe: test CWL tool submission through CPU workers
- [ ] GoWe: test predict-structure CWL tool through GPU workers

## Done (since 2026-08-13 — see STATUS.md for detail)

- [x] #106 — `prune_raw_output` drops `raw_output/` after `run_report`/finalize
      and before the upload, guarded on `raw/` being complete (PR #111)
- [x] #108 — `EntityList.add` refuses past chain ID Z instead of wrapping to A;
      not bypassable by `--force` (PR #112)
- [x] #104 — deleted `boltz-report-msa.cwl`; `boltz-report.cwl` already carries
      `use_msa_server`. Duplicate-CWL guard test added (PR #113)
- [x] #105 — executable `cwltool` coverage for `select-pae.cwl` (PR #113)
- [x] #107 — `monkeypatch.setenv` instead of deleting the env var (PR #113)
- [x] #109 — reported upstream as BV-BRC/dev_container#20; the sh branch of
      `deploy-user-env` is unguarded while the csh branch of the same target
      already guards it. We were never affected (sanitizer ships since
      folding_260815.1)
- [x] Archived the orphan root `app_spec.json` under `app_specs/archive/` for
      build forensics; canonical spec is `app_specs/PredictStructure.json`

- [x] ESMFold2 end-to-end in production: #94/#95/#97 (A3M + regex),
      #98/#102 (runner by path, env repack), #99 (content-based cache
      probe), weights staged at /local_databases/esmfold2
- [x] #48 — CCD codes 1–3 or exactly 5 alphanumeric, validated in
      `EntityList.add` + Perl
- [x] #50 — Boltz PAE npz → predictions/pae.json; verified rendering in a
      production report (B01, task 23425749)
- [x] Containers folding_260814.1 (56/56 matrix incl. AlphaFold A01) and
      folding_260815.1 (current production, B01-verified after repoint)
- [x] #79 + #80 — protein_compare report fixes, merged
      (wilke/protein_structure_analysis#12, #13)
- [x] #51 — closed: runtime hints (BV-BRC-Web#1400) suffice
- [x] #103 — README multi-chain (#52's repo half); wording corrected in
      review (26-record limit is per file)
- [x] Reviewer queue (hengma1001, architvasan) emptied
- [x] Fork-first workflow adopted: review/fix/merge in wilke forks, then one
      upstream PR per repo (BV-BRC-Web#1400, BV-BRC-Docs#283)
- [x] /local_databases: 66 GB of duplicate weights reclaimed; canonical
      layout esmfold2/ + esmfold/
- [x] Filed #104–#109
- [x] 2026-08-21: folding_260821.1 deployed to alpha (first reproducible def
      build); matrix 42/44; #114 found by the matrix, fixed (ef0914b), and
      folding_260821.2 kicked off; #90/#52/#110 closed (upstream PRs merged)

## Inbox

Items captured mid-work — triage into the queue or MEMORY/PLAN later.

- ~~`app_spec.json` untracked at the repo root~~ — resolved: it was a stale
  orphan copy (no esmfold2, no text_input, referenced by nothing), moved out
  of the repo. The canonical spec is `app_specs/PredictStructure.json`
- ~~`docs/bvbrc-web-90-retire-alphafold.patch`~~ — deleted 2026-08-21; #1400 merged
- ~48 GB still reclaimable later: nothing pending — cleanup done 2026-08-17
- There is no `v0.17.0` git tag; newest tag is `v0.16.1` while pyproject has
  been on 0.17.0 since June. Tags are not a usable release marker right now
- Follow-up candidates from the ESMFold2 arc already filed as #104–#109;
  nothing else outstanding from that review
