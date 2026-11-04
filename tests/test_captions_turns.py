"""ADR-049 real timed subtitles: ENDPOINTING turns, from-turns captions, cover.

Real execution only (mocked transports for the provider). No paid calls.
"""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_contracts import TranscriptTurn
from clipforge_providers import get_providers
from clipforge_worker import timeline_render as tr


def _client(tmp_path):
    from clipforge_jobs import JobStore

    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    return client, store


def _upload_clip(client, tmp_path, name="clip.mp4", duration=4):
    path = tmp_path / name
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=64x36:rate=10:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("ffmpeg could not generate test clip")
    with open(path, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    return upload.json()["job_id"]


def test_turn_contract_rejects_bad_bounds():
    with pytest.raises(Exception):
        TranscriptTurn.model_validate({"turn_id": 1, "start_ms": 500, "end_ms": 100, "text": "x"})
    with pytest.raises(Exception):
        TranscriptTurn.model_validate({"turn_id": -1, "start_ms": 0, "end_ms": 100, "text": "x"})
    # 0-indexed ids are accepted: the id is the model's opaque key.
    assert TranscriptTurn.model_validate(
        {"turn_id": 0, "start_ms": 0, "end_ms": 100, "text": "ok"}).turn_id == 0


def test_transcribe_rejects_bad_asr_mode(tmp_path):
    client, _ = _client(tmp_path)
    path = tmp_path / "r.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(path)],
                   capture_output=True, check=True)
    with open(path, "rb") as fh:
        resp = client.post("/api/transcribe", files={"file": ("r.wav", fh, "audio/wav")},
                           data={"mode": "WORD_LEVEL"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unsupported_asr_mode"


def test_transcribe_mock_ignores_mode(tmp_path):
    client, _ = _client(tmp_path)
    path = tmp_path / "r.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(path)],
                   capture_output=True, check=True)
    with open(path, "rb") as fh:
        resp = client.post("/api/transcribe", files={"file": ("r.wav", fh, "audio/wav")},
                           data={"mock_fixture_id": "pt_keep_me_sharp", "mode": "ENDPOINTING"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["turns"] == []  # mock never invents timings


def test_from_turns_maps_real_timings(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.create_from_turns",
        "params": {"turns": [
            {"start_ms": 0, "end_ms": 1500, "text": "Ola mundo"},
            {"start_ms": 2000, "end_ms": 3500, "text": "Segunda frase aqui"},
        ]}})
    assert executed.status_code == 200, executed.text
    assert executed.json()["result"]["timing"].startswith("turn")
    texts = client.get(f"/api/jobs/{job_id}/texts").json()["texts"]
    assert [(t["start_s"], t["duration_s"]) for t in texts] == [(0.0, 1.5), (2.0, 1.5)]
    assert store.get(job_id).clip_texts[0].text == "Ola mundo"


def test_from_turns_splits_long_turns_and_skips_blips(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path, duration=12)
    long_text = " ".join(["palavra"] * 40)
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.create_from_turns",
        "params": {"turns": [
            {"start_ms": 0, "end_ms": 100, "text": "blip"},
            {"start_ms": 500, "end_ms": 10500, "text": long_text},
        ]}})
    assert executed.status_code == 200, executed.text
    texts = client.get(f"/api/jobs/{job_id}/texts").json()["texts"]
    assert len(texts) >= 2  # long turn split into sequential lines
    assert all(t["duration_s"] <= 8.0 for t in texts)
    assert texts[0]["start_s"] >= 0.5 - 1e-9  # blip skipped, first line starts the 10 s turn
    assert all(len(t["text"]) >= 15 for t in texts)  # no stray stub lines


def test_from_turns_rejects_out_of_range(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.create_from_turns",
        "params": {"turns": [{"start_ms": 30000, "end_ms": 32000, "text": "fora"}]}})
    assert executed.status_code == 422
    assert executed.json()["error"]["code"] == "turn_out_of_range"


