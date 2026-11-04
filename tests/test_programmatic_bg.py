"""ADR-052 Magic Background: programmatic animated backdrop, end to end (mock).

Real FFmpeg/OpenCV composition with synthetic masks (mock AI only).
No paid calls, no image generation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_contracts.capabilities import ProgrammaticBackdrop, ReplaceBackgroundParams
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker import programmatic_bg
from clipforge_worker.programmatic_bg import render_frame
from clipforge_worker.renderer import RenderRequest, render_video
from clipforge_worker.worker_process import PersistentWorker

W, H = 64, 36
FPS = 10
FRAMES = 20


def _ffmpeg(*args) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-300:]


def _client(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    return client, store


def _upload(client, path: Path, name: str = "clip.mp4") -> dict:
    with open(path, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": (name, fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    return upload.json()


def _make_clip(path: Path, size: str = "64x36", duration: int = 4) -> Path:
    _ffmpeg("-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))
    return path


SPEC = {
    "gradient_top": "#0B1E3A",
    "gradient_bottom": "#2E6BE6",
    "shapes": [
        {"kind": "ring", "color": "#7FB0FF", "size": 0.16, "speed": 0.4, "phase": 0.0},
        {"kind": "circle", "color": "#FFD9A0", "size": 0.07, "speed": 0.6, "phase": 1.2},
    ],
    "motion": "subtle",
}


def test_backdrop_contract_validation():
    good = ProgrammaticBackdrop.model_validate(SPEC)
    assert good.motion == "subtle" and len(good.shapes) == 2
    with pytest.raises(Exception):
        ProgrammaticBackdrop.model_validate({**SPEC, "gradient_top": "blue"})
    with pytest.raises(Exception):
        ProgrammaticBackdrop.model_validate({**SPEC, "shapes": [{"kind": "star", "color": "#FFFFFF"}]})
    # asset_source rules are enforced on both contracts.
    with pytest.raises(Exception):
        ReplaceBackgroundParams.model_validate(
            {"prompt": "x", "asset_source": "programmatic"})
    with pytest.raises(Exception):
        ReplaceBackgroundParams.model_validate(
            {"prompt": "x", "asset_source": "local_asset",
             "backdrop": SPEC})
    ok = ReplaceBackgroundParams.model_validate(
        {"prompt": "blue studio", "asset_source": "programmatic", "backdrop": SPEC})
    assert ok.backdrop is not None and ok.backdrop.gradient_bottom == "#2E6BE6"


def test_backdrop_frame_is_deterministic_and_animated():
    first = render_frame(1.0, W, H, SPEC)
    assert np.array_equal(first, render_frame(1.0, W, H, SPEC))
    later = render_frame(1.5, W, H, SPEC)
    assert not np.array_equal(first, later)  # motion actually advances
    assert first.shape == (H, W, 3) and first.dtype == np.uint8
    # Vertical gradient: top is darker than the bottom for this spec.
    assert float(first[:4].mean()) < float(first[-4:].mean())


def test_backdrop_frame_rejects_bad_spec():
    with pytest.raises(Exception):
        render_frame(0.0, W, H, {"gradient_top": "not-a-color", "gradient_bottom": "#000000"})
    with pytest.raises(Exception):
        render_frame(0.0, 0, H, SPEC)


def _masks_with_subject(directory: Path, frames: int = FRAMES) -> None:
    from clipforge_worker.masks import MaskWriter

    yy, xx = np.mgrid[0:H, 0:W]
    masks = [np.where(((yy - 18) ** 2 + (xx - (10 + i * 2)) ** 2) <= 64, 255, 0).astype(np.uint8)
             for i in range(frames)]
    MaskWriter().write_sequence(directory, masks, fps=FPS, subject_id="person_1", source_video_id="tiny")


def test_replace_with_programmatic_backdrop_renders_and_moves(tmp_path):
    src = _make_clip(tmp_path / "src.mp4", duration=2)
    masks = tmp_path / "masks"
    _masks_with_subject(masks)
    out = tmp_path / "out.mp4"
    result = render_video(RenderRequest(
        source_path=src, masks_dir=masks, output_path=out,
        output_relative_path="jobs/test/output.mp4", mode="replace_background",
        background_path=None, background_spec=SPEC,
    ))
    assert result.frame_count == FRAMES
    cap = cv2.VideoCapture(str(out))
    ok_a, first = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, FRAMES - 1)
    ok_b, last = cap.read()
    cap.release()
    assert ok_a and ok_b
    # Animated backdrop: first and last frames differ outside the subject.
    assert not np.array_equal(first, last)
    # Blue-dominant backdrop where the mask is empty (corners stay blue-ish).
    corner = first[0:4, 0:4].astype(np.int32)
    assert int(corner[:, :, 0].mean()) > int(corner[:, :, 2].mean())


def test_mock_director_plans_programmatic_backdrop(tmp_path):
    client, _ = _client(tmp_path)
    job = _upload(client, _make_clip(tmp_path / "src.mp4"), "src.mp4")
    voice = client.post(f"/api/jobs/{job['job_id']}/voice", json={
        "transcript": "substitui o fundo por um gradiente azul animado minimalista"})
    assert voice.status_code == 200, voice.text
    store = JobStore(tmp_path / "storage")
    worker = PersistentWorker(store, get_providers("mock"), poll_seconds=0.05)
    for _ in range(60):
        if not worker.run_once():
            break
    review = client.get(f"/api/jobs/{job['job_id']}/plan")
    assert review.status_code == 200, review.text
    payload = review.json()
    ops = {op["capability_id"]: op for op in payload["plan"]["operations"]}
    assert "background.replace" in ops
    params = ops["background.replace"]["params"]
    assert params["asset_source"] == "programmatic"
    assert params["backdrop"]["gradient_bottom"] == "#2E6BE6"


def test_full_magic_background_flow_mock(tmp_path):
    client, _ = _client(tmp_path)
    job = _upload(client, _make_clip(tmp_path / "src.mp4"), "src.mp4")
    job_id, project_id = job["job_id"], job["project_id"]
    voice = client.post(f"/api/jobs/{job_id}/voice", json={
        "transcript": "substitui o fundo por um gradiente azul animado minimalista"})
    assert voice.status_code == 200, voice.text
    store = JobStore(tmp_path / "storage")
    worker = PersistentWorker(store, get_providers("mock"), poll_seconds=0.05)
    for _ in range(60):
        if not worker.run_once():
            break
    review = client.get(f"/api/jobs/{job_id}/plan").json()
    subjects = [s["object_id"] for s in review.get("subjects", [])]
    assert subjects, "mock segmentation should detect subjects"
    approved = client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": subjects[:1]})
    assert approved.status_code == 200, approved.text
    for _ in range(120):
        if not worker.run_once():
            break
    final = client.get(f"/api/jobs/{job_id}").json()
    assert final["status"] == "completed", final.get("error")
    assert final["result"]["render_status"] == "verified"
    out = store.job_dir(job_id) / "output.mp4"
    assert out.is_file() and out.stat().st_size > 0
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264"
    assert any(s["codec_type"] == "audio" for s in probe["streams"])
    # Published as a project asset for reuse.
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    assert any(a["original_filename"].endswith("-editado.mp4") for a in assets), assets
    # Animated background: frames across the video differ.
    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) > 10
    _, early = cap.read()
    cap.set(cv2.CAP_PROP_POS_FRAMES, 10)
    _, late = cap.read()
    cap.release()
    assert not np.array_equal(early, late)
    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200 and len(dl.content) > 0
