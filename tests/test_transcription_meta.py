"""Tests for the Meta Muse Voice Transcribe provider — mocked transport only.

No external requests: every test injects httpx.MockTransport. The suite asserts
the exact documented multipart contract, normalization, error mapping, and that
exactly one request is issued (no automatic retries).
"""

from __future__ import annotations

import json
import wave
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest

from clipforge_director import LiveCallAuthorization, LiveCallNotAuthorizedError
from clipforge_providers.transcription_meta import (
    InvalidAudioError,
    MetaVoiceTranscriptionProvider,
    MissingCredentialsError,
    TranscriptionAPIError,
    TranscriptionRateLimitedError,
    TranscriptionTimeoutError,
)


class _TestAuthorization(LiveCallAuthorization):
    """Provider-level authorization double; the real ledger is tested separately."""

    def __init__(self, function: str = "transcription") -> None:
        self._function = function
        self._reserved = False

    def reserve(self) -> int:
        if self._reserved:
            raise RuntimeError("already reserved")
        self._reserved = True
        return 1

BASE = "https://api.meta.ai"


def write_wav(path: Path, seconds: float = 1.0, rate: int = 24000) -> Path:
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def parse_multipart(content: bytes, content_type: str) -> dict[str, tuple[str | None, str, bytes]]:
    raw = b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + content
    message = BytesParser(policy=policy.default).parsebytes(raw)
    parts: dict[str, tuple[str | None, str, bytes]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        parts[name] = (filename, part.get_content_type(), part.get_payload(decode=True))
    return parts


def provider(
    handler, *, key: str = "test-key", timeout: float = 30.0, wrap_auth: bool = True
) -> MetaVoiceTranscriptionProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=BASE)
    instance = MetaVoiceTranscriptionProvider(key, timeout_seconds=timeout, client=client)
    if wrap_auth:
        original_transcribe = instance.transcribe_audio

        def transcribe_audio(*args, **kwargs):
            kwargs.setdefault("authorization", _TestAuthorization("transcription"))
            return original_transcribe(*args, **kwargs)

        instance.transcribe_audio = transcribe_audio  # type: ignore[method-assign]
    return instance


def test_missing_credentials_fails_before_any_request():
    with pytest.raises(MissingCredentialsError):
        MetaVoiceTranscriptionProvider("   ")


def test_direct_transcription_requires_authorization_before_network(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"transcript": "should not be reached"})

    instance = provider(handler, wrap_auth=False)
    with pytest.raises(LiveCallNotAuthorizedError):
        instance.transcribe_audio(tmp_path / "missing.wav")
    assert calls["n"] == 0


def test_request_construction_and_normalization(tmp_path):
    wav = write_wav(tmp_path / "recording.wav")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["accept"] = request.headers.get("accept")
        captured["parts"] = parse_multipart(request.read(), request.headers["content-type"])
        return httpx.Response(200, json={
            "sessionId": "srv-session-123",
            "transcript": "Desfoca  o fundo, por favor.",
            "audioDurationMs": 1000,
            "turns": [],
        })

    result = provider(handler).transcribe_audio(wav)

    assert captured["method"] == "POST"
    assert captured["url"].startswith(f"{BASE}/v1/asr/transcribe?sessionId=clipforge-")
    assert captured["auth"] == "Bearer test-key"
    assert captured["accept"] == "application/json"
    request_json = json.loads(captured["parts"]["request"][2])
    assert request_json == {
        "model": "muse-voice-transcribe-1.0",
        "audioEncoding": "WAV",
        "mode": "PUSH_TO_TALK",
        "languageBias": ["Portuguese"],
    }
    filename, content_type, audio = captured["parts"]["audio"]
    assert filename == "recording.wav"
    assert content_type == "audio/wav"
    assert audio[:4] == b"RIFF"
    assert result.text == "Desfoca o fundo, por favor."  # whitespace normalized
    assert result.provider_name == "meta-muse-voice-transcribe"
    assert result.is_mock is False
    assert result.confidence is None  # not provided by the documented response
    assert result.session_id == "srv-session-123"
    assert result.audio_duration_ms == 1000


def test_exactly_one_request_no_retry(tmp_path):
    wav = write_wav(tmp_path / "a.wav")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"sessionId": "s", "transcript": "ok", "audioDurationMs": 500, "turns": []})

    provider(handler).transcribe_audio(wav)
    assert calls["n"] == 1


def test_rate_limit_maps_without_retry(tmp_path):
    wav = write_wav(tmp_path / "a.wav")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"type": "rate_limit", "message": "too many"})

    with pytest.raises(TranscriptionRateLimitedError) as exc:
        provider(handler).transcribe_audio(wav)
    assert exc.value.retry_after == "2"
    assert calls["n"] == 1


def test_timeout_maps_and_no_retry(tmp_path):
    wav = write_wav(tmp_path / "a.wav")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(TranscriptionTimeoutError):
        provider(handler, timeout=2.0).transcribe_audio(wav)
    assert calls["n"] == 1


def test_api_error_is_safe_and_does_not_leak_key(tmp_path):
    wav = write_wav(tmp_path / "a.wav")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"type": "server_error", "message": "internal failure"})

    with pytest.raises(TranscriptionAPIError) as exc:
        provider(handler, key="super-secret-key").transcribe_audio(wav)
    assert exc.value.status_code == 500
    assert "internal failure" in str(exc.value)
    assert "super-secret-key" not in str(exc.value)


def test_invalid_wav_rejected_before_request(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav at all")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"transcript": "x"})

    with pytest.raises(InvalidAudioError):
        provider(handler).transcribe_audio(bad)
    assert calls["n"] == 0


def test_stereo_or_wrong_rate_rejected(tmp_path):
    stereo = tmp_path / "stereo.wav"
    with wave.open(str(stereo), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(24000)
        fh.writeframes(b"\x00\x00" * 2000)
    with pytest.raises(InvalidAudioError):
        provider(lambda r: httpx.Response(200, json={})).transcribe_audio(stereo)
