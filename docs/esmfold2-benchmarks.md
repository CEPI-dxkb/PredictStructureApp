# ESMFold2 — Benchmarks & Preflight Sizing

Measured on **NVIDIA H200 NVL** (143 GB), driver 580.95.05 (CUDA 13.0), host with
384 cores / 1.5 TB RAM, via the standalone Apptainer image `container/esmfold2.def`
(`ubuntu:22.04` base, PyTorch 2.12.0+cu130). All runs: `--seed 0`, `--num-loops 3`,
`--num-sampling-steps 50`, weights warm in the bound HF cache.

- **GPU**: `apptainer run --nv`; model in **bf16**.
- **CPU**: `--device cpu`; runner forces **fp32** (bf16 CPU kernels mix dtypes and crash),
  thread count capped at `OMP_NUM_THREADS=32` (uncapped 384-thread runs are ~2× slower
  from contention).
- `load` = `from_pretrained` + move to device. `fold` = `ESMFold2InputBuilder().fold()`.
- `wall` includes container start + torch/esm imports + normalization (~18–20 s fixed).
- Timings from the runner's `PERF` log line; wall/host-RAM from `/usr/bin/time -v`.

## Test cases

| Case        | Input                          | Entities                |
|-------------|--------------------------------|-------------------------|
| prot_small  | crambin, 46 res                | 1 protein               |
| prot_medium | adenylate kinase, 214 res      | 1 protein               |
| prot_large  | enolase, 434 res               | 1 protein               |
| multimer    | 2 chains, 55 res               | 2 proteins              |
| prot_ligand | crambin + ATP (CCD)            | protein + ligand        |
| prot_dna    | crambin + 20bp DNA             | protein + DNA           |
| rna         | 20 nt                          | 1 RNA                   |
| samples2    | crambin, num_diffusion=2       | 1 protein, 2 samples    |

## GPU (H200, bf16)

| Case        | Wall  | Load | Fold  | Peak VRAM | Host RAM | pLDDT | pTM  | ipTM  |
|-------------|-------|------|-------|-----------|----------|-------|------|-------|
| prot_small  | 32.4s | 5.0s | 7.3s  | 13.9 GB   | 16.2 GB  | 62.1  | 0.44 | –     |
| prot_medium | 32.4s | 5.0s | 8.4s  | 14.5 GB   | 16.2 GB  | 95.9  | 0.95 | –     |
| prot_large  | 35.8s | 4.6s | 12.1s | 16.9 GB   | 16.2 GB  | 97.8  | 0.99 | –     |
| multimer    | 33.2s | 4.9s | 8.1s  | 13.9 GB   | 16.2 GB  | 42.8  | 0.21 | 0.069 |
| prot_ligand | 31.3s | 5.0s | 7.3s  | 13.9 GB   | 16.2 GB  | 52.3  | 0.41 | 0.17  |
| prot_dna    | 31.5s | 4.8s | 7.2s  | 13.9 GB   | 16.2 GB  | 46.7  | 0.26 | 0.11  |
| rna         | 32.7s | 4.9s | 7.9s  | 13.8 GB   | 16.2 GB  | 71.3  | 0.12 | –     |
| samples2    | 31.8s | 5.2s | 7.4s  | 13.9 GB   | 16.2 GB  | 62.0  | 0.44 | –     |

## CPU (fp32, 32 threads)

