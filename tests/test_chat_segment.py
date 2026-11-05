"""Timeline trecho selection -> director awareness (segment flow).

The user marks a trecho on the timeline; /api/chat validates it against the
real source duration and the router scopes SAM proposals to that window with
an honest frame/cost estimate. Side-effect free: no jobs, no ledger, no
provider calls.
"""

import subprocess

from fastapi.testclient import TestClient

from clipforge_api.main import _classify_chat, create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker


def _client(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    worker = PersistentWorker(store, providers, poll_seconds=0.05)
    return client, store, worker


def _upload_clip(client, tmp_path, name="clip.mp4", duration=2):
    path = tmp_path / name
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=64x36:rate=10:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
    with open(path, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    return upload.json()["job_id"]


def test_bg_with_valid_segment_names_trecho_and_estimate(tmp_path):
    client, store, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    before = len(store.list_jobs())
    resp = client.post("/api/chat", json={
        "message": "remove o fundo",
        "job_id": job_id,
        "segment": {"start_s": 0.0, "end_s": 1.0},
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "edit_proposal"
    assert body["needs_confirmation"] is True
    assert "00:00–00:01" in body["reply"]
    assert "10 frames" in body["reply"]
    assert body["pending_segment"] == {"start_s": 0.0, "end_s": 1.0}
    assert len(store.list_jobs()) == before


def test_segment_outside_duration_rejected(tmp_path):
    client, _, _ = _client(tmp_path)
    job_id = _upload_clip(client, tmp_path)
    resp = client.post("/api/chat", json={
        "message": "remove o fundo",
        "job_id": job_id,
        "segment": {"start_s": 0.0, "end_s": 30.0},
    })
    assert resp.status_code == 422, resp.text


def test_segment_without_clip_rejected(tmp_path):
    client, _, _ = _client(tmp_path)
    resp = client.post("/api/chat", json={
        "message": "remove o fundo",
        "segment": {"start_s": 0.0, "end_s": 1.0},
    })
    assert resp.status_code == 422, resp.text


def test_long_video_without_segment_asks_for_trecho():
    out = _classify_chat("remove o fundo", True, duration_s=1800.0, fps=30.0)
    assert out["intent"] == "edit_proposal"
    assert out["needs_confirmation"] is False
    assert out["pending_text"] is None
    assert "trecho" in out["reply"].lower()


def test_segment_above_sam_cap_asks_shorter():
    out = _classify_chat(
        "remove o fundo", True,
        segment={"start_s": 0.0, "end_s": 600.0},
        duration_s=1800.0, fps=30.0,
    )
    assert out["needs_confirmation"] is False
    assert out["pending_text"] is None
    assert "15" in out["reply"] and "curto" in out["reply"].lower()


def test_short_video_without_segment_keeps_existing_flow():
    out = _classify_chat("remove o fundo", True, duration_s=6.0, fps=30.0)
    assert out["needs_confirmation"] is True
    assert out["pending_kind"] == "edit"
    assert "pending_segment" not in out
