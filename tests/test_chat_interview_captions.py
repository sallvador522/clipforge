"""Chat director interview + chat video attach path + captions tool.

Real execution only: deterministic router, validated tool calls against the
persisted job, no mocks of the units under test. No paid calls.
"""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_providers import get_providers


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


def test_interview_asks_style_first(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/chat", json={"message": "quero um video sobre o mar"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "idea_interview"
    assert body["needs_confirmation"] is False
    assert body["interview"]["needed"] == ["style"]
    assert body["interview"]["options"]["styles"]


def test_interview_style_then_duration(tmp_path):
    client, _ = _client(tmp_path)
    first = client.post("/api/chat", json={"message": "quero um video"}).json()
    second = client.post("/api/chat", json={
        "message": "documentario", "interview": first["interview"]["answered"]}).json()
    assert second["intent"] == "idea_interview"
    assert second["interview"]["needed"] == ["duration_s"]
    assert second["interview"]["answered"] == {"style": "documentary"}


def test_interview_duration_then_aspect(tmp_path):
    client, _ = _client(tmp_path)
    first = client.post("/api/chat", json={"message": "quero um video"}).json()
    answered = dict(first["interview"]["answered"], **{"style": "cinematic"})
    second = client.post("/api/chat", json={"message": "30 segundos", "interview": answered}).json()
    assert second["intent"] == "idea_interview"
    assert second["interview"]["needed"] == ["aspect"]
    assert second["interview"]["answered"] == {"style": "cinematic", "duration_s": 30}


def test_interview_complete_proposes_with_options(tmp_path):
    client, _ = _client(tmp_path)
    first = client.post("/api/chat", json={"message": "quero um video"}).json()
    brief = "quero um video"
    answered = dict(first["interview"]["answered"], **{"style": "bold", "duration_s": 25, "brief": brief})
    done = client.post("/api/chat", json={"message": "vertical", "interview": answered}).json()
    assert done["intent"] == "idea_proposal"
    assert done["pending_text"] == brief
    assert done["needs_confirmation"] is True
    assert done["pending_idea_options"] == {
        "style": "bold", "duration_seconds": 25, "aspect_ratio": "9:16"}
    assert done["interview"]["needed"] == []


def test_interview_asks_for_topic_when_brief_too_short(tmp_path):
    client, _ = _client(tmp_path)
    done = client.post("/api/chat", json={
        "message": "vertical",
        "interview": {"style": "bold", "duration_s": 25, "brief": "abc"}}).json()
    assert done["intent"] == "idea_interview"
    assert done["interview"]["needed"] == ["brief"]
    assert done["needs_confirmation"] is False


def test_interview_complete_message_at_once(tmp_path):
    client, _ = _client(tmp_path)
    done = client.post("/api/chat", json={
        "message": "quero um video documentario de 25 segundos horizontal"}).json()
    assert done["intent"] == "idea_proposal"
    assert done["pending_idea_options"] == {
        "style": "documentary", "duration_seconds": 25, "aspect_ratio": "16:9"}


def test_interview_does_not_guess_slots(tmp_path):
    client, _ = _client(tmp_path)
    body = client.post("/api/chat", json={"message": "quero um video giro"}).json()
    assert body["intent"] == "idea_interview"
    assert body["interview"]["answered"] == {}
    assert body["interview"]["needed"] == ["style"]


def test_interview_smalltalk_and_cancel_untouched(tmp_path):
    client, _ = _client(tmp_path)
    assert client.post("/api/chat", json={"message": "ola"}).json()["intent"] == "smalltalk"
    assert client.post("/api/chat", json={"message": "cancelar"}).json()["intent"] == "cancel"


def test_interview_skipped_with_clip(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    body = client.post("/api/chat", json={"message": "quero um video", "job_id": job_id}).json()
    assert body["intent"] == "edit_proposal"
    assert "interview" not in body or body.get("interview") is None


def test_bg_intent_names_meta_path(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    for message in ("remove o fundo", "desfoca o fundo por favor", "quero trocar o fundo"):
        body = client.post("/api/chat", json={"message": message, "job_id": job_id}).json()
        assert body["intent"] == "edit_proposal", message
        assert body["needs_confirmation"] is True
        assert "SAM" in body["reply"] and "Muse" in body["reply"], message


def test_captions_tool_creates_timed_lines(tmp_path):
    client, store = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.create",
        "params": {"transcript": "Ola mundo esta e a nossa historia de teste para as legendas do video"}})
    assert executed.status_code == 200, executed.text
    result = executed.json()["result"]
    assert len(result["created"]) == 2
    assert result["timing"].startswith("uniform")
    texts = client.get(f"/api/jobs/{job_id}/texts").json()["texts"]
    assert [t["text"] for t in texts] == [c["text"] for c in result["created"]]
    first, second = texts
    assert first["start_s"] == 0.0 and second["start_s"] == pytest.approx(2.0)
    assert first["y"] == pytest.approx(0.82)


def test_captions_tool_respects_overlay_cap(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    filler = [{"overlay_id": f"txt_fill{i:05d}", "text": "x"} for i in range(20)]
    assert client.put(f"/api/jobs/{job_id}/texts", json={"texts": filler}).status_code == 200
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.create", "params": {"transcript": "uma linha a mais"}})
    assert executed.status_code == 409
    assert executed.json()["error"]["code"] == "too_many_overlays"


def test_captions_tool_rejects_empty(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    executed = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "captions.create", "params": {"transcript": "   "}})
    assert executed.status_code == 422


def test_chat_proposes_captions_and_clarifies(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    proposal = client.post("/api/chat", json={
        "message": "adiciona legendas 'A nossa historia comeca aqui'", "job_id": job_id}).json()
    assert proposal["needs_confirmation"] is True
    assert len(proposal["pending_tool_calls"]) == 1
    assert proposal["pending_tool_calls"][0]["tool"] == "captions.create"
    assert proposal["pending_tool_calls"][0]["params"]["transcript"] == "A nossa historia comeca aqui"
    question = client.post("/api/chat", json={
        "message": "adiciona legendas", "job_id": job_id}).json()
    assert question["needs_confirmation"] is False
    assert question["pending_tool_calls"] == []


def test_tools_catalogue_lists_captions(tmp_path):
    client, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    names = {t["name"] for t in client.get(f"/api/jobs/{job_id}/tools").json()["tools"]}
    assert "captions.create" in names
    assert len(names) == 14
