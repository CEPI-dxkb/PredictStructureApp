# Service Script Test Params

Params JSON files for testing `App-PredictStructure.pl` end-to-end.
Each file is a complete BV-BRC AppService params payload that can be
passed to the service script.

## Files

| File | Tool | Input mode | MSA | Notes |
|------|------|-----------|-----|-------|
| `esmfold_input_file.json` | ESMFold | input_file | none | Fastest test (~30s) |
| `esmfold_text_input.json` | ESMFold | text_input (inline) | none | Tests inline sequence path |
| `boltz_input_file.json` | Boltz-2 | input_file | none (single-seq) | Requires `msa: empty` converter fix |
| `boltz_msa_upload.json` | Boltz-2 | input_file | upload (.a3m) | Tests MSA file download+use |
| `openfold_input_file.json` | OpenFold 3 | input_file | none | |
| `chai_input_file.json` | Chai-1 | input_file | none | |
| `alphafold_input_file.json` | AlphaFold 2 | input_file | none (uses own pipeline) | Slowest (~26m monomer) |
| `auto_input_file.json` | auto | input_file | none | Tests auto-selection logic |

## Paths

All paths use `/data/...` and `/output` which are standard bind-mount
targets inside the container:

- `/data` <- host `test_data/`
- `/output` <- per-run writable dir

For BV-BRC real-submission testing, replace `input_file`, `output_path`,
and `msa_file` with real workspace paths (`ws:/user@patricbrc/...`).

## Running via the Perl service script

Direct invocation inside the container:

```bash
apptainer exec --nv \
  --bind <test_data>:/data \
  --bind <tmp_out>:/output \
  --bind /local_databases:/local_databases \
  <folding_sif> \
  perl /kb/module/service-scripts/App-PredictStructure.pl \
    http://localhost \
    /kb/module/app_specs/PredictStructure.json \
    /path/to/params.json
```

The `ApptainerRunner.service()` helper in
`tests/acceptance/conftest.py` does exactly this.

## Running via BV-BRC AppService

The BV-BRC test harness submits these params via:

```bash
p3-submit-app PredictStructure params.json
```

or via the service CLI wrapper inside the AppService container.

## Updating the params

When adding new fields to `app_specs/PredictStructure.json`, update the
relevant param files here so test coverage stays in sync. Both the
acceptance tests (tests/acceptance/test_phase3_service_script.py) and
BV-BRC test harness read these files.
