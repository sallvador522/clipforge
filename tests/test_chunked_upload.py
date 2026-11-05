"""Resumable chunked session upload (ADR-057, production).

PUT raw chunk bodies; the server assembles in order and runs the standard
session-upload finalize (probe, job, asset). No job exists until complete
succeeds; aborted/invalid uploads leave no orphans.
"""

import subprocess

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers


def _client(tmp_path):
    store = JobStore(tmp_path / "storage")
    return TestClient(create_app(storage_root=tmp_path / "storage", providers=get_providers("mock"))), store


def _clip(tmp_path, name="chunked.mp4", duration=2):
    path = tmp_path / name
    result = subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=64x36:rate=10:duration={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg unavailable: {result.stderr[-200:]}")
    return path


def _split(data: bytes, n: int) -> list[bytes]:
    size = (len(data) + n - 1) // n
    return [data[i * size:(i + 1) * size] for i in range(n)]


def test_chunked_roundtrip_is_byte_identical(tmp_path):
    client, store = _client(tmp_path)
    raw = _clip(tmp_path).read_bytes()
    parts = _split(raw, 4)
    init = client.post("/api/uploads/chunked", json={
        "filename": "clip.mp4", "total_bytes": len(raw), "total_chunks": 4})
    assert init.status_code == 201, init.text
    upload_id = init.json()["upload_id"]
    for i, part in enumerate(parts):
        resp = client.put(f"/api/uploads/chunked/{upload_id}/{i}", content=part,
                          headers={"Content-Type": "application/octet-stream"})
        assert resp.status_code == 200, resp.text
    done = client.post(f"/api/uploads/chunked/{upload_id}/complete")
    assert done.status_code == 201, done.text
    job = store.get(done.json()["job_id"])
    stored = (tmp_path / "storage" / job.source_relative_path).read_bytes()
    assert stored == raw


def test_chunked_resume_and_missing_chunks(tmp_path):
    client, _ = _client(tmp_path)
    raw = _clip(tmp_path).read_bytes()
    parts = _split(raw, 3)
    init = client.post("/api/uploads/chunked", json={
        "filename": "clip.mp4", "total_bytes": len(raw), "total_chunks": 3})
    upload_id = init.json()["upload_id"]
    client.put(f"/api/uploads/chunked/{upload_id}/0", content=parts[0])
    status = client.get(f"/api/uploads/chunked/{upload_id}")
    assert status.json()["received"] == [0]
    early = client.post(f"/api/uploads/chunked/{upload_id}/complete")
    assert early.status_code == 409, early.text
    assert "1" in early.json()["error"]["message"]
    # Resume the rest; duplicate PUT of chunk 0 stays idempotent.
    client.put(f"/api/uploads/chunked/{upload_id}/0", content=parts[0])
    client.put(f"/api/uploads/chunked/{upload_id}/1", content=parts[1])
    client.put(f"/api/uploads/chunked/{upload_id}/2", content=parts[2])
    assert client.post(f"/api/uploads/chunked/{upload_id}/complete").status_code == 201


def test_chunked_rejects_bad_shapes(tmp_path):
    client, _ = _client(tmp_path)
    raw = _clip(tmp_path).read_bytes()
    bad_ext = client.post("/api/uploads/chunked", json={
        "filename": "evil.exe", "total_bytes": 10, "total_chunks": 1})
    assert bad_ext.status_code == 422
    too_many = client.post("/api/uploads/chunked", json={
        "filename": "c.mp4", "total_bytes": 10, "total_chunks": 99999})
    assert too_many.status_code == 422
    assert client.post("/api/uploads/chunked", json={
        "filename": "c.mp4", "total_bytes": 10, "total_chunks": 1,
        "project_id": "prj_missing"}).status_code == 404
    init = client.post("/api/uploads/chunked", json={
        "filename": "clip.mp4", "total_bytes": len(raw), "total_chunks": 1})
    upload_id = init.json()["upload_id"]
    assert client.put(f"/api/uploads/chunked/{upload_id}/7", content=b"x").status_code == 422
    assert client.put(f"/api/uploads/chunked/{upload_id}/0", content=b"").status_code == 422
    assert client.get("/api/uploads/chunked/deadbeefdeadbeefdeadbeefdeadbeef").status_code == 404
    # Size mismatch on complete.
    client.put(f"/api/uploads/chunked/{upload_id}/0", content=raw + b"extra")
    mismatch = client.post(f"/api/uploads/chunked/{upload_id}/complete")
    assert mismatch.status_code == 422, mismatch.text
    assert mismatch.json()["error"]["code"] == "size_mismatch"


def test_chunked_abort_cleans_up(tmp_path):
    client, _ = _client(tmp_path)
    raw = _clip(tmp_path).read_bytes()
    init = client.post("/api/uploads/chunked", json={
        "filename": "clip.mp4", "total_bytes": len(raw), "total_chunks": 2})
    upload_id = init.json()["upload_id"]
    client.put(f"/api/uploads/chunked/{upload_id}/0", content=raw[:10])
    assert client.delete(f"/api/uploads/chunked/{upload_id}").status_code == 200
    assert client.get(f"/api/uploads/chunked/{upload_id}").status_code == 404


def test_over_30min_video_rejected_honestly(tmp_path):
    """Production cap: a 31-min clip is refused with duration_too_long, no job."""
    path = tmp_path / "long.mp4"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1860",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1860",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(path)],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("31-min fixture encode timed out on this host")
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate long fixture: {result.stderr[-200:]}")
    client, store = _client(tmp_path)
    with path.open("rb") as fh:
        upload = client.post("/api/uploads", files={"file": ("long.mp4", fh, "video/mp4")})
    assert upload.status_code == 422, upload.text
    assert upload.json()["error"]["code"] == "duration_too_long"
    assert len(store.list_jobs()) == 0


def test_chunked_invalid_media_leaves_no_orphans(tmp_path):
    client, store = _client(tmp_path)
    payload = b"\x00\x01\x02\x03" * 1024
    init = client.post("/api/uploads/chunked", json={
        "filename": "clip.mp4", "total_bytes": len(payload), "total_chunks": 1})
    upload_id = init.json()["upload_id"]
    client.put(f"/api/uploads/chunked/{upload_id}/0", content=payload)
    before = len(store.list_jobs())
    resp = client.post(f"/api/uploads/chunked/{upload_id}/complete")
    assert resp.status_code == 422, resp.text
    assert len(store.list_jobs()) == before
