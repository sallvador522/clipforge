"""ADR-044 timeline API + worker composition (mock transports, real FFmpeg)."""

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker


def _ffmpeg(*args) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]


def _tiny_video(path: Path, duration: float = 2.0) -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=size=64x36:rate=10:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    )
    return path


def _tiny_wav(path: Path, duration: float = 1.0) -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=880:duration={duration}",
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", str(path),
    )
    return path


def _client(tmp_path):
    providers = get_providers("mock")
    app = create_app(storage_root=tmp_path / "storage", providers=providers)
    http = TestClient(app)
    return http, tmp_path / "storage"


def _upload_session(http, path: Path) -> dict:
    with path.open("rb") as handle:
        response = http.post("/api/uploads", files={"file": ("session.mp4", handle, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()


def _import_asset(http, project_id: str, path: Path, filename: str, ctype: str) -> dict:
    with path.open("rb") as handle:
        response = http.post(
            f"/api/projects/{project_id}/assets",
            files={"file": (filename, handle, ctype)},
        )
    assert response.status_code == 201, response.text
    return response.json()


def _assets_by_name(http, project_id: str) -> dict:
    items = http.get(f"/api/projects/{project_id}/assets").json()["assets"]
    return {item["original_filename"]: item for item in items}


def _setup(http, tmp_path):
    """Session job + a second video asset + an audio asset. Returns ids."""
    session_path = _tiny_video(tmp_path / "session.mp4")
    job = _upload_session(http, session_path)
    project_id = job["project_id"]
    second_path = _tiny_video(tmp_path / "second.mp4")
    _import_asset(http, project_id, second_path, "second.mp4", "video/mp4")
    wav_path = _tiny_wav(tmp_path / "note.wav")
    _import_asset(http, project_id, wav_path, "note.wav", "audio/wav")
    assets = _assets_by_name(http, project_id)
    return job, assets


def _put(http, job_id, payload):
    return http.put(f"/api/jobs/{job_id}/timeline", json=payload)


def test_timeline_get_empty_and_put_valid(tmp_path):
    http, _ = _client(tmp_path)
    job, assets = _setup(http, tmp_path)
    job_id = job["job_id"]
    assert http.get(f"/api/jobs/{job_id}/timeline").json() == {
        "timeline": {"clips": []}, "program_duration_s": 0.0,
    }
    payload = {"timeline": {"clips": [
        {"clip_id": "clip_aaaaaaaaaaaa", "asset_id": assets["session.mp4"]["asset_id"],
         "track": "V1", "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 2.0},
        {"clip_id": "clip_bbbbbbbbbbbb", "asset_id": assets["second.mp4"]["asset_id"],
         "track": "V2", "timeline_start_s": 1.0, "source_in_s": 0.0, "source_out_s": 1.0},
        {"clip_id": "clip_cccccccccccc", "asset_id": assets["note.wav"]["asset_id"],
         "track": "A1", "timeline_start_s": 0.5, "source_in_s": 0.0, "source_out_s": 1.0},
    ]}}
    response = _put(http, job_id, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["program_duration_s"] == 2.0
    assert len(body["timeline"]["clips"]) == 3
    assert http.get(f"/api/jobs/{job_id}/timeline").json()["program_duration_s"] == 2.0


def test_timeline_rejects_overlap_and_mismatch_and_range(tmp_path):
    http, _ = _client(tmp_path)
    job, assets = _setup(http, tmp_path)
    job_id = job["job_id"]
    session = assets["session.mp4"]["asset_id"]
    second = assets["second.mp4"]["asset_id"]
    wav = assets["note.wav"]["asset_id"]

    def one(clip):
        return {"timeline": {"clips": [clip]}}

    def clip(cid, asset, track, start=0.0, inn=0.0, out=1.0):
        return {"clip_id": cid, "asset_id": asset, "track": track,
                "timeline_start_s": start, "source_in_s": inn, "source_out_s": out}

    # Overlap on the same track (contract-level 422 from FastAPI).
    response = _put(http, job_id, {"timeline": {"clips": [
        clip("clip_aaaaaaaaaaaa", session, "V1", 0.0, 0.0, 2.0),
        clip("clip_bbbbbbbbbbbb", session, "V1", 1.0, 0.0, 1.0),
    ]}})
    assert response.status_code == 422
    # Video on an audio track.
    response = _put(http, job_id, one(clip("clip_aaaaaaaaaaaa", session, "A1")))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "timeline_track_mismatch"
    # Audio on a video track.
    response = _put(http, job_id, one(clip("clip_aaaaaaaaaaaa", wav, "V1")))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "timeline_track_mismatch"
    # Source beyond the asset duration.
    response = _put(http, job_id, one(clip("clip_aaaaaaaaaaaa", session, "V1", 0.0, 0.0, 60.0)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "timeline_source_out_of_range"
    # Unknown asset.
    response = _put(http, job_id, one(clip("clip_aaaaaaaaaaaa", "ast_000000000000", "V1")))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "timeline_asset_not_found"
    # Failed body stays untouched.
    assert http.get(f"/api/jobs/{job_id}/timeline").json()["timeline"] == {"clips": []}


def test_timeline_put_allows_browser_preflight(tmp_path):
    """Regression: the studio PUTs JSON from :3000, so OPTIONS preflight must
    allow PUT or the browser reports the API as unreachable on every drop."""
    http, _ = _client(tmp_path)
    job, assets = _setup(http, tmp_path)
    job_id = job["job_id"]
    session = assets["session.mp4"]["asset_id"]
    origin = {"Origin": "http://localhost:3000"}
    preflight = http.options(
        f"/api/jobs/{job_id}/timeline",
        headers={**origin,
                 "Access-Control-Request-Method": "PUT",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert preflight.status_code == 200, preflight.text
    assert "PUT" in preflight.headers.get("access-control-allow-methods", "")
    payload = {"timeline": {"clips": [
        {"clip_id": "clip_aaaaaaaaaaaa", "asset_id": session,
         "track": "V1", "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 1.0},
    ]}}
    response = http.put(f"/api/jobs/{job_id}/timeline", json=payload, headers=origin)
    assert response.status_code == 200, response.text


def test_timeline_render_rejects_bad_format(tmp_path):
    http, _ = _client(tmp_path)
    job, assets = _setup(http, tmp_path)
    job_id = job["job_id"]
    session = assets["session.mp4"]["asset_id"]
    payload = {"timeline": {"clips": [{
        "clip_id": "clip_aaaaaaaaaaaa", "asset_id": session, "track": "V1",
        "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 2.0}]}}
    assert _put(http, job_id, payload).status_code == 200
    response = http.post(f"/api/jobs/{job_id}/timeline/render", json={"format": "square"})
    assert response.status_code == 422


def test_timeline_render_explicit_landscape_overrides_source(tmp_path):
    """User explicitly chooses 16:9 over the tiny portrait-ish source."""
    http, storage = _client(tmp_path)
    job, assets = _setup(http, tmp_path)
    job_id = job["job_id"]
    session = assets["session.mp4"]["asset_id"]
    payload = {"timeline": {"clips": [{
        "clip_id": "clip_aaaaaaaaaaaa", "asset_id": session, "track": "V1",
        "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 2.0}]}}
    assert _put(http, job_id, payload).status_code == 200
    response = http.post(f"/api/jobs/{job_id}/timeline/render", json={"format": "landscape"})
    assert response.status_code == 200, response.text
    assert response.json()["timeline_format"] == "landscape"

    store = JobStore(storage)
    from clipforge_worker.worker_process import PersistentWorker
    worker = PersistentWorker(store, get_providers("mock"), poll_seconds=0.05)
    for _ in range(20):
        if not worker.run_once():
            break
    body = http.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "completed", body.get("error")
    out_path = storage / body["result"]["rendered"]["output_relative_path"]
    probe = _ffprobe(out_path)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (int(video["width"]), int(video["height"])) == (1280, 720)


def test_timeline_not_allowed_once_voice_attached(tmp_path):
    http, _ = _client(tmp_path)
    job, _ = _setup(http, tmp_path)
    job_id = job["job_id"]
    voice = http.post(f"/api/jobs/{job_id}/voice", json={"transcript": "blur the background please"})
    assert voice.status_code == 200, voice.text
    response = _put(http, job_id, {"timeline": {"clips": []}})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "timeline_not_allowed"


def test_timeline_render_empty_rejected(tmp_path):
    http, _ = _client(tmp_path)
    job, _ = _setup(http, tmp_path)
    response = http.post(f"/api/jobs/{job['job_id']}/timeline/render")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "timeline_empty"


def _ffprobe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-300:]
    import json
    return json.loads(result.stdout)


def test_timeline_render_end_to_end(tmp_path):
    http, storage = _client(tmp_path)
    job, assets = _setup(http, tmp_path)
    job_id = job["job_id"]
    session = assets["session.mp4"]["asset_id"]
    second = assets["second.mp4"]["asset_id"]
    wav = assets["note.wav"]["asset_id"]
    payload = {"timeline": {"clips": [
        {"clip_id": "clip_aaaaaaaaaaaa", "asset_id": session,
         "track": "V1", "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 2.0},
        {"clip_id": "clip_bbbbbbbbbbbb", "asset_id": second,
         "track": "V2", "timeline_start_s": 1.0, "source_in_s": 0.0, "source_out_s": 1.0},
        {"clip_id": "clip_cccccccccccc", "asset_id": wav,
         "track": "A1", "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 1.0},
    ]}}
    assert _put(http, job_id, payload).status_code == 200
    # Default canvas preserves the tiny source (64x36@10fps, no fixed 1280x720).
    response = http.post(f"/api/jobs/{job_id}/timeline/render", json={"format": "source"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["timeline_format"] == "source"

    store = JobStore(storage)
    from clipforge_worker.worker_process import PersistentWorker
    worker = PersistentWorker(store, get_providers("mock"), poll_seconds=0.05)
    for _ in range(20):
        if not worker.run_once():
            break
    body = http.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "completed", body.get("error")
    rendered = body["result"]["rendered"]
    assert body["result"]["render_status"] == "verified"
    out_path = storage / rendered["output_relative_path"]
    assert out_path.is_file()
    probe = _ffprobe(out_path)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (int(video["width"]), int(video["height"])) == (64, 36)
    num, _, den = video["avg_frame_rate"].partition("/")
    assert abs(float(num) / float(den or 1) - 10.0) < 0.1
    assert any(s["codec_type"] == "audio" for s in probe["streams"])
    duration = float(probe["format"]["duration"])
    assert abs(duration - 2.0) < 0.3

    download = http.get(f"/api/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    assert int(download.headers["content-length"]) > 10_000
