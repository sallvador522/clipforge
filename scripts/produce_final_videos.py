"""Hackathon final-rescue deliverables (ADR-047 showcase).

Real pipeline only: FFmpeg-generated synthetic sources (labelled as such in
the readiness report), real API + worker composition with persisted text
overlays and colour grade, ffprobe-verified MP4s copied to the user's
Videos/Video folder. Zero paid calls.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker

OUT_DIR = Path("C:/Users/New User/Videos/Video")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _run(*args: str) -> str:
    result = subprocess.run(list(args), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def _probe(path: Path) -> dict:
    return json.loads(_run("ffprobe", "-v", "error", "-count_frames",
                           "-show_streams", "-show_format", "-of", "json", str(path)))


def _make_source(path: Path, duration: int = 6) -> None:
    _run("ffmpeg", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))


def _wait(worker: PersistentWorker, store: JobStore, job_id: str) -> None:
    for _ in range(120):
        worker.run_once()
        status = store.get(job_id).status.value
        if status == "completed":
            return
        if status == "failed":
            raise AssertionError(f"job failed: {store.get(job_id).error}")
    raise AssertionError("worker did not finish")


def _contact_sheet(video: Path, out: Path) -> None:
    _run("ffmpeg", "-y", "-i", str(video),
         "-vf", "select='eq(n\\,0)+eq(n\\,60)+eq(n\\,120)+eq(n\\,179)',scale=320:180,tile=4x1",
         "-frames:v", "1", str(out))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="clipforge-final-"))
    bundle = get_providers("mock")
    store = JobStore(tmp / "storage")
    client = TestClient(create_app(storage_root=tmp / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)

    src = tmp / "source.mp4"
    _make_source(src)

    with open(src, "rb") as fh:
        upload = client.post("/api/uploads", files={"file": ("demo.mp4", fh, "video/mp4")})
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    project_id = upload.json()["project_id"]
    assets = client.get(f"/api/projects/{project_id}/assets").json()["assets"]
    asset_id = assets[0]["asset_id"]

    # --- Deliverable 1: Properties-driven program -------------------------
    texts = client.put(f"/api/jobs/{job_id}/texts", json={"texts": [
        {"overlay_id": "txt_final00001", "text": "A tua marca começa aqui",
         "style": "rise", "start_s": 0.5, "duration_s": 3.0,
         "x": 0.5, "y": 0.3, "scale": 1.2, "color": "#FFD400", "weight": "bold"},
        {"overlay_id": "txt_final00002", "text": "Edita-me no palco ou no chat",
         "style": "reveal", "start_s": 1.0, "duration_s": 3.5,
         "x": 0.5, "y": 0.78, "scale": 0.9, "color": "#FFFFFF", "weight": "normal"},
    ]})
    assert texts.status_code == 200, texts.text
    colour = client.put(f"/api/jobs/{job_id}/colour",
                        json={"contrast": 1.15, "brightness": 0.03, "saturation": 1.25})
    assert colour.status_code == 200, colour.text
    timeline = client.put(f"/api/jobs/{job_id}/timeline", json={"timeline": {"clips": [{
        "clip_id": "clip_abcdef123456", "asset_id": asset_id, "track": "V1",
        "timeline_start_s": 0.0, "source_in_s": 0.0, "source_out_s": 6.0}]}})
    assert timeline.status_code == 200, timeline.text
    # ADR-051: deliverables explicitly choose the 16:9 canvas (source is 640x360).
    assert client.post(f"/api/jobs/{job_id}/timeline/render",
                       json={"format": "landscape"}).status_code == 200
    _wait(worker, store, job_id)

    out1 = store.job_dir(job_id) / "output_timeline.mp4"
    probe1 = _probe(out1)
    assert probe1["streams"][0]["width"] == 1280
    dest1 = OUT_DIR / "ClipForge_Final_PropertiesTest.mp4"
    shutil.copyfile(out1, dest1)
    _contact_sheet(dest1, OUT_DIR / "ClipForge_Final_PropertiesTest_contact.png")
    print(f"deliverable 1: {dest1} bytes={dest1.stat().st_size} duration={probe1['format']['duration']}")

    # --- Deliverable 2: Muse tool edit + re-render -------------------------
    chat = client.post("/api/chat", json={
        "message": "Muda o texto para 'Transformamos ideias em marcas'",
        "job_id": job_id, "selected_text_id": "txt_final00001"})
    assert chat.status_code == 200, chat.text
    calls = chat.json()["pending_tool_calls"]
    assert len(calls) == 1 and calls[0]["tool"] == "text.update", chat.json()
    executed = client.post(f"/api/jobs/{job_id}/tools/execute",
                           json={"tool": calls[0]["tool"], "params": calls[0]["params"]})
    assert executed.status_code == 200, executed.text
    warm = client.post(f"/api/jobs/{job_id}/tools/execute", json={
        "tool": "colour.set",
        "params": {"contrast": 1.25, "brightness": 0.03, "saturation": 1.4}})
    assert warm.status_code == 200, warm.text

    # ADR-051: deliverables explicitly choose the 16:9 canvas (source is 640x360).
    assert client.post(f"/api/jobs/{job_id}/timeline/render",
                       json={"format": "landscape"}).status_code == 200
    _wait(worker, store, job_id)
    probe2 = _probe(out1)
    dest2 = OUT_DIR / "ClipForge_Final_Editing.mp4"
    shutil.copyfile(out1, dest2)
    _contact_sheet(dest2, OUT_DIR / "ClipForge_Final_Editing_contact.png")
    print(f"deliverable 2: {dest2} bytes={dest2.stat().st_size} duration={probe2['format']['duration']}")
    print(f"ledger untouched (mock only). tmp storage: {tmp}")


if __name__ == "__main__":
    main()
