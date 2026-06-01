# Project Status

**Last updated:** 2026-05-15
**Current version:** v0.16.1
**Production container:** `folding_260515.2.sif` (commit d7f2a43)

## Release v0.16.1

### Bug fixes

- **SMILES normalizer crash** -- Boltz PDB output for ligand-containing structures has corrupted line layout that crashes BioPython's PDB parser (upstream Boltz #298, #630). Fixed by preferring mmCIF over PDB in `_extract_bfactors()` and `promote_best_model()`.
- **protein_compare report crash** -- Same root cause. Fixed in protein_compare v0.2.1: `StructureLoader.load()` prefers `.cif` sibling when loading `.pdb` files.
- **Boltz GPU constraint** -- Boltz torch+cu130 requires CUDA 13.0+. Changed preflight constraint from `V100|H100|H200` to `H200` only. Mango (CUDA 12.6) and peach (CUDA 12.2) correctly rejected.
- **AlphaFold DB path** -- Perl defaulted to `/databases`; fixed to `/local_databases/alphafold/databases`.
- **CIF promotion** -- `promote_best_model()` now copies `model_1.cif` alongside `model_1.pdb` to the top-level output directory.

### Verified -- BV-BRC API (folding_260515.2.sif)

| Task ID | Test | Tool | Host | Status | Time |
|---|---|---|---|---|---|
| 22200613 | T01 | ESMFold | coconut | PASS | 0:46 |
| 22200616 | T02 | Boltz+MSA | coconut | PASS | 1:18 |
| 22200617 | T07 | Boltz+SMILES(CCO) | coconut | PASS | 1:20 |
| 22200618 | T06 | Boltz+ligand(ATP) | coconut | PASS | 1:21 |
| 22200619 | T08 | OpenFold | mango | PASS | 4:51 |
| 22200620 | T10 | Chai | mango | PASS | 4:30 |
| 22200621 | T14 | auto->Boltz | coconut | PASS | 1:27 |

- All Boltz jobs correctly routed to coconut (H200 constraint)
- OpenFold and Chai work on mango (CUDA 12.6, cu121)
- Boltz+SMILES report generation passes end-to-end (issue #41 fixed)

### Also verified -- local AppScript

- [x] Boltz+SMILES: prediction, normalization, confidence, report (folding_260515.2.sif, no dev overlay)
- [x] Full output layout: model_1.{pdb,cif}, report.html, results.json, predictions/, reports/, metadata/, inputs/

### Host coverage (cumulative, all test runs)

| Tool | coconut (H200, CUDA 13.0) | mango (H100, CUDA 12.6) | peach (V100, CUDA 12.2) |
|---|---|---|---|
| ESMFold | PASS | -- | -- |
| Boltz | PASS | N/A (cu130 needs 13.0) | N/A (cu130 needs 13.0) |
| OpenFold | PASS | PASS | -- |
| Chai | PASS | PASS | PASS |
| AlphaFold | PASS | PASS | -- |
| auto->Boltz | PASS | N/A | N/A |

### Host coverage gaps

| Tool | Host | Notes |
|---|---|---|
| ESMFold | mango, peach | Scheduler favors coconut; needs targeted submission |
| OpenFold | peach | Not yet tested |
| AlphaFold | peach | Not yet tested |

## Open issues

| # | Issue | Status | Notes |
|---|---|---|---|
| 38 | Boltz only works on coconut (cu130 needs CUDA 13.0) | Open | Long-term fix: rebuild Boltz with torch+cu124 |
| 39 | Add prediction provenance to characterization report | Open | |
| 40 | ESMFold contacts HuggingFace Hub on every run | Open | Set HF_HUB_OFFLINE=1 |
| 41 | Boltz PDB ligand lines crash BioPython | Fixed in v0.16.1 | Also fixed in protein_compare v0.2.1 |

## Infrastructure

### GPU hosts

| Host | GPU | CUDA | Boltz (cu130) | OF/Chai (cu121) | ESMFold (cu124) |
|---|---|---|---|---|---|
| coconut | 8x H200 NVL (141GB) | 13.0 | YES | YES | YES |
| mango | 8x H100 NVL (95GB) | 12.6 | NO | YES | YES |
| peach | 2x V100 PCIE (32GB) | 12.2 | NO | YES | YES |

### Containers

| SIF | Date | Status | Notes |
|---|---|---|---|
| folding_260515.2.sif | 2026-05-15 | **Production** | v0.16.1: all fixes verified via API |
| folding_260514.4.sif | 2026-05-14 | Broken | Missing ~3GB, scheduler instant-fail |
| folding_260514.2.sif | 2026-05-14 | Stale code | Version says 0.16.1 but normalizers.py was old |
| folding_260515.1.sif | 2026-05-15 | Stale code | Same issue as 260514.2 |
| folding_260513.1.sif | 2026-05-13 | Previous prod | v0.16.0 baseline, no SMILES fix |

### Dependencies

| Repo | Version | Status |
|---|---|---|
| PredictStructureApp | v0.16.1 | Pushed to GitHub |
| protein_compare | v0.2.1 | Committed + tagged, needs push (SSH key) |

## Next steps

1. Push protein_compare v0.2.1 to GitHub (fix SSH auth)
2. Fill host coverage gaps (ESMFold on mango/peach, OpenFold on peach, AlphaFold on peach)
3. Run full 24-case API test matrix
4. Issue #38: evaluate torch+cu124 rebuild for Boltz (enables mango/peach)
5. Issue #40: set HF_HUB_OFFLINE=1 for ESMFold
6. Write Phase 4 API submission script (currently manual curl)
