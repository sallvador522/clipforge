import subprocess
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.masks import MaskLoader, MaskWriter
from clipforge_worker.renderer import RenderingError, render_video, RenderRequest, verify_render_output
from clipforge_worker.worker_process import PersistentWorker

W, H, FPS, FRAMES = 64, 36, 10.0, 10


def _make_video(path: Path, with_audio=True, corrupt=False) -> Path:
    if corrupt:
        path.write_bytes(b"definitely not a video")
        return path
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={W}x{H}:rate={FPS}:duration=1"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if with_audio else []
    cmd += [str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-300:]
    return path


def _make_masks(directory: Path, frames=FRAMES, missing=False, corrupt_one=False):
    yy, xx = np.mgrid[0:H, 0:W]
    masks = [np.where(((yy - 18) ** 2 + (xx - (10 + i * 4)) ** 2) <= 100, 255, 0).astype(np.uint8) for i in range(frames)]
    MaskWriter().write_sequence(directory, masks, fps=FPS, subject_id="person_1", source_video_id="tiny")
    if missing:
        (directory / "frame_000004.png").unlink()
    if corrupt_one:
        (directory / "frame_000003.png").write_bytes(b"junk")


def _request(tmp_path, source, masks, output, mode="blur_background", background=None):
    return RenderRequest(
        source_path=source, masks_dir=masks, output_path=output,
        output_relative_path="jobs/test/output.mp4", mode=mode, background_path=background,
    )


def test_blur_render_produces_verified_mp4_with_audio(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks)
    output = tmp_path / "out.mp4"
    result = render_video(_request(tmp_path, source, masks, output))
    assert result.mode == "blur_background" and result.frame_count == FRAMES
    assert (result.width, result.height) == (W, H) and result.has_audio is True
    assert abs(result.duration_seconds - 1.0) < 0.6 and result.file_size_bytes > 0
    # Subject stays sharp (near-identical to source) while the background corner
    # is measurably smoother in the output than in the source.
    import cv2

    def first_frame(p):
        cap = cv2.VideoCapture(str(p))
        ok_, f = cap.read()
        cap.release()
        assert ok_
        return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(float)

    out_gray, src_gray = first_frame(output), first_frame(source)
    subject_diff = abs(out_gray[14:22, 6:14] - src_gray[14:22, 6:14]).mean()  # ellipse centre on frame 0
    assert subject_diff < 12  # sharp subject preserved (codec tolerance only)
    assert out_gray[0:6, 52:64].var() < src_gray[0:6, 52:64].var()  # blurred background is smoother


def test_replace_render_uses_local_background(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks)
    background = tmp_path / "bg.png"
    import cv2

    cv2.imwrite(str(background), np.full((H, W, 3), (40, 90, 200), dtype=np.uint8))  # solid orange (BGR)
    output = tmp_path / "out.mp4"
    result = render_video(_request(tmp_path, source, masks, output, mode="replace_background", background=background))
    assert result.mode == "replace_background" and result.frame_count == FRAMES
    cap = cv2.VideoCapture(str(output))
    ok, frame = cap.read()
    cap.release()
    assert ok
    corner = frame[2, 2].astype(int)  # far from subject: must be the replacement colour (approx, codec tolerance)
    assert abs(corner[0] - 40) < 25 and abs(corner[2] - 200) < 25


def test_missing_masks_fail_rendering(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks, missing=True)
    with pytest.raises(Exception):
        render_video(_request(tmp_path, source, masks, tmp_path / "out.mp4"))


def test_corrupt_mask_fails_rendering(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks, corrupt_one=True)
    with pytest.raises(Exception):
        render_video(_request(tmp_path, source, masks, tmp_path / "out.mp4"))


def test_corrupt_source_fails_rendering(tmp_path):
    source = _make_video(tmp_path / "src.mp4", corrupt=True)
    masks = tmp_path / "masks"
    _make_masks(masks)
    with pytest.raises(RenderingError):
        render_video(_request(tmp_path, source, masks, tmp_path / "out.mp4"))


def test_frame_count_mismatch_fails_rendering(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks, frames=FRAMES - 3)  # masks end before the video does
    with pytest.raises(RenderingError):
        render_video(_request(tmp_path, source, masks, tmp_path / "out.mp4"))


def test_invalid_background_fails_rendering(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks)
    with pytest.raises(RenderingError):
        render_video(_request(tmp_path, source, masks, tmp_path / "o.mp4",
                              mode="replace_background", background=tmp_path / "nope.png"))
    bad_bg = tmp_path / "bad.png"
    bad_bg.write_bytes(b"junk")
    with pytest.raises(RenderingError):
        render_video(_request(tmp_path, source, masks, tmp_path / "o.mp4",
                              mode="replace_background", background=bad_bg))


def test_verify_rejects_wrong_expectations(tmp_path):
    source = _make_video(tmp_path / "src.mp4")
    masks = tmp_path / "masks"
    _make_masks(masks)
    output = tmp_path / "out.mp4"
    render_video(_request(tmp_path, source, masks, output))
    with pytest.raises(RenderingError):
        verify_render_output(output, width=W, height=H, frame_count=999, duration=1.0, expect_audio=True)
    with pytest.raises(RenderingError):
        verify_render_output(output, width=999, height=H, frame_count=FRAMES, duration=1.0, expect_audio=True)


def test_masks_are_streamed_not_loaded_all_at_once(tmp_path):
    masks = tmp_path / "masks"
    _make_masks(masks)
    iterator = MaskLoader().iter_masks(masks)
    index, first = next(iterator)  # consume lazily, one frame at a time (bounded memory)
    assert index == 0 and first.shape == (H, W)
    rest = list(iterator)
    assert len(rest) == FRAMES - 1


def _upload(client, tiny):
    with open(tiny, "rb") as fh:
        return client.post("/api/uploads", files={"file": ("clip.mp4", fh, "video/mp4")})


def test_download_only_after_verified_render(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    worker = PersistentWorker(store, providers, poll_seconds=0.05)
    source = _make_video(tmp_path / "clip.mp4")

    job_id = _upload(client, source).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409  # nothing rendered yet

    client.post(f"/api/jobs/{job_id}/voice", json={"audio_fixture_id": "pt_keep_me_sharp"})
    while worker.run_once():
        pass
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
    resp = client.get(f"/api/jobs/{job_id}/download")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("video/mp4")
    assert len(resp.content) > 1000 and resp.content.find(b"ftyp") > -1  # real MP4 bytes

    # Clarification jobs complete without rendering: download still refused.
    job2 = _upload(client, source).json()["job_id"]
    client.post(f"/api/jobs/{job2}/voice", json={"audio_fixture_id": "pt_ambiguous_person"})
    while worker.run_once():
        pass
    assert client.get(f"/api/jobs/{job2}").json()["status"] == "completed"
    assert client.get(f"/api/jobs/{job2}/download").status_code == 409
