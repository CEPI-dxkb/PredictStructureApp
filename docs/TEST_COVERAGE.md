# Test Coverage

Snapshot of the PredictStructureApp test suite.

## Inventory

- **357 unit tests** (no GPU, no container) -- adapters, converters,
  normalizers, results, CLI, CWL backend, entities, config.
- **175 acceptance tests** (require Apptainer container; some require
  GPU, workspace token).
- 13 phase test files in `tests/acceptance/`.

## Validation status

Full T1-T5 sweep on `/scout/containers/folding_260425.1.sif`
(H200 NVL): **53 tier-marked tests, 0 failed, 0 skipped, ~25 min total**.

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

Real bugs surfaced and fixed during validation:

1. Service-script tests passed silently when the BV-BRC framework
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

## Rating: A−

### Strengths

| | |
|---|---|
| **Phased isolation** | Native tool → adapter → CLI → service-script. Catches "which layer broke." |
| **Tiered ladder** | T1-T5 fixtures used uniformly across phases. Same regression contract from smoke to scaling. |
| **Schema validation** | `confidence`, `metadata`, `results` schemas validated on every run, not just file presence. |
| **Multi-container parametrization** | Parametrized over both production SIFs automatically. |
| **Real workspace round-trip** | `p3-cp` upload + listing verified; not mocked. |
| **Markers + selective runs** | `phase1/2/3`, `tier1-5`, `slow`, `gpu`, `workspace`, `cwl` -- can scope a run from seconds to hours. |
| **Dev overlay** | `PREDICT_STRUCTURE_DEV_SERVICE=1` lets you iterate without rebuilding the SIF. |
| **Debug-mode heavy in Phase 2** | Most CLI integration uses `--debug` so the surface is exercised in seconds, not GPU-hours. |
| **Per-test runtime extraction** | Pytest hook + `scripts/runtime_summary.py` emit per-tier aggregates. |
| **External Q/A format** | Phase 3 cases ship `.expected.json` predicates for non-pytest consumers. |

## Tier ladder

| Tier | Fixture | Size | MSA | Phase 2 | Phase 3 |
|---|---|---|:-:|:-:|:-:|
| `tier1` | `simple_protein.fasta` (crambin) | 46 aa | `crambin.a3m` | ✓ | ✓ |
| `tier2` | `medium_protein.fasta` (1AKE) | 214 aa | `medium_protein.a3m` | ✓ | ✓ |
| `tier3` | crambin + ligand (Phase 2) / text_input protein+DNA (Phase 3) | small | crambin / none | ✓ | ✓ |
| `tier4` | `multimer.fasta` | 2 chains | none | ✓ | ✓ |
| `tier5` | `large_protein.fasta` (yeast enolase) | 434 aa | `large_protein.a3m` | ✓ | ✓ |

Per-tool MSA policy (codified in `tests/acceptance/matrix.py::msa_args_for`):

| Tool | MSA |
|---|---|
| **Boltz** | Required (or `--use-msa-server`, excluded by scope). |
| **Chai** | Required. |
| **OpenFold** | Optional but preferred. |
| **AlphaFold** | Builds its own MSA from databases. Do not pass one. |
| **ESMFold** | Single-sequence model, ignores MSA. |

## Open follow-ups

Tracked as GitHub issues:

- **#23** -- full multi-tool CWL workflow execution test (currently the
  `aggregate-results` CLI is exercised standalone; full 4-tool fan-out
  deferred for cost reasons).
- **#24** -- container build CI (currently a dep change can break the
  SIF and only manual rebuild catches it).
- **#25** -- Phase 1 native T2/T5 tier tests (Phase 2/3 tier coverage
  is the higher-leverage layer; Phase 1 was deferred as low-ROI).
- **#28** -- SIF rebuild needed: `folding_260425.1.sif`'s baked-in
  `predict-structure` CLI is older than the latest source, so the new
  `finalize-results` subcommand is missing in production.

