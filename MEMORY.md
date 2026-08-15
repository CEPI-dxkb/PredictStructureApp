# Memory — Decisions, Rules, and Lessons

Project-level institutional knowledge. Append-only (mark superseded, never delete).
For Claude-only context (preferences, feedback), use auto-memory instead.

## Decisions

- **Adapter pattern over plugin pattern** — Each tool gets a dedicated adapter class (prepare_input, build_command, run, normalize_output). Keeps tool-specific logic isolated and independently testable. (2026-05)
- **Delegation, not monolith** — BV-BRC service script dispatches to per-tool containers rather than bundling all tools into one Docker image. Keeps images small and independently updatable. (2026-05)
- **A3M as MSA lingua franca** — All MSA input goes through A3M format; adapters convert to tool-native (Parquet for Chai, YAML injection for Boltz). Single format to validate. (2026-05)
- **Explicit entity flags in CLI** — `--protein`, `--dna`, `--rna`, `--ligand`, `--smiles` instead of positional args or auto-detection. Unambiguous, composable, matches app_spec. (2026-05)
- **mmCIF preferred over PDB for ligands** — Boltz PDB output for ligand-containing structures has corrupted line layout (upstream #298, #630). Always prefer mmCIF when available. (2026-05)
- **CCD validation lives in `EntityList.add`, not at the CLI edge** — A malformed CCD code is invalid for every tool, so it is a data-model invariant, not tool policy. Enforcing it in `add()` covers the CLI, the `--job` batch path, adapters, and library callers in one place; `_build_entity_list` converts the `ValueError` to a `click.UsageError` (exit 2, no traceback). (Issue #48, 2026-08)

## Rules / Constraints

- **Boltz requires CUDA 13.0+** — torch+cu130; only runs on coconut (H200). Constraint set to `H200` in preflight. (Issue #38)
- **Run short API tests before AlphaFold** — AlphaFold takes ~23 min. If the image is broken, that's wasted. Short tests (ESMFold, Boltz, OpenFold, Chai) finish in ~2 min and catch most issues.
- **Container code can be stale** — pip caches wheels; a new SIF may contain old predict_structure code even with a new version tag. Always verify with `apptainer exec $SIF python -c "import predict_structure; print(predict_structure.__version__)"`.
- **CCD codes are 1-3 OR exactly 5 alphanumeric — never 4** — wwPDB reserved 4 characters so component IDs cannot be confused with PDB entry IDs, and began issuing 5-character "extended" IDs in 2023 (A1H1F, A1AJ7), asking developers to lift hard-coded length limits. Enumerating RCSB's whole component space (50,983 IDs) gives len1=16, len2=129, len3=43,387, **len4=0**, len5=6,647; the 804 10-character `PRD_xxxxxx` entries are BIRD identifiers, a different namespace, deliberately excluded. Boltz's bundled snapshot (`/local_databases/boltz/mols`) has the same shape and contains `A1H1F.pkl`. Our old `^[A-Za-z0-9]{1,3}$` therefore **rejected valid ligands**. All archive IDs are uppercase, so input is normalized on the way in. Sources: pdbj.org/news/starting_5-character_CCDID, rcsb.org/news/feature/63ff72ccc031758bf1c30ff7, github.com/wwPDB/extended-wwPDB-identifier-examples. (Issue #48, 2026-08)
- **The CCD rule is duplicated in Perl — keep it self-policing** — `service-scripts/App-PredictStructure.pl` re-implements the check for the BV-BRC submit path, and there are no Perl tests in `tests/`. `tests/test_entities.py::TestPerlRegexParity` asserts the Perl literal is `CCD_CODE_RE.pattern` verbatim, wrapped in `\A`/`\z`. Use `\A`/`\z` (Perl) and `re.fullmatch` (Python), never `^`/`$`: `$` also matches before a trailing newline in both languages, so `"ATP\n"` slips through an anchored match.

## Lessons Learned

- **folding_260601.1 broke on mango** — All OpenFold/Chai/AlphaFold jobs failed in ~9s. Root cause: container-level breakage on CUDA 12.6 hosts. Fixed in folding_260602.1. Lesson: always test on all three hosts, not just coconut. (2026-06-01)
- **90-environment.sh syntax matters** — `[[ ]]` bash syntax in a `#!/bin/sh` script with empty if-block bodies crashes silently, preventing PATH setup. Use unconditional exports. (2026-05-22)
- **Swapped input/MSA files cause cryptic failures** — Boltz rejects .fa as MSA ("only a3m or csv") but the error isn't obvious from the API. Preflight MSA validation (PR #42) now catches this. (2026-05-31)
