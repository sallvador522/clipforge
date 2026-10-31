# Benchmark (ADR-006) — RUN at Milestone 4

- Spec: `benchmark_spec.json` — 300 frames, 1280x720, 30 FPS, 10 s source; background blur and background replacement measured independently.
- Prepare the source locally: `python scripts/prepare_benchmark.py` (FFmpeg lavfi; fully local). Run: `python scripts/run_benchmark.py` (uses the real renderer, mock segmentation masks, local background asset; no external calls). Raw results: `results/benchmark_results.json`; outputs in `outputs/` (gitignored).

## Measured results (baseline, sequential renderer, pre-optimization)

Machine: Intel Core i5-4330M @ 2.80GHz (2 cores / 4 threads), 7.9 GB RAM, Windows 10, Python 3.13.2.

| Case | Total time | FPS | Peak RAM (process tree) | CPU avg / peak | Output size |
|---|---|---|---|---|---|
| Background blur | 199.29 s | 1.51 | 358.7 MB | 267.5% / 474.9% | 1,246,300 B |
| Background replacement | 25.16 s | 11.92 | 363.3 MB | 104.2% / 193.4% | 949,510 B |

Both outputs verified: 300 frames, 1280x720, 10.000 s video + 10.000 s audio (in sync), playable MP4.

Interpretation: memory is bounded and flat (~360 MB peak regardless of case — streaming design works). Blur is ~8x slower than replacement because a full-resolution large-sigma Gaussian runs per frame; that is the first optimization candidate (downscale-blur) now that a baseline exists, per ADR-006. CPU >100% comes from x264/FFmpeg threads; compositing itself is sequential. These numbers are specific to this old 2-core machine and are not a product performance promise.
