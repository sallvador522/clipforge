"""Prepare the ADR-006 benchmark source clip locally with FFmpeg. No external calls.

Generates benchmarks/assets/source_720p_10s.mp4: 300 frames, 1280x720, 30 FPS,
10 seconds, with a sine audio track for later audio-sync verification.
This only PREPARES the benchmark; it measures no rendering performance.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "benchmarks" / "assets" / "source_720p_10s.mp4"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(ASSET),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print("FFmpeg failed (libx264 may be unavailable in this build); no asset generated.", file=sys.stderr)
        return 1
    probe = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,avg_frame_rate:format=duration,size",
        "-of", "json", str(ASSET),
    ])
    if probe.returncode != 0:
        print(probe.stderr, file=sys.stderr)
        return 1
    info = json.loads(probe.stdout)
    print(json.dumps(info, indent=2))
    print(f"Benchmark source prepared: {ASSET} (preparation only; no performance measured).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
