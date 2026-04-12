# Acceptance Test Results

Date: 2026-04-11

## Summary

Full end-to-end run on both production containers, all phases including AlphaFold.

| Phase | folding_prod.sif | all-2026-0410.01.sif |
|-------|:----------------:|:--------------------:|
| **Phase 1** native (13 tests) | 13 pass | 11 pass, 2 fail |
| **Phase 2** CLI (64 tests) | 48 pass, 11 fail, 5 xfail | 33 pass, 26 fail, 5 xfail |
| **Phase 3** service+ws (36 tests) | 33 pass, 3 fail | 25 pass, 11 fail |
| **Total** (113 tests) | **94 pass, 14 fail, 5 xfail** | **69 pass, 39 fail, 5 xfail** |
| Runtime | 160 min | 150 min |

### Failure Breakdown

| Root cause | prod | all | Fix |
|-----------|:----:|:---:|-----|
| OpenFold adapter checkpoint bug | 9 | 9 | Adapter code fix needed |
| ESMFold missing from container | 0 | 17 | Container build |
| `all` has no BV-BRC layer | 0 | 11 | By design (tool-only container) |
| AlphaFold wrong data dir in test | 1 | 1 | Fixed (was `/databases`, now `/local_databases/alphafold/databases`) |
| `text_input` not in app_spec | 1 | 1 | App spec update needed |
| Workspace p3-ls UTF-8 | 1 | 0 | Minor encoding issue |
| Workspace upload verify | 1 | 0 | Listing path mismatch |
| Auto-select cpu picks openfold | 0 | 1 | ESMFold unavailable in container |

---

## Phase 1: Native Tool Results

Tests each folding tool directly (bypassing predict-structure).

- **folding_prod.sif**: 13/13 PASS (38 min)
- **all-2026-0410.01.sif**: 11/13 PASS (37 min)

| Test | folding_prod.sif | all-2026-0410.01.sif |
|------|:----------------:|:--------------------:|
| Boltz protein+msa | PASS 69s | PASS 58s |
| Boltz protein (no msa) | PASS 19s | PASS 18s |
| Boltz protein msa:empty | PASS 65s | PASS 58s |
| Boltz dna | PASS 62s | PASS 59s |
| ESMFold protein GPU | PASS 34s | FAIL (binary missing) |
| ESMFold protein CPU | PASS 27s | FAIL (binary missing) |
| Chai protein | PASS 65s | PASS 63s |
| Chai protein+msa | PASS 67s | PASS 66s |
| Chai dna | PASS 58s | PASS 63s |
| OpenFold protein | PASS 96s | PASS 88s |
| OpenFold protein+msa | PASS 88s | PASS 88s |
| OpenFold dna | PASS 91s | PASS 92s |
| AlphaFold protein | PASS 26m | PASS 26m |

### Key Finding

All native tools work correctly on both containers (except ESMFold missing
from `all`). OpenFold works natively but fails through predict-structure,
isolating the bug to the adapter layer.

---

## Phase 2: predict-structure CLI Results

Tests the unified CLI adapter layer with the full tool x input x parameter matrix.

### folding_prod.sif: 48 pass, 11 fail, 5 xfail

| Category | Result |
|----------|--------|
| Auto-selection (5 tests) | 5/5 PASS |
| Debug mode (6 tests) | 6/6 PASS |
| Entity flags (1 test) | PASS |
| Job batch mode (1 test) | PASS |
| ESMFold via CLI (8 tests) | 8/8 PASS |
| Boltz via CLI (5 tests) | 5/5 PASS |
| Chai via CLI (7 tests) | 6/6 PASS + 1 xfail (SMILES) |
| AlphaFold via CLI (5 tests) | 3 PASS + 2 xfail (DNA/ligand) + 1 FAIL (wrong data dir, fixed) |
| OpenFold via CLI (8 tests) | 0/8 FAIL (adapter bug) |
| Output normalization (7 tests) | 7/7 PASS |
| GPU tool output (3 tests) | 1/3 FAIL (OpenFold) |

### all-2026-0410.01.sif: 33 pass, 26 fail, 5 xfail

Same as prod except all ESMFold tests fail (binary missing) and auto-select
`--device cpu` picks openfold instead of esmfold.

---

## Phase 3: Perl Service Script + Workspace Results

### folding_prod.sif: 33 pass, 3 fail

| Category | Result |
|----------|--------|
| Preflight (25 tests) | 25/25 PASS |
| Perl syntax check | PASS |
| Service: ESMFold input_file | PASS |
| Service: ESMFold text_input | FAIL (`text_input` not in app_spec) |
| Service: Boltz | PASS |
| Service: OpenFold | PASS |
| Service: Chai | PASS |
| Service: MSA upload (Boltz) | PASS |
| Workspace: p3-whoami | PASS |
| Workspace: p3-ls | FAIL (UTF-8 decode) |
| Workspace: upload+verify | FAIL (listing mismatch) |
| Workspace: ESMFold roundtrip | PASS |

### all-2026-0410.01.sif: Phase 3 N/A

The `all` container is a tool-only container without the BV-BRC service layer.
No `/kb/module/`, no Perl BV-BRC modules, no `p3-*` workspace tools.
All Phase 3 tests fail by design on this container.

---

## Known Issues

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | OpenFold adapter checkpoint resolution fails | High | Open -- native tool works, adapter broken |
| 2 | ESMFold missing from `all` container | High | Container build issue |
| 3 | `text_input` param not in PredictStructure.json app_spec | Medium | App spec update needed |
| 4 | `all` container has no BV-BRC layer | Info | By design (tool-only) |
| 5 | AlphaFold/JAX grabs all GPUs | Fixed | `CUDA_VISIBLE_DEVICES` injected by test framework |
| 6 | AlphaFold data dir hardcoded as `/databases` in tests | Fixed | Updated to `/local_databases/alphafold/databases` |
| 7 | Workspace p3-ls UTF-8 decode error | Low | Binary content in workspace listing |
| 8 | Workspace upload verify listing mismatch | Low | Path or timing issue |

---

## Environment

- **Host**: 8x NVIDIA H200 NVL (144GB VRAM each)
- **Containers**: `/scout/containers/folding_prod.sif`, `/scout/containers/all-2026-0410.01.sif`
- **Model weights**: `/local_databases/` (boltz, chai, openfold, alphafold/databases)
- **HF cache**: `/local_databases/cache/hub/`
- **Workspace token**: `~/.patric_token`
- **GPU pinning**: prod on GPUs 0-3, all on GPUs 4-7
