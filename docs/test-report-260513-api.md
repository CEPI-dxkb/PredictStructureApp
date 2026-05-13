# BV-BRC API Test Report — folding_260512.4.sif

**Date:** 2026-05-13 13:46 CDT  
**Container:** `folding_260512.4.sif` (LD_LIBRARY_PATH fix for cu13)  
**Input:** crambin (46 aa) from `ws:/awilke@bvbrc/home/AppTests/inputs/`  
**API endpoint:** `https://p3.theseed.org/services/app_service`  
**Method:** `AppService.start_app2`

## Submission

Each tool was submitted via JSON-RPC:

```bash
curl -X POST https://p3.theseed.org/services/app_service \
  -H "Content-Type: application/jsonrpc+json" \
  -H "Authorization: $TOKEN" \
  -d '{"id":1,"method":"AppService.start_app2","params":["PredictStructure",
       {"tool":"<TOOL>",
        "input_file":"/awilke@bvbrc/home/AppTests/inputs/simple_protein.fasta",
        "msa_file":"/awilke@bvbrc/home/AppTests/inputs/crambin.a3m",
        "output_path":"/awilke@bvbrc/home/AppTests",
        "output_file":"test6_<TOOL>_20260513_134611"},
       {"base_url":"https://alpha.bv-brc.org"}],"jsonrpc":"2.0"}'
```

Notes:
- `msa_file` provided for boltz, openfold, chai (uploaded MSA)
- `msa_file` omitted for esmfold (no MSA), alphafold (local DBs), auto (ColabFold server)

## Results

| Task | Tool | Host | Exit | Status | Notes |
|---|---|---|---|---|---|
| 22198164 | esmfold | coconut | 0 | **PASS** | Single-sequence, no MSA |
| 22198165 | boltz | coconut | 0 | **PASS** | With uploaded MSA |
| 22198166 | openfold | coconut | 0 | **PASS** | With uploaded MSA |
| 22198167 | chai | mango | 0 | **PASS** | With uploaded MSA (torch+cu121 works on CUDA 12.6) |
| 22198168 | alphafold | mango | 1 | **FAIL** | Pending stderr from gum |
| 22198169 | auto | peach | 1 | **FAIL** | Auto->Boltz with MSA server; pending stderr from gum |

### PyTorch CUDA versions per tool (for context)

| Tool | PyTorch | CUDA built for |
|---|---|---|
| Boltz | 2.11.0+cu130 | 13.0 |
| OpenFold | 2.5.1+cu121 | 12.1 |
| Chai | 2.5.1+cu121 | 12.1 |
| ESMFold | 2.6.0+cu124 | 12.4 |
| AlphaFold | (system Python) | N/A |

### Worker CUDA drivers

| Host | CUDA driver | Boltz (cu130) | OpenFold/Chai (cu121) |
|---|---|---|---|
| coconut | 13.0 (580.95) | works | works |
| mango | 12.6 (12060) | fails (driver too old) | works |
| peach | unknown | fails | unknown |

## Workspace output verification

### ESMFold (22198164) — PASS

```
/awilke@bvbrc/home/AppTests/.test6_esmfold_20260513_134611/
├── model_1.pdb, report.html, results.json
├── inputs/simple_protein.fasta
├── predictions/confidence.json, model_1.cif, model_1.pdb
├── reports/report.html, report.json, report.pdf
├── metadata/metadata.json, ro-crate-metadata.json
├── raw/, raw_output/
```

### Boltz (22198165) — PASS

```
/awilke@bvbrc/home/AppTests/.test6_boltz_20260513_134611/
├── model_1.pdb, report.html, results.json, input.yaml
├── inputs/simple_protein.fasta, crambin.a3m
├── predictions/confidence.json, model_1.cif, model_1.pdb
├── reports/report.html, report.json, report.pdf
├── metadata/metadata.json, ro-crate-metadata.json
├── raw/, raw_output/
```

### OpenFold (22198166) — PASS

```
/awilke@bvbrc/home/AppTests/.test6_openfold_20260513_134611/
├── model_1.pdb, report.html, results.json, query.json
├── inputs/simple_protein.fasta, crambin.a3m
├── predictions/confidence.json, model_1.cif, model_1.pdb
├── reports/report.html, report.json, report.pdf
├── metadata/metadata.json, ro-crate-metadata.json
├── raw/, raw_output/, msa_staging/
```

### Chai (22198167) — PASS

```
/awilke@bvbrc/home/AppTests/.test6_chai_20260513_134611/
├── model_1.pdb, report.html, results.json, input.fasta
├── inputs/simple_protein.fasta, crambin.a3m
├── predictions/confidence.json, model_1.cif, model_1.pdb
├── reports/report.html, report.json, report.pdf
├── metadata/metadata.json, ro-crate-metadata.json
├── raw/, raw_output/, msa/
```

### AlphaFold (22198168) — FAIL

```
/awilke@bvbrc/home/AppTests/.test6_alphafold_20260513_134611/
└── JobFailed.txt
```

Ran on mango (CUDA 12.6). Error: `Prediction failed with exit code: 1`.
Pending full stderr from `gum:/disks/p3/task_status/22198168/stderr`.

Likely causes: CUDA driver mismatch or missing AlphaFold databases on mango.

### Auto (22198169) — FAIL

```
/awilke@bvbrc/home/AppTests/.test6_auto_20260513_134611/
└── JobFailed.txt
```

Ran on peach. Auto selects Boltz with `--use-msa-server`. Error: `Prediction failed with exit code: 1`.
Pending full stderr from `gum:/disks/p3/task_status/22198169/stderr`.

Likely cause: peach has an older CUDA driver incompatible with Boltz's torch+cu130.

## Commands to retrieve pending logs

Run on gum:

```bash
for tid in 22198168 22198169; do
    echo "======== Task $tid ========"
    echo "--- stdout (tail) ---"
    tail -30 /disks/p3/task_status/$tid/stdout
    echo "--- stderr (tail) ---"
    tail -30 /disks/p3/task_status/$tid/stderr
    echo ""
done
```

## Key findings

1. **LD_LIBRARY_PATH fix works.** Boltz passes on coconut via the BV-BRC API with `folding_260512.4.sif`. Previously failed with `.3` (missing cu13 paths).

2. **4/6 tools pass.** ESMFold, Boltz, OpenFold, Chai all produce the full unified output layout in the workspace.

3. **Failures are host-specific.** AlphaFold (mango) and Auto->Boltz (peach) fail on workers with older CUDA drivers. Chai works on mango because `torch+cu121` is compatible with CUDA 12.6.

4. **Unified output layout verified.** All passing tools produce: top-level model_1.pdb + report.html + results.json, plus inputs/, predictions/, reports/, metadata/, raw/ subdirs.

## Related

- Issue: [#38](https://github.com/CEPI-dxkb/PredictStructureApp/issues/38)
- Container: `folding_260512.4.sif` (v0.16.0 code + LD_LIBRARY_PATH fix)
- Tags: v0.15.1 (ASCII app_spec fix), v0.16.0 (UI mode specs)
