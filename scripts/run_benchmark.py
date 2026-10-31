"""Real ADR-006 benchmark: 300 frames, 1280x720, 30 FPS, blur vs replacement.

Runs the actual Milestone 4 renderer on local synthetic media only (mock
segmentation masks + local background asset; no external calls). Measures
elapsed time, FPS, peak RAM, CPU, output size, and verifies the output
(duration, streams, frame count, audio). Results are written to
benchmarks/results/benchmark_results.json. Machine specs are recorded.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/contracts", "packages/providers", "packages/jobs", "apps/worker", "apps/api"):
    sys.path.insert(0, str(ROOT / _p))

from clipforge_providers import get_providers  # noqa: E402
from clipforge_worker.masks import MaskLoader  # noqa: E402
from clipforge_worker.renderer import RenderRequest, render_video  # noqa: E402

SOURCE = ROOT / "benchmarks" / "assets" / "source_720p_10s.mp4"
MASKS = ROOT / "benchmarks" / "assets" / "masks"
OUTPUTS = ROOT / "benchmarks" / "outputs"
RESULTS = ROOT / "benchmarks" / "results" / "benchmark_results.json"
BACKGROUND = ROOT / "assets" / "backgrounds" / "studio_landscape.png"


class ResourceMonitor(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak_rss_mb = 0.0
        self.cpu_samples: list[float] = []
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        proc = psutil.Process()
        while not self._stop.is_set():
            rss = proc.memory_info().rss
            cpu = proc.cpu_percent(interval=None)
            for child in proc.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                    cpu += child.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self.peak_rss_mb = max(self.peak_rss_mb, rss / (1024 * 1024))
            self.cpu_samples.append(cpu)
            time.sleep(0.05)


def _machine_specs() -> dict:
    return {
        "machine": platform.machine(),
        "os": f"{platform.system()} {platform.release()}",
        "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "python": platform.python_version(),
    }


def _run_case(mode: str, background: Path | None) -> dict:
    output = OUTPUTS / f"benchmark_{mode}.mp4"
    monitor = ResourceMonitor()
    monitor.start()
    start = time.perf_counter()
    try:
        result = render_video(
            RenderRequest(
                source_path=SOURCE, masks_dir=MASKS, output_path=output,
                output_relative_path=f"benchmarks/outputs/{output.name}", mode=mode,
                background_path=background, expect_audio=True,
            )
        )
    finally:
        elapsed = time.perf_counter() - start
        monitor.stop()
        monitor.join(timeout=2)
    return {
        "mode": mode,
        "total_processing_time_seconds": round(elapsed, 2),
        "frames_per_second": round(result.frame_count / elapsed, 2),
        "peak_ram_mb_process_tree": round(monitor.peak_rss_mb, 1),
        "cpu_percent_avg_process_tree": round(sum(monitor.cpu_samples) / max(len(monitor.cpu_samples), 1), 1),
        "cpu_percent_peak_process_tree": round(max(monitor.cpu_samples, default=0.0), 1),
        "output_file_size_bytes": result.file_size_bytes,
        "frame_count_verified": result.frame_count,
        "duration_seconds_verified": round(result.duration_seconds, 3),
        "resolution_verified": f"{result.width}x{result.height}",
        "audio_stream_present": result.has_audio,
        "output": str(output.relative_to(ROOT)),
    }


def main() -> int:
    if not SOURCE.is_file():
        print("Benchmark source missing; running prepare_benchmark.py first...")
        if subprocess.run([sys.executable, str(ROOT / "scripts" / "prepare_benchmark.py")]).returncode != 0:
            return 1
    if not (MASKS / "manifest.json").is_file():
        print("Generating 300 synthetic benchmark masks (mock segmentation, local only)...")
        get_providers("mock").segmentation.segment(
            job_id="benchmark", source_video_id="benchmark-source", output_dir=MASKS,
            width=1280, height=720, frame_count=300, fps=30.0,
        )
    _, manifest = MaskLoader().load_manifest(MASKS)
    assert manifest.frame_count == 300 and (manifest.video_width, manifest.video_height) == (1280, 720)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    cases = [_run_case("blur_background", None), _run_case("replace_background", BACKGROUND)]
    report = {
        "benchmark": "clipforge-cpu-render-benchmark (ADR-006)",
        "ai_mode": "mock",
        "machine_specs": _machine_specs(),
        "source": str(SOURCE.relative_to(ROOT)),
        "cases": cases,
        "notes": (
            "Sequential bounded-memory renderer (ADR-006 baseline, pre-optimization). "
            "CPU% is the process tree (worker + FFmpeg child) sampled every 50 ms; "
            "values above 100% mean multiple cores were used by FFmpeg/x264 threads."
        ),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nResults written to {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
