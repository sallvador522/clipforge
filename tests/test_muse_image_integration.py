"""End-to-end Muse Image workflow test with real SAM masks and real audio.

The SAM response and Muse Image HTTP transport are injected, so no external
request is made. The real API, worker, provider, mask combiner and renderer run.
"""

from __future__ import annotations

import dataclasses
import io
import json
import socket
import subprocess
from pathlib import Path

import cv2
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clipforge_api.main import create_app
from clipforge_contracts import TranscriptResult, sha256_file
from clipforge_jobs import JobStore
from clipforge_providers import (
    MuseImageBackgroundProvider,
    SamSegmentationProvider,
    get_providers,
)
from clipforge_worker import processor as processor_module
from clipforge_worker.processor import JobProcessor
from clipforge_worker.worker_process import PersistentWorker

FIXTURES = Path(__file__).parent / "fixtures" / "sam"


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch):
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    local_hosts = {"127.0.0.1", "::1", "localhost"}

    def is_local(address) -> bool:
        return isinstance(address, tuple) and bool(address) and address[0] in local_hosts

    def connect(sock, address, *args, **kwargs):
        if is_local(address):
            return original_connect(sock, address, *args, **kwargs)
        raise AssertionError("External network access is forbidden in this test.")

    def create_connection(address, *args, **kwargs):
        if is_local(address):
            return original_create_connection(address, *args, **kwargs)
        raise AssertionError("External network access is forbidden in this test.")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


@pytest.fixture(scope="session")
def audio_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("muse-image-e2e") / "source.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=0.5",
            "-f", "lavfi", "-i", "sine=frequency=660:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate the audio fixture: {result.stderr[-300:]}")
    return path


def _png(width: int = 64, height: int = 36, color=(0, 200, 0)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _has_audio(probe: dict) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))


def _pcm_md5(path: Path) -> str:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    line = next(line for line in result.stdout.splitlines() if line.startswith("MD5="))
    return line.split("=", 1)[1].strip()