| Case        | Wall      | Load | Fold    | Host RAM | pLDDT | pTM  | ipTM  |
|-------------|-----------|------|---------|----------|-------|------|-------|
| prot_small  | 39.5s     | 4.3s | 16.8s   | 28.1 GB  | 63.4  | 0.46 | –     |
| prot_medium | 4m15s     | 4.6s | 231.6s  | 28.8 GB  | 90.5  | 0.89 | –     |
| prot_large  | 14m50s    | 4.3s | 866.6s  | 32.2 GB  | 97.8  | 0.99 | –     |
| multimer    | 42.9s     | 4.2s | 20.1s   | 28.1 GB  | 43.7  | 0.20 | 0.061 |
| prot_ligand | 53.3s     | 4.0s | 31.5s   | 28.1 GB  | 41.6  | 0.33 | 0.133 |
| prot_dna    | 55.6s     | 4.2s | 31.1s   | 28.1 GB  | 48.2  | 0.28 | 0.140 |
| rna         | 36.9s     | 4.2s | 12.9s   | 27.9 GB  | 72.0  | 0.12 | –     |
| samples2    | 40.8s     | 4.8s | 17.5s   | 28.1 GB  | 63.7  | 0.46 | –     |

## GPU vs CPU — fold-time speedup

| Case        | GPU fold | CPU fold | GPU speedup |
|-------------|----------|----------|-------------|
| rna (20)    | 7.9s     | 12.9s    | 1.6×        |
| prot_small  | 7.3s     | 16.8s    | 2.3×        |
| samples2    | 7.4s     | 17.5s    | 2.4×        |
| multimer    | 8.1s     | 20.1s    | 2.5×        |
| prot_ligand | 7.3s     | 31.5s    | 4.3×        |
| prot_dna    | 7.2s     | 31.1s    | 4.3×        |
| prot_medium | 8.4s     | 231.6s   | **27.6×**   |
| prot_large  | 12.1s    | 866.6s   | **71.6×**   |

## Findings

- **All entity types verified on both devices:** protein, DNA, RNA, CCD ligand
  (ATP → 31 HETATM), multi-chain. ipTM is populated only for multi-entity inputs;
  CPU and GPU agree closely (e.g. ligand ipTM 0.13 CPU vs 0.17 GPU).
- **GPU advantage explodes with size.** For small inputs (≤55 res) GPU is only ~2×
  faster — fixed overhead (imports, model load, normalization) dominates. By 214 res
  GPU is ~28× faster, and by 434 res ~72×. CPU fold time is roughly quadratic in
  sequence length; GPU fold barely moves (7→12 s across 46→434 res).
- **Confidence is consistent across devices.** Large-protein pLDDT/pTM match exactly
  (97.8 / 0.99); small-protein values differ slightly (62.1 GPU vs 63.4 CPU) from
  bf16-vs-fp32 numerics plus the pure-PyTorch attention/RoPE fallbacks (no
  transformer_engine / xformers / flash-attn installed).
- **Memory:** GPU path ~13.8–16.9 GB VRAM + ~16 GB host RAM (bf16 weights on GPU).
  CPU path needs ~28–32 GB host RAM (fp32 weights resident); large inputs push toward
  the upper end.
- **`num-samples` is cheap** on both devices — 2 diffusion samples added no meaningful
  time or memory; the ESMC trunk dominates.

## Preflight sizing (per `ESMFold2Adapter.preflight()`)

| Field          | Value                          | Rationale |
|----------------|--------------------------------|-----------|
| `requires_gpu` | `True`                         | CPU works (fp32) but 2–72× slower depending on size; impractical beyond small inputs. |
| GPU            | 1 × A100\|H100\|H200, `gpu2`   | ≤17 GB VRAM across all tested sizes; constraint matches partition policy. |
| `cpu`          | 8                              | CPU runs benefit from threads but GPU is the target; 8 is adequate. |
| `memory`       | **32G**                        | Peak host RSS 16 GB (GPU) / 28–32 GB (CPU fp32); 32 G covers both. |
| `runtime`      | **3600s**                      | GPU ≤36 s for everything tested (warm; +~1 min cold weight download). 1 h is ample. |
| `storage`      | 50G                            | Model weights + outputs. |

> Sizes beyond ~450 residues and large multi-chain complexes were not benchmarked;
> VRAM and fold time grow with total token count — revisit for >1000-residue jobs.
> On CPU specifically, a 434-residue protein already takes ~15 min — large CPU jobs
> are impractical, reinforcing `requires_gpu: True`.
