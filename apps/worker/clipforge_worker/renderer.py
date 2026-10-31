"""Real FFmpeg + OpenCV rendering engine (Milestone 4, ADR-002/005/006).

Decodes source frames sequentially with OpenCV (bounded memory: one frame and
one mask in RAM at a time), composites the subject over a blurred or replaced
background using a feathered alpha from the validated PNG masks, pipes raw
frames to FFmpeg (libx264), and muxes the ORIGINAL audio from the source file.
The output is verified with ffprobe (streams, resolution, frame count,
duration, audio) before any success is reported. Nothing here is simulated.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from clipforge_contracts import RenderResult
from clipforge_worker.masks import MaskLoader

logger = logging.getLogger("clipforge.renderer")


class RenderingError(Exception):
    pass


@dataclass(frozen=True)
class RenderRequest:
    source_path: str | Path
    masks_dir: str | Path
    output_path: str | Path
    output_relative_path: str
    mode: str  # "blur_background" | "replace_background"
    background_path: str | Path | None = None
    blur_strength: float = 0.8
    feather_radius: int = 5  # px Gaussian feather on alpha edges (edge smoothing)
    expect_audio: bool = True


def _probe(path: Path, count_frames: bool = False) -> dict:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    if count_frames:
        cmd.insert(3, "-count_frames")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RenderingError(f"ffprobe failed on {path.name}: {result.stderr.strip()[-300:]}")
    return json.loads(result.stdout)


def _audio_codec(source: Path) -> str | None:
    data = _probe(source)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            return stream.get("codec_name")
    return None


def verify_render_output(
    output_path: str | Path, *, width: int, height: int, frame_count: int, duration: float,
    expect_audio: bool, mode: str = "blur_background", output_relative_path: str = "",
) -> RenderResult:
    """Verify the actual file. Raises RenderingError on any mismatch."""
    path = Path(output_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise RenderingError("Rendered output is missing or empty.")
    data = _probe(path, count_frames=True)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RenderingError("Rendered output has no video stream.")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (width, height):
        raise RenderingError(
            f"Output resolution {video.get('width')}x{video.get('height')} != expected {width}x{height}."
        )
    frames = video.get("nb_read_frames") or video.get("nb_frames")
    actual_frames = int(frames) if frames and str(frames).isdigit() else -1
    if actual_frames != frame_count:
        raise RenderingError(f"Output frame count {actual_frames} != expected {frame_count}.")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if expect_audio and not has_audio:
        raise RenderingError("Output is missing the original audio stream.")
    out_duration = float(data.get("format", {}).get("duration", 0) or 0)
    if out_duration <= 0 or abs(out_duration - duration) > 0.6:
        raise RenderingError(f"Output duration {out_duration:.2f}s != expected ~{duration:.2f}s.")
    fps_raw = video.get("avg_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return RenderResult(
        output_relative_path=output_relative_path,
        mode=mode,  # type: ignore[arg-type]
        width=width, height=height, fps=fps, frame_count=actual_frames,
        duration_seconds=out_duration, file_size_bytes=path.stat().st_size, has_audio=has_audio,
    )


def _load_background(path: str | Path | None, width: int, height: int) -> np.ndarray:
    if path is None:
        raise RenderingError("replace_background requires a background image; none was provided.")
    bg_path = Path(path)
    if not bg_path.is_file():
        raise RenderingError(f"Background image not found: {bg_path}")
    image = cv2.imread(str(bg_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RenderingError(f"Background image is corrupt or unreadable: {bg_path}")
    if image.shape[1] != width or image.shape[0] != height:
        # Backgrounds are cover-fitted to the frame; masks are NEVER resized like this (ADR-005).
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
    return image


def _composite(frame: np.ndarray, mask: np.ndarray, background: np.ndarray, feather_radius: int) -> np.ndarray:
    alpha = mask.astype(np.float32) / 255.0
    if feather_radius > 0:
        ksize = feather_radius * 2 + 1
        alpha = cv2.GaussianBlur(alpha, (ksize, ksize), 0)
    alpha3 = alpha[:, :, None]
    return (frame.astype(np.float32) * alpha3 + background.astype(np.float32) * (1.0 - alpha3)).astype(np.uint8)


def render_video(request: RenderRequest, on_stage: Callable[[str], None] | None = None) -> RenderResult:
    source = Path(request.source_path)
    output = Path(request.output_path)
    if not source.is_file():
        raise RenderingError(f"Source video not found: {source}")
    if request.mode not in ("blur_background", "replace_background"):
        raise RenderingError(f"Unknown render mode: {request.mode!r}")
    output.parent.mkdir(parents=True, exist_ok=True)

    loader = MaskLoader()
    _, manifest = loader.load_manifest(request.masks_dir)  # full manifest validation up front
    width, height, fps = manifest.video_width, manifest.video_height, manifest.fps

    background_image: np.ndarray | None = None
    if request.mode == "replace_background":
        background_image = _load_background(request.background_path, width, height)

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RenderingError(f"Source video could not be decoded: {source}")
    src_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if (src_w, src_h) != (width, height):
        capture.release()
        raise RenderingError(
            f"Source dimensions {src_w}x{src_h} do not match mask manifest {width}x{height}; refusing to guess."
        )

    audio_codec = _audio_codec(source) if request.expect_audio else None
    audio_args: list[str] = []
    if audio_codec:
        # AAC/MP3 copy losslessly into MP4; other codecs are re-encoded to AAC (still the original audio).
        audio_args = ["-map", "1:a:0", "-c:a", "copy" if audio_codec in ("aac", "mp3") else "aac"]

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "-", "-i", str(source),
        "-map", "0:v:0", *audio_args,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        # NB: no -shortest here. The 2018 system FFmpeg drops the video stream
        # when -shortest is combined with copied audio (verified empirically);
        # video length is governed exactly by the frames we pipe in.
        "-movflags", "+faststart", str(output),
    ]
    logger.info("render_start mode=%s frames=%d size=%dx%d fps=%s", request.mode, manifest.frame_count, width, height, fps)
    # FFmpeg stderr goes to a temp log file, never an unread PIPE: at 720p the
    # encoder's log output would fill a pipe buffer and deadlock the render.
    log_path = output.with_suffix(".ffmpeg.log")
    log_file = log_path.open("wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_file)
    frames_written = 0
    try:
        mask_iter = iter(loader.iter_masks(request.masks_dir))
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            try:
                _, mask = next(mask_iter)
            except StopIteration as exc:
                raise RenderingError(
                    f"Source has more frames than masks (frame {frames_written}); mask sequence is incomplete."
                ) from exc
            if request.mode == "blur_background":
                sigma = 5 + request.blur_strength * 45
                processed_bg = cv2.GaussianBlur(frame, (0, 0), sigmaX=sigma)
            else:
                processed_bg = background_image
            composited = _composite(frame, mask, processed_bg, request.feather_radius)
            try:
                proc.stdin.write(composited.tobytes())
            except BrokenPipeError as exc:
                raise RenderingError("FFmpeg encoder closed unexpectedly during rendering.") from exc
            frames_written += 1
        if frames_written == 0:
            raise RenderingError("Source video decoded zero frames (corrupt or unsupported source).")
        if frames_written != manifest.frame_count:
            raise RenderingError(
                f"Source decoded {frames_written} frames but mask manifest declares {manifest.frame_count}."
            )
    finally:
        capture.release()
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    return_code = proc.wait()
    log_file.close()
    if return_code != 0:
        stderr_tail = log_path.read_text(encoding="utf-8", errors="replace")[-400:] if log_path.is_file() else ""
        output.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise RenderingError(f"FFmpeg encoding failed: {stderr_tail.strip()}")
    log_path.unlink(missing_ok=True)

    if on_stage:
        on_stage("verifying")
    return verify_render_output(
        output, width=width, height=height, frame_count=manifest.frame_count,
        duration=manifest.frame_count / fps, expect_audio=bool(audio_codec),
        mode=request.mode, output_relative_path=request.output_relative_path,
    )