def _fixture_events(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["events"]


def _upload(client, path: Path) -> str:
    with path.open("rb") as handle:
        response = client.post("/api/uploads", files={"file": ("source.mp4", handle, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def _voice(client, job_id: str, transcript: str, *, consent: bool | None = None) -> None:
    payload = {"transcript": transcript}
    if consent is not None:
        payload["subject_detection_consent"] = consent
    response = client.post(f"/api/jobs/{job_id}/voice", json=payload)
    assert response.status_code == 200, response.text


def test_muse_image_composes_with_sam_masks_and_preserves_audio(
    tmp_path, audio_video, monkeypatch
):
    captured_payload: dict = {}
    post_calls = {"n": 0}
    generated_png = _png()

    def post(url, **kwargs):
        post_calls["n"] += 1
        captured_payload["url"] = url
        captured_payload.update(kwargs)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-muse-e2e"},
            json={
                "created": 1_784_584_435,
                "data": [{"b64_json": __import__("base64").b64encode(generated_png).decode("ascii")}],
                "output_format": "png",
                "usage": {"input_tokens": 12, "output_tokens": 24, "total_tokens": 36},
            },
        )

    sam = SamSegmentationProvider(
        "test-key",
        event_stream=lambda _payload: _fixture_events("multiple_people"),
        file_uploader=lambda _path: "file-sam-e2e",
        file_deleter=lambda _file_id: None,
    )
    image = MuseImageBackgroundProvider("test-key", http_post=post)
    bundle = dataclasses.replace(
        get_providers("mock"),
        segmentation=sam,
        segmentation_mode="live",
        background=image,
        image_mode="live",
    )
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, audio_video)
    _voice(
        client,
        job_id,
        "Replace the background with a professional recording studio.",
        consent=True,
    )
    assert worker.run_once() is True
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "awaiting_approval"

    review = client.get(f"/api/jobs/{job_id}/plan").json()
    assert review["legacy_plan"]["intent"] == "replace_background"
    replace = next(
        capability
        for capability in review["capabilities"]
        if capability["capability_id"] == "background.replace"
    )
    assert replace["status"] == "available_live"
    assert replace["simulated"] is False

    render_requests = []
    original_render = processor_module.render_video

    def spy_render(request, on_stage=None):
        render_requests.append(request)
        return original_render(request, on_stage=on_stage)

    monkeypatch.setattr(processor_module, "render_video", spy_render)

    approved = client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": ["0"]})
    assert approved.status_code == 200, approved.text
    assert worker.run_once() is True
    result = client.get(f"/api/jobs/{job_id}/result").json()
    background = result["background"]
    assert background["is_mock"] is False
    assert background["provider_name"] == "muse-image"
    assert background["model"] == "muse-image-1.0"
    assert background["request_id"] == "req-muse-e2e"
    assert background["size_requested"] == "1536x1024"
    assert background["prompt"].startswith("professional recording studio")
    assert background["image_sha256"]
    background_path = Path(background["image_path"])
    assert background_path == store.job_dir(job_id) / "background" / "background.png"
    assert background_path.is_file()
    assert (store.job_dir(job_id) / "background" / "background.json").is_file()

    assert captured_payload["url"] == "https://api.meta.ai/v1/images/generations"
    payload = captured_payload["json"]
    assert payload["model"] == "muse-image-1.0"
    assert payload["n"] == 1
    assert payload["response_format"] == "b64_json"
    assert payload["output_format"] == "png"
    assert payload["size"] == "1536x1024"
    assert "professional recording studio" in payload["prompt"]
    assert not {"image", "images", "file_id", "input_video", "mask", "video"} & set(payload)
    assert post_calls["n"] == 1

    ledger = json.loads((tmp_path / "storage" / "live-call-ledger.json").read_text())
    assert ledger["image"] == 1

    assert len(render_requests) == 1
    request = render_requests[0]
    assert Path(request.source_path) == store.source_path(store.get(job_id))
    assert Path(request.background_path) == background_path
    assert request.mode == "replace_background"

    output = store.job_dir(job_id) / "output.mp4"
    assert output.is_file()
    probe = _probe(output)
    assert _has_audio(probe)
    assert int(next(s for s in probe["streams"] if s["codec_type"] == "video")["nb_read_frames"]) == 5
    assert _pcm_md5(output) == _pcm_md5(audio_video)
    assert sha256_file(store.source_path(store.get(job_id))) == sha256_file(audio_video)

    capture = cv2.VideoCapture(str(output))
    ok, frame = capture.read()
    capture.release()
    assert ok
    corner = frame[2, 2].astype(int)
    assert corner[1] > 140 and corner[0] < 80 and corner[2] < 80

    # Repeated generation step reuses the persisted image and makes no second POST.
    processor = JobProcessor(store, bundle)
    reused, _ = processor._get_or_generate_background(
        job_id,
        store.get(job_id).result,
        prompt=background["prompt"],
        orientation="landscape",
    )
    assert reused.image_sha256 == background["image_sha256"]
    assert post_calls["n"] == 1


class _FailingLiveBackground:
    provider_name = "muse-image"
    execution_mode = "live"
    model = "muse-image-1.0"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("muse image failed for test")


def test_failed_generation_is_not_retried_or_replaced_with_mock(tmp_path, audio_video):
    failing = _FailingLiveBackground()
    bundle = dataclasses.replace(
        get_providers("mock"),
        background=failing,
        image_mode="live",
    )
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, audio_video)
    _voice(client, job_id, "Replace the background with a professional recording studio.")
    assert worker.run_once() is True
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "awaiting_approval"
    approved = client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": ["0"]})
    assert approved.status_code == 200, approved.text
    assert worker.run_once() is True

    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert "muse image failed for test" in failed["error"]["message"]
    assert failing.calls == 1
    record = store.get(job_id)
    assert record.result is not None
    assert record.result.background is None
    assert record.result.background_generation_attempted is True
    assert not (store.job_dir(job_id) / "output.mp4").exists()

    processor = JobProcessor(store, bundle)
    with pytest.raises(ValueError, match="already attempted"):
        processor._execute_approved_plan(
            job_id,
            store.get(job_id),
            TranscriptResult(
                text="Replace the background with a professional recording studio.",
                provider_name="test",
                is_mock=True,
            ),
        )
    assert failing.calls == 1
