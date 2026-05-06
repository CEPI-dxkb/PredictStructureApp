# App Specs

BV-BRC application specifications for the unified PredictStructure service.

Two specs live here, with different roles:

| File | Loaded by BV-BRC AppService | Purpose |
|---|:-:|---|
| [`PredictStructure.json`](PredictStructure.json) | ✅ yes (active form) | Minimal user-facing spec — drives the BV-BRC web UI form. Currently the spec used in production. |
| [`PredictStructureFull.spec`](PredictStructureFull.spec) | ❌ no | Reference / documentation — exposes every option the `predict-structure` CLI supports. |

Why two? `Bio::KBase::AppService::AppSpecs::enumerate` (in the BV-BRC framework) auto-discovers app definitions via `glob("$dir/*.json")`. Only `.json` is registered as a live app; `.spec` is just a comment file in this directory and stays out of the service registry. That gives us a place to document the full surface area without registering a second app.

## `PredictStructure.json` — basic, UI-facing (9 parameters)

The current production form. Focuses on **entity inputs** and **the workspace destination**; tool-specific tuning knobs use sensible defaults baked into the predict-structure CLI.

| Parameter | Type | Required | Notes |
|---|---|:-:|---|
| `tool` | enum | yes | `auto` \| `boltz` \| `openfold` \| `chai` \| `alphafold` \| `esmfold` |
| `input_file` | wsfile | no | Protein FASTA |
| `dna_file` | wsfile | no | DNA FASTA (Boltz / OpenFold / Chai) |
| `rna_file` | wsfile | no | RNA FASTA (Boltz / OpenFold / Chai) |
| `ligand` | list of string | no | CCD codes (incl. glycans NAG, MAN, …) |
| `smiles` | list of string | no | SMILES strings for arbitrary small molecules |
| `msa_file` | wsfile | no | Pre-computed MSA (.a3m / .sto). Required for Boltz / OpenFold / Chai by BV-BRC policy |
| `output_path` | folder | **yes** | Workspace upload destination |
| `output_file` | wsfile | no | Optional filename prefix |

### What's NOT in the basic spec (and why)

The following are **set by CLI defaults** and not exposed on the form:

| Field | Default | Tools affected |
|---|---|---|
| `num_samples` | 1 | Boltz, OpenFold, Chai |
| `num_recycles` | 3 | Boltz, Chai, ESMFold |
| `seed` | 42 | OpenFold, Chai, AlphaFold |
| `output_format` | `pdb` | all |
| `device` | `gpu` (`cpu` for ESMFold via Perl auto-detect) | all |

Plus all per-tool tuning (`sampling_steps`, `use_potentials`, `af2_*`, `fp16`, `num_diffusion_samples`, `use_templates`, …). To override any of these, run via direct CLI / CWL invocation (see [docs/CWL_WORKFLOWS.md](../docs/CWL_WORKFLOWS.md)) or use the full reference below.

### Auto-select decision tree

When `tool: auto` (the default), the chosen prediction tool depends on the entity inputs and whether an MSA file is provided. A UI can mirror the same logic to show the user which tool will run as they fill in the form:

| `input_file` | DNA / RNA / lig / SMILES | `msa_file` | → Auto picks |
|:-:|:-:|:-:|---|
| ✓ | — | — | **ESMFold** (fast single-sequence), fallback **AlphaFold** (slow, local DB MSA) |
| ✓ | — | ✓ | **Boltz** > OpenFold > Chai > ESMFold > AlphaFold |
| ✓ | ✓ | — | **ERROR** — Boltz/OpenFold/Chai need MSA; AF/ESMFold can't handle non-protein |
| ✓ | ✓ | ✓ | **Boltz** > OpenFold > Chai |
| — | DNA / RNA only | any | **Boltz** > OpenFold > Chai |

Full decision tree, capability matrix, and UI pseudocode: [`docs/tool-selection.md`](../docs/tool-selection.md).

### MSA policy

External MSA servers (`use_msa_server` / `msa_server_url`) are **disabled** in the BV-BRC AppScript per project policy. The Perl script (`service-scripts/App-PredictStructure.pl`) ignores those flags and refuses to run Boltz / OpenFold / Chai without `msa_file`. AlphaFold builds its own MSA from local databases; ESMFold needs no MSA.

If `msa_file` is present, MSA-upload mode is active. Absent → single-sequence (only valid for ESMFold) or local-database (AlphaFold).

## `PredictStructureFull.spec` — full / reference (38 parameters)

Lives here as documentation of every parameter the `predict-structure` CLI accepts. **Not auto-registered**: the file extension keeps it outside the BV-BRC AppService glob.

Covers:

- All 9 basic-spec fields above (strict superset).
- Shared tuning: `num_samples`, `num_recycles`, `seed`, `output_format`, `device`.
- MSA-server (CLI / CWL only): `use_msa_server`, `msa_server_url` — labelled "POLICY: ignored by App-PredictStructure.pl".
- Boltz / Chai shared: `sampling_steps`.
- Boltz only: `use_potentials`.
- Chai only: `no_esm_embeddings`, `use_templates_server`, `constraint_path`, `template_hits_path`, `num_trunk_samples`, `recycle_msa_subsample`, `no_low_memory`.
- AlphaFold only: `af2_data_dir`, `af2_model_preset`, `af2_db_preset`, `af2_max_template_date`.
- ESMFold only: `fp16`, `chunk_size`, `max_tokens_per_batch`.
- OpenFold only: `num_diffusion_samples`, `num_model_seeds`, `use_templates`.
- Workflow-level (protein-compare report step): `report_name`, `report_format`.

Use this file as the reference when authoring CWL job-spec YAML or `params.json` for direct AppScript invocations.

## Job spec vs app spec

- **App spec** (this directory) = schema. Defines what's valid.
- **Job spec** = an instance with concrete values, e.g. `test_data/service_params/tier1_boltz.json`.

The BV-BRC framework validates each job spec against the registered app spec at submission time: unknown keys → warning (job continues); required-but-missing → fatal; out-of-enum → fatal. See [`Bio::KBase::AppService::AppScript::preprocess_parameters`](https://github.com/BV-BRC/AppService/blob/master/lib/Bio/KBase/AppService/AppScript.pm) for the validation source.

## Mapping app_spec → CLI

The Perl AppScript (`service-scripts/App-PredictStructure.pl`) translates parameters as follows:

```
tool                  → predict-structure <tool>     (subcommand)
input_file            → --protein <local-path>
dna_file              → --dna     <local-path>
rna_file              → --rna     <local-path>
ligand[]              → --ligand <ccd> ...           (repeated)
smiles[]              → --smiles <smi> ...           (repeated)
msa_file              → --msa <local-path>           (downloads first)
num_samples           → --num-samples
num_recycles          → --num-recycles
seed                  → --seed
output_format         → --output-format
output_path           → workspace upload destination (post-prediction)
```

Full mapping including per-tool flags is documented in [`CLAUDE.md`](../CLAUDE.md#parameter-mapping-shared--native).

## Default resource allocation

| Resource | Value |
|---|---|
| CPU | 8 |
| Memory | 64 GB (200 GB for OpenFold per its preflight) |
| Runtime | 14400 s (4 h) |
| Storage | 50 GB |
| GPU | 1× A100 \| H100 \| H200 (none for ESMFold on CPU) |
| Partition | `gpu2` |

Each adapter's `preflight()` can override these in `Bio::KBase::AppService::AppScript`'s preflight callback.
