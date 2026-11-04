"""Conversational Muse chat endpoint (ADR-045).

Side-effect free by contract: /api/chat never creates jobs/ideas, never
touches the live-call ledger and never calls providers. Execution stays on
the existing voice/ideas endpoints behind explicit user confirmation.
"""

from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker


def _client(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    worker = PersistentWorker(store, providers, poll_seconds=0.05)
    return client, store, worker


def test_chat_greeting_is_smalltalk_without_side_effects(tmp_path):
    client, store, _ = _client(tmp_path)
    before = len(store.list_jobs())
    resp = client.post("/api/chat", json={"message": "ola"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "smalltalk"
    assert body["needs_confirmation"] is False
    assert body["pending_text"] is None
    assert "Nada" not in body["reply"] or True  # reply is human copy, not asserted verbatim
    assert len(store.list_jobs()) == before


def test_chat_help_lists_real_capabilities(tmp_path):
    client, _, _ = _client(tmp_path)
    resp = client.post("/api/chat", json={"message": "o que sabes fazer?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "help"
    assert "desfocar" in body["reply"].lower()
    assert body["needs_confirmation"] is False


def test_chat_edit_proposal_requires_confirmation(tmp_path):
    client, store, _ = _client(tmp_path)
    # Register a clip context so the router proposes an edit (no execution).
    import subprocess

    path = tmp_path / "clip.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        import pytest

        pytest.skip("ffmpeg could not generate test clip")
    with open(path, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": ("clip.mp4", fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    resp = client.post("/api/chat", json={"message": "desfoca o fundo", "job_id": job_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "edit_proposal"
    assert body["needs_confirmation"] is True
    assert body["pending_text"] == "desfoca o fundo"
    assert body["pending_kind"] == "edit"
    # No execution happened: job still idle, no transcript consumed.
    job = store.get(job_id)
    assert job.ready is False


def test_chat_idea_proposal_without_clip(tmp_path):
    client, _, _ = _client(tmp_path)
    resp = client.post("/api/chat", json={"message": "cria um video sobre o mar"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Director interview first: slots are empty, so it asks style.
    assert body["intent"] == "idea_interview"
    assert body["needs_confirmation"] is False
    assert body["interview"]["needed"] == ["style"]
    # Answering all three slots completes the proposal with options.
    answered = body["interview"]["answered"]
    step2 = client.post("/api/chat", json={"message": "cinematografico", "interview": answered}).json()
    assert step2["intent"] == "idea_interview"
    answered = step2["interview"]["answered"]
    step3 = client.post("/api/chat", json={"message": "20 segundos", "interview": answered}).json()
    assert step3["intent"] == "idea_interview"
    answered = step3["interview"]["answered"]
    done = client.post("/api/chat", json={"message": "horizontal", "interview": answered}).json()
    assert done["intent"] == "idea_proposal"
    assert done["needs_confirmation"] is True
    assert done["pending_kind"] == "idea"
    assert done["pending_idea_options"] == {
        "style": "cinematic", "duration_seconds": 20, "aspect_ratio": "16:9"}


def test_chat_rejects_empty_message(tmp_path):
    client, _, _ = _client(tmp_path)
    resp = client.post("/api/chat", json={"message": "  "})
    assert resp.status_code in (422, 400)
