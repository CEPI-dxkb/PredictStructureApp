# TODO

Tactical checklist — derived from current PLAN phase. Check off as you go.

## Next up

- [ ] Next container rebuild: picks up protein_compare #79 + #80 report fixes
      automatically (pip from wilke/protein_structure_analysis main); batch
      with the next code change rather than rebuilding for it alone
- [ ] #106 — stop uploading raw bytes twice (exclude `raw_output/` from the
      workspace upload, or clean it after `run_report`); highest-impact of the
      new batch
- [ ] #108 — hard-stop in `EntityList.add` when chain IDs are exhausted
      (silent wrap past 26 combined entities today)
- [ ] #109 — file the upstream dev_container issue (PYTHONPATH trailing
      colon), link it, close ours
- [ ] #104/#105/#107 — small CWL/test cleanups, good batch candidates
- [ ] Watch upstream PRs: BV-BRC-Web#1400 (→ closes #90) and
      BV-BRC-Docs#283 (→ closes #52); nudge maintainers if idle
- [ ] #96 — ESMFold2 MSA via our ColabFold server; blocked on the server
      address; reuse `scripts/_colabfold_api_msa.py`, follow the openfold
      interface pattern (do not write a new client)
- [ ] #88 — eye-icon REPORT action; fold into the next consolidated
      BV-BRC-Web fork PR
- [ ] #85 — AlphaFold decommission decision, review 2026-11-13
- [ ] GoWe: test CWL tool submission through CPU workers
- [ ] GoWe: test predict-structure CWL tool through GPU workers

## Done (since 2026-08-13 — see STATUS.md for detail)

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

## Inbox

Items captured mid-work — triage into the queue or MEMORY/PLAN later.

- `app_spec.json` sits untracked at the repo root — looks generated; decide
  whether to delete or ignore
- `docs/bvbrc-web-90-retire-alphafold.patch` is superseded by the fork-first
  BV-BRC-Web#1400 flow; delete once #1400 merges
- ~48 GB still reclaimable later: nothing pending — cleanup done 2026-08-17
- There is no `v0.17.0` git tag; newest tag is `v0.16.1` while pyproject has
  been on 0.17.0 since June. Tags are not a usable release marker right now
- Follow-up candidates from the ESMFold2 arc already filed as #104–#109;
  nothing else outstanding from that review
