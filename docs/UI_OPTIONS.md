# UI Options Reference

Guide for building the PredictStructure web form. Cross-references every
option with every tool, ranked by importance tier. Per-tool app_spec
files live at `app_specs/modes/<tool>.json`; the annotated merged spec
is at `app_specs/PredictStructureMerged.spec`.

## Supported tools

| Tool | Engine | MSA | Entity support | CPU | Priority (auto) |
|---|---|---|---|---|---|
| **Boltz-2** | Diffusion | ColabFold server (auto) or upload | protein, DNA, RNA, ligand, SMILES | no | 1 |
| **OpenFold 3** | Diffusion | ColabFold server (auto) or upload | protein, DNA, RNA, ligand, SMILES | no | 2 |
| **Chai-1** | Diffusion | ColabFold server (auto) or upload | protein, DNA, RNA, ligand, SMILES | no | 3 |
| **ESMFold** | Single-sequence | None | protein only | yes | 4 |
| **AlphaFold 2** | Co-evolutionary | Local databases (built-in) | protein only | no | 5 |

## Importance tiers

| Tier | Visibility | Description |
|---|---|---|
| **T1** | Always visible | Required fields -- the minimum to submit a job |
| **T2** | Visible in main form | Recommended fields -- entity separators, quality knobs, output format |
| **T3** | Collapsed "Advanced" | Tool-specific tuning -- hidden by default, shown when user expands |

## Option x tool matrix

B=Boltz, OF=OpenFold, C=Chai, AF=AlphaFold, E=ESMFold. Default shown in parentheses.

### Tier 1 -- Required / always visible

| Option | B | OF | C | AF | E | Type | Default |
|---|:-:|:-:|:-:|:-:|:-:|---|---|
| `tool` | x | x | x | x | x | enum | auto |
| `input_file` | x | x | x | x | x | wsfile | -- |
| `output_path` | x | x | x | x | x | folder | -- |
| `output_file` | x | x | x | x | x | wsfile | -- |

### Tier 2 -- Recommended / main form

| Option | B | OF | C | AF | E | Type | Default | Notes |
|---|:-:|:-:|:-:|:-:|:-:|---|---|---|
| `dna_file` | x | x | x | - | - | wsfile | -- | Hide for AF/ESM |
| `rna_file` | x | x | x | - | - | wsfile | -- | Hide for AF/ESM |
| `ligand` | x | x | x | - | - | list(string) | -- | CCD codes (incl. glycans). Hide for AF/ESM |
| `smiles` | x | x | x | - | - | list(string) | -- | Hide for AF/ESM |
| `msa_file` | x | x | x | - | - | wsfile | -- | Optional upload; server used automatically if empty. Hide for AF/ESM |
| `num_samples` | x | x | x | - | - | int | 1 | Quality vs speed. Hide for AF/ESM |
| `output_format` | x | x | x | x | x | enum | pdb | |

### Tier 3 -- Advanced / collapsed

#### Shared

| Option | B | OF | C | AF | E | Type | Default |
|---|:-:|:-:|:-:|:-:|:-:|---|---|
| `num_recycles` | x | - | x | - | x | int | 3 |
| `seed` | - | x | x | x | - | int | 42 |
| `debug` | x | x | x | x | x | bool | false |

#### Boltz-specific

| Option | Type | Default | Description |
|---|---|---|---|
| `sampling_steps` | int | 200 | Diffusion sampling steps (also Chai) |
| `use_potentials` | bool | false | Inference-time potentials |

#### Chai-specific

| Option | Type | Default | Description |
|---|---|---|---|
| `sampling_steps` | int | 200 | Diffusion timesteps (shared with Boltz) |
| `no_esm_embeddings` | bool | false | Disable ESM2 language model embeddings |
| `use_templates_server` | bool | false | PDB template server |
| `constraint_path` | wsfile | -- | Constraint JSON for guided prediction |
| `template_hits_path` | wsfile | -- | Pre-computed template hits |
| `num_trunk_samples` | int | 1 | Trunk samples per prediction |
| `recycle_msa_subsample` | int | 0 | MSA subsample per recycle (0 = all) |
| `no_low_memory` | bool | false | Disable low-memory mode |

#### OpenFold-specific

| Option | Type | Default | Description |
|---|---|---|---|
| `num_diffusion_samples` | int | 5 | Diffusion samples per query |
| `num_model_seeds` | int | 1 | Independent model seeds |
| `use_templates` | bool | true | PDB template structures |

#### AlphaFold-specific

| Option | Type | Default | Description |
|---|---|---|---|
| `af2_data_dir` | string | /databases | Path to AF2 genetic databases |
| `af2_model_preset` | enum | monomer | monomer / monomer_ptm / monomer_casp14 / multimer |
| `af2_db_preset` | enum | reduced_dbs | reduced_dbs (~17GB) / full_dbs (~1.8TB) |
| `af2_max_template_date` | string | 2022-01-01 | Max PDB template date (YYYY-MM-DD) |

#### ESMFold-specific

