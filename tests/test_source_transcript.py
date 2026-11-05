"""Chunked source-audio transcription (ADR-060).

Videos longer than the provider's 10-min/32 MB per-request cap are split
into safety-margin blocks, transcribed once each with per-block ledger
slots, and joined with millisecond offsets. Any block failure aborts with
NO partial transcript. Mock mode is deterministic and free.
"""

import dataclasses
import subprocess

import pytest
from fastapi.testclient import TestClient

from clipforge_api import transcribe as mod
from clipforge_api.main import create_app
from clipforge_contracts import TranscriptResult, TranscriptTurn
from clipforge_director import LiveCallBudget
from clipforge_jobs import JobStore
from clipforge_providers import (
    TranscriptionAPIError,
    get_providers,
)


def _audio(tmp_path, name="src.mp4", duration=2, audio=True):
    path = tmp_path / name
    cmd = ["ffmpeg", "-y",
           "-f", "lavfi", "-i", f"testsrc=size=64x36:rate=10:duration={duration}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    else:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"ffmpeg unavailable: {result.stderr[-200:]}")
    return path


def _upload(client, path, name="clip.mp4"):
    with path.open("rb") as fh:
        resp = client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


def test_estimate_math():
    est = mod.estimate_source_transcript(1800.0)
    assert est["blocks"] == 4
    assert est["billed_seconds"] == 570 * 3 + 90
    assert est["estimated_usd"] == round(1800 * 0.00005, 6)
    assert mod.estimate_source_transcript(0.0)["blocks"] == 0
    one = mod.estimate_source_transcript(30.0)
    assert one["blocks"] == 1 and one["billed_seconds"] == 30


def test_join_offsets_and_reindexes_turns():
    a = TranscriptResult(text="ola mundo", language="pt-BR", provider_name="x",
                         is_mock=False, turns=[TranscriptTurn(turn_id=5, start_ms=0, end_ms=900, text="ola mundo")])
    b = TranscriptResult(text="adeus", language="pt-BR", provider_name="x",
                         is_mock=False, turns=[TranscriptTurn(turn_id=0, start_ms=100, end_ms=800, text="adeus")])
    joined = mod.join_transcript_blocks([(a, 0), (b, 60_000)])
    assert joined.text == "ola mundo adeus"
    assert [(t.turn_id, t.start_ms, t.end_ms) for t in joined.turns] == [(0, 0, 900), (1, 60100, 60800)]
    assert joined.is_mock is False


def test_split_blocks_with_offsets(tmp_path):
    wav = tmp_path / "full.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration=25",
                    "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav)],
                   capture_output=True, check=True)
    parts = mod.split_wav(wav, tmp_path / "blocks", block_seconds=10.0)
    assert len(parts) == 3
    assert [offset for _, offset in parts] == [0, 10_000, 20_000]


def test_endpoint_estimate_without_confirmation(tmp_path):
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=get_providers("mock")))
    job_id = _upload(client, _audio(tmp_path))
    resp = client.post(f"/api/jobs/{job_id}/source-transcript", json={"confirmed": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_confirmation"] is True
    assert body["estimate"]["blocks"] == 1
    assert body["transcript"] is None
    # Nothing ran: no ledger file, no sidecar transcript.
    assert not (tmp_path / "storage" / "live-call-ledger.json").exists()
    assert client.get(f"/api/jobs/{job_id}/source-transcript").json()["status"] == "idle"


def test_endpoint_confirmed_mock_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "TRANSCRIPT_BLOCK_SECONDS", 10.0)
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=get_providers("mock")))
    job_id = _upload(client, _audio(tmp_path, duration=25))
    import time

    resp = client.post(f"/api/jobs/{job_id}/source-transcript", json={"confirmed": True})
    assert resp.status_code == 202, resp.text
    body = None
    for _ in range(60):
        time.sleep(1)
        body = client.get(f"/api/jobs/{job_id}/source-transcript").json()
        if body["status"] in ("completed", "failed"):
            break
    assert body is not None and body["status"] == "completed", body
    assert body["estimate"]["blocks"] == 3
    assert body["transcript"].count("bloco") == 3
    assert body["is_mock"] is True
    assert body["error"] is None


def test_block_failure_aborts_without_partial(tmp_path):
    from types import SimpleNamespace

    class Flaky:
        def __init__(self):
            self.calls = 0

        def transcribe_audio(self, path, language_bias=None, mode=None, authorization=None):
            self.calls += 1
            if self.calls == 2:
                raise TranscriptionAPIError(502, "boom")
            return TranscriptResult(text=f"parte {self.calls}", language="pt-BR",
                                    provider_name="stub", is_mock=False, turns=[])

    providers = SimpleNamespace(transcription_mode="live", transcription=Flaky())
    budget = LiveCallBudget(tmp_path / "ledger")
    wav = tmp_path / "full.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=25",
                    "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav)],
                   capture_output=True, check=True)
    with pytest.raises(Exception) as exc:
        mod.transcribe_source_blocks(
            wav_path=wav, duration_seconds=25.0, providers=providers,
            budget=budget, block_seconds=10.0)
    assert "Bloco 2/3" in str(exc.value)


def test_chat_routes_transcribe_request_with_estimate(tmp_path):
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=get_providers("mock")))
    job_id = _upload(client, _audio(tmp_path, duration=65))
    resp = client.post("/api/chat", json={"message": "transcreve o áudio deste vídeo", "job_id": job_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_confirmation"] is True
    assert body["pending_kind"] == "transcript"
    assert "1 bloco" in body["reply"]


def test_chat_no_audio_is_clarification_not_proposal(tmp_path):
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=get_providers("mock")))
    job_id = _upload(client, _audio(tmp_path, audio=False), name="silent.mp4")
    resp = client.post("/api/chat", json={"message": "transcreve o áudio deste vídeo", "job_id": job_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_confirmation"] is False
    assert body["pending_text"] is None
