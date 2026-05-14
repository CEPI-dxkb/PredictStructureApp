# Testing Guide

Comprehensive testing reference for PredictStructure. Covers local container testing, dev code overlay, BV-BRC API submission, and multi-host coverage.

## GPU compute hosts

| Host | GPU | Count | VRAM | Driver | CUDA | Boltz (cu130) | OF/Chai (cu121) | ESMFold (cu124) |
|---|---|---|---|---|---|---|---|---|
| **coconut** | H200 NVL | 8x | 141 GB | 580.95 | 13.0 | YES | YES | YES |
| **mango** | H100 NVL | 8x | 95 GB | 560.35 | 12.6 | NO | YES | YES |
| **peach** | V100 PCIE | 2x | 32 GB | 535.183 | 12.2 | NO | YES | YES |

Boltz (`torch+cu130`) requires CUDA 13.0+; only works on coconut.
OpenFold/Chai (`torch+cu121`) and ESMFold (`torch+cu124`) work on all hosts.
AlphaFold uses JAX/TensorFlow; works wherever AF2 databases are mounted.

## Testing layers

| Layer | What it tests | How to run |
|---|---|---|
| **Phase 1** | Native tool binaries (boltz, chai-lab, run_openfold, etc.) | `pytest tests/acceptance/test_phase1_native_tools.py --sif <sif>` |
| **Phase 2** | `predict-structure` CLI (adapters, normalization, output layout) | `pytest tests/acceptance/test_phase2_*.py --sif <sif>` |
| **Phase 3** | Perl AppScript (validation, download, predict, report, upload) | `pytest tests/acceptance/test_phase3_*.py --sif <sif>` or manual apptainer |
| **Phase 4** | BV-BRC API (scheduler, workspace I/O, production path) | `curl` to AppService JSON-RPC endpoint |
| **Unit** | Python code (normalizers, results, entities, converters) | `pytest tests/ --ignore=tests/acceptance` |

## Container invocation

### Production image (test the baked-in code)

```bash
apptainer exec --nv \
    --bind /local_databases:/local_databases \
    --env P3_WORKDIR=/work \
    --env HF_HOME=/local_databases/cache \
    /scout/containers/folding_prod.sif \
    <command>
```

### Dev code overlay (test local changes without rebuilding the SIF)

```bash
apptainer exec --nv \
    --bind /local_databases:/local_databases \
    --bind $PWD/service-scripts:/build/dev_container/modules/PredictStructureApp/service-scripts \
    --bind $PWD/app_specs:/build/dev_container/modules/PredictStructureApp/app_specs \
    --bind $PWD/predict_structure:/opt/conda-predict/lib/python3.12/site-packages/predict_structure \
    --env P3_WORKDIR=/work \
    --env HF_HOME=/local_databases/cache \
    /scout/containers/folding_prod.sif \
    <command>
```

### Custom SIF (A/B testing)

Replace `/scout/containers/folding_prod.sif` with the target SIF path (e.g., `/scout/containers/folding_260512.4.sif`).

## Required bind mounts

| Mount | Purpose | R/W | Notes |
|---|---|---|---|
| `/local_databases` | All tool weights + caches | RW | Top-level mount covers all subdirs |
| `/local_databases/boltz` | Boltz model weights + CCD | RW | Boltz writes `mols.tar` on first run |
| `/local_databases/chai` | Chai model weights | RO | |
| `/local_databases/openfold` | OpenFold weights | RO | |
| `/local_databases/alphafold/databases` | AF2 genetic DBs (~2TB) | RO | pdb70, uniref90, mgnify, etc. |
| `/local_databases/cache` | HuggingFace shared cache | RW | ESMFold model weights |

## Required environment variables

