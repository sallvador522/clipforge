"""Social export transcoding (Reels / YouTube).

Real FFmpeg-only format conversion of an already verified render.
No AI, no mock: decodes the verified output, cover-fits it to the target
aspect, re-encodes with libx264 + AAC, and verifies the actual file.

Originals are never overwritten: exports are cached under
jobs/<job_id>/exports/ and written atomically via .tmp + os.replace.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

EXPORT_FORMATS: dict[str, dict[str, int | str]] = {
    "original": {"width": 0, "height": 0, "label": "Original"},
    "reels": {"width": 1080, "height": 1920, "label": "Reels 9:16"},
    "youtube": {"width": 1920, "height": 1080, "label": "YouTube 16:9"},
}

EXPORT_FILENAMES: dict[str, str] = {
    "original": "clipforge-{job_id}.mp4",
    "reels": "clipforge-{job_id}-reels.mp4",
    "youtube": "clipforge-{job_id}-youtube.mp4",
}


class ExportError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ExportError("export_probe_failed", f"Could not probe {path.name} for export.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ExportError("export_probe_failed", "ffprobe returned invalid output.") from exc


def _has_audio(data: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def export_video(job_dir: Path, verified_path: Path, export_format: str) -> Path:
    """Transcode (or locate) the social export. Returns the verified export path."""
    if export_format not in EXPORT_FORMATS:
        raise ExportError("invalid_export_format", f"Unknown export format: {export_format}. Use reels or youtube.")
    if export_format == "original":
        return verified_path

    target = EXPORT_FORMATS[export_format]
    width, height = int(target["width"]), int(target["height"])

    exports_dir = job_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    output_path = exports_dir / f"output_{export_format}.mp4"

    # Cache hit: verified exports are immutable derivations of the verified render.
    if output_path.is_file() and output_path.stat().st_size > 0:
        return output_path

    if not verified_path.is_file() or verified_path.stat().st_size == 0:
        raise ExportError("download_not_ready", "Verified render is missing on disk.")

    source_probe = _probe(verified_path)
    expect_audio = _has_audio(source_probe)
    try:
        source_duration = float(source_probe.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        source_duration = 0.0

    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    tmp_path = output_path.with_name(output_path.stem + ".tmp.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(verified_path),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "veryfast",
        "-movflags", "+faststart",
    ]
    if expect_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd.append(str(tmp_path))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        tail = (result.stderr or "")[-400:].strip()
        raise ExportError("export_failed", f"Social export failed ({export_format}): {tail}")

    # Verify the actual export file before exposing it.
    try:
        data = _probe(tmp_path)
    except ExportError:
        tmp_path.unlink(missing_ok=True)
        raise
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        tmp_path.unlink(missing_ok=True)
        raise ExportError("export_failed", "Export has no video stream.")
    if int(video.get("width", 0)) != width or int(video.get("height", 0)) != height:
        tmp_path.unlink(missing_ok=True)
        raise ExportError(
            "export_failed",
            f"Export resolution {video.get('width')}x{video.get('height')} != expected {width}x{height}.",
        )
    has_audio = _has_audio(data)
    if expect_audio and not has_audio:
        tmp_path.unlink(missing_ok=True)
        raise ExportError("export_failed", "Export is missing the original audio stream.")
    try:
        out_duration = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        out_duration = 0.0
    if source_duration > 0 and (out_duration <= 0 or abs(out_duration - source_duration) > 0.8):
        tmp_path.unlink(missing_ok=True)
        raise ExportError(
            "export_failed",
            f"Export duration {out_duration:.2f}s diverges from source ~{source_duration:.2f}s.",
        )

    os.replace(tmp_path, output_path)
    return output_path
