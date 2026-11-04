"""Post-MVP multitrack composition (ADR-044).

Composes an explicit user Timeline into one verified MP4 with real
FFmpeg/OpenCV — never mocked. Video: z-order V2 over V1, letterboxed onto a
fixed 1280x720 canvas at 30 FPS, frame-accurate sequential reads (no
imprecise seeking). Audio: every sounding clip (video clips with audio plus
A1/A2) mixed with per-clip delay (A1+A2 mix, user decision). Memory stays
bounded: at most one open decoder per track plus one output frame.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from clipforge_contracts import ClipTextOverlay, ColourGrade, Timeline
from clipforge_worker.renderer import RenderingError, verify_render_output

logger = logging.getLogger("clipforge.timeline_render")

CANVAS_W = 1280
CANVAS_H = 720
CANVAS_FPS = 30.0

#: ADR-047 entrance/exit choreography burned into the export. The Studio
#: preview plays richer per-style anime.js motion; the MP4 carries a fade +
#: rise that is identical for every style. The mapping is stated in the UI.
TEXT_FADE_MS = 240
TEXT_RISE_PX = 26

_FONT_CACHE: dict[tuple[int, bool], object] = {}


def _load_font(size_px: int, bold: bool):
    """Arial when available (Windows/macOS), else PIL's built-in bitmap font."""
    key = (size_px, bold)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    candidates = (
        ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ARIALNB.TTF"]
        if bold
        else ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/ARIALN.TTF"]
    ) + [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font = None
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size_px)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size=size_px)
    _FONT_CACHE[key] = font
    return font


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


#: ADR-049 caption band cover: the bottom band where burned-in subtitles
#: live (same geometry our captions use). Fixed geometry, never model-drawn.
COVER_BAND_TOP = 0.72