| Option | Type | Default | Description |
|---|---|---|---|
| `fp16` | bool | false | Half-precision inference |
| `chunk_size` | int | -- | Chunk size for long sequences |
| `max_tokens_per_batch` | int | -- | Max tokens per batch |

## Entity-type support matrix

| Entity | B | OF | C | AF | E |
|---|:-:|:-:|:-:|:-:|:-:|
| Protein (FASTA) | x | x | x | x | x |
| DNA (FASTA) | x | x | x | - | - |
| RNA (FASTA) | x | x | x | - | - |
| Ligand (CCD code) | x | x | x | - | - |
| SMILES (string) | x | x | x | - | - |
| Multi-chain | x | x | x | x (multimer preset) | single only |

## MSA handling

| Scenario | What happens |
|---|---|
| No `msa_file`, tool = B/OF/C | ColabFold server fetches MSA automatically (`--use-msa-server`) |
| `msa_file` uploaded | Passed directly (`--msa <file>`), server not used |
| Tool = AlphaFold | Builds MSA from local databases (jackhmmer/hhsearch); ignores msa_file |
| Tool = ESMFold | No MSA (single-sequence by design); ignores msa_file |

**UI hint:** The MSA file upload is always optional. Show a subtle note:
"MSA fetched automatically via ColabFold server. Upload to override."

## Auto-select decision tree

With MSA server enabled by default, auto always prefers the highest-quality tool:

| Input | Auto picks | Why |
|---|---|---|
| Protein only | **Boltz** | MSA via server; highest priority |
| Protein + DNA/RNA/ligand | **Boltz** | Multi-entity; MSA via server |
| Protein + uploaded MSA | **Boltz** | Explicit MSA; highest priority |
| (any input, explicit tool) | User's choice | Bypass auto |

Full decision tree with pseudocode: [`docs/tool-selection.md`](tool-selection.md)

## Client-side validation rules

The UI should prevent submission for these states:

| Condition | Error message |
|---|---|
| No entity inputs (no protein/dna/rna/ligand/smiles) | "Provide at least one input" |
| Ligand CCD code not 1-3 or exactly 5 chars, or non-alphanumeric | "Invalid CCD code (1-3 or 5 alphanumeric)" |
| Ligand CCD code contains `(` (linked glycan string) | "Linked glycan strings are not supported — enter one CCD code per monosaccharide" |
| Empty SMILES string | "SMILES string cannot be empty" |
| Missing output_path | "Output folder is required" |
| Missing output_file | "Job name is required" |
| Tool = alphafold/esmfold + DNA/RNA/ligand/SMILES provided | "AlphaFold/ESMFold supports protein only" |

## Per-tool app_spec files

Load from `app_specs/modes/<tool>.json` when the user switches tools:

| File | Params | Use case |
|---|---|---|
| `modes/auto.json` | 11 | Default landing page |
| `modes/boltz.json` | 15 | Boltz-2 with all options |
| `modes/openfold.json` | 16 | OpenFold 3 with all options |
| `modes/chai.json` | 22 | Chai-1 with all options (most knobs) |
| `modes/alphafold.json` | 11 | AlphaFold 2 (protein-only, DB options) |
| `modes/esmfold.json` | 10 | ESMFold (protein-only, minimal) |

Each file follows the BV-BRC app_spec schema (id, type, default,
required, label, desc). The annotated merged spec with `section`,
`tools`, and `tier` keys is at `app_specs/PredictStructureMerged.spec`.

## UI wireframe

```
+-------------------------------------------------------+
|  Tool Selection Bar                                    |
|  [Auto*] [Boltz] [OpenFold] [Chai] [AlphaFold] [ESM]  |
+-------------------------------------------------------+
|                                                        |
|  -- Entity Inputs --                                   |
|  Protein FASTA  [upload / paste / workspace]           |
|  DNA FASTA      [upload]  (hidden if AF/ESM)           |
|  RNA FASTA      [upload]  (hidden if AF/ESM)           |
|  Ligands        [+ add CCD]  (hidden if AF/ESM)        |
|  SMILES         [+ add]  (hidden if AF/ESM)            |
|  MSA File       [upload]  "auto-fetched if empty"      |
|                                                        |
|  -- Output --                                          |
|  Output Folder  [browse workspace]                     |
|  Job Name       [__________________]                   |
|                                                        |
|  -- Options --                                         |
|  Samples [1]   Format [PDB]                            |
|                                                        |
|  > Advanced Options  (collapsed; tool-specific)        |
|    Loads fields from app_specs/modes/<tool>.json        |
|                                                        |
|  [i] Will run: Boltz (MSA via ColabFold server)        |
|  [i] Estimated: 8 CPU, 96G RAM, ~30 min, GPU           |
|                                                        |
|  [ Submit ]                                            |
+-------------------------------------------------------+
```

When user switches tool:
1. Load `app_specs/modes/<tool>.json`
2. Show/hide entity inputs per entity-type support matrix
3. Update Advanced Options section
4. Update resource estimate via `predict-structure preflight`
