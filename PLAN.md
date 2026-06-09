# Plan

**Version:** v1 (2026-06-09)
**Goal:** Production-harden PredictStructureApp and expand CWL/GoWe integration

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

## Changelog

- v1 (2026-06-09): Initial plan extracted from STATUS.md and session history
