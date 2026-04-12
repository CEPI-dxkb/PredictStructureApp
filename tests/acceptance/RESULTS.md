# Acceptance Test Results

Date: 2026-04-11

## Summary

Full end-to-end run on both production containers, all phases including AlphaFold.
Results reflect fixes applied during the testing session.

### Current Status (after fixes)

| Phase | folding_prod.sif | all-2026-0410.01.sif |
|-------|:----------------:|:--------------------:|
| **Phase 1** native (13 tests) | 13 pass | 11 pass, 2 fail |
| **Phase 2** CLI (64 tests) | ~57 pass, ~2 fail, 5 xfail | ~40 pass, ~19 fail, 5 xfail |
| **Phase 3** service+ws (36 tests) | 33 pass, 3 fail | 25 pass, 11 fail |

### Fixes Applied During Testing

| Fix | Impact |
|-----|--------|
| `tools.yml` OpenFold data_dir `/scout/data/openfold` -> `openfold` | OpenFold checkpoint resolves correctly |
| OpenFold CLI `--use-msa-server` and `--use-templates` default False | No MSA server dependency, avoids evoformer JIT on H200 |
| OpenFold adapter `use_msas` default False in query JSON | Skips MSA processing entirely when not provided |
| Auto-resolve `runner.yml` from data dir (H200 DeepSpeed workaround) | OpenFold runs through predict-structure on H200 |
| Boltz converter `msa: empty` for protein without MSA | Boltz single-sequence mode works |
| AlphaFold data dir in tests `/databases` -> `/local_databases/alphafold/databases` | AlphaFold tests find databases |
| Dev code via PYTHONPATH=/mnt/predict-structure (not /opt overlay) | No JIT interference with other conda envs |
| `App-PredictStructure.pl` full path + correct arg format | Service script invocation works |
| Workspace token `pytest.skip` instead of `pytest.fail` | Tests skip gracefully without token |

### Remaining Failures

| Issue | prod | all | Notes |
|-------|:----:|:---:|-------|
| OpenFold normalizer residue count mismatch | 1 | 1 | Reports 326 instead of 46 (per-atom vs per-residue?) |
| ESMFold missing from container | 0 | 17 | `/opt/conda-esmfold/` not installed |
| `all` has no BV-BRC layer | 0 | 11 | By design (tool-only container) |
| `text_input` not in app_spec | 1 | 1 | PredictStructure.json needs update |
| Workspace p3-ls UTF-8 decode | 1 | 0 | Binary content in listing |
| Workspace upload verify | 1 | 0 | Listing path mismatch |
| Auto-select cpu picks openfold | 0 | 1 | ESMFold unavailable |

---

## Phase 1: Native Tool Results

Tests each folding tool directly (bypassing predict-structure) to establish
ground truth for what each tool can do natively.

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

### Phase 1 Findings

- All native tools work correctly on both containers (except ESMFold missing from `all`).
- Boltz `protein (no msa)` exits 0 but produces no output -- Boltz requires
  explicit MSA field (`msa: empty` or file) for protein chains.
- DNA-only inputs work without MSA on Boltz, Chai, and OpenFold.
- OpenFold works natively but failed through predict-structure (adapter issues,
  now fixed).

---

## Phase 2: predict-structure CLI Results

Tests the unified CLI adapter layer. Results reflect fixes to OpenFold adapter
(data dir, MSA/template defaults, runner.yml).

### folding_prod.sif: 26 pass, 0 fail, 5 xfail (fast tests, 8 min)

| Category | Result |
|----------|--------|
| Auto-selection (5 tests) | 5/5 PASS |
| Debug mode (6 tests) | 6/6 PASS |
| Entity flags (1 test) | PASS |
| Job batch mode (1 test) | PASS |
| ESMFold via CLI (8 tests) | 8/8 PASS |
| Output normalization (7 tests) | 7/7 PASS |
| xfail (entity rejection) | 5/5 XFAIL (expected) |

### Full matrix (including slow tests)

| Tool | Result | Notes |
|------|--------|-------|
| Boltz | 5/5 PASS | protein_msa, protein, dna + param variations |
| Chai | 6/6 PASS + 1 xfail | protein_smiles rejected (expected) |
| AlphaFold | 4/4 PASS + 2 xfail | protein, multimer + DNA/ligand rejected |
| ESMFold | 5/5 PASS + 2 xfail | protein, cpu, multimer + DNA/ligand rejected |
| OpenFold | ~7/8 PASS, 1 validation fail | Runs successfully, normalizer residue count issue |

### all-2026-0410.01.sif

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

---

## Issues Tracker

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | OpenFold adapter: data dir, MSA/templates defaults | High | **Fixed** |
| 2 | OpenFold evoformer JIT fails on H200 without runner.yml | High | **Fixed** (runner.yml auto-resolved from data dir) |
| 3 | OpenFold normalizer residue count (326 vs 46) | Medium | Open -- per-atom vs per-residue pLDDT |
| 4 | ESMFold missing from `all` container | High | Open -- container build issue |
| 5 | `text_input` param not in PredictStructure.json | Medium | Open -- app spec update needed |
| 6 | `all` container has no BV-BRC layer | Info | By design (tool-only) |
| 7 | AlphaFold/JAX grabs all GPUs | Fixed | `CUDA_VISIBLE_DEVICES` injected by framework |
| 8 | AlphaFold data dir wrong in tests | Fixed | `/local_databases/alphafold/databases` |
| 9 | Boltz requires MSA for protein chains | Fixed | `msa: empty` in converter |
| 10 | Dev overlay breaks JIT in other conda envs | Fixed | PYTHONPATH at /mnt instead of /opt bind |
| 11 | Workspace p3-ls UTF-8 decode | Low | Binary content in listing |
| 12 | Workspace upload verify mismatch | Low | Path or timing issue |

---

## Environment

- **Host**: 8x NVIDIA H200 NVL (144GB VRAM each)
- **Containers**: `/scout/containers/folding_prod.sif`, `/scout/containers/all-2026-0410.01.sif`
- **Model weights**: `/local_databases/` (boltz, chai, openfold, alphafold/databases)
- **OpenFold runner.yml**: `/local_databases/openfold/runner.yml` (disables DeepSpeed evo_attention for H200)
- **HF cache**: `/local_databases/cache/hub/`
- **Dev code overlay**: `PYTHONPATH=/mnt/predict-structure` (bind at /mnt, not /opt)
- **Workspace token**: `~/.patric_token`
- **GPU pinning**: `CUDA_VISIBLE_DEVICES` per run via `--gpu-id`