def verify_caption_legibility(video_path: str | Path, texts: list[ClipTextOverlay] | None,
                              fps: float) -> list[dict]:
    """ADR-051 Muse analyse-and-redo gate: one sampled frame per overlay.

    For every overlay, grabs the mid-window frame and checks that (a) bright
    caption pixels exist in the caption band and (b) the text block bounding
    box sits inside the frame margins. Returns failure dicts (empty = pass).
    Pure read-only QA over a real file — never invents a pass.
    """
    import cv2 as _cv2

    failures: list[dict] = []
    if not texts:
        return failures
    cap = _cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return [{"overlay_id": t.overlay_id, "reason": "unreadable_video"} for t in texts]
    try:
        width = int(cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
        band_top = int(height * COVER_BAND_TOP)
        for overlay in texts:
            mid_s = overlay.start_s + overlay.duration_s / 2.0
            cap.set(_cv2.CAP_PROP_POS_MSEC, mid_s * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                failures.append({"overlay_id": overlay.overlay_id, "reason": "missing_frame"})
                continue
            gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
            band = gray[band_top:, :]
            bright_ratio = float((band > 200).mean())
            if bright_ratio < 0.0005:
                failures.append({"overlay_id": overlay.overlay_id,
                                 "reason": "no_caption_pixels_in_band"})
                continue
            _, bw = _cv2.threshold(band, 200, 255, _cv2.THRESH_BINARY)
            n, _, stats, centroids = _cv2.connectedComponentsWithStats(bw, 8)
            min_blob = max(4, (width * height) // 15000)
            big = [(stats[i, 4], centroids[i]) for i in range(1, n) if stats[i, 4] >= min_blob]
            if not big:
                failures.append({"overlay_id": overlay.overlay_id,
                                 "reason": "no_text_blobs_in_band"})
                continue
            xs = [c[0] for _, c in big]
            if min(xs) < width * 0.005 or max(xs) > width * 0.995:
                failures.append({"overlay_id": overlay.overlay_id,
                                 "reason": "text_touches_frame_edge"})
    finally:
        cap.release()
    return failures


def apply_caption_cover(frame_bgr: np.ndarray) -> np.ndarray:
    """Blur the caption band to hide pre-existing burned-in subtitles.

    Fixed geometry; call only when the user explicitly enabled the cover
    (caption_cover on the job). Local OpenCV, never AI.
    """
    h, w = frame_bgr.shape[:2]
    y0 = int(h * COVER_BAND_TOP)
    band = frame_bgr[y0:, :]
    k = 31 if min(band.shape[:2]) >= 31 else (min(band.shape[:2]) // 2 * 2 + 1)
    frame_bgr[y0:, :] = cv2.GaussianBlur(band, (k, k), 0)
    return frame_bgr


def apply_colour_grade(frame_bgr: np.ndarray, grade: ColourGrade | None) -> np.ndarray:
    """ADR-047 local contrast/brightness/saturation. Identity is a no-op."""
    if grade is None or grade.is_identity():
        return frame_bgr
    graded = cv2.convertScaleAbs(frame_bgr, alpha=grade.contrast, beta=grade.brightness * 255.0)
    if grade.saturation != 1.0:
        hsv = cv2.cvtColor(graded, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * grade.saturation, 0, 255)
        graded = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return graded


def _overlay_alpha_ms(overlay: ClipTextOverlay, t_ms: int) -> tuple[float, float]:
    """(opacity 0..1, rise progress 0..1) for the frame timestamp."""
    start_ms = int(round(overlay.start_s * 1000))
    total_ms = int(round(overlay.duration_s * 1000))
    end_ms = start_ms + total_ms
    if t_ms < start_ms or t_ms >= end_ms:
        return 0.0, 1.0
    fade = min(TEXT_FADE_MS, max(60, total_ms // 4))
    elapsed = t_ms - start_ms
    remaining = end_ms - t_ms
    opacity = min(1.0, elapsed / fade, remaining / fade)
    enter = min(TEXT_FADE_MS * 2, max(200, total_ms - 120))
    rise = min(1.0, elapsed / enter)
    return max(0.0, opacity), min(1.0, rise)


def _measure(text: str, font) -> tuple[int, int]:
    """Text bounding box in pixels (left/top-inclusive width/height)."""
    box = ImageDraw.Draw(Image.new("RGBA", (8, 8))).textbbox((0, 0), text, font=font)
    return max(1, box[2] - box[0]), max(1, box[3] - box[1])


def _fit_overlay_lines(text: str, max_width_px: int, base_px: int, bold: bool,
                       max_lines: int = 4) -> tuple[list[str], object]:
    """Greedy word-wrap + shrink so every line fits max_width_px.

    Returns the lines and the font that renders them. Font size only ever
    shrinks from base_px (never below 12 px); words longer than the width
    are hard-cut. Pure function — the same inputs always fit the same way.
    """
    words = text.split() or [""]
    size_px = base_px
    while size_px >= 12:
        font = _load_font(size_px, bold)
        lines: list[str] = []
        current = ""
        overflow = False
        for word in words:
            trial = (current + " " + word).strip()
            width, _ = _measure(trial, font)
            if width <= max_width_px or not current:
                if width > max_width_px and not current:
                    # Single word wider than the canvas: hard-cut it.
                    cut = word
                    while cut:
                        chunk, rest = cut[:24], cut[24:]
                        lines.append(chunk)
                        cut = rest
                        if len(lines) >= max_lines:
                            overflow = True
                            break
                    current = ""
                    if overflow:
                        break
                    continue
                current = trial
            else:
                lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    overflow = True
                    break
        if not overflow and current:
            lines.append(current)
        if overflow or len(lines) > max_lines:
            size_px -= 2
            continue
        widths = [_measure(line, font)[0] for line in lines]
        if widths and max(widths) <= max_width_px:
            return [line[:140] for line in lines], font
        size_px -= 2
    font = _load_font(12, bold)
    return [text[:140]], font


def draw_text_overlays(
    frame_bgr: np.ndarray,
    texts: list[ClipTextOverlay] | None,
    t: float,
) -> np.ndarray:
    """Burn the active overlays into a BGR canvas frame. Pure function of
    (frame, texts, t): the same inputs always produce the same pixels.

    ADR-051 fit guarantee: every line is wrapped and shrunk to fit inside
    the frame (max 92% width, block bottom at most 97% height), so a long
    caption can never render cut off.
    """
    if not texts:
        return frame_bgr
    t_ms = int(round(t * 1000))
    active = [o for o in texts if o.start_s * 1000 <= t_ms < (o.start_s + o.duration_s) * 1000]
    if not active:
        return frame_bgr
    canvas = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    base_px = max(12, int(round(52 * canvas.height / 720)))
    for overlay in active:
        opacity, rise = _overlay_alpha_ms(overlay, t_ms)
        if opacity <= 0.0:
            continue
        size_px = max(12, int(round(base_px * overlay.scale)))
        lines, font = _fit_overlay_lines(overlay.text, int(canvas.width * 0.92), size_px,
                                         overlay.weight == "bold")
        line_sizes = [_measure(line, font) for line in lines]
        block_h = sum(h for _, h in line_sizes) + 6 * (len(lines) - 1)
        max_bottom = int(canvas.height * 0.97)
        cy = min(overlay.y * canvas.height, max_bottom - block_h / 2)
        cy = max(block_h / 2 + 2, cy) + (1.0 - rise) * TEXT_RISE_PX
        r, g, b = _hex_to_rgb(overlay.color)
        top = cy - block_h / 2
        for (line, (lw, lh)) in zip(lines, line_sizes):
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer_draw = ImageDraw.Draw(layer)
            layer_draw.text(
                (overlay.x * canvas.width, top + lh / 2),
                line,
                font=font,
                fill=(r, g, b, 255),
                anchor="mm",
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255),
            )
            top += lh + 6
            if opacity < 1.0:
                alpha = layer.split()[3].point(lambda v: int(v * opacity))
                layer.putalpha(alpha)
            canvas = Image.alpha_composite(canvas, layer)
    return cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)


@dataclass(frozen=True)
class TimelineMedia:
    """Resolved asset file for one timeline clip."""

    path: Path
    kind: str  # "video" | "audio"
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False


def _letterbox(frame: np.ndarray, canvas_w: int = CANVAS_W, canvas_h: int = CANVAS_H) -> np.ndarray:
    """Fit a BGR frame inside the canvas, black bars, no distortion."""
    h, w = frame.shape[:2]
    scale = min(canvas_w / w, canvas_h / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)
    y0, x0 = (canvas_h - nh) // 2, (canvas_w - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = resized
    return canvas


class _ClipReader:
    """Sequential frame source for one placed clip. Opens on first use and
    advances monotonically — never seeks, so timestamps stay exact."""

    def __init__(self, media: TimelineMedia, source_in_s: float) -> None:
        self._cap = cv2.VideoCapture(str(media.path))
        if not self._cap.isOpened():
            raise RenderingError(f"Timeline source could not be decoded: {media.path.name}")
        self._fps = media.fps or CANVAS_FPS
        self._consumed = 0
        self._current: np.ndarray | None = None
        self._advance_to(source_in_s)

    def _advance_to(self, t: float) -> None:
        target = int(t * self._fps)
        while self._consumed < target:
            if not self._cap.read()[0]:
                break
            self._consumed += 1
        ok, frame = self._cap.read()
        if not ok:
            raise RenderingError("Timeline source ended before the placed clip range.")
        self._consumed += 1
        self._current = frame

    def frame_at(self, t: float) -> np.ndarray:
        while (self._consumed + 1) / self._fps <= t + 1e-9:
            ok, frame = self._cap.read()
            if not ok:
                raise RenderingError("Timeline source ended before the placed clip range.")
            self._consumed += 1
            self._current = frame
        assert self._current is not None
        return self._current

    def close(self) -> None:
        self._cap.release()


def _primary_source_dims(timeline, resolve_asset) -> tuple[int, int, float] | None:
    """Primary video source dimensions + fps (first V2 clip, else first V1).

    ADR-051: the composition preserves the original format by default instead
    of forcing everything into a fixed landscape canvas. Returns None when the
    program has no video track (audio-only uses the fixed fallback canvas).
    """
    from clipforge_contracts import VIDEO_TRACKS

    for track in ("V2", "V1"):
        if track not in VIDEO_TRACKS:
            continue
        clips = sorted(
            (c for c in timeline.clips if c.track == track),
            key=lambda c: c.timeline_start_s,
        )
        if not clips:
            continue
        try:
            media = resolve_asset(clips[0].asset_id)
        except Exception:
            continue
        if media.kind == "video" and media.width > 0 and media.height > 0:
            return media.width, media.height, float(media.fps or 0.0)
    return None


def compose_timeline(
    timeline: Timeline,
    resolve_asset,
    output_path: str | Path,
    output_relative_path: str,
    on_stage=None,
    texts: list[ClipTextOverlay] | None = None,
    colour: ColourGrade | None = None,
    caption_cover: bool = False,
    canvas: tuple[int, int] | None = None,
    fps: float | None = None,
) -> object:
    """Compose the program. resolve_asset(asset_id) -> TimelineMedia.

    ADR-047: `texts` burns persisted clip overlays into every frame where
    they are active; `colour` grades every frame first. ADR-049:
    `caption_cover` blurs the fixed caption band before burn-in to hide
    pre-existing burned-in subtitles. ADR-051: `canvas`/`fps` default to the
    primary source (first V2 else V1 video) so portrait stays portrait —
    explicit (1280, 720)/(720, 1280) only when the user chooses another
    format. All real OpenCV/PIL operations, verified like the rest of the
    composition.
    """
    from clipforge_contracts import TimelineClip

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    program_s = timeline.program_duration_s()
    if program_s <= 0 or not timeline.clips:
        raise RenderingError("Timeline is empty; nothing to compose.")

    out_w, out_h, out_fps = CANVAS_W, CANVAS_H, CANVAS_FPS
    if canvas is None or fps is None:
        primary = _primary_source_dims(timeline, resolve_asset)
        if primary is not None:
            if canvas is None:
                out_w, out_h = primary[0], primary[1]
            if fps is None and primary[2] > 0:
                out_fps = primary[2]
    if canvas is not None:
        out_w, out_h = int(canvas[0]), int(canvas[1])
    if fps is not None:
        out_fps = float(fps)
    if out_w <= 0 or out_h <= 0 or out_fps <= 0:
        raise RenderingError("Invalid composition canvas.")
    total_frames = max(1, round(program_s * out_fps))

    video_tracks = ("V2", "V1")  # topmost first
    by_track: dict[str, list[TimelineClip]] = {}
    for clip in timeline.clips:
        by_track.setdefault(clip.track, []).append(clip)
    for clips in by_track.values():
        clips.sort(key=lambda c: c.timeline_start_s)

    def active_on(track: str, t: float) -> TimelineClip | None:
        for clip in by_track.get(track, []):
            if clip.timeline_start_s - 1e-9 <= t < clip.timeline_end_s - 1e-9:
                return clip
        return None

    audio_segments: list[tuple[TimelineMedia, float, float, float]] = []
    seen_audio: set[str] = set()
    for clip in timeline.clips:
        media = resolve_asset(clip.asset_id)
        if media.kind == "video" and media.has_audio and clip.clip_id not in seen_audio:
            seen_audio.add(clip.clip_id)
            audio_segments.append((media, clip.timeline_start_s, clip.duration_s, clip.source_in_s))
        elif media.kind == "audio":
            audio_segments.append((media, clip.timeline_start_s, clip.duration_s, clip.source_in_s))

    # Video pipe first, then one seeked audio input per sounding clip.
    # -r accepts fractional rates (e.g. 25 fps sources stay 25 fps).
    cmd: list[str] = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{out_w}x{out_h}",
        "-r", str(out_fps), "-i", "-",
    ]
    filter_parts: list[str] = []
    for i, (media, offset, dur, ss) in enumerate(audio_segments):
        cmd += ["-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-vn", "-i", str(media.path)]
        ms = max(0, round(offset * 1000))
        filter_parts.append(f"[{i + 1}:a]aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{i}]")
    if audio_segments:
        labels = "".join(f"[a{i}]" for i in range(len(audio_segments)))
        filter_parts.append(f"{labels}amix=inputs={len(audio_segments)}:duration=longest[aout]")
        cmd += ["-filter_complex", ",".join(filter_parts)]
        cmd += ["-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-map", "0:v:0", "-an"]
    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(out_fps),
        "-movflags", "+faststart", str(output),
    ]

    log_path = output.with_suffix(".ffmpeg.log")
    log_file = log_path.open("wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_file)
    readers: dict[str, _ClipReader] = {}
    try:
        if on_stage:
            on_stage("composing")
        frames_written = 0
        black = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        for n in range(total_frames):
            t = n / out_fps
            chosen = None
            for track in video_tracks:
                chosen = active_on(track, t)
                if chosen is not None:
                    break
            if chosen is None:
                frame = black.copy()
            else:
                reader = readers.get(chosen.clip_id)
                if reader is None:
                    media = resolve_asset(chosen.asset_id)
                    reader = _ClipReader(media, chosen.source_in_s + (t - chosen.timeline_start_s))
                    readers[chosen.clip_id] = reader
                # Release readers whose clip is no longer active on any video track.
                for cid in [c for c in readers if c != chosen.clip_id]:
                    other = next((c for c in timeline.clips if c.clip_id == cid), None)
                    if other is None or not (other.timeline_start_s - 1e-9 <= t < other.timeline_end_s - 1e-9):
                        readers.pop(cid).close()
                frame = _letterbox(reader.frame_at(chosen.source_in_s + (t - chosen.timeline_start_s)), out_w, out_h)
            # ADR-047 grade + text apply to every program frame, including gaps.
            # ADR-049 cover applies before burn-in so our captions stay sharp.
            frame = apply_colour_grade(frame, colour)
            if caption_cover:
                frame = apply_caption_cover(frame)
            frame = draw_text_overlays(frame, texts, t)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError as exc:
                raise RenderingError("FFmpeg encoder closed unexpectedly during timeline composition.") from exc
            frames_written += 1
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    finally:
        for reader in readers.values():
            try:
                reader.close()
            except Exception:
                pass
    return_code = proc.wait()
    log_file.close()
    if return_code != 0:
        stderr_tail = log_path.read_text(encoding="utf-8", errors="replace")[-400:] if log_path.is_file() else ""
        output.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        raise RenderingError(f"Timeline FFmpeg encoding failed: {stderr_tail.strip()}")
    log_path.unlink(missing_ok=True)

    if on_stage:
        on_stage("verifying")
    return verify_render_output(
        output, width=out_w, height=out_h, frame_count=frames_written,
        duration=frames_written / out_fps, expect_audio=bool(audio_segments),
        mode="timeline_assemble", output_relative_path=output_relative_path,
    )
