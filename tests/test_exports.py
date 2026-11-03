import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipforge_api.exports import ExportError, export_video
from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker


W, H, FPS, FRAMES = 64, 36, 10.0, 10


def _make_video(path: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={W}x{H}:rate={FPS}:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-300:]
    return path


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    return json.loads(result.stdout)


def _completed_client(tmp_path: Path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    worker = PersistentWorker(store, providers, poll_seconds=0.05)
    source = _make_video(tmp_path / "clip.mp4")
    with open(source, "rb") as fh:
        job_id = client.post("/api/uploads", files={"file": ("clip.mp4", fh, "video/mp4")}).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_keep_me_sharp"})
    while worker.run_once():
        pass
    review = client.get(f"/api/jobs/{job_id}/plan").json()
    subject_ids = [s["object_id"] for s in review["subjects"]][:1]
    assert client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": subject_ids}).status_code == 200
    while worker.run_once():
        pass
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
    return client, job_id


def test_export_rejects_unknown_format(tmp_path):
    client, job_id = _completed_client(tmp_path)
    resp = client.get(f"/api/jobs/{job_id}/download?format=square")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_export_format"


def test_export_reels_and_youtube_are_real_verified_files(tmp_path):
    client, job_id = _completed_client(tmp_path)

    reels = client.get(f"/api/jobs/{job_id}/download?format=reels")
    assert reels.status_code == 200
    assert reels.headers["content-type"].startswith("video/mp4")
    assert "reels" in reels.headers.get("content-disposition", "")
    reels_path = tmp_path / "reels.mp4"
    reels_path.write_bytes(reels.content)
    data = _probe(reels_path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (int(video["width"]), int(video["height"])) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in data["streams"])

    youtube = client.get(f"/api/jobs/{job_id}/download?format=youtube")
    assert youtube.status_code == 200
    yt_path = tmp_path / "yt.mp4"
    yt_path.write_bytes(youtube.content)
    data = _probe(yt_path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (int(video["width"]), int(video["height"])) == (1920, 1080)

    # Cache hit returns the same file; original stays untouched.
    again = client.get(f"/api/jobs/{job_id}/download?format=reels")
    assert again.content == reels.content
    original = client.get(f"/api/jobs/{job_id}/download")
    assert original.status_code == 200
    assert original.content != reels.content


def test_export_video_unit_rejects_unknown(tmp_path):
    with pytest.raises(ExportError):
        export_video(tmp_path, tmp_path / "missing.mp4", "square")
