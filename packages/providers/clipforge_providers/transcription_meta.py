"""Meta Muse Voice Transcribe provider (Milestone 6A).

Official configuration verified against:
- https://dev.meta.ai/docs/speech-to-text
- https://dev.meta.ai/docs/api-reference/voice/transcribe
- https://dev.meta.ai/docs/pricing-rate-limits

Facts implemented here (as documented): model `muse-voice-transcribe-1.0`,
`POST https://api.meta.ai/v1/asr/transcribe`, Bearer auth, multipart with a
`request` JSON part and an `audio` WAV part, request fields `model`,
`audioEncoding: "WAV"`, `mode: "PUSH_TO_TALK"`, `languageBias: ["Portuguese"]`,
optional `sessionId` query parameter, JSON response `{sessionId, transcript,
audioDurationMs, turns}`. Audio must be mono 16-bit PCM WAV at 16 or 24 kHz
(the caller converts; this provider rejects anything else by contract).

No automatic retries: exactly one HTTP request per call. Credentials and raw
audio are never logged.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Sequence

import httpx

from clipforge_contracts import TranscriptResult
from clipforge_director.ledger import LiveCallAuthorization, LiveCallNotAuthorizedError

logger = logging.getLogger("clipforge.providers.transcription")

DEFAULT_BASE_URL = "https://api.meta.ai"
TRANSCRIBE_PATH = "/v1/asr/transcribe"
DEFAULT_MODEL = "muse-voice-transcribe-1.0"
DEFAULT_LANGUAGE_BIAS: tuple[str, ...] = ("Portuguese",)
DEFAULT_TIMEOUT_SECONDS = 30.0


class TranscriptionError(Exception):
    """Base class for transcription failures."""


class MissingCredentialsError(TranscriptionError):
    """MODEL_API_KEY is required for live transcription."""


class InvalidAudioError(TranscriptionError):
    """Audio is not a supported mono 16-bit PCM WAV at 16/24 kHz."""


class TranscriptionTimeoutError(TranscriptionError):
    """The request timed out. No retry is attempted."""


class TranscriptionRateLimitedError(TranscriptionError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TranscriptionAPIError(TranscriptionError):
    def __init__(self, status_code: int, message: str, error_type: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


def _wav_format(path: Path) -> tuple[int, int, int]:
    """Return (audio_format, channels, sample_rate) from the WAV fmt chunk."""
    with path.open("rb") as fh:
        header = fh.read(44)
    if len(header) < 44 or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise InvalidAudioError("Audio is not a RIFF/WAVE file.")
    audio_format = int.from_bytes(header[20:22], "little")
    channels = int.from_bytes(header[22:24], "little")
    sample_rate = int.from_bytes(header[24:28], "little")
    bits = int.from_bytes(header[34:36], "little")
    if audio_format != 1 or bits != 16:
        raise InvalidAudioError("Audio must be 16-bit integer PCM.")
    if channels != 1:
        raise InvalidAudioError("Audio must be mono.")
    if sample_rate not in (16000, 24000):
        raise InvalidAudioError("Audio must be 16 kHz or 24 kHz.")
    return audio_format, channels, sample_rate


class MetaVoiceTranscriptionProvider:
    """TranscriptionProvider adapter for the hosted Muse Voice Transcribe model."""

    provider_name = "meta-muse-voice-transcribe"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise MissingCredentialsError(
                "MODEL_API_KEY is required for live transcription. Set it server-side; it is never sent to the browser."
            )
        self._api_key = api_key.strip()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
            follow_redirects=False,
        )
        self._base_url = base_url

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def transcribe(self, audio_fixture_id: str) -> TranscriptResult:
        raise ValueError("Fixtures are mock-only; live transcription takes an audio file via transcribe_audio().")

    def transcribe_audio(
        self,
        audio_path: str | Path,
        *,
        language_bias: Sequence[str] = DEFAULT_LANGUAGE_BIAS,
        authorization: LiveCallAuthorization | None = None,
    ) -> TranscriptResult:
        if not isinstance(authorization, LiveCallAuthorization):
            raise LiveCallNotAuthorizedError(
                "A valid LiveCallAuthorization is required before a live transcription request. "
                "No request was attempted."
            )
        path = Path(audio_path)
        if not path.is_file():
            raise InvalidAudioError(f"Audio file not found: {path}")
        _wav_format(path)  # local guard: never upload a container the API will reject

        session_id = f"clipforge-{uuid.uuid4().hex}"
        request_config = {
            "model": self._model,
            "audioEncoding": "WAV",
            "mode": "PUSH_TO_TALK",
            "languageBias": list(language_bias),
        }
        logger.info("transcription_request session_id=%s bytes=%d", session_id, path.stat().st_size)
        authorization.reserve()

        try:
            with path.open("rb") as audio_fh:
                response = self._client.post(
                    TRANSCRIBE_PATH,
                    params={"sessionId": session_id},
                    headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                    files={
                        "request": (None, json.dumps(request_config), "application/json"),
                        "audio": (path.name, audio_fh, "audio/wav"),
                    },
                )
        except httpx.TimeoutException as exc:
            logger.warning("transcription_timeout session_id=%s", session_id)
            raise TranscriptionTimeoutError(
                f"Transcription timed out after {self._timeout_seconds:.0f}s (session {session_id})."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("transcription_transport_error session_id=%s type=%s", session_id, type(exc).__name__)
            raise TranscriptionError(
                f"Could not reach the transcription service (session {session_id})."
            ) from exc

        if response.status_code == 429:
            logger.warning("transcription_rate_limited session_id=%s", session_id)
            raise TranscriptionRateLimitedError(
                f"Transcription is rate limited (session {session_id}). No automatic retry was attempted.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            message, error_type = self._safe_error(response)
            logger.warning(
                "transcription_api_error session_id=%s status=%d type=%s",
                session_id, response.status_code, error_type,
            )
            raise TranscriptionAPIError(
                response.status_code,
                f"Transcription failed with HTTP {response.status_code}: {message} (session {session_id}).",
                error_type=error_type,
            )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise TranscriptionAPIError(502, f"Transcription returned invalid JSON (session {session_id}).") from exc

        transcript = payload.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip():
            raise TranscriptionAPIError(502, f"Transcription response contained no transcript (session {session_id}).")
        audio_duration_ms = payload.get("audioDurationMs")
        response_session = payload.get("sessionId") if isinstance(payload.get("sessionId"), str) else session_id
        logger.info(
            "transcription_ok session_id=%s duration_ms=%s turns=%d",
            response_session,
            audio_duration_ms if isinstance(audio_duration_ms, int) else "unknown",
            len(payload.get("turns") or []),
        )
        return TranscriptResult(
            text=" ".join(transcript.split()),
            language="pt-BR",  # languageBias steers the model; pt-BR is ClipForge's UI language
            confidence=None,  # documented response has no confidence score; never invent one
            provider_name=self.provider_name,
            is_mock=False,
            session_id=response_session,
            audio_duration_ms=audio_duration_ms if isinstance(audio_duration_ms, int) else None,
        )

    @staticmethod
    def _safe_error(response: httpx.Response) -> tuple[str, str | None]:
        """Extract only the documented client-safe message/type, never headers or the key."""
        try:
            body = response.json()
        except ValueError:
            return "unexpected error response", None
        if not isinstance(body, dict):
            return "unexpected error response", None
        message = body.get("message")
        error_type = body.get("type")
        return (
            message if isinstance(message, str) and message.strip() else "unexpected error response",
            error_type if isinstance(error_type, str) else None,
        )
