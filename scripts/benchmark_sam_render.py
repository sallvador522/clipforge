"""Full-resolution SAM-compatible mask/render benchmark (Milestone 6D).

Uses the existing 300-frame 1280x720 30 FPS 10 s local source with audio and a
deterministic mock two-subject mask fixture. It exercises the same per-object
mask contract, selection union and real FFmpeg/OpenCV renderer that the live
SAM provider feeds. This is NOT a SAM detection-quality benchmark and makes no
external request.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
for path in (
    "packages/contracts",
    "packages/providers",
    "packages/jobs",
    "packages/director",
    "apps/worker",
    "apps/api",
):
    sys.path.insert(0, str(ROOT / path))

from clipforge_providers import MockSegmentationProvider  # noqa: E402
from clipforge_worker.masks import MaskLoader, combine_subject_masks  # noqa: E402
from clipforge_worker.renderer import RenderRequest, render_video  # noqa: E402

SOURCE = ROOT / "benchmarks" / "assets" / "source_720p_10s.mp4"
OUTPUT_DIR = ROOT / "benchmarks" / "outputs" / "sam_6d"
RESULTS = ROOT / "benchmarks" / "results" / "sam_render_benchmark.json"


class ResourceMonitor(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak_rss_mb = 0.0
        self.cpu_samples: list[float] = []
        self._stop = threading.Event()

    def run(self) -> None:
        process = psutil.Process()
        while not self._stop.is_set():
            rss = process.memory_info().rss
            cpu = process.cpu_percent(interval=None)
            for child in process.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                    cpu += child.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self.peak_rss_mb = max(self.peak_rss_mb, rss / (1024 * 1024))
            self.cpu_samples.append(cpu)
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop.set()


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing benchmark source: {SOURCE}. Run scripts/prepare_benchmark.py first.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    storage = OUTPUT_DIR / "job"
    masks = storage / "masks"

    segment_start = time.perf_counter()
    segmentation = MockSegmentationProvider().segment(
        job_id="sam-benchmark",
        source_video_id="sam-benchmark-source",
        output_dir=masks,
        width=1280,
        height=720,
        frame_count=300,
        fps=30.0,
        source_path=SOURCE,
    )
    segment_elapsed = time.perf_counter() - segment_start
    selected_id = segmentation.subjects[0].object_id
    selected_dir = storage / "selected"
    union_start = time.perf_counter()
    selected_manifest = combine_subject_masks(
        segmentation.subjects,
        [selected_id],
        selected_dir,
        fps=30.0,
        source_video_id="sam-benchmark-source",
        source_sha256=segmentation.source_sha256,
    )
    union_elapsed = time.perf_counter() - union_start
    selected_loader = MaskLoader().load(selected_dir)
    assert selected_manifest.frame_count == 300
    assert selected_loader.masks.shape == (300, 720, 1280)

    output = OUTPUT_DIR / "sam_selected_blur_720p.mp4"
    monitor = ResourceMonitor()
    monitor.start()
    render_start = time.perf_counter()
    try:
        rendered = render_video(
            RenderRequest(
                source_path=SOURCE,
                masks_dir=selected_dir,
                output_path=output,
                output_relative_path="benchmarks/outputs/sam_6d/sam_selected_blur_720p.mp4",
                mode="blur_background",
                expect_audio=True,
            ),
            on_stage=lambda stage: print(f"stage={stage}", flush=True),
        )
    finally:
        render_elapsed = time.perf_counter() - render_start
        monitor.stop()
        monitor.join(timeout=2)

    report = {
        "benchmark": "clipforge-sam-6d-full-resolution (mock masks; no SAM request)",
        "source": str(SOURCE),
        "source_contract": {
            "frame_count": 300,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "duration_seconds": 10.0,
            "audio_preserved": True,
        },
        "segmentation": {
            "provider": segmentation.provider_name,
            "is_mock": segmentation.is_mock,
            "subjects": [subject.object_id for subject in segmentation.subjects],
            "selected_subject_ids": [selected_id],
            "elapsed_seconds": round(segment_elapsed, 2),
            "per_object_manifest": segmentation.subjects[0].mask_manifest_path,
            "preview_path": segmentation.subjects[0].preview_path,
        },
        "selection_union": {
            "elapsed_seconds": round(union_elapsed, 2),
            "manifest": str(selected_dir / "manifest.json"),
            "sam_object_ids": selected_manifest.sam_object_ids,
        },
        "render": {
            "mode": rendered.mode,
            "total_processing_time_seconds": round(render_elapsed, 2),
            "frames_per_second": round(rendered.frame_count / render_elapsed, 2),
            "peak_ram_mb_process_tree": round(monitor.peak_rss_mb, 1),
            "cpu_percent_avg_process_tree": round(
                sum(monitor.cpu_samples) / max(len(monitor.cpu_samples), 1), 1
            ),
            "cpu_percent_peak_process_tree": round(max(monitor.cpu_samples, default=0.0), 1),
            "output_file_size_bytes": rendered.file_size_bytes,
            "frame_count_verified": rendered.frame_count,
            "duration_seconds_verified": rendered.duration_seconds,
            "resolution_verified": f"{rendered.width}x{rendered.height}",
            "audio_stream_present": rendered.has_audio,
            "output": str(output),
        },
        "machine_specs": {
            "machine": platform.machine(),
            "os": f"{platform.system()} {platform.release()}",
            "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
            "logical_cores": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "python": platform.python_version(),
        },
        "notes": (
            "SAM detection is mocked with two deterministic ellipse objects. "
            "The benchmark validates the per-object mask contract, selected union, "
            "bounded-memory path and full-resolution real render. It is not evidence "
            "of SAM detection quality or a live API call."
        ),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
