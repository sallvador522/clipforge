"""ADR-051 source canvas, guaranteed-fit captions, verify-and-redo gate.

Real FFmpeg/OpenCV composition only (mock transports). No paid calls.
"""

from __future__ import annotations

import json
import subprocess

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_contracts import ClipTextOverlay
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker import timeline_render as tr
from clipforge_worker.worker_process import PersistentWorker


def _ffmpeg(*args) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]


def _client(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    return client, store


def _clip(tmp_path, name, size="64x36", rate=10, duration=2):
    path = tmp_path / name
    _ffmpeg("-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))
    return path


def _upload(client, path, name):
    with open(path, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    return upload.json()


def test_fit_wraps_long_line_inside_frame():
    lines, font = tr._fit_overlay_lines(
        "Esta e uma legenda muito comprida que nunca pode sair do video", 331, 52, True)
    assert len(lines) >= 2
    for line in lines:
        width, _ = tr._measure(line, font)
        assert width <= 331


def test_fit_never_exceeds_frame_on_tiny_canvas():
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    overlay = ClipTextOverlay.model_validate({
        "overlay_id": "txt_fit000000001", "text": "Uma frase bastante comprida para um video pequeno",
        "start_s": 0.0, "duration_s": 2.0, "x": 0.5, "y": 0.82, "scale": 1.0})
    out = tr.draw_text_overlays(frame.copy(), [overlay], t=1.0)
    assert out.shape == frame.shape
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    assert n > 1  # text was burned
    right = max(stats[i, 0] + stats[i, 2] for i in range(1, n))
    bottom = max(stats[i, 1] + stats[i, 3] for i in range(1, n))
    assert right < 320 and bottom < 180  # fully inside the frame


def _dark_clip(tmp_path, name, size="128x96", duration=2):
    path = tmp_path / name
    _ffmpeg("-f", "lavfi", "-i", f"color=c=0x202020:size={size}:rate=10:duration={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))
    return path


def test_verify_legibility_pass_and_fail(tmp_path):
    client, store = _client(tmp_path)
    _dark_clip(tmp_path, "src.mp4")
    job = _upload(client, tmp_path / "src.mp4", "src.mp4")
    job_id, project_id = job["job_id"], job["project_id"]
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    asset_id = assets[0]["asset_id"]
    texts = client.put(f"/api/jobs/{job_id}/texts", json={"texts": [{
        "overlay_id": "txt_verify000001", "text": "Legenda visivel aqui",
        "start_s": 0.0, "duration_s": 2.0}]})
    assert texts.status_code == 200, texts.text
    assert client.put(f"/api/jobs/{job_id}/timeline", json={"timeline": {"clips": [{
        "clip_id": "clip_abcdef123456", "asset_id": asset_id, "track": "V1",
        "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 2.0}]}}).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/timeline/render").status_code == 200
    worker = PersistentWorker(store, get_providers("mock"), poll_seconds=0.05)
    for _ in range(60):
        if not worker.run_once():
            break
    out = store.job_dir(job_id) / "output_timeline.mp4"
    overlays = store.get(job_id).clip_texts
    assert tr.verify_caption_legibility(out, overlays, fps=10.0) == []
    # Same overlays against a captionless render must fail honestly.
    assert client.put(f"/api/jobs/{job_id}/texts", json={"texts": []}).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/timeline/render").status_code == 200
    for _ in range(60):
        if not worker.run_once():
            break
    failures = tr.verify_caption_legibility(out, overlays, fps=10.0)
    assert failures and failures[0]["overlay_id"] == "txt_verify000001"


def test_source_canvas_preserves_portrait(tmp_path):
    client, store = _client(tmp_path)
    _clip(tmp_path, "vert.mp4", size="36x64", duration=2)
    job = _upload(client, tmp_path / "vert.mp4", "vert.mp4")
    job_id, project_id = job["job_id"], job["project_id"]
    assert job["source_info"]["width"] == 36 and job["source_info"]["height"] == 64
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    asset_id = assets[0]["asset_id"]
    assert client.put(f"/api/jobs/{job_id}/timeline", json={"timeline": {"clips": [{
        "clip_id": "clip_abcdef123456", "asset_id": asset_id, "track": "V1",
        "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 2.0}]}}).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/timeline/render").status_code == 200
    worker = PersistentWorker(store, get_providers("mock"), poll_seconds=0.05)
    for _ in range(60):
        if not worker.run_once():
            break
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "completed", body.get("error")
    out = store.root / body["result"]["rendered"]["output_relative_path"]
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (int(video["width"]), int(video["height"])) == (36, 64)
