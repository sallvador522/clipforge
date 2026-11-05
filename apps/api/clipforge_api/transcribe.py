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
from clipforge_director import (
    LedgerIntegrityError,
    LedgerLockedError,
    LiveBudgetExceeded,
    LiveCallAuthorization,
    LiveCallBudget,
    LiveCallNotAuthorizedError,
)
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

# ADR-060 production source transcription: Meta caps one file request at
# 10 min / 32 MB, so job audio is split into safety-margin blocks.
TRANSCRIPT_BLOCK_SECONDS = 570.0  # 9.5 min: under the 10-min cap with headroom
TRANSCRIPT_BLOCK_MAX_BYTES = 27 * 1024 * 1024  # 570 s mono 16-bit 24 kHz ~ 27.4 MB… verified per block below
META_ASR_USD_PER_SECOND = 0.00005  # $0.18/audio-hour, billed per whole second processed


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
    budget: LiveCallBudget | None = None,
    asr_mode: str = "PUSH_TO_TALK",
) -> tuple[TranscriptResult, str]:
    """Validate, convert (temp), and transcribe exactly once. Returns (result, transcribe_mode)."""
    if asr_mode not in ("PUSH_TO_TALK", "ENDPOINTING"):
        raise AudioValidationError(
            "unsupported_asr_mode",
            "Transcription mode must be PUSH_TO_TALK or ENDPOINTING.",
            status_code=422,
        )
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
    if mode == "live" and budget is None:
        raise AudioValidationError(
            "live_budget_not_configured",
            "Live transcription requires the live-call budget ledger. No request was attempted.",
            status_code=503,
        )

    session_log_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="clipforge-asr-") as tmp:
        source = Path(tmp) / f"upload{suffix}"
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
            authorization = LiveCallAuthorization(budget, "transcription") if budget is not None else None
            try:
                result = providers.transcription.transcribe_audio(
                    wav_path, language_bias=LANGUAGE_BIAS, mode=asr_mode, authorization=authorization
                )
            except LiveBudgetExceeded as exc:
                raise AudioValidationError("live_budget_exhausted", str(exc), status_code=429) from exc
            except LedgerIntegrityError as exc:
                raise AudioValidationError("live_budget_integrity_error", str(exc), status_code=503) from exc
            except LedgerLockedError as exc:
                raise AudioValidationError("live_budget_locked", str(exc), status_code=503) from exc
            except LiveCallNotAuthorizedError as exc:
                raise AudioValidationError("live_budget_not_authorized", str(exc), status_code=503) from exc
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


def estimate_source_transcript(duration_seconds: float) -> dict:
    """Cost blocks for transcribing a job's full audio. No network, no cost.

    Billed per whole second processed, estimated conservatively with ceil per
    block (Meta rounds down; the estimate never understates).
    """
    import math

    total = max(0.0, float(duration_seconds))
    blocks = max(1, math.ceil(total / TRANSCRIPT_BLOCK_SECONDS)) if total > 0 else 0
    billed = 0
    for i in range(blocks):
        start = i * TRANSCRIPT_BLOCK_SECONDS
        billed += math.ceil(min(TRANSCRIPT_BLOCK_SECONDS, total - start))
    return {
        "blocks": blocks,
        "audio_seconds": round(total, 1),
        "billed_seconds": billed,
        "estimated_usd": round(billed * META_ASR_USD_PER_SECOND, 6),
    }


def split_wav(path: Path, out_dir: Path, block_seconds: float = TRANSCRIPT_BLOCK_SECONDS) -> list[tuple[Path, int]]:
    """Split a WAV into sequential blocks. Returns [(block_path, offset_ms)]."""
    import math

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        duration = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
    except (json.JSONDecodeError, TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise AudioValidationError("invalid_audio", "The converted audio has no measurable duration.")
    out_dir.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[Path, int]] = []
    n = max(1, math.ceil(duration / block_seconds))
    for i in range(n):
        start = i * block_seconds
        length = min(block_seconds, duration - start)
        if length <= 0:
            break
        dest = out_dir / f"block_{i:03d}.wav"
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
             "-i", str(path), "-c:a", "pcm_s16le", str(dest)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
            raise AudioValidationError(
                "transcription_split_failed", f"Audio block {i + 1}/{n} could not be extracted.")
        if dest.stat().st_size > 32 * 1024 * 1024:
            raise AudioValidationError(
                "transcription_block_too_large", f"Audio block {i + 1}/{n} exceeds the provider file cap.")
        parts.append((dest, int(round(start * 1000))))
    if not parts:
        raise AudioValidationError("invalid_audio", "No audio blocks could be extracted.")
    return parts


