# Plan

**Version:** v2 (2026-06-09)
**Goal:** Production-harden PredictStructureApp, expand CWL/GoWe integration, onboard new tools

## Phase 1: Stabilize production (mostly complete)

- Unified adapter layer with 5 tools (Boltz, OpenFold, Chai, AlphaFold, ESMFold)
- GPU VRAM precheck, MSA validation, run logging (PR #42, merged)
- Container fixes (env vars, bash syntax, HF_HOME paths)
- Production container: folding_260602.1.sif — 47/47 tests pass on all 3 hosts

## Phase 2: Resolve open issues

- Issue #38: Boltz only works on coconut — evaluate torch+cu124 rebuild
- Issue #39: Add prediction provenance to protein_compare report
- Issue #40: ESMFold contacts HuggingFace Hub on every run — set HF_HUB_OFFLINE=1
- Push protein_compare v0.2.1 (blocked on SSH key)

## Phase 3: CWL / GoWe integration

- GoWe worker infrastructure (GPU + CPU workers)
- CWL tool definitions for BV-BRC dispatch
- Workspace upload flow testing
- Multi-step workflows (predict → extract → report → merge)

## Phase 4: Testing infrastructure

- Formalize test matrix (tool x entity x host)
- Negative test coverage via API
- Automated host-coverage tracking
- Testing skill / documentation

## Phase 5: New tool onboarding — ESMFold2

ESMFold2 (`biohub/ESMFold2`) is a diffusion-based successor to ESMFold v1. Multi-entity (protein, DNA, RNA, ligands), no MSA required. PR #44 adds the adapter; remaining work to make it functional:

- **Adapter** — PR #44 (open). Review findings: fix `_copy_raw` import, `num_samples` default, add `min_gpu_memory_mb`, wire up registration. Create `normalize_esmfold2_output()` in normalizers.py.
- **Runner** — `predict_structure.runners.esmfold2` (new module). No upstream CLI; runner calls the Python API directly, writes `model_1.cif` + `confidence.json`.
- **Registration** — `adapters/__init__.py`, CLI subcommand in `cli.py`, `tools.yml` entry, `App-PredictStructure.pl` dispatch, `PredictStructure.json` app_spec.
- **Container** — Install ESMFold2 + dependencies in SIF. Determine CUDA/PyTorch compatibility with existing tool stack.
- **Weights** — Download model to `/local_databases/esmfold2` on all hosts. Determine size and HuggingFace Hub requirements.
- **Testing** — Unit tests for entity→JSON conversion and command building. Add ESMFold2 cases to API test matrix (Phase 4). Verify on all 3 hosts.

## Changelog

- v2 (2026-06-09): Add Phase 5 (ESMFold2 onboarding) based on PR #44 review
- v1 (2026-06-09): Initial plan extracted from STATUS.md and session history
