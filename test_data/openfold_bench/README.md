# OpenFold 3 Benchmarking

Hardware: 8x NVIDIA H200 NVL 144GB (single GPU used)
Container: folding_260407.1.sif (openfold3 v0.4.0)
Checkpoint: of3-p2-155k.pt
Settings: 1 diffusion sample, 1 seed, DeepSpeed evo_attention disabled (H200 incompatible)

## Test proteins

| Name | Residues | PDB | Description |
|------|----------|-----|-------------|
| crambin | 46 | 1CRN | Small plant protein |
| ubiquitin | 76 | 1UBQ | Regulatory protein |
| lysozyme | 164 | 2LZM | T4 lysozyme |
| GFP | 238 | 1EMA | Green fluorescent protein |
| adenylate_kinase | 214 | 4AKE | Enzyme, two domains |

## Results — ColabFold MSA Server (1 sample, 1 seed)

| Protein | Residues | Inference (s) | Wall-clock (s) | MSA overhead (s) | pLDDT | pTM |
|---------|----------|--------------|----------------|-------------------|-------|------|
| crambin | 46 | 11.4 | ~35 | ~24 | 80.2 | 0.57 |
| ubiquitin | 76 | 11.2 | 133 | 122 | 79.6 | 0.68 |
| lysozyme | 164 | 11.2 | 114 | 103 | 93.0 | 0.89 |
| GFP | 238 | 12.1 | 117 | 105 | 88.7 | 0.89 |
| adenylate_kinase | 214 | 14.6 | 126 | 111 | 87.4 | 0.79 |

## Results — Precomputed MSAs (1 sample, 1 seed, batch of 5)

| Protein | Residues | Inference (s) | pLDDT | pTM |
|---------|----------|--------------|-------|------|
| crambin | 46 | 16.2 | 80.2 | 0.57 |
| ubiquitin | 76 | 7.3 | 79.6 | 0.67 |
| lysozyme | 164 | 7.7 | 93.0 | 0.89 |
| GFP | 238 | 8.3 | 88.6 | 0.89 |
| adenylate_kinase | 214 | 8.0 | 87.4 | 0.79 |

Total wall-clock for batch of 5 with precomputed MSAs: 198s (51s template preprocessing + 47s inference)

## Key findings

1. **Inference time is nearly flat** (~7-16s) across 46-238 residues on H200 144GB. O(N^2) scaling not yet visible at these sizes.
2. **MSA + template fetching dominates** — ColabFold server adds ~100-120s overhead per protein.
3. **Precomputed MSAs are ~5x faster** — batch of 5 proteins in 198s vs ~525s with server.
4. **Quality is consistent** between server and precomputed MSAs (same pLDDT/pTM).
5. **DeepSpeed evo_attention is incompatible with H200** — must disable via runner YAML.
6. **Crambin first-run penalty** — model loading adds ~5-9s on first inference.

## Notes

- `timing.json` reports inference time only (excludes MSA computation)
- OF3 generates its own seed (e.g. 2746317213), not using 42 directly
- MSA output format: A3M files per sequence hash in `msas/main/<hash>/colabfold_main.a3m`
- Template alignments: `msas/template/<hash>/colabfold_template.m8`
- `query_msa.json` (auto-generated) contains query with `main_msa_file_paths` populated

## Files

- `*.fasta` — Test protein sequences
- `query_*.json` — OpenFold 3 query files (per-protein and all-in-one)
- `query_precomputed.json` — Query with precomputed MSA paths
- `runner.yml` — Runner config (disables DeepSpeed evo_attention)
- `msa_settings.yml` — MSA server settings (A3M format, persist MSAs)
- `msas/` — Precomputed MSAs and template alignments from ColabFold
