"""Application-path regression: original audio survives SAM-gated rendering.

The SAM transport is injected (no network). The real provider still creates the
temporary video-only upload, and the real API/worker/renderer path runs end to end.
"""

from __future__ import annotations

import dataclasses
import json
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import _capability_payload, create_app
from clipforge_contracts import get_capability, sha256_file
from clipforge_jobs import JobStore
from clipforge_providers import SamSegmentationProvider, get_providers
from clipforge_worker import processor as processor_module
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
    path = tmp_path_factory.mktemp("audio-e2e") / "source.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate the audio fixture: {result.stderr[-300:]}")
    return path


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames",
            "-show_streams", "-show_format", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _has_audio(probe: dict) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))


def _video_stream(probe: dict) -> dict:
    return next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")


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


def _upload(client, path: Path) -> str:
    with path.open("rb") as handle:
        response = client.post("/api/uploads", files={"file": ("source.mp4", handle, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def _voice(client, job_id: str, *, consent: bool | None) -> None:
    payload = {"transcript": "blur the background"}
    if consent is not None:
        payload["subject_detection_consent"] = consent
    response = client.post(f"/api/jobs/{job_id}/voice", json=payload)
    assert response.status_code == 200, response.text


def _fixture_events(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["events"]


def test_app_approval_render_uses_original_audio_and_real_sam_masks(
    tmp_path, audio_video, monkeypatch
):
    uploaded: list[Path] = []
    uploaded_probe: dict = {}
    deleted: list[str] = []

    def upload(path: Path) -> str:
        uploaded.append(Path(path))
        uploaded_probe.update(_probe(Path(path)))
        return "file-e2e123"

    def stream(_payload: dict):
        return _fixture_events("multiple_people")

    sam = SamSegmentationProvider(
        "test-key",
        event_stream=stream,
        file_uploader=upload,
        file_deleter=deleted.append,
    )
    bundle = dataclasses.replace(
        get_providers("mock"),
        segmentation=sam,
        segmentation_mode="live",
    )
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, audio_video)
    record = store.get(job_id)
    source_path = store.source_path(record)
    original_hash = sha256_file(source_path)
    assert _has_audio(_probe(source_path))

    _voice(client, job_id, consent=True)
    assert worker.run_once() is True
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "awaiting_approval"

    # The canonical upload is untouched; only a temporary video-only copy went to SAM.
    assert len(uploaded) == 1
    sam_input = uploaded[0]
    assert sam_input != source_path
    assert not _has_audio(uploaded_probe)
    sam_video = _video_stream(uploaded_probe)
    assert (sam_video["width"], sam_video["height"]) == (64, 36)
    assert int(sam_video["nb_read_frames"]) == 5
    assert sha256_file(source_path) == original_hash
    assert _has_audio(_probe(source_path))
    assert deleted == ["file-e2e123"]

    review = client.get(f"/api/jobs/{job_id}/plan").json()
    assert review["segmentation"]["is_mock"] is False
    assert review["segmentation"]["provider"] == "meta-sam"
    assert body["result"]["segmentation"]["source_sha256"] == original_hash
    assert review["segmentation"]["frame_count"] == 5
    assert (review["segmentation"]["width"], review["segmentation"]["height"]) == (64, 36)
    subject_ids = [subject["object_id"] for subject in review["subjects"]]
    assert subject_ids == ["0", "1"]
    isolate = next(
        capability
        for capability in review["capabilities"]
        if capability["capability_id"] == "subject.isolate"
    )
    assert isolate["status"] == "available_live"
    assert isolate["simulated"] is False

    render_calls: list[Path] = []
    original_render = processor_module.render_video

    def spy_render(request, on_stage=None):
        render_calls.append(Path(request.source_path))
        return original_render(request, on_stage=on_stage)

    monkeypatch.setattr(processor_module, "render_video", spy_render)

    approved = client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": ["0"]})
    assert approved.status_code == 200, approved.text
    assert worker.run_once() is True
    result = client.get(f"/api/jobs/{job_id}/result").json()
    assert result["rendered"]["has_audio"] is True
    assert result["rendered"]["frame_count"] == 5
    assert (result["rendered"]["width"], result["rendered"]["height"]) == (64, 36)

    output = store.job_dir(job_id) / "output.mp4"
    assert output.is_file()
    output_probe = _probe(output)
    assert _has_audio(output_probe)
    assert int(_video_stream(output_probe)["nb_read_frames"]) == 5
    assert render_calls == [source_path]
    assert _pcm_md5(output) == _pcm_md5(source_path)

    assert sha256_file(source_path) == original_hash
    assert _has_audio(_probe(source_path))
    manifest = json.loads(
        (store.job_dir(job_id) / "masks" / "objects" / "object_0" / "manifest.json").read_text()
    )
    assert manifest["source_sha256"] == original_hash
    selected = json.loads(
        (store.job_dir(job_id) / "masks" / "selected" / "manifest.json").read_text()
    )
    assert selected["sam_object_ids"] == ["0"]


def test_worker_refuses_masks_bound_to_another_source(tmp_path, audio_video):
    bundle = get_providers("mock")
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, audio_video)
    _voice(client, job_id, consent=None)
    assert worker.run_once() is True
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "awaiting_approval"

    record = store.get(job_id)
    assert record.result is not None and record.result.segmentation is not None
    tampered = record.result.segmentation.model_copy(update={"source_sha256": "b" * 64})
    store.update(
        job_id,
        result=record.result.model_copy(update={"segmentation": tampered}),
    )

    approved = client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": ["0"]})
    assert approved.status_code == 200, approved.text
    assert worker.run_once() is True
    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert "do not belong to the original upload" in failed["error"]["message"]
    assert not (store.job_dir(job_id) / "output.mp4").exists()


def test_worker_refuses_tampered_subject_manifest_provenance(tmp_path, audio_video):
    bundle = get_providers("mock")
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, audio_video)
    _voice(client, job_id, consent=None)
    assert worker.run_once() is True

    manifest_path = (
        store.job_dir(job_id) / "masks" / "objects" / "object_0" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["source_sha256"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    approved = client.post(f"/api/jobs/{job_id}/approve", json={"subject_ids": ["0"]})
    assert approved.status_code == 200, approved.text
    assert worker.run_once() is True
    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert "subject mask manifest does not belong" in failed["error"]["message"]
    assert not (store.job_dir(job_id) / "output.mp4").exists()


def test_plan_capability_reports_mock_provider(tmp_path, audio_video):
    bundle = get_providers("mock")
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, audio_video)
    _voice(client, job_id, consent=None)
    assert worker.run_once() is True

    review = client.get(f"/api/jobs/{job_id}/plan").json()
    isolate = next(
        capability
        for capability in review["capabilities"]
        if capability["capability_id"] == "subject.isolate"
    )
    assert review["segmentation"]["is_mock"] is True
    assert isolate["status"] == "available_mock"
    assert isolate["simulated"] is True


def test_capability_payload_reports_unavailable_without_provider():
    payload = _capability_payload(get_capability("subject.isolate"), None, None)
    assert payload["status"] == "disabled"
    assert payload["simulated"] is True
