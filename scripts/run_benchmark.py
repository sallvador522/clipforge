"""Benchmark harness stub (ADR-006).

The renderer (Milestone 4) does not exist yet, so there is nothing truthful to
measure. This stub refuses to emit numbers rather than fabricating timings.
Implement the real harness (timing, peak RAM, CPU, output size, ffprobe
duration/stream/audio-sync checks, frame integrity) with the renderer.
"""

import sys


def main() -> int:
    print(
        "Benchmark not run: the FFmpeg+OpenCV renderer (Milestone 4) is not implemented yet. "
        "No performance figures exist and none are claimed. See benchmarks/benchmark_spec.json.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