| Variable | Value | Tool | Who sets it |
|---|---|---|---|
| `HF_HOME` | `/local_databases/cache` | ESMFold | Perl auto-detects; SIF `%environment` sets `/local_databases/esmfold`; Perl prefers `/local_databases/cache` if writable |
| `BOLTZ_CACHE` | `/local_databases/boltz` | Boltz | SIF `%environment` |
| `CHAI_DOWNLOADS_DIR` | `/local_databases/chai` | Chai | SIF `%environment` |
| `OPENFOLD_DATA_DIR` | `/local_databases/openfold` | OpenFold | SIF `%environment` |
| `P3_WORKDIR` | `/work` (or `.`) | AppScript | Set manually for local tests |
| `PREDICT_STRUCTURE_SKIP_UPLOAD` | `1` | CWL only | Skip workspace upload for CWL execution |

## Testing the AppScript locally

### Quick smoke (ESMFold, fastest)

```bash
WORKDIR=$(mktemp -d)
cat > /tmp/test_esmfold.json <<'EOF'
{
  "tool": "esmfold",
  "input_file": "/data/simple_protein.fasta",
  "output_path": "/awilke@bvbrc/home/AppTests",
  "output_file": "local_esmfold_test"
}
EOF

apptainer exec --nv \
    --bind $WORKDIR:/work \
    --bind /local_databases:/local_databases \
    --bind $PWD/service-scripts:/build/dev_container/modules/PredictStructureApp/service-scripts \
    --bind $PWD/app_specs:/build/dev_container/modules/PredictStructureApp/app_specs \
    --bind $PWD/predict_structure:/opt/conda-predict/lib/python3.12/site-packages/predict_structure \
    --bind $PWD/test_data:/data \
    --env P3_WORKDIR=/work --env HF_HOME=/local_databases/cache \
    /scout/containers/folding_prod.sif \
    perl /build/dev_container/modules/PredictStructureApp/service-scripts/App-PredictStructure.pl \
        "" /build/dev_container/modules/PredictStructureApp/app_specs/PredictStructure.json \
        /tmp/test_esmfold.json

# Verify output
ls $WORKDIR/output/model_1.pdb $WORKDIR/output/results.json $WORKDIR/output/predictions/
```

### Boltz with uploaded MSA

```bash
cat > /tmp/test_boltz.json <<'EOF'
{
  "tool": "boltz",
  "input_file": "/data/simple_protein.fasta",
  "msa_file": "/data/msa/crambin.a3m",
  "output_path": "/awilke@bvbrc/home/AppTests",
  "output_file": "local_boltz_test"
}
EOF
# Same apptainer exec command as above, with /tmp/test_boltz.json
```

### Boltz with MSA server (no upload)

```bash
cat > /tmp/test_auto.json <<'EOF'
{
  "tool": "auto",
  "input_file": "/data/simple_protein.fasta",
  "output_path": "/awilke@bvbrc/home/AppTests",
  "output_file": "local_auto_test"
}
EOF
# auto will select boltz and use ColabFold MSA server
```

## Testing via BV-BRC API (Phase 4)

### Prerequisites

- Auth token at `~/.patric_token`
- Test data uploaded to workspace at `ws:/awilke@bvbrc/home/AppTests/inputs/`
  (simple_protein.fasta, dna.fasta, rna.fasta, crambin.a3m)

### Submit a job

```bash
TOKEN=$(cat ~/.patric_token)
curl -s -X POST https://p3.theseed.org/services/app_service \
  -H "Content-Type: application/jsonrpc+json" \
  -H "Authorization: $TOKEN" \
  -d '{"id":1,"method":"AppService.start_app2",
       "params":["PredictStructure",
                 {"tool":"esmfold",
                  "input_file":"/awilke@bvbrc/home/AppTests/inputs/simple_protein.fasta",
                  "output_path":"/awilke@bvbrc/home/AppTests",
                  "output_file":"api_test_esmfold"},
                 {"base_url":"https://alpha.bv-brc.org"}],
       "jsonrpc":"2.0"}'
```

Response: `result[0].id` is the task ID, `result[0].state_code` is `Q` (queued).

### Poll for completion