def join_transcript_blocks(
    results: list[tuple["TranscriptResult", int]],
) -> "TranscriptResult":
    """Join per-block transcripts with millisecond offsets. Turns are reindexed
    sequentially (turn_id is per-response opaque); text is concatenated."""
    from clipforge_contracts import TranscriptResult as _TranscriptResult
    from clipforge_contracts import TranscriptTurn as _TranscriptTurn

    texts: list[str] = []
    turns: list[_TranscriptTurn] = []
    next_id = 0
    for result, offset_ms in results:
        text = (result.text or "").strip()
        if text:
            texts.append(text)
        for turn in result.turns or []:
            turns.append(_TranscriptTurn(
                turn_id=next_id,
                start_ms=int(turn.start_ms) + offset_ms,
                end_ms=int(turn.end_ms) + offset_ms,
                text=turn.text,
                speaker=getattr(turn, "speaker", None),
            ))
            next_id += 1
    if not texts:
        raise AudioValidationError("transcription_failed", "Transcription returned no text.")
    first = results[0][0]
    return _TranscriptResult(
        text=" ".join(texts),
        turns=turns,
        language=first.language,
        provider_name=first.provider_name,
        is_mock=any(r.is_mock for r, _ in results),
    )


def transcribe_source_blocks(
    *,
    wav_path: Path,
    duration_seconds: float,
    providers,
    budget: "LiveCallBudget | None",
    block_seconds: float = TRANSCRIPT_BLOCK_SECONDS,
    language_bias: tuple[str, ...] = LANGUAGE_BIAS,
) -> "TranscriptResult":
    """Transcribe a full-length WAV in provider-capped blocks and join.

    Live: one one-shot budget authorization per block (fail-closed, no
    retries); any block failure aborts with NO partial transcript presented
    as complete. Mock: deterministic labelled fixture, zero cost.
    """
    from clipforge_director import LiveCallAuthorization

    mode = getattr(providers, "transcription_mode", "mock")
    parts = split_wav(wav_path, wav_path.parent / "blocks", block_seconds)
    results: list[tuple[TranscriptResult, int]] = []
    try:
        for index, (block_path, offset_ms) in enumerate(parts):
            if mode == "mock":
                from clipforge_contracts import TranscriptResult as _TR

                results.append((_TR(
                    text=f"[simulação] transcrição do áudio (bloco {index + 1}/{len(parts)})",
                    language="pt-BR",
                    provider_name="mock",
                    is_mock=True,
                ), offset_ms))
                continue
            if budget is None:
                raise AudioValidationError(
                    "live_budget_not_configured",
                    "Live transcription requires the live-call budget ledger. No request was attempted.",
                    status_code=503,
                )
            authorization = LiveCallAuthorization(budget, "transcription")
            try:
                result = providers.transcription.transcribe_audio(
                    block_path, language_bias=language_bias,
                    mode="ENDPOINTING", authorization=authorization,
                )
            except TranscriptionTimeoutError as exc:
                raise AudioValidationError(
                    "transcription_timeout", f"Bloco {index + 1}/{len(parts)} excedeu o tempo: {exc}.",
                    status_code=504) from exc
            except TranscriptionRateLimitedError as exc:
                raise AudioValidationError(
                    "transcription_rate_limited", f"Bloco {index + 1}/{len(parts)} limitado: {exc}.",
                    status_code=429) from exc
            except (InvalidAudioError, TranscriptionAPIError, TranscriptionError) as exc:
                raise AudioValidationError(
                    "transcription_failed", f"Bloco {index + 1}/{len(parts)} falhou: {exc}.",
                    status_code=502) from exc
            results.append((result, offset_ms))
    finally:
        import shutil as _shutil

        _shutil.rmtree(wav_path.parent / "blocks", ignore_errors=True)
    return join_transcript_blocks(results)


def convert_to_wav_window(source: Path, target: Path, start_s: float, length_s: float) -> None:
    """Extract [start_s, start_s+length_s) and convert to mono 16-bit PCM WAV
    24 kHz, then verify the actual output. Used for trecho-scoped work."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{max(0.0, start_s):.3f}", "-t", f"{max(0.1, length_s):.3f}",
         "-i", str(source), "-vn",
         "-ac", "1", "-ar", str(TARGET_SAMPLE_RATE), "-c:a", "pcm_s16le",
         "-map_metadata", "-1", str(target)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise AudioValidationError("conversion_failed", "Audio window extraction failed.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,channels,sample_rate,sample_fmt",
         "-of", "json", str(target)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        stream = json.loads(probe.stdout)["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise AudioValidationError("conversion_failed", "Converted window could not be verified.") from exc
    if (
        stream.get("codec_name") != "pcm_s16le"
        or int(stream.get("channels", 0)) != 1
        or int(stream.get("sample_rate", 0)) != TARGET_SAMPLE_RATE
    ):
        raise AudioValidationError("conversion_failed", "Converted window is not mono 16-bit PCM 24 kHz WAV.")


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioValidationError(
            "ffmpeg_missing", "FFmpeg/ffprobe are required for audio conversion but were not found.", 503
        )
