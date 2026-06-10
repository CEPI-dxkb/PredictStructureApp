# Memory — Decisions, Rules, and Lessons

Project-level institutional knowledge. Append-only (mark superseded, never delete).
For Claude-only context (preferences, feedback), use auto-memory instead.

## Decisions

- **Adapter pattern over plugin pattern** — Each tool gets a dedicated adapter class (prepare_input, build_command, run, normalize_output). Keeps tool-specific logic isolated and independently testable. (2026-05)
- **Delegation, not monolith** — BV-BRC service script dispatches to per-tool containers rather than bundling all tools into one Docker image. Keeps images small and independently updatable. (2026-05)
- **A3M as MSA lingua franca** — All MSA input goes through A3M format; adapters convert to tool-native (Parquet for Chai, YAML injection for Boltz). Single format to validate. (2026-05)
- **Explicit entity flags in CLI** — `--protein`, `--dna`, `--rna`, `--ligand`, `--smiles` instead of positional args or auto-detection. Unambiguous, composable, matches app_spec. (2026-05)
- **mmCIF preferred over PDB for ligands** — Boltz PDB output for ligand-containing structures has corrupted line layout (upstream #298, #630). Always prefer mmCIF when available. (2026-05)

## Rules / Constraints

- **Boltz requires CUDA 13.0+** — torch+cu130; only runs on coconut (H200). Constraint set to `H200` in preflight. (Issue #38)
- **Run short API tests before AlphaFold** — AlphaFold takes ~23 min. If the image is broken, that's wasted. Short tests (ESMFold, Boltz, OpenFold, Chai) finish in ~2 min and catch most issues.
- **Container code can be stale** — pip caches wheels; a new SIF may contain old predict_structure code even with a new version tag. Always verify with `apptainer exec $SIF python -c "import predict_structure; print(predict_structure.__version__)"`.

## Lessons Learned

- **folding_260601.1 broke on mango** — All OpenFold/Chai/AlphaFold jobs failed in ~9s. Root cause: container-level breakage on CUDA 12.6 hosts. Fixed in folding_260602.1. Lesson: always test on all three hosts, not just coconut. (2026-06-01)
- **90-environment.sh syntax matters** — `[[ ]]` bash syntax in a `#!/bin/sh` script with empty if-block bodies crashes silently, preventing PATH setup. Use unconditional exports. (2026-05-22)
- **Swapped input/MSA files cause cryptic failures** — Boltz rejects .fa as MSA ("only a3m or csv") but the error isn't obvious from the API. Preflight MSA validation (PR #42) now catches this. (2026-05-31)
