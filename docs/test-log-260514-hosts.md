# Host Coverage Test Log — 2026-05-14

**Container:** `folding_260513.1.sif`
**Goal:** Every tool runs on every host (coconut, mango, peach)
**Timestamp:** 20260514_103702

## Run 1 — 18 jobs

| Task | Test | Tool | Host | Status |
|---|---|---|---|---|
| 22199285 | T01 esmfold | ESMFold | coconut | PASS |
| 22199286 | T02 boltz_msa | Boltz | peach | FAIL (CUDA 12.2) |
| 22199287 | T03 openfold | OpenFold | coconut | PASS |
| 22199288 | T04 chai | Chai | peach | PASS |
| 22199289 | T05 alphafold | AlphaFold | mango | PASS |
| 22199290 | T06 auto | auto->Boltz | coconut | PASS |
| 22199291 | T07 boltz_dna | Boltz | coconut | PASS |
| 22199292 | T08 of_dna | OpenFold | coconut | PASS |
| 22199293 | T09 chai_dna | Chai | peach | PASS |
| 22199294 | T10 boltz_rna | Boltz | coconut | PASS |
| 22199295 | T11 boltz_lig | Boltz | peach | FAIL (CUDA 12.2) |
| 22199296 | T12 chai_lig | Chai | coconut | PASS |
| 22199297 | T13 boltz_smi | Boltz | coconut | FAIL (investigate!) |
| 22199298 | T14 auto_msa | auto->Boltz | peach | FAIL (CUDA 12.2) |
| 22199299 | T15 auto_dna | auto->Boltz | coconut | PASS |
| 22199300 | T16 mmcif | Boltz | coconut | PASS |
| 22199301 | T17 debug | ESMFold | coconut | PASS |
| 22199302 | T18 boltz_srv | Boltz | peach | FAIL (CUDA 12.2) |

## Host x Tool coverage matrix (Run 1)

C=coconut, M=mango, P=peach. PASS/FAIL/--=not scheduled

| Tool | coconut | mango | peach |
|---|---|---|---|
| ESMFold | PASS (T01,T17) | -- | -- |
| Boltz | PASS (T07,T10,T16,T06,T15) | -- | FAIL (T02,T11,T18) |
| OpenFold | PASS (T03,T08) | -- | -- |
| Chai | PASS (T12) | -- | PASS (T04,T09,T288) |
| AlphaFold | -- | PASS (T05) | -- |
| auto->Boltz | PASS (T06,T15,T299) | -- | FAIL (T14,T298) |

### Gaps to fill (need Run 2)

| Tool | Missing host | Expected |
|---|---|---|
| ESMFold | mango, peach | PASS (cu124 works on both) |
| OpenFold | mango, peach | PASS (cu121 works on both) |
| Chai | mango | PASS (cu121 works) |
| AlphaFold | coconut, peach | PASS if DBs mounted |
| Boltz | mango | FAIL expected (CUDA 12.6, cu130 needs 13.0) |

### Issues found

- **T13 boltz+SMILES on coconut: FAIL** — unexpected. All other Boltz variants pass on coconut. Needs stderr from gum: `tail -30 /disks/p3/task_status/22199297/stderr`

## Run 2 — Gap-filling (12 jobs, 20260514_111524)

| Task | Test | Tool | Host | Status |
|---|---|---|---|---|
| 22199345 | R2_esm_1 | ESMFold | coconut | PASS |
| 22199346 | R2_esm_2 | ESMFold | coconut | PASS |
| 22199348 | R2_esm_3 | ESMFold | coconut | PASS |
| 22199349 | R2_of_1 | OpenFold | coconut | PASS |
| 22199350 | R2_of_2 | OpenFold | coconut | PASS |
| 22199352 | R2_of_3 | OpenFold | mango | PASS |
| 22199353 | R2_chai_1 | Chai | mango | PASS |
| 22199355 | R2_chai_2 | Chai | peach | PASS |
| 22199356 | R2_af_1 | AlphaFold | mango | PASS |
| 22199357 | R2_af_2 | AlphaFold | coconut | PASS |
| 22199358 | R2_boltz_1 | Boltz | mango | FAIL (CUDA 12.6) |
| 22199359 | R2_boltz_2 | Boltz | coconut | PASS |

## Combined host x tool coverage (Run 1 + Run 2)

C=coconut, M=mango, P=peach

| Tool | coconut | mango | peach |
|---|---|---|---|
| ESMFold | PASS (T01,T17,R2x3) | -- | -- |
| Boltz | PASS (T06,T07,T10,T15,T16,R2) | FAIL (R2, CUDA 12.6) | FAIL (T02,T11,T18, CUDA 12.2) |
| OpenFold | PASS (T03,T08,R2x2) | PASS (R2) | -- |
| Chai | PASS (T12,T296) | PASS (R2) | PASS (T04,T09,R2) |
| AlphaFold | PASS (R2) | PASS (T05,R2) | -- |
| auto->Boltz | PASS (T06,T15) | -- | FAIL (T14, CUDA 12.2) |

### Still missing

| Tool | Host | Status |
|---|---|---|
| ESMFold | mango | NOT TESTED (all 3 landed on coconut) |
| ESMFold | peach | NOT TESTED |
| OpenFold | peach | NOT TESTED |
| AlphaFold | peach | NOT TESTED |

### Issues

- **T13 boltz+SMILES on coconut: FAIL** — unexpected code bug. Needs: `tail -30 /disks/p3/task_status/22199297/stderr`
- **Boltz on mango/peach: FAIL** — expected, CUDA 12.6/12.2 too old for torch+cu130 (#38)
- **ESMFold didn't land on mango or peach** in 6 attempts — scheduler favors coconut for ESMFold (no GPU policy?)
