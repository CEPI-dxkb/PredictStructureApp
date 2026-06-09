# Plan: Testing skill + comprehensive AppScript test plan

## Context

We've been testing PredictStructure through ad-hoc commands across
multiple sessions. The testing patterns (apptainer bind mounts, env
vars, container selection, API submission, workspace verification) are
complex and error-prone. A testing skill would codify this knowledge
so any engineer can run consistent, repeatable tests.

Additionally, we need a comprehensive test plan that covers every tool
x option combination via the AppScript (the production path), and
ensures jobs land on all 3 compute hosts (coconut, mango, peach)
through queue saturation.

## Deliverables

### 1. Testing documentation (`docs/TESTING_GUIDE.md`)

A reference doc covering:

**Testing layers:**
- Phase 1: Native tools (bypasses predict-structure, tests raw binaries)
- Phase 2: CLI integration (predict-structure inside container)
- Phase 3: AppScript (full Perl → Python → tool pipeline)
- Phase 4: BV-BRC API (production scheduler + workspace upload)

**Container invocation patterns:**
```bash
# Production image
apptainer exec --nv --bind /local_databases:/local_databases \
    /scout/containers/folding_prod.sif <command>

# Dev code overlay (bind-mount modified source)
apptainer exec --nv \
    --bind /local_databases:/local_databases \
    --bind $PWD/service-scripts:/build/dev_container/modules/PredictStructureApp/service-scripts \
    --bind $PWD/app_specs:/build/dev_container/modules/PredictStructureApp/app_specs \
    --bind $PWD/predict_structure:/opt/conda-predict/lib/python3.12/site-packages/predict_structure \
    /scout/containers/folding_prod.sif <command>
```

**Required bind mounts:**
| Mount | Purpose | Read/Write |
|---|---|---|
| `/local_databases` | All tool weights + caches | RW |
| `/local_databases/boltz` | Boltz weights + CCD | RW (writes mols.tar) |
| `/local_databases/chai` | Chai weights | RO |
| `/local_databases/openfold` | OpenFold weights | RO |
| `/local_databases/alphafold/databases` | AF2 genetic DBs (~2TB) | RO |
| `/local_databases/cache` | HuggingFace cache (ESMFold) | RW |

**Required env vars:**
| Var | Value | Tool | Set by |
|---|---|---|---|
| `HF_HOME` | `/local_databases/cache` | ESMFold | Perl auto-detects or SIF %env |
| `BOLTZ_CACHE` | `/local_databases/boltz` | Boltz | SIF %env |
| `CHAI_DOWNLOADS_DIR` | `/local_databases/chai` | Chai | SIF %env |
| `P3_WORKDIR` | `/work` or `.` | AppScript | Set explicitly for local tests |
| `PREDICT_STRUCTURE_SKIP_UPLOAD` | `1` | CWL | Skip workspace upload |

**Infrastructure — 3 GPU compute hosts:**

| Host | GPU | Count | VRAM | Driver | CUDA | Boltz (cu130) | OF/Chai (cu121) |
|---|---|---|---|---|---|---|---|
| coconut | H200 NVL | 8x | 141GB each | 580.95 | 13.0 | YES | YES |
| mango | H100 NVL | 8x | 95GB each | 560.35 | 12.6 | NO (needs 13.0) | YES |
| peach | V100 PCIE | 2x | 32GB each | 535.183 | 12.2 | NO (needs 13.0) | YES |

- Boltz (torch+cu130) only works on coconut (CUDA 13.0+)
- OpenFold/Chai (torch+cu121) work on all hosts (CUDA 12.1+)
- ESMFold (torch+cu124) works on all hosts (CUDA 12.2+)
- AlphaFold uses JAX — CUDA compat TBD per host
- mango has most GPU memory (8x 95GB); ideal for large proteins
- peach V100 32GB may OOM on large complexes
- BV-BRC API: `https://p3.theseed.org/services/app_service`
- GoWe: `http://localhost:8091`
- Workspace test data: `ws:/awilke@bvbrc/home/AppTests/inputs/`

### 2. Testing skill (`.claude/skills/test-predict.md`)

A Claude Code skill invoked via `/test-predict` that supports:

```
/test-predict                           # quick smoke (ESMFold, local)
/test-predict boltz                     # single tool, local AppScript
/test-predict all                       # all 5 tools, local AppScript
/test-predict api                       # submit all tools via BV-BRC API
/test-predict api boltz                 # submit single tool via API
/test-predict api --saturate            # submit 12+ jobs to hit all hosts
/test-predict phase1                    # native tool tests via pytest
/test-predict phase1 --sif <path>      # specific container
/test-predict verify <task_id>         # check workspace output for a task
```

The skill knows:
- How to construct apptainer commands with correct bind mounts
- How to overlay dev code for testing local changes
- How to submit via BV-BRC API and poll for completion
- How to verify workspace output structure
- How to report results in a consistent table format

### 3. Comprehensive AppScript test matrix

**Base matrix: 5 tools x entity types**

