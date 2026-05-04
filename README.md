# PredictStructureApp

Unified protein structure prediction for BV-BRC. Wraps **Boltz-2**, **Chai-1**, **AlphaFold 2**, and **ESMFold** behind a single CLI, CWL tool, and BV-BRC AppService interface with automatic parameter mapping, format conversion, and output normalization.

## Installation

### Prerequisites

- Python 3.10+
- [conda](https://docs.conda.io/en/latest/) or [miniconda](https://docs.anaconda.com/miniconda/)

### Quick start

```bash
# Create and activate environment
conda create -n predict-structure python=3.12 -y
conda activate predict-structure

# Install with all optional dependencies
pip install -e ".[all]"

# Verify
predict-structure --version
predict-structure --help
```

### Minimal install (core only)

```bash
pip install -e .
```

### Optional dependency groups

| Group | What it adds | Install |
|-------|-------------|---------|
| `chai` | PyArrow (A3M→Parquet MSA conversion) | `pip install -e ".[chai]"` |
| `esmfold` | PyTorch, Transformers, Accelerate | `pip install -e ".[esmfold]"` |
| `cwl` | cwltool | `pip install -e ".[cwl]"` |
| `dev` | pytest, black, ruff, mypy | `pip install -e ".[dev]"` |
| `all` | Everything above | `pip install -e ".[all]"` |

> **Note:** The prediction tools themselves (boltz, chai-lab, etc.) must be installed separately or run inside their respective Docker containers.

## Usage

### Entity flags

Input is specified via explicit entity flags instead of a positional file argument. Each flag can be repeated to build multi-entity complexes.

| Flag | Type | Description |
|------|------|-------------|
| `--protein` | file path | Protein FASTA file (repeatable for multi-chain) |
| `--dna` | file path | DNA FASTA file (repeatable) |
| `--rna` | file path | RNA FASTA file (repeatable) |
| `--ligand` | string | Ligand CCD code, e.g. `ATP` (repeatable) |
| `--smiles` | string | SMILES string (repeatable) |
| `--glycan` | string | Glycan specification (repeatable) |

A multi-sequence FASTA file passed to `--protein` is treated as a multi-chain complex (not a batch of separate predictions).

### Basic examples

```bash
# Protein structure prediction with Boltz-2
predict-structure boltz --protein input.fasta -o output/

# Protein with ESMFold (single-sequence, CPU-capable)
predict-structure esmfold --protein input.fasta -o output/ --fp16

# Chai-1 with MSA
predict-structure chai --protein input.fasta -o output/ --msa alignment.a3m

# AlphaFold 2 (requires database directory)
predict-structure alphafold --protein input.fasta -o output/ --af2-data-dir /databases

# Auto-discover best available tool
predict-structure auto --protein input.fasta -o output/

# Debug mode — print the command without executing
predict-structure boltz --protein input.fasta -o output/ --debug
```

### Multi-entity complexes

Boltz and Chai support multi-entity predictions with proteins, DNA, RNA, and ligands:

```bash
# Protein-ligand complex
predict-structure boltz --protein protein.fasta --ligand ATP -o output/

# Protein-DNA complex
predict-structure boltz --protein protein.fasta --dna dna.fasta -o output/

# Protein with SMILES ligand
predict-structure boltz --protein protein.fasta --smiles "CCO" -o output/

# Multi-chain protein + ligand with Chai
predict-structure chai --protein chainA.fasta --protein chainB.fasta --ligand ATP -o output/

# Protein-RNA complex
predict-structure boltz --protein protein.fasta --rna rna.fasta -o output/
```

> **Note:** AlphaFold and ESMFold only support protein entities. Passing `--dna`, `--ligand`, etc. to these tools will produce an error.

### Entity support by tool

| Entity | Boltz-2 | Chai-1 | AlphaFold 2 | ESMFold |
|--------|---------|--------|-------------|---------|
| Protein | yes | yes | yes | yes |
| DNA | yes | yes | - | - |
| RNA | yes | yes | - | - |
| Ligand (CCD) | yes | yes | - | - |
| SMILES | yes | - | - | - |
| Glycan | - | - | - | - |

### Boltz YAML pass-through

For full Boltz-2 feature support (custom constraints, covalent bonds, etc.), pass a native Boltz YAML manifest via `--protein`:

```bash
predict-structure boltz --protein complex.yaml -o output/
```

The CLI detects Boltz YAML files automatically (`.yaml`/`.yml` with `version` and `sequences` keys) and passes them through without conversion.

### Batch predictions with `--job`

The `--job` option runs multiple independent predictions from a YAML spec file:

```bash
predict-structure --job jobs.yaml -o output/
```

Each job gets a numbered subdirectory (`job_000/`, `job_001/`, ...). The `--job` flag is exclusive with subcommands — you cannot combine `--job` with `boltz`, `chai`, etc.

#### Job file format

```yaml
# jobs.yaml
- protein:
    - /path/to/protein1.fasta
  options:
    num_samples: 5
    device: gpu

- protein:
    - /path/to/protein2.fasta
  ligands:
    - ATP
  tool: boltz
  options:
    num_samples: 3
    use_potentials: true

- protein:
    - /path/to/protein3.fasta
  dna:
    - /path/to/dna.fasta
  tool: chai
  options:
    sampling_steps: 100

- protein:
    - /path/to/protein4.fasta
  options:
    device: cpu
    backend: subprocess
```

Each job entry supports:

| Key | Type | Description |
|-----|------|-------------|
| `protein` | list of paths | Protein FASTA files |
| `dna` | list of paths | DNA FASTA files |
| `rna` | list of paths | RNA FASTA files |
| `ligands` | list of strings | Ligand CCD codes |
| `smiles` | list of strings | SMILES strings |
| `glycans` | list of strings | Glycan specifications |
| `tool` | string | Tool name (optional — auto-selected if omitted) |
| `options` | dict | Any shared or tool-specific options |

### Global options

These options are available on all tool subcommands:

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-o`, `--output-dir` | path | (required) | Output directory |
| `-n`, `--num-samples` | int | 1 | Number of structure samples (diffusion samples for Boltz/Chai) |
| `--num-recycles` | int | 3 | Recycling iterations |
| `--seed` | int | none | Random seed |
| `--msa` | path | none | MSA file (.a3m, .sto, .pqt) |
| `--output-format` | enum | `pdb` | `pdb` or `mmcif` |
| `--debug` | flag | off | Print the command instead of executing |

### Execution options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--backend` | enum | `subprocess` | `subprocess`, `docker`, or `cwl` |
| `--device` | enum | `gpu` | `gpu` or `cpu` |
| `--image` | string | none | Override Docker image (docker backend only) |
| `--cwl-runner` | string | `cwltool` | CWL runner command (cwl backend only) |
| `--cwl-tool` | string | none | Path to CWL tool definition (cwl backend only) |

### Tool-specific options

#### Boltz-2

```bash
predict-structure boltz --protein input.fasta -o output/ \
  --num-samples 5 \
  --sampling-steps 200 \
  --use-msa-server \
  --msa-server-url https://my-mmseqs-server.com \
  --use-potentials
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--sampling-steps` | int | 200 | Diffusion sampling steps |
| `--use-msa-server` | flag | off | Use remote MSA server |
| `--msa-server-url` | string | none | Custom MSA server URL (implies `--use-msa-server`) |
| `--use-potentials` | flag | off | Enable potential terms |

#### Chai-1

```bash
predict-structure chai --protein input.fasta -o output/ \
  --num-samples 5 \
  --use-msa-server \
  --no-esm-embeddings
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--sampling-steps` | int | 200 | Diffusion timesteps |
| `--use-msa-server` | flag | off | Use remote MSA server |
| `--msa-server-url` | string | none | Custom MSA server URL (implies `--use-msa-server`) |
| `--no-esm-embeddings` | flag | off | Disable ESM2 language model embeddings |
| `--use-templates-server` | flag | off | Use PDB template server |
| `--constraint-path` | path | none | Constraint JSON file |
| `--template-hits-path` | path | none | Pre-computed template hits file |
| `--num-trunk-samples` | int | 1 | Trunk forward passes (independent of `--num-samples` diffusion samples) |
| `--recycle-msa-subsample` | int | 0 | MSA subsample per recycle (0 = all) |
| `--no-low-memory` | flag | off | Disable low-memory mode |

#### AlphaFold 2

```bash
predict-structure alphafold --protein input.fasta -o output/ \
  --af2-data-dir /databases \
  --af2-model-preset monomer \
  --af2-db-preset reduced_dbs
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--af2-data-dir` | path | (required) | AlphaFold database directory (~2 TB) |
| `--af2-model-preset` | string | `monomer` | `monomer`, `monomer_casp14`, or `multimer` |
| `--af2-db-preset` | string | `reduced_dbs` | `reduced_dbs` or `full_dbs` |
| `--af2-max-template-date` | string | `2022-01-01` | Max template date (YYYY-MM-DD) |

#### ESMFold

```bash
predict-structure esmfold --protein input.fasta -o output/ \
  --fp16 \
  --num-recycles 8 \
  --device cpu
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--fp16` | flag | off | Half-precision (FP16) inference |
| `--chunk-size` | int | none | Chunk size for long sequences |
| `--max-tokens-per-batch` | int | none | Max tokens per batch |

### Auto-discovery

The `auto` subcommand detects which tools are installed and picks the best one:

| Condition | Selection |
|-----------|-----------|
| `--device cpu` (protein only) | ESMFold preferred |
| Non-protein entities present | AlphaFold and ESMFold excluded |
| GPU available | Boltz > Chai > AlphaFold > ESMFold (accuracy priority) |

AlphaFold is only auto-selected when both the executable and the database directory (`/databases`) are found.

### Parameter mapping (shared → native)

| Shared Flag | Boltz-2 | Chai-1 | AlphaFold 2 | ESMFold |
|-------------|---------|--------|-------------|---------|
| `--output-dir` | `--out_dir` | positional | `--output_dir` | `-o` |
| `--num-samples` | `--diffusion_samples` | `--num-diffn-samples` | N/A | N/A |
| `--num-recycles` | `--recycling_steps` | `--num-trunk-recycles` | implicit | `--num-recycles` |
| `--seed` | N/A | `--seed` | `--random_seed` | N/A |
| `--device` | `--accelerator` | `--device` | implicit | `--cpu-only` |
| `--msa` | inject into YAML | `--msa-directory` (a3m→pqt) | `--msa_dir` | ignored |

### CWL

```bash
# Validate
cwltool --validate cwl/tools/predict-structure.cwl

# Run
cwltool cwl/tools/predict-structure.cwl cwl/jobs/crambin-esmfold.yml
```

### Docker

```bash
# Build BV-BRC integration layer
cd container
docker build -t dxkb/predict-structure-bvbrc:latest-gpu \
  -f Dockerfile.PredictStructure-bvbrc .

# Run as BV-BRC service
docker run --gpus all -v $(pwd)/test_data:/data \
  dxkb/predict-structure-bvbrc:latest-gpu \
  App-PredictStructure /data/params.json

# Convert to Apptainer/Singularity for HPC
singularity build predict-structure-bvbrc.sif \
  docker://dxkb/predict-structure-bvbrc:latest-gpu
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  CLI  (predict-structure <tool> --protein f.fa [OPTS])  │
│  click.group() with per-tool subcommands + --job batch  │
├─────────────────────────────────────────────────────────┤
│  Entity Layer                                           │
│  EntityList · EntityType · detect_sequence_type          │
│  --protein/--dna/--rna/--ligand/--smiles/--glycan       │
├─────────────────────────────────────────────────────────┤
│  Adapter Layer                                          │
│  Boltz │ Chai │ AlphaFold │ ESMFold                     │
│  Entity→native format · Param mapping · Output normalize│
├─────────────────────────────────────────────────────────┤
│  Execution Backends                                     │
│  subprocess │ docker │ cwl                              │
├─────────────────────────────────────────────────────────┤
│  Per-Tool Containers (delegation, not bundled)          │
│  dxkb/boltz │ dxkb/chai │ wilke/alphafold │ dxkb/esmfold│
└─────────────────────────────────────────────────────────┘
```

PredictStructureApp does **not** bundle all tools into a single image. The CLI and BV-BRC service script dispatch to the appropriate per-tool container. This keeps images small and independently updatable.

### Project layout

```
PredictStructureApp/
├── predict_structure/          # Python package
│   ├── cli.py                  # CLI entry point (click group + subcommands)
│   ├── entities.py             # Entity data model (EntityType, EntityList, detection)
│   ├── adapters/               # Per-tool adapters (build_command, normalize_output)
│   │   ├── base.py             # Abstract BaseAdapter with validate_entities()
│   │   ├── boltz.py            # Boltz-2 (entities→YAML, mmCIF→PDB)
│   │   ├── chai.py             # Chai-1 (entities→typed FASTA, A3M→Parquet MSA)
│   │   ├── alphafold.py        # AlphaFold 2 (entities→FASTA, database path wiring)
│   │   └── esmfold.py          # ESMFold (entities→FASTA, HuggingFace transformers)
│   ├── converters.py           # Format conversions (entities→YAML/FASTA, A3M→Parquet, mmCIF↔PDB)
│   ├── normalizers.py          # Unified output layout + confidence.json
│   ├── config.py               # Tool config loader (tools.yml)
│   └── backends/               # Execution backends
│       ├── subprocess.py       # Direct subprocess execution
│       ├── docker.py           # Docker with volume mounts
│       └── cwl.py              # CWL via cwltool/toil
├── app_specs/                  # BV-BRC service parameter definitions
│   └── PredictStructure.json
├── cwl/                        # CWL tool and workflow definitions
│   ├── tools/predict-structure.cwl
│   └── jobs/                   # Example job YAMLs
├── service-scripts/            # BV-BRC AppService entry point (Perl)
├── container/                  # Dockerfiles for BV-BRC integration layer
├── tests/                      # pytest test suite
├── test_data/                  # Sample inputs for testing
└── pyproject.toml              # Package metadata and dependencies
```

## Testing

```bash
conda activate predict-structure

# Full test suite
pytest

# Verbose with coverage
pytest -v --cov=predict_structure

# Specific test areas
pytest tests/test_entities.py -v              # Entity model and detection
pytest tests/test_cli.py -v                   # CLI argument parsing
pytest tests/test_adapters.py -v              # Adapter logic
pytest tests/test_converters.py -v            # Format conversions
pytest tests/test_cwl_tool.py -v              # CWL validation
pytest tests/test_cwl_backend.py -v           # CWL backend
```

### BV-BRC Makefile tests

```bash
make test-client     # t/client-tests/*.t
make test-server     # t/server-tests/*.t
make test-prod       # t/prod-tests/*.t
```

## Output format

Every prediction produces a standardized output directory:

```
output/
├── model_1.pdb          # Structure (PDB)
├── model_1.cif          # Structure (mmCIF)
├── confidence.json      # {plddt_mean, ptm, per_residue_plddt[]}
├── metadata.json        # {tool, params, runtime, version}
└── raw_output/          # Original tool output (unmodified)
```

## Defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| `tool` | `auto` | Auto-discovers best available tool |
| `num_samples` | 1 | |
| `num_recycles` | 3 | |
| `output_format` | `pdb` | |
| `device` | `gpu` | |
| `backend` | `subprocess` | |
| `sampling_steps` | 200 | Boltz, Chai only |
| `af2_model_preset` | `monomer` | AlphaFold only |
| `af2_db_preset` | `reduced_dbs` | AlphaFold only |
| `af2_max_template_date` | `2022-01-01` | AlphaFold only; prevents template data leakage |
| `af2_data_dir` | `/databases` | AlphaFold only; container default |

## Resource requirements

| Tool | CPU | Memory | GPU | Typical runtime |
|------|-----|--------|-----|-----------------|
| Boltz-2 | 8 | 64-96 GB | A100/H100/H200 | 2-4 h |
| Chai-1 | 8 | 64 GB | A100/H100/H200 | 2-3 h |
| AlphaFold 2 | 8 | 64 GB | A100/H100/H200 | 2-8 h |
| ESMFold | 8 | 32 GB | Optional (CPU OK) | 5-15 min |

GPU constraint in SLURM: `A100|H100|H200` on `gpu2` partition.

## License

MIT
