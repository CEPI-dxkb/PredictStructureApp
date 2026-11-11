# Production-change checks, 2026-11-10

Run on coconut, one H200 (GPU 7), container folding_260901.1.sif with the merged
main overlaid (PYTHONPATH). Single-chain random sequences, no MSA, --force.

- length_sweep.tsv: per-tool length sweep (peak_mib = whole-GPU memory sampled
  every 5 s, includes allocator caching). Boltz OOM at 4000; OpenFold ok to 4000;
  ESMFold ok at 1500, OOM at 2000+. ESMFold2 not measurable: HF checkpoint
  biohub/ESMFold2 revision 69869f7 changed config (EsmFold2Model, "architectures")
  and the installed transformers cannot load it. AlphaFold 2 not tested.
- esmfold_crambin.ss3.txt: DSSP written by write_dssp for an ESMFold crambin model.
- report_with_ss_file.html vs report_heuristic_fallback.html: same model,
  8.7% helix / 4.3% sheet / 87% coil vs 0% / 0% / 100% (Calpha fallback).