```bash
curl -s -X POST https://p3.theseed.org/services/app_service \
  -H "Content-Type: application/jsonrpc+json" \
  -H "Authorization: $TOKEN" \
  -d '{"id":3,"method":"AppService.enumerate_tasks","params":[0,5],"jsonrpc":"2.0"}'
```

Response: `result[0]` is a list of task dicts. Parse `status` field for `completed` or `failed`.

### Check which host ran the job

```bash
curl -s -X POST https://p3.theseed.org/services/app_service \
  -H "Content-Type: application/jsonrpc+json" \
  -H "Authorization: $TOKEN" \
  -d '{"id":2,"method":"AppService.query_task_details","params":["<TASK_ID>"],"jsonrpc":"2.0"}'
```

Response: `result[0].hostname` and `result[0].exitcode`.

### Verify workspace output

```bash
apptainer exec /scout/containers/folding_prod.sif bash -c '
  echo "=== top level ==="
  p3-ls /awilke@bvbrc/home/AppTests/.<output_file>/
  for sub in predictions metadata reports inputs; do
    echo "--- $sub/ ---"
    p3-ls /awilke@bvbrc/home/AppTests/.<output_file>/$sub/ 2>&1
  done
'
```

Expected unified layout:
```
.<output_file>/
|-- model_1.pdb, report.html, results.json     (top-level)
|-- inputs/                                      (staged user inputs)
|-- predictions/confidence.json, model_1.cif, model_1.pdb
|-- reports/report.html, report.json, report.pdf
|-- metadata/metadata.json, ro-crate-metadata.json
|-- raw/
\-- raw_output/
```

### Get failure logs

From gum (the monitoring host):
```bash
tail -30 /disks/p3/task_status/<TASK_ID>/stdout
tail -30 /disks/p3/task_status/<TASK_ID>/stderr
```

## Queue saturation (multi-host coverage)

The BV-BRC scheduler distributes jobs across available workers. To ensure all 3 hosts are covered, submit 12+ jobs simultaneously:

```bash
# Submit 12 jobs with different tools/params to saturate the queue
for tool in esmfold boltz openfold chai; do
    for variant in base dna ligand; do
        # submit job...
    done
done
```

After completion, group results by hostname to verify coverage:
```
coconut: n jobs (all tools should pass)
mango:   n jobs (Boltz may fail -- CUDA 12.6)
peach:   n jobs (Boltz may fail -- CUDA 12.2)
```

## Workspace test data

Persistent test inputs at `ws:/awilke@bvbrc/home/AppTests/inputs/`:

| File | Type | Size | Description |
|---|---|---|---|
| `simple_protein.fasta` | Protein | 46 aa | Crambin |
| `dna.fasta` | DNA | 20 nt | Test DNA |
| `rna.fasta` | RNA | 40 nt | Test RNA |
| `crambin.a3m` | MSA | 365 seqs | Pre-computed crambin MSA |

Upload with:
```bash
apptainer exec /scout/containers/folding_prod.sif \
    p3-cp test_data/simple_protein.fasta ws:/awilke@bvbrc/home/AppTests/inputs/simple_protein.fasta
```

## Known issues

| Issue | Affected | Status |
|---|---|---|
| Boltz `torch+cu130` needs CUDA 13.0+ | mango, peach | Open (#38); fix: rebuild with `torch+cu124` |
| `/local_databases/boltz/` must be writable | peach | Boltz writes `mols.tar` on first run |
| AlphaFold DB path was `/databases` (wrong) | All hosts | Fixed in `edbc138`; correct: `/local_databases/alphafold/databases` |
| `libnvrtc-builtins.so.13.0` not on `LD_LIBRARY_PATH` | Older SIFs | Fixed in `folding_260512.4.sif` |
| Non-ASCII in app_spec breaks MySQL | Scheduler | Fixed in `v0.15.1` |

## Related docs

- [Tool selection decision tree](tool-selection.md)
- [UI options reference](UI_OPTIONS.md)
- [Output normalization](OUTPUT_NORMALIZATION.md)
- [App specs README](../app_specs/README.md)
- [Test report 2026-05-13](test-report-260513-api.md)
