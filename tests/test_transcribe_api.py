"""Transcription API tests: upload validation, WAV conversion, provider selection,
mock isolation, live wiring via mocked transport, and duplicate-request protection.

The live provider is always backed by httpx.MockTransport here; no request can
leave the machine (a socket guard is active for the mock-mode test).
"""

from __future__ import annotations

import json
import socket
import subprocess
import wave
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_api.transcribe import convert_to_wav
from clipforge_jobs import JobStore
from clipforge_providers import (
    MockBackgroundGenerationProvider,
    MockEditingPlannerProvider,
    MockSegmentationProvider,
    MockTranscriptionProvider,
    ProviderBundle,
    get_providers,
)
from clipforge_providers.transcription_meta import (
    MetaVoiceTranscriptionProvider,
    MissingCredentialsError,
)
from clipforge_worker.worker_process import PersistentWorker


@pytest.fixture(scope="module")
def spoken_webm(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("audio") / "voice.webm"
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libopus", "-b:a", "32k", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg cannot produce webm/opus here: {result.stderr[-200:]}")
    return path


def make_app(tmp_path, providers=None):
    return TestClient(create_app(storage_root=tmp_path / "storage", providers=providers or get_providers("mock")))


def post_audio(client, path: Path, fixture: str | None = "pt_keep_me_sharp"):
    data = {"mock_fixture_id": fixture} if fixture else {}
    with open(path, "rb") as fh:
        return client.post("/api/transcribe", files={"file": ("voice.webm", fh, "audio/webm")}, data=data)


def test_health_reports_transcription_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT", raising=False)
    monkeypatch.delenv("CLIPFORGE_LIVE_DIRECTOR_LIMIT", raising=False)
    body = make_app(tmp_path).get("/health").json()
    assert body["transcribe_mode"] == "mock"
    assert body["director_mode"] == "mock"
    assert body["live_transcription_available"] is False
    assert body["live_call_limits"] == {"transcription": 2, "director": 2}
    assert body["live_calls_used"] == {"transcription": 0, "director": 0}


def test_conversion_produces_mono_24k_pcm16(spoken_webm, tmp_path):
    target = tmp_path / "converted.wav"
    convert_to_wav(spoken_webm, target)
    with wave.open(str(target), "rb") as fh:
        assert fh.getnchannels() == 1
        assert fh.getsampwidth() == 2
        assert fh.getframerate() == 24000
        assert fh.getnframes() > 0


def test_mock_transcription_requires_explicit_fixture(spoken_webm, tmp_path):
    resp = post_audio(make_app(tmp_path), spoken_webm, fixture=None)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "mock_fixture_required"


