# ESMFold2 — Benchmarks & Preflight Sizing

Measured on **NVIDIA H200 NVL** (143 GB), driver 580.95.05 (CUDA 13.0), via the
standalone Apptainer image `container/esmfold2.def` (`ubuntu:22.04` base, PyTorch
2.12.0+cu130). All runs: `--seed 0`, `--num-loops 3`, `--num-sampling-steps 50`,
weights warm in the bound HF cache. Timings from the runner's `PERF` log line;
wall-clock and host RAM from `/usr/bin/time -v`.

`load` = `from_pretrained` + move to device. `fold` = `ESMFold2InputBuilder().fold()`.
`wall` includes container start + torch/esm imports + normalization (~18–20 s fixed
overhead on top of load+fold).

## GPU (H200)

| Case            | Input              | Wall  | Load | Fold  | Peak VRAM | Host RAM | pLDDT | pTM  | ipTM  |
|-----------------|--------------------|-------|------|-------|-----------|----------|-------|------|-------|
| prot_small      | protein, 46 res    | 32.4s | 5.0s | 7.3s  | 13.9 GB   | 16.2 GB  | 62.1  | 0.44 | –     |
| prot_medium     | protein, 214 res   | 32.4s | 5.0s | 8.4s  | 14.5 GB   | 16.2 GB  | 95.9  | 0.95 | –     |
| prot_large      | protein, 434 res   | 35.8s | 4.6s | 12.1s | 16.9 GB   | 16.2 GB  | 97.8  | 0.99 | –     |
| multimer        | 2 chains, 55 res   | 33.2s | 4.9s | 8.1s  | 13.9 GB   | 16.2 GB  | 42.8  | 0.21 | 0.069 |
| prot_ligand     | crambin + ATP (CCD)| 31.3s | 5.0s | 7.3s  | 13.9 GB   | 16.2 GB  | 52.3  | 0.41 | 0.17  |
| prot_dna        | crambin + 20bp DNA | 31.5s | 4.8s | 7.2s  | 13.9 GB   | 16.2 GB  | 46.7  | 0.26 | 0.11  |
| rna             | RNA, 20 nt         | 32.7s | 4.9s | 7.9s  | 13.8 GB   | 16.2 GB  | 71.3  | 0.12 | –     |
| samples2        | crambin, 2 samples | 31.8s | 5.2s | 7.4s  | 13.9 GB   | 16.2 GB  | 62.0  | 0.44 | –     |

## CPU (fp32 fallback)

| Case       | Input           | Wall  | Load | Fold  | Host RAM | pLDDT | pTM  |
|------------|-----------------|-------|------|-------|----------|-------|------|
| cpu_small  | protein, 46 res | 58.4s | 5.1s | 35.9s | 27.8 GB  | 63.4  | 0.46 |

## Findings

- **All entity types verified:** protein, DNA, RNA, CCD ligand (ATP → 31 HETATM),
  multi-chain. ipTM is populated only for multi-entity inputs (monomers report 0.0).
- **VRAM floor ≈ 13.8 GB** (the frozen ESMC trunk dominates); grows modestly with
  length (16.9 GB at 434 res). Fits any 24 GB+ GPU; A100/H100/H200 have wide headroom.
- **Host RAM ≈ 16 GB** on the GPU path. The model loads in **bf16** on GPU.
- **`num-samples` is cheap:** 2 diffusion samples added no measurable time or VRAM —
  the ESMC trunk dominates, diffusion sampling is marginal.
- **Fixed overhead dominates short jobs:** ~25 s of every run is container start +
  imports + model load; the fold itself is 7–12 s for everything tested.
- **CPU requires fp32.** The checkpoint loads in bf16, but CPU kernels mix fp32/bf16
  and raise `expected m1 and m2 to have the same dtype`. The runner forces `.float()`
  on the CPU path. CPU is then ~4.5× slower (36 s vs 7 s fold for crambin) and uses
  ~1.7× host RAM (fp32 weights resident). **GPU is strongly preferred**; CPU is a
  small-input fallback only.

## Preflight sizing (per `ESMFold2Adapter.preflight()`)

| Field        | Value             | Rationale |
|--------------|-------------------|-----------|
| `requires_gpu` | `True`          | bf16 model; CPU path works but ~5× slower. |
| GPU          | 1 × A100\|H100\|H200, `gpu2` | ≤17 GB VRAM tested; constraint matches partition policy. |
| `cpu`        | 8                 | Unchanged. |
| `memory`     | **32G**           | Peak host RSS 16 GB (GPU) / 28 GB (CPU fp32); 32 G covers both. |
| `runtime`    | **3600s**         | Tested ≤36 s GPU / ≤58 s CPU warm; first run adds ~1 min cold weight download. 1 h is ample for far larger inputs. |
| `storage`    | 50G               | Unchanged. |

> Sizes beyond ~450 residues and large multi-chain complexes were not benchmarked;
> VRAM and fold time grow with total token count, so revisit for >1000-residue jobs.
