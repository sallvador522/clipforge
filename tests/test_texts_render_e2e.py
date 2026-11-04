"""ADR-047 end-to-end: persisted texts + colour -> real timeline composition.

Real execution only: ffmpeg-generated source, real worker composition,
ffprobe verification, frame-level proof that the overlay is burned in
inside its window (and absent outside it), then a Muse tool edit followed
by a second verified render. No mocks of the pipeline.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker


def _ffmpeg(*args: str) -> None:
    result = subprocess.run(["ffmpeg", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
         "-of", "json", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
    return json.loads(result.stdout)


def _grab_frame(video: Path, at_s: float, out: Path) -> None:
    _ffmpeg("-y", "-ss", f"{at_s:.2f}", "-i", str(video),
            "-frames:v", "1", str(out))


def _read_png(path: Path) -> np.ndarray:
    import cv2

    frame = cv2.imread(str(path))
    assert frame is not None
    return frame


def _run_until_done(worker: PersistentWorker, job_id: str, store: JobStore, limit: int = 60) -> str:
    for _ in range(limit):
        worker.run_once()
        status = store.get(job_id).status.value
        if status in ("completed", "failed"):
            return status
    raise AssertionError("worker did not finish in time")


def test_texts_and_colour_render_into_verified_mp4(tmp_path):
    bundle = get_providers("mock")
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)

    # Real source: solid red + tone, generated locally by FFmpeg.
    src = tmp_path / "src.mp4"
    _ffmpeg("-y", "-f", "lavfi", "-i", "color=c=red:size=320x180:rate=30:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
    with open(src, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": ("src.mp4", fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    project_id = upload.json()["project_id"]
    assert project_id

    # Persist the overlay + grade through the real API.
    texts = client.put(f"/api/jobs/{job_id}/texts", json={"texts": [{
        "overlay_id": "txt_e2e00001", "text": "A TUA MARCA AQUI",
        "style": "rise", "start_s": 0.0, "duration_s": 2.0,
        "x": 0.5, "y": 0.5, "scale": 1.2, "color": "#FFD400", "weight": "bold",
    }]})
    assert texts.status_code == 200, texts.text
    coloured = client.put(f"/api/jobs/{job_id}/colour",
                          json={"contrast": 1.15, "brightness": 0.05, "saturation": 1.2})
    assert coloured.status_code == 200, coloured.text

    # Timeline: whole clip on V1. Asset lookup from the project library.
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    assert len(assets) >= 1
    asset_id = assets[0]["asset_id"]
    timeline = client.put(f"/api/jobs/{job_id}/timeline", json={"timeline": {"clips": [{
        "clip_id": "clip_abcdef123456", "asset_id": asset_id, "track": "V1",
        "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 3.0}]}})
    assert timeline.status_code == 200, timeline.text

    rendered = client.post(f"/api/jobs/{job_id}/timeline/render", json={"format": "landscape"})
    assert rendered.status_code == 200, rendered.text
    assert _run_until_done(worker, job_id, store) == "completed"

    out = store.job_dir(job_id) / "output_timeline.mp4"
    assert out.is_file() and out.stat().st_size > 0
    probe = _probe(out)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (1280, 720)
    assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
    assert abs(float(probe["format"]["duration"]) - 3.0) < 0.15
    assert int(video["nb_read_frames"]) == 90

    # Frame proof: text pixels inside the window, clean red outside it.
    inside = tmp_path / "inside.png"
    outside = tmp_path / "outside.png"
    _grab_frame(out, 1.0, inside)
    _grab_frame(out, 2.8, outside)
    fi = _read_png(inside).astype(np.int32)
    fo = _read_png(outside).astype(np.int32)
    h, w = fi.shape[:2]
    cy, cx = slice(int(h * 0.35), int(h * 0.65)), slice(int(w * 0.3), int(w * 0.7))
    # Yellow text on red: strong green channel where the text is.
    assert int(((fi[cy, cx][:, :, 1] > 120)).sum()) > 300
    # Outside the window the centre is uniform graded red (no overlay).
    centre = fo[cy, cx]
    spatial_std = max(float(centre[:, :, c].std()) for c in range(3))
    assert spatial_std < 12, spatial_std

    # Muse tool edit on the completed job: real proposal -> real execution.
    chat = client.post("/api/chat", json={
        "message": "Muda o texto para 'Luz e forma'",
        "job_id": job_id, "selected_text_id": "txt_e2e00001"})
    assert chat.status_code == 200, chat.text
    calls = chat.json()["pending_tool_calls"]
    assert len(calls) == 1 and calls[0]["tool"] == "text.update"
    assert calls[0]["params"]["text"] == "Luz e forma"
    done = client.post(f"/api/jobs/{job_id}/tools/execute",
                       json={"tool": calls[0]["tool"], "params": calls[0]["params"]})
    assert done.status_code == 200, done.text
    assert store.get(job_id).clip_texts[0].text == "Luz e forma"

    # Second render carries the edited text; output stays verified.
    second = client.post(f"/api/jobs/{job_id}/timeline/render", json={"format": "landscape"})
    assert second.status_code == 200, second.text
    assert _run_until_done(worker, job_id, store) == "completed"
    again = tmp_path / "again.png"
    _grab_frame(out, 1.0, again)
    fa = _read_png(again).astype(np.int32)
    assert not np.array_equal(fi, fa)