def test_mock_transcription_returns_fixture_and_never_network(spoken_webm, tmp_path, monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def guarded(host, *args, **kwargs):
        if host not in ("127.0.0.1", "localhost", None):
            raise AssertionError(f"external name resolution attempted in mock transcription: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)

    resp = post_audio(make_app(tmp_path), spoken_webm)
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_mock"] is True
    assert body["transcribe_mode"] == "mock"
    assert body["text"] == "Mantém-me nítido e desfoca o resto."
    assert body["provider_name"] == "mock-transcription"


def test_upload_validation(spoken_webm, tmp_path):
    client = make_app(tmp_path)
    data = {"mock_fixture_id": "pt_keep_me_sharp"}

    resp = client.post("/api/transcribe", files={"file": ("notes.txt", b"hello", "text/plain")}, data=data)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "unsupported_audio_extension"

    resp = client.post("/api/transcribe", files={"file": ("empty.webm", b"", "audio/webm")}, data=data)
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "empty_audio"

    resp = client.post("/api/transcribe", files={"file": ("fake.webm", b"not audio", "audio/webm")}, data=data)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_audio"


def test_wav_upload_conversion_does_not_overwrite_input(tmp_path):
    import wave

    path = tmp_path / "instruction.wav"
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(22050)
        fh.writeframes(b"\x00\x00" * 22050)
    client = make_app(tmp_path)
    with path.open("rb") as fh:
        resp = client.post(
            "/api/transcribe",
            files={"file": ("instruction.wav", fh, "audio/wav")},
            data={"mock_fixture_id": "pt_keep_me_sharp"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "Mantém-me nítido e desfoca o resto."


def test_live_bundle_uses_mocked_transport_and_converts_audio(spoken_webm, tmp_path):
    captured: dict = {}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        content_type = request.headers["content-type"]
        raw = b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + request.read()
        message = BytesParser(policy=policy.default).parsebytes(raw)
        parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
        captured["request_json"] = json.loads(parts["request"].get_payload(decode=True))
        captured["audio"] = parts["audio"].get_payload(decode=True)
        captured["auth"] = request.headers["authorization"]
        assert str(request.url).startswith("https://api.meta.ai/v1/asr/transcribe?sessionId=clipforge-")
        return httpx.Response(200, json={
            "sessionId": "server-session",
            "transcript": "Mantém-me nítido e desfoca o resto.",
            "audioDurationMs": 1000,
            "turns": [],
        })

    live = MetaVoiceTranscriptionProvider(
        "unit-test-key", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
    )
    bundle = ProviderBundle(
        transcription=live,
        planner=MockEditingPlannerProvider(),
        segmentation=MockSegmentationProvider(),
        background=MockBackgroundGenerationProvider(),
        mode="mock",
        transcription_mode="live",
    )
    client = make_app(tmp_path, bundle)
    resp = post_audio(client, spoken_webm, fixture=None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_mock"] is False and body["transcribe_mode"] == "live"
    assert body["session_id"] == "server-session"
    assert body["text"] == "Mantém-me nítido e desfoca o resto."
    assert captured["auth"] == "Bearer unit-test-key"
    assert captured["request_json"]["languageBias"] == ["Portuguese"]
    assert captured["request_json"]["mode"] == "PUSH_TO_TALK"
    assert captured["audio"][:4] == b"RIFF"  # API receives the converted WAV, not the browser's webm
    assert calls["n"] == 1  # exactly one billable request

    health = client.get("/health").json()
    assert health["transcribe_mode"] == "live" and health["live_transcription_available"] is True
    assert json.loads((tmp_path / "storage" / "live-call-ledger.json").read_text())["transcription"] == 1


def test_live_transcription_refuses_when_budget_is_exhausted(spoken_webm, tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"transcript": "should never be called", "turns": []})

    storage = tmp_path / "storage"
    storage.mkdir(parents=True)
    (storage / "live-call-ledger.json").write_text('{"transcription": 2}', encoding="utf-8")
    bundle = ProviderBundle(
        transcription=MetaVoiceTranscriptionProvider(
            "k", client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
        ),
        planner=MockEditingPlannerProvider(),
        segmentation=MockSegmentationProvider(),
        background=MockBackgroundGenerationProvider(),
        mode="mock",
        transcription_mode="live",
    )
    resp = post_audio(make_app(tmp_path, bundle), spoken_webm, fixture=None)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "live_budget_exhausted"
    assert calls["n"] == 0


def test_live_errors_map_to_http_and_are_not_retried(spoken_webm, tmp_path):
    calls = {"n": 0}

    def rate_limited(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"message": "rate limited"})

    bundle = ProviderBundle(
        transcription=MetaVoiceTranscriptionProvider(
            "k", client=httpx.Client(transport=httpx.MockTransport(rate_limited), base_url="https://api.meta.ai")
        ),
        planner=MockEditingPlannerProvider(),
        segmentation=MockSegmentationProvider(),
        background=MockBackgroundGenerationProvider(),
        mode="mock",
        transcription_mode="live",
    )
    resp = post_audio(make_app(tmp_path, bundle), spoken_webm, fixture=None)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "transcription_rate_limited"
    assert calls["n"] == 1

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    bundle2 = ProviderBundle(
        transcription=MetaVoiceTranscriptionProvider(
            "k", timeout_seconds=1, client=httpx.Client(transport=httpx.MockTransport(timeout), base_url="https://api.meta.ai")
        ),
        planner=MockEditingPlannerProvider(),
        segmentation=MockSegmentationProvider(),
        background=MockBackgroundGenerationProvider(),
        mode="mock",
        transcription_mode="live",
    )
    resp = post_audio(make_app(tmp_path / "b", bundle2), spoken_webm, fixture=None)
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "transcription_timeout"


def test_provider_selection_is_scoped_to_transcription(monkeypatch):
    monkeypatch.setenv("CLIPFORGE_AI_MODE", "mock")
    monkeypatch.delenv("CLIPFORGE_TRANSCRIBE_MODE", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    bundle = get_providers()
    assert isinstance(bundle.transcription, MockTranscriptionProvider)
    assert bundle.transcription_mode == "mock"

    monkeypatch.setenv("CLIPFORGE_TRANSCRIBE_MODE", "live")
    with pytest.raises(MissingCredentialsError):
        get_providers()  # clear failure when the key is missing, before any request

    monkeypatch.setenv("MODEL_API_KEY", "dummy-key")
    bundle = get_providers()
    assert isinstance(bundle.transcription, MetaVoiceTranscriptionProvider)
    assert bundle.transcription_mode == "live"
    assert isinstance(bundle.segmentation, MockSegmentationProvider)
    assert isinstance(bundle.planner, MockEditingPlannerProvider)
    assert isinstance(bundle.background, MockBackgroundGenerationProvider)

    monkeypatch.setenv("CLIPFORGE_TRANSCRIBE_MODE", "banana")
    with pytest.raises(ValueError):
        get_providers()


def test_confirmed_transcript_is_planned_without_retranscribing(spoken_webm, tmp_path):
    client = make_app(tmp_path)
    upload = client.post("/api/uploads", files={"file": ("clip.mp4", _tiny_video(tmp_path), "video/mp4")})
    assert upload.status_code == 201
    job_id = upload.json()["job_id"]

    transcribed = post_audio(client, spoken_webm, fixture="pt_keep_me_sharp").json()
    assert transcribed["is_mock"] is True

    confirmed = client.post(
        f"/api/jobs/{job_id}/voice",
        json={"transcript": transcribed["text"], "transcription_session_id": transcribed.get("session_id")},
    )
    assert confirmed.status_code == 200 and confirmed.json()["ready"] is True

    worker = PersistentWorker(JobStore(tmp_path / "storage"), get_providers("mock"))
    assert worker.run_once() is True
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "awaiting_approval"
    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 200
    assert worker.run_once() is True
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "completed"
    result = client.get(f"/api/jobs/{job_id}/result").json()
    assert result["transcript"]["text"] == transcribed["text"]
    assert result["transcript"]["provider_name"] == "user-confirmed"
    assert result["plan"]["intent"] == "blur_background"


def test_voice_requires_exactly_one_source(tmp_path):
    client = make_app(tmp_path)
    upload = client.post("/api/uploads", files={"file": ("clip.mp4", _tiny_video(tmp_path), "video/mp4")})
    job_id = upload.json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/voice", json={}).status_code == 422
    resp = client.post(
        f"/api/jobs/{job_id}/voice",
        json={"transcript": "Desfoca o fundo.", "audio_fixture_id": "pt_blur_people_behind"},
    )
    assert resp.status_code == 422


def _tiny_video(tmp_path: Path) -> bytes:
    path = tmp_path / "tiny.mp4"
    if not path.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            capture_output=True,
        )
    return path.read_bytes()