| # | Tool | Entities | MSA | Expected |
|---|---|---|---|---|
| 1 | esmfold | protein | -- | pass (single-seq) |
| 2 | boltz | protein | file | pass |
| 3 | boltz | protein | server | pass (auto MSA) |
| 4 | boltz | protein+DNA | file | pass |
| 5 | boltz | protein+RNA | file | pass |
| 6 | boltz | protein+ligand(ATP) | file | pass |
| 7 | boltz | protein+SMILES(CCO) | file | pass |
| 8 | openfold | protein | file | pass |
| 9 | openfold | protein+DNA | file | pass |
| 10 | chai | protein | file | pass |
| 11 | chai | protein+DNA | file | pass |
| 12 | chai | protein+ligand(ATP) | file | pass |
| 13 | alphafold | protein | local DBs | pass (slow) |
| 14 | auto | protein | server | pass (->boltz) |
| 15 | auto | protein | file | pass (->boltz) |
| 16 | auto | protein+DNA | file | pass (->boltz) |

**Parameter variations:**

| # | Tool | Variation | Expected |
|---|---|---|---|
| 17 | boltz | output_format=mmcif | pass |
| 18 | esmfold | debug=true | pass (--verbose in log) |
| 19 | boltz | num_samples=2 | pass (2 models) |
| 20 | chai | num_recycles=5 | pass |

**Negative tests (should fail fast):**

| # | Tool | Input | Expected error |
|---|---|---|---|
| 21 | boltz | no input | "No inputs supplied" |
| 22 | boltz | invalid CCD "TOOLONG" | "Invalid ligand CCD code" |
| 23 | boltz | non-FASTA file | "expected FASTA format" |
| 24 | esmfold | protein+DNA | "does not support" (adapter rejection) |

**Total: 24 test cases**

### 4. Queue saturation strategy for multi-host coverage

With 3 hosts and round-robin scheduling, submitting n=12 jobs should
ensure each host gets ~4 jobs. Strategy:

```
Batch 1 (12 jobs): tools x entity variations
  → expect ~4 per host, covering coconut + mango + peach
Batch 2 (if needed): re-run failed jobs targeting specific hosts
```

The skill's `--saturate` mode submits all 24 test cases at once.
After completion, group results by host and report coverage:

```
coconut (CUDA 13.0, H-series):  all tools pass
mango   (CUDA 12.6):            Boltz fails (cu130 needs 13.0+), others pass
peach   (CUDA 12.2, V100):      Boltz fails (cu130 needs 13.0+), others pass
```

Expected: Boltz only passes on coconut. OpenFold/Chai/ESMFold pass
everywhere. AlphaFold passes wherever /local_databases/alphafold/databases
is mounted.

This documents which tools work on which hosts and identifies
infrastructure gaps.

### 5. Improvements over current testing

| Current issue | Improvement |
|---|---|
| Ad-hoc curl commands for API | Skill encodes submission + poll + verify |
| Status parsing breaks on API response format | Skill uses correct `result[0]` nested list format |
| No host-coverage tracking | Skill groups results by host, flags gaps |
| Dev code testing requires remembering 3 bind mounts | Skill's `--dev` flag adds them automatically |
| No negative testing | Skill includes expected-failure test cases |
| AlphaFold skipped (slow) | Skill's `--include-alphafold` flag; default skips |
| Results not persisted | Skill writes JSON report to `docs/test-reports/` |
| No container comparison testing | Skill accepts `--sif <path>` for A/B testing |

## Files to create / modify

| File | Action |
|---|---|
| `docs/TESTING_GUIDE.md` | NEW — complete testing reference |
| `.claude/skills/test-predict.md` | NEW — testing skill (replaces test-bvbrc.md) |
| `.claude/skills/test-bvbrc.md` | DELETE — superseded by test-predict |
| `test_data/service_params/api_test_matrix.json` | NEW — the 24-case test matrix as machine-readable JSON |
| `docs/test-report-260513-api.md` | UPDATE — link to testing guide |
| `app_specs/README.md` | UPDATE — link to testing guide |

## Verification

- Testing engineer runs `/test-predict` smoke → ESMFold completes locally
- Testing engineer runs `/test-predict all` → 5 tools pass locally
- Testing engineer runs `/test-predict api --saturate` → 12+ jobs submitted, results grouped by host
- Sysadmin reviews bind mount table + env vars for correctness
- Software engineer reviews the skill for correctness of container invocation patterns

## Review checklist

**Software engineer should verify:**
- [ ] Bind mount paths match the SIF's expected layout
- [ ] Dev overlay paths match actual SIF site-packages location
- [ ] Env vars are complete (no missing cache dirs)
- [ ] API submission format matches current AppService.start_app2 contract
- [ ] Workspace output verification checks all subdirs

**Sysadmin should verify:**
- [ ] `/local_databases` is mounted RW on all hosts
- [ ] `/local_databases/boltz/mols.tar` is pre-cached (avoids download-on-first-run)
- [ ] `/local_databases/alphafold/databases/` is synced to all hosts
- [ ] CUDA drivers on mango/peach (need >= 13.0 for Boltz, >= 12.1 for others)
- [ ] Container cache at `/disks/patric-common/container-cache/` is current

**Testing engineer should verify:**
- [ ] `/test-predict` smoke runs without errors
- [ ] `/test-predict api` submits and polls correctly
- [ ] `/test-predict verify <task_id>` checks workspace output
- [ ] Results report format is clear and actionable
