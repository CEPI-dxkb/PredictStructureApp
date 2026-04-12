# Acceptance Test Results

Last updated: 2026-04-12

## Latest: folding_260411.1.sif

Full end-to-end run with all fixes baked into the container.

| Phase | Tests | Passed | Failed | XFail |
|-------|:-----:|:------:|:------:|:-----:|
| **Phase 1** native | 13 | **13** | 0 | 0 |
| **Phase 2** CLI | 64 | **54** | 5 | 5 |
| **Phase 3** service+ws | 36 | **34** | 2 | 0 |
| **Total** | **113** | **101** | **7** | **5** |

Runtime: 198 min (3.3h) on GPUs 0-3

### Phase 1: Native Tools -- 13/13 PASS

| Test | Time |
|------|------|
| Boltz protein+msa | 69s |
| Boltz protein (no msa) | 19s |
| Boltz protein msa:empty | 65s |
| Boltz dna | 62s |
| ESMFold protein GPU | 34s |
| ESMFold protein CPU | 27s |
| Chai protein | 65s |
| Chai protein+msa | 67s |
| Chai dna | 58s |
| OpenFold protein | 96s |
| OpenFold protein+msa | 88s |
| OpenFold dna | 91s |
| AlphaFold protein | 26m |

### Phase 2: CLI -- 54 pass, 5 fail, 5 xfail

| Category | Result |
|----------|--------|
| Auto-selection (5) | 5/5 PASS |
| Debug mode (6) | 6/6 PASS |
| Entity flags (1) | PASS |
| Job batch mode (1) | PASS |
| ESMFold via CLI (8) | 8/8 PASS |
| Boltz via CLI (5) | 5/5 PASS |
| Chai via CLI (7) | 6/6 PASS + 1 xfail (SMILES) |
| AlphaFold via CLI (5) | 3/3 PASS + 2 xfail (DNA/ligand) |
| OpenFold via CLI (8) | 4/8 -- see below |
| Output normalization (7) | 7/7 PASS |
| GPU tool output (3) | 2/3 PASS |

**OpenFold Phase 2 failures (5):**
- `openfold-protein`: PASS prediction, FAIL validation (residue count 326 vs 46)
- `openfold-protein_msa`: rc=1 -- IndexError in MSA processing (input format mismatch)
- `openfold-protein_diff3`: PASS prediction, FAIL validation (residue count)
- `openfold subcommand_full`: PASS prediction, FAIL validation (residue count)
- `openfold gpu_tool_output`: PASS prediction, FAIL validation (residue count)

Root causes: (1) normalizer reports per-atom pLDDT count instead of per-residue
(4 tests), (2) precomputed MSA file naming doesn't match OpenFold's expected
format (1 test).

### Phase 3: Service + Workspace -- 34 pass, 2 fail

| Category | Result |
|----------|--------|
| Preflight (25) | 25/25 PASS |
| Perl syntax | PASS |
| Service: ESMFold input_file | PASS |
| Service: ESMFold text_input | PASS |
| Service: Boltz | PASS |
| Service: OpenFold | PASS |
| Service: Chai | PASS |
| Service: MSA upload (Boltz) | PASS |
| Workspace: p3-whoami | PASS |
| Workspace: p3-ls | FAIL (UTF-8 decode) |
| Workspace: upload+verify | FAIL (listing mismatch) |
| Workspace: ESMFold roundtrip | PASS |

---

## Container Comparison

| | folding_prod.sif | folding_260411.1.sif | Delta |
|--|:----------------:|:--------------------:|:-----:|
| Phase 1 | 13 pass | 13 pass | -- |
| Phase 2 | 48 pass, 11 fail | 54 pass, 5 fail | +6 |
| Phase 3 | 33 pass, 3 fail | 34 pass, 2 fail | +1 |
| **Total** | **94 pass, 14 fail** | **101 pass, 7 fail** | **+7** |

Improvements in 260411.1:
- OpenFold runs through predict-structure (data_dir, MSA/template defaults fixed)
- ESMFold text_input works (app_spec updated)

---

## Remaining Failures (7)

| # | Issue | Tests | Severity |
|---|-------|:-----:|----------|
| 1 | OpenFold normalizer residue count (326 vs 46) | 4 | Medium -- per-atom vs per-residue pLDDT |
| 2 | OpenFold precomputed MSA IndexError | 1 | Medium -- MSA file naming mismatch |
| 3 | Workspace p3-ls UTF-8 decode | 1 | Low |
| 4 | Workspace upload verify listing | 1 | Low |

## Issues Tracker

| # | Issue | Status |
|---|-------|--------|
| 1 | OpenFold adapter: data dir, MSA/templates defaults | **Fixed in 260411.1** |
| 2 | OpenFold evoformer JIT on H200 | **Fixed** (runner.yml) |
| 3 | OpenFold normalizer residue count | Open |
| 4 | OpenFold precomputed MSA input format | Open |
| 5 | ESMFold missing from `all` container | Open (container build) |
| 6 | `text_input` not in app_spec | **Fixed in 260411.1** |
| 7 | `all` container has no BV-BRC layer | By design |
| 8 | AlphaFold/JAX grabs all GPUs | **Fixed** (CUDA_VISIBLE_DEVICES) |
| 9 | Boltz requires MSA for protein | **Fixed** (msa: empty) |
| 10 | OpenFold use_msas tied to use_msa_server | **Fixed in 260411.1** |
| 11 | Dev overlay at /opt breaks JIT | **Fixed** (PYTHONPATH at /mnt) |
| 12 | Evoformer JIT inconsistency shell vs pytest | Open (TODO -- see notes) |
| 13 | Workspace p3-ls UTF-8 / upload verify | Open (low priority) |

## Environment

- **Host**: 8x NVIDIA H200 NVL (144GB VRAM each)
- **Container**: `/scout/containers/folding_260411.1.sif` (22GB)
- **Model weights**: `/local_databases/` (boltz, chai, openfold, alphafold/databases)
- **OpenFold runner.yml**: `/local_databases/openfold/runner.yml`
- **HF cache**: `/local_databases/cache/hub/`
- **Workspace token**: `~/.patric_token`
- **GPU pinning**: `--gpu-id 0,1,2,3`
