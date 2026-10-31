"""Voice transcription API (Milestone 6A).

Receives the browser's real recording, validates it, converts it to the format
required by Muse Voice Transcribe (mono 16-bit PCM WAV, 24 kHz) with FFmpeg,
and calls the configured transcription provider exactly once.

Mock mode (default) never interprets audio: it requires an explicit mock
fixture and returns a clearly labelled simulated transcript. Live transcription
is enabled only via CLIPFORGE_TRANSCRIBE_MODE=live + MODEL_API_KEY, and this
module performs no automatic retries of billable requests.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from clipforge_contracts import TranscriptResult
from clipforge_providers import (
    InvalidAudioError,
    MissingCredentialsError,
    TranscriptionAPIError,
    TranscriptionError,
    TranscriptionRateLimitedError,
    TranscriptionTimeoutError,
)

logger = logging.getLogger("clipforge.transcription")

AUDIO_EXTENSIONS = {".webm", ".ogg", ".oga", ".wav", ".m4a", ".mp4", ".mp3"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # well below Meta's 32 MB body cap; recordings are seconds
MAX_AUDIO_SECONDS = 60.0
TARGET_SAMPLE_RATE = 24_000
LANGUAGE_BIAS = ("Portuguese",)


class AudioValidationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def probe_audio(path: Path) -> float:
    """Return duration if the file has a valid audio stream. Raises AudioValidationError."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,duration",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise AudioValidationError("invalid_audio", "The uploaded file could not be read as audio.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AudioValidationError("invalid_audio", "Audio probe returned invalid metadata.") from exc
    if not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise AudioValidationError("no_audio_stream", "The uploaded file has no audio stream.")
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise AudioValidationError("invalid_audio", "The uploaded audio has no measurable duration.")
    if duration > MAX_AUDIO_SECONDS:
        raise AudioValidationError("audio_too_long", f"Audio is {duration:.1f}s; the limit is {MAX_AUDIO_SECONDS:.0f}s.")
    return duration


def convert_to_wav(source: Path, target: Path) -> None:
    """FFmpeg conversion to mono 16-bit PCM WAV at 24 kHz, then verify the actual output."""
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(source), "-vn",
            "-ac", "1", "-ar", str(TARGET_SAMPLE_RATE), "-c:a", "pcm_s16le",
            "-map_metadata", "-1", str(target),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise AudioValidationError("conversion_failed", "Audio conversion failed; the recording may be corrupt.")
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,channels,sample_rate,sample_fmt",
            "-of", "json", str(target),
        ],
        capture_output=True, text=True, timeout=30,
    )
    try:
        stream = json.loads(probe.stdout)["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise AudioValidationError("conversion_failed", "Converted audio could not be verified.") from exc
    if (
        stream.get("codec_name") != "pcm_s16le"
        or int(stream.get("channels", 0)) != 1
        or int(stream.get("sample_rate", 0)) != TARGET_SAMPLE_RATE
    ):
        raise AudioValidationError(
            "conversion_failed",
            f"Converted audio is not mono 16-bit PCM {TARGET_SAMPLE_RATE} Hz WAV "
            f"(got {stream.get('codec_name')}, {stream.get('channels')}ch, {stream.get('sample_rate')} Hz).",
        )


def transcribe_upload(
    upload_bytes: bytes,
    filename: str,
    *,
    providers,
    mock_fixture_id: str | None,
) -> tuple[TranscriptResult, str]:
    """Validate, convert (temp), and transcribe exactly once. Returns (result, transcribe_mode)."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise AudioValidationError(
            "unsupported_audio_extension",
            f"Extension {suffix or '(none)'} is not accepted; use {sorted(AUDIO_EXTENSIONS)}.",
        )
    if not upload_bytes:
        raise AudioValidationError("empty_audio", "The uploaded recording is empty.", status_code=400)
    if len(upload_bytes) > MAX_AUDIO_BYTES:
        raise AudioValidationError("audio_too_large", "The recording exceeds the size limit.", status_code=413)

    mode = getattr(providers, "transcription_mode", "mock")
    if mode == "mock" and not mock_fixture_id:
        raise AudioValidationError(
            "mock_fixture_required",
            "Mock transcription cannot interpret audio. Select a mock command so the simulated transcript is explicit.",
        )

    session_log_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="clipforge-asr-") as tmp:
        source = Path(tmp) / f"recording{suffix}"
        source.write_bytes(upload_bytes)
        duration = probe_audio(source)
        wav_path = Path(tmp) / "recording.wav"
        convert_to_wav(source, wav_path)
        logger.info(
            "audio_prepared request=%s mode=%s duration=%.2fs wav_bytes=%d",
            session_log_id, mode, duration, wav_path.stat().st_size,
        )

        if mode == "mock":
            # Audio is deliberately NOT interpreted in mock mode; the transcript is the
            # explicitly selected fixture and is labelled simulated end-to-end.
            result = providers.transcription.transcribe(mock_fixture_id or "")
        else:
            try:
                result = providers.transcription.transcribe_audio(wav_path, language_bias=LANGUAGE_BIAS)
            except TranscriptionTimeoutError as exc:
                raise AudioValidationError("transcription_timeout", str(exc), status_code=504) from exc
            except TranscriptionRateLimitedError as exc:
                raise AudioValidationError("transcription_rate_limited", str(exc), status_code=429) from exc
            except InvalidAudioError as exc:
                raise AudioValidationError("invalid_audio", str(exc), status_code=422) from exc
            except MissingCredentialsError as exc:
                raise AudioValidationError("transcription_not_configured", str(exc), status_code=503) from exc
            except TranscriptionAPIError as exc:
                raise AudioValidationError("transcription_failed", str(exc), status_code=502) from exc
            except TranscriptionError as exc:
                raise AudioValidationError("transcription_failed", str(exc), status_code=502) from exc
    # Temporary audio (source and converted WAV) is deleted when the context exits.
    return result, mode


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioValidationError(
            "ffmpeg_missing", "FFmpeg/ffprobe are required for audio conversion but were not found.", 503
        )