def test_cover_tool_and_endpoints(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    assert client.get(f"/api/jobs/{job_id}/caption-cover").json() == {"caption_cover": False}
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.cover", "params": {"enabled": True}})
    assert executed.status_code == 200, executed.text
    assert executed.json()["result"] == {"caption_cover": True}
    assert store.get(job_id).caption_cover is True
    assert client.get(f"/api/jobs/{job_id}/caption-cover").json() == {"caption_cover": True}
    put = client.put(f"/api/jobs/{job_id}/caption-cover", json={"enabled": False})
    assert put.status_code == 200 and put.json() == {"caption_cover": False}
    assert client.get(f"/api/jobs/{job_id}").json()["caption_cover"] is False


def test_chat_bg_programmatic_names_local_path(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    body = client.post("/api/chat", json={
        "message": "substitui o fundo por um gradiente azul animado", "job_id": job_id}).json()
    assert body["intent"] == "edit_proposal"
    assert body["needs_confirmation"] is True
    assert "program" in body["reply"].lower()


def test_chat_cover_intent_proposes_tool(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    body = client.post("/api/chat", json={
        "message": "tapa as legendas queimadas", "job_id": job_id}).json()
    assert body["needs_confirmation"] is True
    assert body["pending_tool_calls"][0]["tool"] == "captions.cover"
    assert body["pending_tool_calls"][0]["params"] == {"enabled": True}


def test_chat_captions_reply_mentions_cover(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    body = client.post("/api/chat", json={
        "message": "adiciona legendas 'Ola'", "job_id": job_id}).json()
    assert "queimadas" in body["reply"]


def test_cover_blurs_band_only_in_pixels():
    cv2 = pytest.importorskip("cv2")
    frame = np.full((720, 1280, 3), 128, dtype=np.uint8)
    frame[600:604, 400:800] = 255  # thin fake burned-in text line in the band
    top_before = frame[100, 640].copy()
    covered = tr.apply_caption_cover(frame.copy())
    band_before = frame[int(720 * tr.COVER_BAND_TOP):, :]
    band_after = covered[int(720 * tr.COVER_BAND_TOP):, :]
    assert not np.array_equal(band_after, band_before)  # band blurred
    assert np.array_equal(covered[100, 640], top_before)  # top untouched
    assert covered.shape == frame.shape


def test_tools_catalogue_lists_turns_cover_and_translate(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    names = {t["name"] for t in client.get(f"/api/jobs/{job_id}/tools").json()["tools"]}
    assert {"captions.create_from_turns", "captions.cover", "captions.translate"} <= names
    assert len(names) == 14


def _translate_provider(handler, tmp_path):
    import httpx
    from clipforge_director import LiveCallAuthorization, LiveCallBudget
    from clipforge_providers import SparkSubtitleTranslator

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
    provider = SparkSubtitleTranslator("test-key", client=client)
    auth = LiveCallAuthorization(LiveCallBudget(tmp_path / "ledger"), "director")
    return provider, auth


def test_translate_parses_numbered_lines(tmp_path):
    import httpx

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "1. Olá mundo\n2. Segunda frase"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        })

    provider, auth = _translate_provider(handler, tmp_path)
    result = provider.translate_lines(["Hello world", "Second sentence"], authorization=auth)
    assert result.translated_text == "Olá mundo\nSegunda frase"
    assert result.estimated_cost_usd == round(100 * 0.10 / 1_000_000 + 20 * 0.20 / 1_000_000, 6)
    assert seen["payload"]["reasoning_effort"] == "minimal"
    assert seen["payload"]["max_completion_tokens"] >= 1000


def test_translate_rejects_misnumbered_lines(tmp_path):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "1. Olá\n3. Errada"}}],
            "usage": {},
        })

    provider, auth = _translate_provider(handler, tmp_path)
    with pytest.raises(Exception):
        provider.translate_lines(["Hi", "Bye"], authorization=auth)


def test_translate_requires_authorization():
    from clipforge_providers import SparkSubtitleTranslator

    with pytest.raises(Exception):
        SparkSubtitleTranslator("k").translate_lines(["Hi"], authorization=None)


def test_translate_tool_fails_closed_without_key(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "")
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.translate", "params": {"transcript": "Hello world"}})
    assert executed.status_code == 503
    assert executed.json()["error"]["code"] == "translation_not_configured"


def test_chat_translate_intent_proposes_tool(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    body = client.post("/api/chat", json={
        "message": "traduz para português 'Hello world, welcome'", "job_id": job_id}).json()
    assert body["needs_confirmation"] is True
    assert body["pending_tool_calls"][0]["tool"] == "captions.translate"
    assert body["pending_tool_calls"][0]["params"]["transcript"] == "Hello world, welcome"
    assert "$0.0001" in body["reply"]
    question = client.post("/api/chat", json={
        "message": "traduz para português", "job_id": job_id}).json()
    assert question["needs_confirmation"] is False
    assert question["pending_tool_calls"] == []
