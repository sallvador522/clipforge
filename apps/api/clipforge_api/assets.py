"""Project asset validation + SVG sanitization (P0).

Server-side only. Validates actual file content, never just extensions:
- video: existing ffprobe MVP limits (media.probe_video).
- audio: ffprobe audio stream + duration.
- images: magic bytes + Pillow decode.
- text: UTF-8 + size cap + SRT/VTT cue count.
- SVG: strict XML + allowlist sanitizer. Original preserved, sanitized copy
  served as image/svg+xml. Never executed.

No new dependencies: stdlib + Pillow (already installed) + ffprobe.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

from PIL import Image

from clipforge_api.media import UploadValidationError, probe_video
from clipforge_jobs.models import SourceInfo

MAX_ASSET_BYTES = 4 * 1024 * 1024 * 1024  # ADR-044: 15-min media; import buffers in memory, disk is the real bound
MAX_TEXT_BYTES = 1 * 1024 * 1024
MAX_SVG_BYTES = 2 * 1024 * 1024

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".srt", ".vtt"}
SVG_EXTENSIONS = {".svg"}

MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".srt": "text/plain",
    ".vtt": "text/vtt",
    ".svg": "image/svg+xml",
}


def mime_for_suffix(suffix: str) -> str:
    return MIME_BY_EXT.get(suffix.lower(), "application/octet-stream")


# -- audio ---------------------------------------------------------------------


def probe_audio_file(path: Path) -> dict:
    """Validate an audio file with ffprobe. Returns duration/codec/channels/rate."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,channels,sample_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise UploadValidationError("invalid_audio", "The uploaded file could not be read as audio.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise UploadValidationError("invalid_audio", "Audio probe returned invalid metadata.") from exc
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise UploadValidationError("no_audio_stream", "The uploaded file has no audio stream.")
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise UploadValidationError("invalid_audio", "The uploaded audio has no measurable duration.")
    if duration > 900:
        raise UploadValidationError("audio_too_long", f"Audio is {duration:.1f}s; the limit is 900s (15 min).")
    try:
        channels = int(audio.get("channels", 0) or 0)
    except (TypeError, ValueError):
        channels = 0
    return {
        "duration_seconds": duration,
        "audio_codec": str(audio.get("codec_name", "") or "")[:40] or None,
        "audio_channels": channels or None,
    }


# -- images --------------------------------------------------------------------


_IMAGE_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"RIFF", "webp"),
]


