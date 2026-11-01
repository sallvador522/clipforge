import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_contracts import DirectorAudit
from clipforge_jobs import JobResult, JobStatus, JobStore
from clipforge_providers import get_providers
from clipforge_worker.masks import MaskLoader
from clipforge_worker.worker_process import PersistentWorker


@pytest.fixture(scope="session")
def tiny_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "tiny.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate test clip: {result.stderr[-300:]}")
    return path


@pytest.fixture()
def env(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    worker = PersistentWorker(store, providers, poll_seconds=0.05)
    return client, store, worker


def _upload(client, tiny_video, name="clip.mp4"):
    with open(tiny_video, "rb") as fh:
        return client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})


def _drain(worker, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not worker.run_once():
            return
    raise AssertionError("worker did not drain the queue in time")


def test_health_reports_mock_mode(env):
    client, _, _ = env
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["ai_mode"] == "mock"


def test_cors_allows_local_studio_origin(env):
    client, _, _ = env
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_upload_validation_rejects_bad_inputs(env, tmp_path):
    client, _, _ = env
    bad = tmp_path / "notes.txt"
    bad.write_text("not a video")
    with open(bad, "rb") as fh:
        resp = client.post("/api/uploads", files={"file": ("notes.txt", fh, "text/plain")})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "unsupported_extension"

    resp = client.post("/api/uploads", files={"file": ("empty.mp4", b"", "video/mp4")})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "empty_file"

    resp = client.post("/api/uploads", files={"file": ("fake.mp4", b"not really mp4", "video/mp4")})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "unreadable_media"


def test_upload_sanitizes_filename_and_creates_queued_job(env, tiny_video):
    client, store, _ = env
    resp = _upload(client, tiny_video, name="../../evil/clip.mp4")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued" and body["stage"] == "awaiting_voice" and body["ready"] is False
    assert body["original_filename"] == "clip.mp4"  # path components stripped
    record = store.get(body["job_id"])
    assert store.source_path(record).is_file()
    assert body["source_info"]["width"] == 64 and body["source_info"]["frame_count"] >= 9


def test_result_serializes_director_audit_with_datetime(env, tiny_video):
    client, store, _ = env
    job_id = _upload(client, tiny_video).json()["job_id"]
    audit = DirectorAudit(
        request_id="req_abcdef123456",
        server_request_id="srv-audit-1",
        provider="meta-muse-spark-director-lite",
        model="muse-spark-1.3-contributor",
        service_mode="contributor",
        wire_schema="lite",
        prompt_tokens=2781,
        completion_tokens=1856,
        total_tokens=4637,
        estimated_cost_usd=0.000649,
        validation_status="accepted",
        http_status=200,
        finish_reason="stop",
    )
    store.update(
        job_id,
        status=JobStatus.COMPLETED,
        stage="completed",
        result=JobResult(director_audit=audit, render_status="awaiting_approval"),
    )

    resp = client.get(f"/api/jobs/{job_id}/result")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["director_audit"]["request_id"] == "req_abcdef123456"
    assert body["director_audit"]["validation_status"] == "accepted"
    assert isinstance(body["director_audit"]["recorded_at"], str)


def test_complete_mock_job_lifecycle(env, tiny_video):
    client, store, worker = env
    job_id = _upload(client, tiny_video).json()["job_id"]

    # Non-blocking: no worker has run, status retrieval is instant and job stays queued.
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    assert client.get(f"/api/jobs/{job_id}/result").status_code == 409

    resp = client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_keep_me_sharp"})
    assert resp.status_code == 200 and resp.json()["ready"] is True

    _drain(worker)
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "completed" and body["attempts"] == 1
    assert body["error"] is None

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    data = result.json()
    assert data["plan"]["intent"] == "keep_sharp_blur_rest"
    assert data["render_status"] == "verified"  # real renderer since Milestone 4
    assert data["rendered"]["mode"] == "blur_background" and data["rendered"]["has_audio"] is True
    assert (store.job_dir(job_id) / "output.mp4").stat().st_size > 0
    assert data["segmentation"]["is_mock"] is True

    # Masks on disk are real and valid; original upload is preserved.
    seq = MaskLoader().load(store.job_dir(job_id) / "masks")
    assert len(seq) == data["segmentation"]["frame_count"]
    assert store.source_path(store.get(job_id)).is_file()

    # Voice can no longer be attached to a completed job.
    resp = client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_keep_me_sharp"})
    assert resp.status_code == 409


def test_replace_background_lifecycle_includes_background_asset(env, tiny_video):
    client, _, worker = env
    job_id = _upload(client, tiny_video).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_replace_background_studio"})
    _drain(worker)
    data = client.get(f"/api/jobs/{job_id}/result").json()
    assert data["plan"]["intent"] == "replace_background"
    assert data["background"]["is_mock"] is True
    assert Path(data["background"]["image_path"]).is_file()


def test_clarification_lifecycle_completes_without_segmentation(env, tiny_video):
    client, store, worker = env
    job_id = _upload(client, tiny_video).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_ambiguous_person"})
    _drain(worker)
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "completed" and body["stage"] == "clarification_needed"
    data = client.get(f"/api/jobs/{job_id}/result").json()
    assert data["requires_clarification"] is True and data["segmentation"] is None
    assert not (store.job_dir(job_id) / "masks").exists()


def test_failed_job_is_isolated_and_original_preserved(env, tiny_video):
    client, store, worker = env
    bad_id = _upload(client, tiny_video).json()["job_id"]
    good_id = _upload(client, tiny_video).json()["job_id"]
    client.post(f"/api/jobs/{bad_id}/voice", json={"audio_fixture_id": "unknown-fixture"})
    client.post(f"/api/jobs/{good_id}/voice", json={"audio_fixture_id": "pt_blur_people_behind"})
    _drain(worker)
    _drain(worker)

    bad = client.get(f"/api/jobs/{bad_id}").json()
    assert bad["status"] == "failed" and bad["error"]["code"] == "FixtureNotFoundError"
    assert store.source_path(store.get(bad_id)).is_file()  # original preserved on failure

    good = client.get(f"/api/jobs/{good_id}").json()
    assert good["status"] == "completed"


def test_job_not_found_shape(env):
    client, _, _ = env
    resp = client.get("/api/jobs/nope")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "job_not_found"


def test_claim_is_exclusive(env, tiny_video):
    client, store, _ = env
    job_id = _upload(client, tiny_video).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_keep_me_sharp"})
    assert store.claim(job_id) is not None
    assert store.claim(job_id) is None  # already processing / claimed


def test_persistent_worker_thread_processes_job(env, tiny_video):
    client, _, worker = env
    job_id = _upload(client, tiny_video).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_blur_people_behind"})

    stop = threading.Event()

    def loop():
        while not stop.is_set():
            if not worker.run_once():
                time.sleep(0.05)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            status = client.get(f"/api/jobs/{job_id}").json()["status"]
            if status in {JobStatus.COMPLETED.value, JobStatus.FAILED.value}:
                break
            time.sleep(0.05)
        assert status == "completed"
    finally:
        stop.set()
        thread.join(timeout=5)
