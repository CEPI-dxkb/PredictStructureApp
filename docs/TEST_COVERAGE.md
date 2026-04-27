# Test Coverage Analysis

Snapshot rating + gap inventory for the PredictStructureApp test suite.

## Status — branch `tiered-fixture-ladder`

Most of the gaps + the T1–T5 tier ladder have been implemented on the
`tiered-fixture-ladder` branch. Status:

| Item | Status |
|---|---|
| T1–T5 tier markers + Tier dataclass + `msa_args_for` policy helper | ✅ |
| Per-tool MSA policy (Boltz/Chai require, OpenFold prefers, AF builds-own, ESMFold ignores) | ✅ |
| Medium (1AKE 214 aa) + large (enolase 434 aa) protein fixtures | ✅ |
| `scripts/generate_test_msas.sh` (one-shot ColabFold MSA generator) | ✅ -- run out-of-band; commit the resulting `.a3m` |
| `scripts/generate_service_params.py` (18 tier×tool JSON files) | ✅ |
| Phase 2 `TestTierCoverage` (23 cases, debug-mode, ~10s) | ✅ |
| Phase 3 `TestServiceScriptTiers` (T1–T5 service-script execution) | ✅ |
| Layout parity test (gap #1) | ✅ |
| `results.json` schema + sha256 manifest validation (gap #3) | ✅ |
| RO-Crate validation (gap #4, skipped if rocrate not in SIF) | ✅ |
| `finalize-results` / `aggregate-results` standalone tests (gap #6) | ✅ |
| Concurrency hazard in `make_output_path` (gap #7) | ✅ -- UUID8 suffix |
| Failure-mode tests (gap #8) | ✅ |
| `donot_create_result_folder` regression guard (gap #9) | ✅ |
| `KEEP_WORKSPACE` regression test (gap #13) | ✅ |
| `--job` batch end-to-end (gap #14) | ✅ |
| CWL workflow execution test (gap #2) | ✅ -- `tests/acceptance/test_cwl_workflow_execution.py`, gated on `cwltool` |
| Multi-tool workflow execution (gap #5) | partial -- `aggregate-results` exercised via CLI test; full multi-tool fan-out deferred (4× GPU runtime) |
| Container build CI (gap #10) | deferred -- infra, separate follow-up |
| MSA-server mode (gap #11) | out of scope per user lock |
| Phase 1 native T2/T5 tier tests | deferred -- Phase 2/3 tier coverage is the higher-leverage layer |

### Validation status (as of `tiered-fixture-ladder` HEAD)

Full T1-T5 sweep on `folding_260425.1.sif` (H200 NVL): **53 tests
passing, 0 failed, 0 skipped, ~25 min total wall-clock**.

| Tier | Tests | Wall-clock |
|---|---|---|
| `tier1 and not slow` | 21 | 5m54s |
| `tier2` | 9 | 4m57s |
| `tier3` | 6 | 4m07s |
| `tier4` | 9 | 4m55s |
| `tier5` | 8 | 4m57s |

`folding_prod.sif` was validated through T2 only; later tier runs used
`folding_260425.1.sif` (which ships `rocrate 0.15.0`, flipping the 4
RO-Crate skips on `folding_prod.sif` to passes).

Real bugs surfaced + fixed during validation:

1. service-script tests passed silently when the BV-BRC framework
   caught a Perl `die` (returned exit 0). Tests now also assert
   `model_1.pdb` exists post-run.
2. `download_workspace_file` always tried the workspace API first,
   failing on container-local fixture paths. Now tries local file first.
3. ColabFold-API MSA extraction left a trailing NUL byte that broke
   Boltz's a3m parser. `_colabfold_api_msa.py` now strips it.
4. `_has_rocrate_in_container` used bare `python` (PATRIC runtime),
   masking that rocrate WAS installed in the predict-structure env.
   Now uses `/opt/conda-predict/bin/python` explicitly.
5. `results.json` manifest listed `ro-crate-metadata.json` with stale
   size/sha256 (the crate is rewritten *after* the manifest in the
   `_finalize_output` order). Now excluded like `results.json` itself.

## Inventory

- **358 unit tests** (no GPU, no container) — adapters, converters,
  normalizers, results, CLI, CWL backend, entities, config.
- **114 acceptance tests** (require Apptainer container; some require
  GPU, workspace token).
- 8 phase test files; ~2,300 lines of test code.

## Rating: B+

### Strengths

| | |
|---|---|
| **Phased isolation** | Native tool → adapter → CLI → service-script. Catches "which layer broke." |
| **Schema validation** | `confidence.schema.json`, `metadata.schema.json`, `results.schema.json` actually checked, not just file presence. |
| **Multi-container parametrization** | Tests run against both `folding_prod.sif` and `all-…sif` automatically; catches per-image drift. |
| **Real workspace round-trip** | `p3-cp` upload + listing verified; not mocked. |
| **Markers + selective runs** | `phase1/2/3`, `gpu`, `slow`, `workspace` lets you scope a run to seconds vs hours. |
| **Dev overlay** | `PREDICT_STRUCTURE_DEV_SERVICE=1` lets you iterate without rebuilding the SIF. |
| **Debug-mode heavy in Phase 2** | Most CLI integration tests use `--debug` so the surface is exercised in seconds, not hours of GPU. |

### Gaps (ordered by importance)

1. **No CWL ↔ app-script layout parity test.** The whole point of the
   recent unification is that both paths produce the *identical* tree.
   The plan called for `tests/acceptance/test_layout_parity.py` (run both
   flows against the same fixture, diff the relative paths). **Not
   implemented.** Single highest-value missing test.
2. **No CWL workflow execution at acceptance level.** `test_cwl_tool.py`
   validates CWL syntax; `test_cwl_acceptance.py` exercises the backend.
   But no test runs `cwltool cwl/workflows/protein-structure-prediction.cwl`
   end-to-end and asserts the output layout.
3. **`results.json` not validated in acceptance tests.** Schema is
   committed but only unit-tested. After a real prediction (Phase 2/3),
   nobody asserts the manifest's sha256s match the on-disk files.
4. **`ro-crate-metadata.json` is effectively untested in production.**
   `rocrate` isn't in the current SIF, so it's silently skipped — and no
   acceptance test asserts "the file is present" (would fail loudly
   until SIF rebuild) or "validates as a Process Run Crate" via
   `rocrate-validator`.
5. **Multi-tool workflow untested.** `multi-tool-comparison.cwl` got a
   new `aggregate_results` step; only the CWL syntax is validated. No
   test runs the full multi-tool fan-out + aggregation.
6. **`finalize-results` / `aggregate-results` standalone untested.**
   Only unit tests. A direct `predict-structure finalize-results <dir>`
   acceptance test on an existing output dir would catch CLI contract
   drift cheaply.
7. **Concurrency hazard in `make_output_path`.** Uses `datetime.now()`
   to second precision. Two parallel tests starting in the same second
   collide. With `pytest-xdist -n 2` this is a real flake risk. Add PID
   or a UUID suffix.
8. **Thin failure-mode coverage.** `chai_reject_smiles`-style negative
   tests exist in Phase 1 only. Mid-run failures (CUDA OOM → `has_output`
   fallback path in `cli.py:574-579`), partial workspace upload failures,
   missing `confidence.json` after normalization — none exercised.
9. **No regression test for `donot_create_result_folder(1)`.** The
   framework auto-creating the target dir caused the `output/` nesting
   bug. A dedicated assertion ("framework did not create `<output_path>`
   before our upload") would prevent regressions when the AppScript
   framework upgrades.
10. **Container build not tested.** Adding a dep to `pyproject.toml`
    that breaks the SIF build is only caught by manual rebuild.
11. **MSA-server mode untested.** Excluded by deliberate scope decision,
    but it's still live code in adapters — silent rot risk.
12. **Limited input shape coverage.** Only `simple_protein.fasta`
    (crambin, 46 residues) for most Phase 2 tests; no large-input
    boundary tests despite the app spec mentioning input limits.
13. **`PREDICT_STRUCTURE_KEEP_WORKSPACE` regression-untested.** Feature
    added recently; no test asserts cleanup is actually skipped.
14. **`--job` batch mode** has only `--debug` coverage in Phase 2. A
    single `--job` end-to-end run would catch the YAML-parsing path.

### Recommended first batch (highest ROI)

- `tests/acceptance/test_layout_parity.py` — diff CWL vs app-script trees
  on shared fixture (gap #1).
- One ESMFold CWL workflow run via `cwltool` asserting the unified layout
  (#2 + #5).
- Acceptance-level `results.json` schema + sha256 manifest validation (#3).
- Add PID/UUID suffix to `make_output_path` to fix the concurrency
  hazard (#7).

---

## Host-runner vs inside-container test execution

### Current setup (host runner)

- `pytest` runs on the **host** Python env (`predict-structure` conda env).
- Has access to host-installed `cwltool`, host-installed
  `/scout/Experiments/GoWe/bin/cwl-runner`, host workspace token at
  `~/.patric_token`.
- Spawns the SIF via `apptainer exec` for the actual prediction; the
  test code stays outside.
- Catches: container API contract, output schema, workspace round-trip,
  cross-container parity (multiple SIFs side by side).

### Production parallel (inside-container runner)

- BV-BRC AppService spawns `App-PredictStructure.pl` **inside** the SIF.
- For a regression suite that mirrors production, tests would run via
  `apptainer exec folding_prod.sif python -m pytest /opt/predict-structure/tests/ ...`.
- The container's installed `predict-structure` CLI is at
  `/opt/conda-predict/bin/predict-structure`, not on the host PATH.
- Catches: SIF deployment health (paths, deps, env vars, conda envs
  activate correctly), "did this image actually ship boltz?", "is
  `protein_compare` resolvable from the right Python?".

### Are they totally different scopes?

**No — same scope, different orchestration.** Most tests are
layer-agnostic ("predict-structure boltz produces model_1.pdb with valid
confidence.json"). They work identically from host or from inside.

The genuinely different tests are a small minority:

| Test type | Host only | Inside-container only |
|---|---|---|
| Cross-container parity (`prod` vs `all` SIF side by side) | ✓ | — |
| Host-installed GoWe runner integration | ✓ | — |
| CWL workflow via host `cwltool` | ✓ (today) | ✓ (also valid) |
| SIF environment health smoke (paths, conda envs, deps) | — | ✓ |
| BV-BRC AppService framework wiring | — | ✓ |
| Workspace round-trip via `p3-cp` | ✓ | ✓ |

### Recommendation: one test suite, two execution contexts

Don't fork into two suites — the duplication cost > conditional-marker
cost.

1. **Single suite, executed from both contexts.** Add markers:
   - `@pytest.mark.host_runner` — needs host context (cross-container,
     host GoWe).
   - `@pytest.mark.in_container_only` — needs to run inside the SIF
     (env-health smoke).
   - Default (no marker) — works in both contexts.

2. **Make pytest installable in the SIF.** The `pyproject.toml` already
   has `[dev]` extras with pytest; ensure `pip install .[all]` in the
   container Dockerfile picks them up (it does today). Confirm with
   `apptainer exec folding_prod.sif python -c "import pytest"`.

3. **CI matrix:**
   - **Host run** (existing): `pytest tests/ -m "not in_container_only"`.
     Validates the public API and acceptance flows; uses host Python +
     `apptainer exec` for predictions.
   - **Inside-SIF run** (new): `apptainer exec --bind <workspace>
     folding_prod.sif python -m pytest /opt/predict-structure/tests/ -m
     "not host_runner"`. Validates the SIF as a deployable artifact.
   - Both runs share assertions about output layout, schemas, and the
     unified `results.json`.

4. **CWL workflow tests live in both contexts.** When run from host,
   `cwltool` uses `--singularity` to launch the SIF. When run inside the
   SIF, `cwltool --no-container` reuses the already-active environment.
   Either way, the assertion is the same: the produced directory tree
   matches the schema in `docs/OUTPUT_NORMALIZATION.md` §1.

### What this catches

| Failure mode | Host-only run | Inside-SIF run |
|---|---|---|
| Output schema regression | ✓ | ✓ |
| Adapter param mapping bug | ✓ | ✓ |
| SIF missing a tool binary | ✗ (silent skip if env-aware) | ✓ |
| `/opt/conda-predict` PATH broken | ✗ | ✓ |
| Workspace token plumbing | ✓ | ✓ |
| Cross-container drift (prod vs all) | ✓ | ✗ |
| CWL workflow output layout | ✓ | ✓ |
| BV-BRC AppService framework upgrade | partial | ✓ |

The two runs together give you both "is the API contract honored" and
"is this image production-ready" without maintaining two test suites.

### Gating with markers (concrete sketch)

The signal is "is this pytest process running inside the SIF, or on the
host?" Apptainer / Singularity sets a dedicated env var inside the
container, so use that — it's semantically correct and decoupled from
filesystem layout:

```python
# tests/acceptance/conftest.py
import os
import pytest

def _running_in_container() -> bool:
    """True iff the pytest process itself is executing inside an
    Apptainer/Singularity container (not just spawning one via
    `apptainer exec`)."""
    return bool(
        os.environ.get("APPTAINER_CONTAINER")
        or os.environ.get("SINGULARITY_CONTAINER")
    )


def pytest_collection_modifyitems(config, items):
    in_container = _running_in_container()
    skip_host = pytest.mark.skip(reason="requires host execution context")
    skip_sif = pytest.mark.skip(reason="requires inside-container execution")
    for item in items:
        if "host_runner" in item.keywords and in_container:
            item.add_marker(skip_host)
        if "in_container_only" in item.keywords and not in_container:
            item.add_marker(skip_sif)
```

Why the env var, not a path probe:

- `Path("/opt/conda-predict").exists()` would be `True` inside the SIF
  and `False` on the host — but it conflates "am I inside the SIF" with
  "is predict-structure installed at this path." Future container
  rebuilds could move the conda env, silently breaking the gate.
- `APPTAINER_CONTAINER` / `SINGULARITY_CONTAINER` are set automatically
  by the runtime and hold the SIF path; their presence directly answers
  the question we care about.

Then mark a handful of host-specific tests (cross-container
parametrization, host GoWe integration) with `@pytest.mark.host_runner`
and a handful of in-SIF-specific tests (environment health, conda env
activation, framework wiring) with `@pytest.mark.in_container_only`.
Everything else stays portable.

---

## Cross-phase fixture coverage

A separate question from "what tests exist" is "do the same use cases
flow through all three phases?" Currently they don't.

### What's used today

| Fixture | Size | Phase 1 (native) | Phase 2 (CLI) | Phase 3 (service+ws) |
|---|---|:-:|:-:|:-:|
| `simple_protein.fasta` (crambin, 46 aa) | small | ✓ all tools | ✓ all tools | ✓ all 7 service params + both workspace tests |
| `multimer.fasta` (2 chains, 55 aa) | small | ✓ Boltz only | — | — |
| `dna.fasta` (20 nt) | tiny | ✓ Boltz, OpenFold | ✓ multi-entity | — |
| `rna.fasta` (20 nt) | tiny | — | ✓ multi-entity (Boltz) | — |
| `crambin.a3m` MSA | — | ✓ Boltz/Chai/OpenFold | ✓ MSA-mode tests | ✓ `boltz_msa_upload.json` only |
| `complex-chai.fasta` (6 chains, 123 aa) | small/complex | — | — | — |
| ATP ligand / benzene SMILES | — | — | ✓ matrix | — |

### Gaps

1. **No size ladder.** Everything is 20–123 aa. No medium (~200–300 aa,
   real-world target) or large (~500+ aa, scaling check). Crambin is a
   smoke fixture, not a pipeline-correctness fixture.
2. **Phase 3 only runs `simple_protein.fasta`** (protein, no MSA, no
   ligands). Phases 1+2 cover multi-entity (protein+DNA, protein+RNA,
   protein+ligand, multimer); Phase 3 exercises none of those through
   the service-script + workspace path. A regression in the Perl
   `text_input` parser, multi-entity output upload, or report
   generation on protein+ligand input would slip past every test.
3. **`complex-chai.fasta` is unused** — wasted fixture.
4. **Multimer is Phase 1 Boltz only.** Chai / OpenFold / AlphaFold
   multimer paths aren't exercised cross-phase.

### Per-tool MSA policy

"Always add MSA" is wrong — it hides distinct code paths and adds noise
for tools that ignore it.

| Tool | MSA |
|---|---|
| **Boltz** | Required (or `--use-msa-server`). Test both "with MSA file" *and* "no MSA, no server" → expected error path. |
| **Chai** | Required. Same as Boltz. |
| **OpenFold** | Optional but preferred. Exercise both "with MSA" (accuracy path) and "single-seq" (fallback path). |
| **AlphaFold** | Builds its own MSA from the bound database. Passing one is ignored / conflicts. *Do not* add MSA. |
| **ESMFold** | Single-sequence model, ignores MSA entirely. *Do not* add MSA — it's dead weight in the test param. |

### Recommendation: tiered fixture set, used uniformly across phases

| Tier | Fixture | Size | Used in |
|---|---|---|---|
| **T1 smoke** | `simple_protein.fasta` (crambin, current) | 46 aa | Phase 1 + 2 + 3 — every tool, every layer. "Does anything work?" Default fast suite. |
| **T2 functional** | new `medium_protein.fasta` (~200–300 aa, e.g. T4 lysozyme / 1AKE) + matching MSA | medium | Phase 2 + 3 for Boltz/Chai/OpenFold. Long enough for confidence variation, short enough for ~5-min runs. |
| **T3 multi-entity** | T1 + ligand / DNA / RNA combinations | small | Phase 2 + 3. **Currently Phase 1+2 only — gap.** |
| **T4 multimer** | `multimer.fasta` (current) | 2 chains × 25 aa | Phase 2 + 3, gated `slow`. Currently Phase 1 only. |
| **T5 large** | new `large_protein.fasta` (~500 aa) + MSA | large | Phase 2 only, gated `slow`. Scaling regression check. |

MSA per tier follows the per-tool policy above — applied to Boltz, Chai,
OpenFold; absent for ESMFold and AlphaFold. For Boltz/Chai/OpenFold T1
also gets a paired `T1-no-msa` variant to exercise the rejection /
single-seq fallback path.

This gives:
- Every phase exercises every applicable tier — true regression
  coverage along the *layer* dimension as well as the *use-case*
  dimension.
- A clear fast suite (T1 only, minutes) vs full suite (T1–T5, hours).
- Tool-appropriate MSA policy embedded in fixtures, not ad-hoc per test.

Concrete first steps:
1. Add `test_data/medium_protein.fasta` (+ MSA) and
   `test_data/large_protein.fasta`.
2. Refactor `tests/acceptance/matrix.py` to parametrize over
   `(tool, tier)` instead of ad-hoc `ToolTestCase` rows.
3. Promote multimer + multi-entity service-param JSONs into
   `test_data/service_params/` so Phase 3 can reach them.
4. Delete `complex-chai.fasta` if it has no place in the new ladder, or
   slot it into T3 / T4.

## Code pointers

- `tests/acceptance/conftest.py` — `ApptainerRunner`, fixtures, CLI options
- `tests/acceptance/ws_utils.py` — workspace test helpers
- `tests/acceptance/matrix.py` — parametrized tool/input matrix
- `tests/acceptance/validators.py` — output validators
- `tests/acceptance/schemas/` — JSON Schemas (confidence, metadata, results)
- `pyproject.toml [tool.pytest.ini_options]` — registered markers
- `docs/ACCEPTANCE_TESTING.md` — how to run the suite + env vars
- `docs/TESTING_PLAN.md` — original phased plan
