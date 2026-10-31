# Benchmark Preparation (ADR-006) — prepared, NOT run

- Spec: `benchmark_spec.json` — 300 frames, 1280x720, 30 FPS, 10 s source; background blur and background replacement measured independently once the renderer exists.
- Prepare the source clip locally: `python scripts/prepare_benchmark.py` (FFmpeg lavfi `testsrc2` + sine audio; fully local, deterministic, no external calls). Output: `benchmarks/assets/source_720p_10s.mp4` (gitignored).
- `scripts/run_benchmark.py` is an explicit stub: it exits non-zero stating the renderer does not exist yet. It must never print fabricated timings. Real harness implementation (stdlib `time`/`resource` or equivalent, plus ffprobe verification of duration/streams/audio sync and frame counts) is part of Milestone 4.
- No processing times are promised anywhere until measurements are recorded with machine specifications in `docs/STATUS.md`.