def probe_image(data: bytes) -> dict:
    """Validate image magic bytes + Pillow decode. Returns width/height."""
    if not data.startswith(tuple(m for m, _ in _IMAGE_MAGIC)):
        # WebP starts with RIFF....WEBP; check the WEBP marker explicitly.
        if not (data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP"):
            raise UploadValidationError("invalid_image", "The uploaded file is not a PNG, JPG or WebP image.")
    try:
        with Image.open(BytesIO(data)) as img:
            img.load()
            width, height = img.size
            fmt = (img.format or "").upper()
    except Exception as exc:
        raise UploadValidationError("invalid_image", "The uploaded image could not be decoded.") from exc
    if fmt not in {"PNG", "JPEG", "JPG", "WEBP", "MPO"}:
        raise UploadValidationError("invalid_image", f"Unsupported image format ({fmt or 'unknown'}); use PNG, JPG or WebP.")
    if width <= 0 or height <= 0 or width > 8192 or height > 8192:
        raise UploadValidationError("invalid_image", "Image dimensions are invalid or exceed 8192px.")
    return {"width": width, "height": height}


# -- text ----------------------------------------------------------------------


_CUE_RE = re.compile(r"-->")


def probe_text(data: bytes, suffix: str) -> dict:
    """Validate UTF-8 text. Returns line/cue counts for subtitles."""
    if len(data) > MAX_TEXT_BYTES:
        raise UploadValidationError("text_too_large", "Text files are limited to 1 MB.", status_code=413)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("invalid_text_encoding", "Text assets must be valid UTF-8.") from exc
    if "\x00" in text:
        raise UploadValidationError("invalid_text", "Text assets must not contain NUL bytes.")
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    cue_count: int | None = None
    if suffix in {".srt", ".vtt"}:
        cue_count = len(_CUE_RE.findall(text))
        if suffix == ".vtt" and not text.lstrip().startswith("WEBVTT"):
            raise UploadValidationError("invalid_subtitle", "VTT files must start with a WEBVTT header.")
        if cue_count == 0:
            raise UploadValidationError("invalid_subtitle", "No subtitle cues were found in this file.")
    return {"text_lines": lines, "cue_count": cue_count, "text_encoding": "utf-8"}


# -- SVG -----------------------------------------------------------------------


_ALLOWED_TAGS = {
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan", "defs", "lineargradient", "radialgradient",
    "stop", "use", "clippath", "mask", "pattern", "title", "desc", "metadata",
    "switch", "symbol", "marker", "view",
}
_ALLOWED_ATTRS = {
    "id", "class", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx",
    "ry", "width", "height", "d", "points", "viewbox", "preserveaspectratio",
    "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "fill-opacity",
    "opacity", "transform", "font-family", "font-size", "font-weight",
    "text-anchor", "offset", "stop-color", "stop-opacity", "gradientunits",
    "gradienttransform", "xlink:href", "href", "xmlns", "xmlns:xlink",
    "clip-path", "mask", "display", "visibility", "style", "dx", "dy",
    "rotate", "textlength", "lengthadjust",
}
_UNSAFE_URL_RE = re.compile(
    r"url\s*\(\s*(?!#)[^)]*\)|expression\s*\(|@import|javascript\s*:|data\s*:",
    re.IGNORECASE,
)
_UNSAFE_ATTR_VALUE_RE = re.compile(r"javascript\s*:|data\s*:(?!image/(png|jpeg|webp);base64,)", re.IGNORECASE)


def _local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def sanitize_svg(data: bytes) -> bytes:
    """Strict SVG sanitization. Raises UploadValidationError on any unsafe input.

    Rejects: DOCTYPE/ENTITY declarations, non-SVG roots, script/event handlers,
    foreignObject and other active elements, external references, unsafe CSS/URLs.
    Returns the sanitized SVG bytes (with xmlns preserved).
    """
    if len(data) > MAX_SVG_BYTES:
        raise UploadValidationError("svg_too_large", "SVG files are limited to 2 MB.", status_code=413)
    head = data[:4096].decode("latin-1")
    if "<!DOCTYPE" in head.upper() or "<!ENTITY" in head.upper():
        raise UploadValidationError("unsafe_svg", "SVG DOCTYPE and entity declarations are not allowed.")
    if b"\x00" in data:
        raise UploadValidationError("invalid_svg", "SVG files must be valid XML text.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("invalid_svg", "SVG files must be valid UTF-8.") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UploadValidationError("invalid_svg", "The SVG could not be parsed as XML.") from exc
    if _local_name(root.tag).lower() != "svg":
        raise UploadValidationError("invalid_svg", "The file is valid XML but its root element is not <svg>.")

    def _clean(elem: ET.Element) -> None:
        name = _local_name(elem.tag).lower()
        if name not in _ALLOWED_TAGS:
            raise UploadValidationError("unsafe_svg", f"SVG element <{name}> is not allowed.")
        # Attributes: strip namespaces for the allowlist check, reject events.
        for attr in list(elem.attrib.keys()):
            local = _local_name(attr).lower()
            # xlink:href arrives namespaced; normalize to href for the check.
            check = "href" if local == "href" else local
            if local.startswith("on") or check not in _ALLOWED_ATTRS:
                raise UploadValidationError("unsafe_svg", f"SVG attribute '{local}' is not allowed.")
            value = elem.attrib[attr]
            if _UNSAFE_ATTR_VALUE_RE.search(value or ""):
                raise UploadValidationError("unsafe_svg", "SVG contains an unsafe reference (javascript:/data:).")
            if check in {"href"}:
                v = (value or "").strip()
                if v and not (
                    v.startswith("#")
                    or v.startswith("data:image/png;base64,")
                    or v.startswith("data:image/jpeg;base64,")
                    or v.startswith("data:image/webp;base64,")
                ):
                    raise UploadValidationError("unsafe_svg", "SVG external references are not allowed.")
            if check == "style" and _UNSAFE_URL_RE.search(value or ""):
                raise UploadValidationError("unsafe_svg", "SVG inline styles must not load external resources.")
        # <style> element text must not load externals either.
        if name == "style":
            pass  # style is not in allowlist, unreachable; kept explicit.
        for child in list(elem):
            _clean(child)
        # Text content is kept; comments/PIs are dropped by ElementTree already.

    # Reject embedded <style> blocks entirely (allowlisted tags exclude style).
    for elem in root.iter():
        if _local_name(elem.tag).lower() == "style":
            raise UploadValidationError("unsafe_svg", "SVG <style> blocks are not allowed; use presentation attributes.")

    _clean(root)
    # Ensure the SVG namespace is explicit so <img> renders it standalone.
    if "xmlns" not in root.attrib and not root.tag.startswith("{"):
        root.set("xmlns", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def classify_suffix(suffix: str) -> str | None:
    s = suffix.lower()
    if s in VIDEO_EXTENSIONS:
        return "video"
    if s in AUDIO_EXTENSIONS:
        return "audio"
    if s in IMAGE_EXTENSIONS:
        return "image"
    if s in TEXT_EXTENSIONS:
        return "text"
    if s in SVG_EXTENSIONS:
        return "graphics"
    return None
