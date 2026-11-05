"""Upload media validation using ffprobe. Local subprocess only; no external calls."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from clipforge_jobs.models import SourceInfo

MAX_DURATION_SECONDS = 1800.0  # ADR-058: production programs up to 30 min; container tolerance included
MAX_WIDTH = 1280
MAX_HEIGHT = 720
MAX_FPS = 30.5


class UploadValidationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _parse_fps(raw: str | None) -> float:
    if not raw or raw == "0/0":
        return 0.0
    try:
        return float(Fraction(raw))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path: str | Path) -> SourceInfo:
    """Probe a video file and enforce MVP constraints. Raises UploadValidationError."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,width,height,avg_frame_rate,nb_frames",
            "-show_entries", "format=duration",
            "-show_streams", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise UploadValidationError("unreadable_media", "Uploaded file could not be probed as media.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise UploadValidationError("unreadable_media", "ffprobe returned invalid output.") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise UploadValidationError("no_video_stream", "Uploaded file has no video stream.")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    fps = _parse_fps(video.get("avg_frame_rate"))
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if width <= 0 or height <= 0 or fps <= 0 or duration <= 0:
        raise UploadValidationError("invalid_media_metadata", "Video stream metadata is missing or invalid.")
    if width > MAX_WIDTH or height > MAX_HEIGHT:
        raise UploadValidationError(
            "resolution_too_large", f"Video is {width}x{height}; maximum is {MAX_WIDTH}x{MAX_HEIGHT} (720p)."
        )
    if duration > MAX_DURATION_SECONDS:
        raise UploadValidationError(
            "duration_too_long", f"Video is {duration:.2f}s; maximum is 30 minutes."
        )
    if fps > MAX_FPS:
        raise UploadValidationError("fps_too_high", f"Video is {fps:.1f} FPS; maximum is 30 FPS.")

    nb_frames = video.get("nb_frames")
    frame_count = int(nb_frames) if nb_frames and str(nb_frames).isdigit() else round(duration * fps)
    return SourceInfo(
        width=width, height=height, fps=fps, duration_seconds=duration,
        frame_count=max(frame_count, 1), has_audio=has_audio,
    )
