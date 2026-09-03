# Test report — folding_260901.1 on BV-BRC (alpha)

**Date:** 2026-09-03
**Container:** `folding_260901.1.sif`
**Contents:** predict_structure `a593591` (#119 shell-injection fix),
stabiliNNatorApp `d0f1c89` (#22 TSV type / mmCIF input / cysteine filter, #23 residue labels)

## Registration confirmed for both app rows

Read from the **user's own two morning jobs** — no probe submissions were
needed for this half:

| Task | App | `Container path:` |
|---|---|---|
| 23519220 | StabiliNNator | `/disks/patric-common/container-cache/folding_260901.1.sif` |
| 23519232 | PredictStructure | `/disks/patric-common/container-cache/folding_260901.1.sif` |

E01 probe afterwards: PASS, 38 s, coconut (task 23519288).

## Matrix — 52/52 pass

`scripts/submit_api_tests.py matrix`, tag `matrix_20260903_110826`,
results in `docs/test-reports/matrix_20260903_110826.json`.

52 of the 68 cases run in the default selection. Excluded: `A01`/`A02`
(AlphaFold, needs `--include-alphafold`) and the 14 `E02`/`C05`/`R01`/`R02`/
`N01`-`N10` rejection cases (need `--include-negative`, run separately below).

Host distribution: coconut 30, mango 14, peach 4, fir 4 (the four fir jobs are
the StabiliNNator cases on the `compute` partition).

Everything new since the last matrix passed: `B11`/`O07`/`C07` (protein+DNA+RNA),
`B12`/`B13` (DNA-only, RNA-only), `S01`-`S04` (StabiliNNator, `S04` multi-chain).

## Rejection cases — 64/64 pass

`scripts/submit_api_tests.py matrix --include-negative`, tag
`matrix_20260903_113341`, results in
`docs/test-reports/matrix_20260903_113341.json`.

All 12 rejection cases behaved: 10 refused at submit time with no `status`
key (`E02`, `C05`, `R02`, `N01`, `N02`, `N04`, `N06`, `N08`, `N09`, `N10`),
and `N03`/`N07` are `expected: fail` so they schedule and die in the run.

`E02` is representative of the submit-time refusals:

> ESMFold does not support dna input (it supports protein only). Use Boltz-2,
> Chai-1, ESMFold2, and OpenFold 3, which support dna.

**`N03` was fixed mid-session.** It referenced `inputs/not_fasta.txt`, which
was not in the workspace, so it had been failing on "file is empty or
unreadable" — the right verdict for the wrong reason. A plain-text fixture was
uploaded to `AppTests/inputs/not_fasta.txt` and N03 now fails as designed:

```
input_file: expected FASTA format (first non-blank line must start with '>'),
got: 'this file is deliberately not FASTA'
```

The StabiliNNator cases ran on **pear**, **bio-compute-04** and **alder** in
this pass and **fir** in the first — four distinct `compute` hosts, so image
staging on that partition is no longer a single-host result.

## StabiliNNator deploy-specific checks

**TSV typing (#22)** — the reason for this rebuild. Both result folders:

```
.matrix_S04_stabilinnator_multichain_20260903_110826
  tsv  3ft7_disulfide_summary.tsv
  tsv  3ft7_proline_summary.tsv
  json 3ft7_summary.json
  html stabilinnator_report.html
  pdb  3ft7_disulfide.pdb / 3ft7_proline.pdb
```

Correct in `S01` as well. Previously these landed as `unspecified`.

**Residue labels (#23)** — `node tests/verify_report_labels.js` on the S04 report:

```
report_s04.html: chains=AB rows=90
  mislabeled now: 0   (old sequence[pos-1] lookup would mislabel 86/88)
  misplaced gold cysteines: 0
  distinct proline labels: 88/88
```

The counterfactual only shows up on the **raw** `inputs/3ft7.pdb`. The user's
own 09:38 run used `3ft7_clean_0001.pdb`, whose residues are contiguously
renumbered, so offset-lookup and identity-lookup coincide there and the same
verifier reported `would mislabel 0/86`. Both runs are correct; only the raw
structure exercises the regression.

## Incidental finding: the 09:51 UI job failure is not the container

Task 23519232 failed in 0.86 s with:

```
dna_file: file is empty or unreadable (/awilke@bvbrc/home/AppTests/inputs).
  at App-PredictStructure.pl line 222
```

`dna_file` was submitted as a **directory**. Cause chain:

1. `AppTests/inputs/{dna,rna,simple_protein}.fasta` are typed **`reads`** in
   the workspace (`p3-ls -lT`).
2. The form's DNA selector accepts `feature_dna_fasta|aligned_dna_fasta|contigs`
   (`templates/PredictStructure.html:114`), so the browse dialog shows that
   folder as empty.
3. `WorkspaceObjectSelector.js:845` sets the value from the dialog's current
   selection, which can be the folder itself.

The service caught it with an accurate message, so nothing is broken here — but
two UI-side fixes are worth making: retype the six workspace test inputs, and
reject a directory in `getValues()` rather than submitting it.

The same job's `input_file` pointed into `.matrix_B11_…`, a job folder that no
longer exists — stale value carried in the form.

## Workspace state

Every `matrix_*` run folder from the August campaigns was already gone before
this session (probed by name: `Object not found`). `AppTests` was down to eight
entries. The remaining stale objects are older hand-made StabiliNNator runs and
two flat `1crn_small_*.pdb` files from the pre-#18 upload bug; a commented
`p3-rm` block was handed to the user rather than executed here.

Note that this session's two matrix runs wrote ~116 fresh run folders into
`AppTests`, so any cleanup should follow the test run, not precede it.

## Known matrix defect — fixed this session

`N03` referenced `inputs/not_fasta.txt`, which was not in the workspace — a
fixture gap, not a service bug. Fixture uploaded; see the rejection-case
section above.