Out-of-scope per user lock:

- MSA-server mode -- live code in adapters but excluded by deliberate
  scope decision; not exercised.

---

## Host-runner vs inside-container test execution

A separate concern from "what tests exist" is "where does the pytest
process run?" The current setup runs pytest on the **host**, with the
SIF spawned via `apptainer exec` for each test. A parallel future
setup is to run pytest **inside** the SIF (`apptainer exec <sif>
python -m pytest ...`).

### Are they totally different scopes?

**No -- same scope, different orchestration.** Most tests are
layer-agnostic and work identically from either context. The
genuinely different tests are a small minority:

| Test type | Host only | Inside-SIF only |
|---|:-:|:-:|
| Cross-container parity (`prod` vs `all` SIF) | ✓ | -- |
| Host-installed GoWe runner integration | ✓ | -- |
| CWL workflow via host `cwltool` | ✓ | ✓ |
| SIF environment health smoke (paths, conda envs, deps) | -- | ✓ |
| BV-BRC AppService framework wiring | -- | ✓ |
| Workspace round-trip via `p3-cp` | ✓ | ✓ |

### Recommended approach: one suite, two execution contexts

Don't fork into two suites -- the duplication cost outweighs
conditional-marker cost.

1. **Markers**:
   - `@pytest.mark.host_runner` -- needs host context.
   - `@pytest.mark.in_container_only` -- needs inside-SIF context.
   - Default (no marker) -- works in both.

2. **CI matrix**:
   - **Host run** (existing): `pytest tests/ -m "not in_container_only"`.
   - **Inside-SIF run** (new): `apptainer exec <sif> python -m pytest
     /opt/predict-structure/tests/ -m "not host_runner"`. Requires
     test files deployed into the SIF (currently they are NOT --
     Dockerfiles only `COPY test_data/`, see issue #24's sibling
     concern).

3. **Auto-detect via env var**, not filesystem path:
   ```python
   def _running_in_container() -> bool:
       return bool(
           os.environ.get("APPTAINER_CONTAINER")
           or os.environ.get("SINGULARITY_CONTAINER")
       )
   ```
   The env vars are set automatically by the runtime; the
   filesystem-probe approach (`Path("/opt/conda-predict").exists()`)
   conflates "am I in the SIF" with "is predict-structure installed
   here," which is brittle.

### Failure-mode coverage by context

| Failure mode | Host run | Inside-SIF run |
|---|:-:|:-:|
| Output schema regression | ✓ | ✓ |
| Adapter param mapping bug | ✓ | ✓ |
| SIF missing a tool binary | (silent skip) | ✓ |
| `/opt/conda-predict` PATH broken | -- | ✓ |
| Workspace token plumbing | ✓ | ✓ |
| Cross-container drift | ✓ | -- |
| CWL workflow output layout | ✓ | ✓ |
| BV-BRC AppService framework upgrade | partial | ✓ |

Both runs together give you "is the API contract honored" + "is this
image production-ready."

## Code pointers

- `tests/acceptance/conftest.py` -- `ApptainerRunner`, fixtures, CLI options, runtime hook
- `tests/acceptance/ws_utils.py` -- workspace test helpers
- `tests/acceptance/matrix.py` -- `Tier` + `ToolTestCase` parametrization
- `tests/acceptance/validators.py` -- output + manifest validators
- `tests/acceptance/schemas/` -- JSON Schemas (confidence, metadata, results)
- `pyproject.toml [tool.pytest.ini_options]` -- registered markers
- `scripts/runtime_summary.py` -- per-tier runtime breakdowns
- `scripts/run_qa_case.py` -- external Q/A runner for Phase 3
- `docs/ACCEPTANCE_TESTING.md` -- how to run the suite
- `docs/CONTAINER_BUILD.md` -- how to build the SIFs
- `docs/OUTPUT_NORMALIZATION.md` -- the unified output layout spec
