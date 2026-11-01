"""Explicit consent gate for live SAM video processing (ADR-020).

All tests are offline. The "live" test provider is a deterministic local double
that never performs an upload or network request. A socket block makes accidental
external access fail loudly.
"""

from __future__ import annotations

import dataclasses
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_contracts import (
    SUBJECT_DETECTION_DISCLOSURE_VERSION,
    ConsentValidationError,
    SubjectDetectionConsent,
    TranscriptResult,
    sha256_file,
    validate_subject_detection_consent,
)
from clipforge_director import LiveCallAuthorization, LiveCallBudget
from clipforge_jobs import JobRecord, JobResult, JobStatus, JobStore
from clipforge_jobs.models import SourceInfo
from clipforge_providers import (
    MockEditingPlannerProvider,
    MockSegmentationProvider,
    SamSegmentationProvider,
    get_providers,
)
from clipforge_worker.processor import JobProcessor
from clipforge_worker.worker_process import PersistentWorker


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
        raise AssertionError("External network access is forbidden in consent tests.")

    def create_connection(address, *args, **kwargs):
        if is_local(address):
            return original_create_connection(address, *args, **kwargs)
        raise AssertionError("External network access is forbidden in consent tests.")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


@pytest.fixture(scope="session")
def tiny_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("consent-media") / "tiny.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate consent test clip: {result.stderr[-300:]}")
    return path


class FakeLiveSegmentation(MockSegmentationProvider):
    """Local live-like provider: writes mock masks but never contacts Meta."""

    provider_name = "meta-sam"
    model = "sam-3.1"
    execution_mode = "live"

    def __init__(self) -> None:
        self.calls = 0
        self.consents: list[SubjectDetectionConsent | None] = []

    def segment(self, **kwargs):
        self.calls += 1
        self.consents.append(kwargs.get("consent"))
        result = super().segment(**kwargs)
        return result.model_copy(
            update={
                "provider_name": self.provider_name,
                "model": self.model,
                "is_mock": False,
            }
        )


def _live_bundle():
    fake = FakeLiveSegmentation()
    bundle = dataclasses.replace(
        get_providers("mock"),
        segmentation=fake,
        segmentation_mode="live",
    )
    return bundle, fake


def _upload(client, tiny_video: Path, name: str = "clip.mp4"):
    with tiny_video.open("rb") as handle:
        response = client.post("/api/uploads", files={"file": (name, handle, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def _voice(client, job_id: str, consent: bool | None = None):
    payload = {"transcript": "Desfoca o fundo e mantém-me nítido."}
    if consent is not None:
        payload["subject_detection_consent"] = consent
    return client.post(f"/api/jobs/{job_id}/voice", json=payload)


def _job_record(
    tmp_path: Path,
    tiny_video: Path,
    *,
    job_id: str,
    approval_granted: bool = False,
    with_plan: bool = False,
) -> tuple[JobStore, JobRecord]:
    store = JobStore(tmp_path / f"storage-{job_id}")
    source = store.uploads_dir / job_id / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(tiny_video.read_bytes())
    transcript = TranscriptResult(
        text="Desfoca o fundo e mantém-me nítido.",
        language="pt-BR",
        provider_name="test",
        is_mock=True,
    )
    result = None
    if with_plan:
        plan = MockEditingPlannerProvider().create_plan(transcript)
        result = JobResult(transcript=transcript, plan=plan)
    record = JobRecord(
        job_id=job_id,
        original_filename="clip.mp4",
        source_relative_path=f"uploads/{job_id}/source.mp4",
        source_info=SourceInfo(
            width=64, height=36, fps=10.0, duration_seconds=1.0, frame_count=10, has_audio=True
        ),
        source_sha256=sha256_file(source),
        confirmed_transcript=transcript.text,
        transcript_is_mock=True,
        ready=True,
        stage="approved" if approval_granted else "queued",
        status=JobStatus.QUEUED,
        approval_granted=approval_granted,
        result=result,
    )
    store.create(record)
    return store, record


def _consent(job_id: str, source_hash: str) -> SubjectDetectionConsent:
    return SubjectDetectionConsent(
        job_id=job_id,
        source_video_hash=source_hash,
        consent_given=True,
        consent_timestamp=datetime.now(timezone.utc),
        disclosure_version=SUBJECT_DETECTION_DISCLOSURE_VERSION,
        provider="meta-sam",
        model="sam-3.1",
        segmentation_mode="live",
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("job_id", "another-job", "subject_detection_consent_job_mismatch"),
        ("source_video_hash", "b" * 64, "subject_detection_consent_source_mismatch"),
        ("disclosure_version", "old-version", "subject_detection_consent_disclosure_mismatch"),
        ("provider", "other-provider", "subject_detection_consent_provider_mismatch"),
        ("model", "other-model", "subject_detection_consent_model_mismatch"),
        ("segmentation_mode", "mock", "subject_detection_consent_mode_mismatch"),
        ("consent_given", False, "subject_detection_consent_required"),
    ],
)
def test_consent_binding_rejects_mismatches(tmp_path, field, value, code):
    source_hash = "a" * 64
    consent = _consent("job-1", source_hash)
    mutated = consent.model_copy(update={field: value})
    with pytest.raises(ConsentValidationError) as exc:
        validate_subject_detection_consent(
            mutated,
            job_id="job-1",
            source_video_hash=source_hash,
            provider="meta-sam",
            model="sam-3.1",
        )
    assert exc.value.code == code


def test_live_without_consent_is_rejected_before_ready_or_worker(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, tiny_video)

    response = _voice(client, job_id)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "subject_detection_consent_required"
    record = store.get(job_id)
    assert record.ready is False and record.stage == "awaiting_voice"
    assert record.subject_detection_consent is None
    assert worker.run_once() is False
    assert fake.calls == 0


def test_explicitly_false_consent_is_rejected(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    job_id = _upload(client, tiny_video)

    response = _voice(client, job_id, consent=False)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "subject_detection_consent_required"
    assert store.get(job_id).ready is False
    assert fake.calls == 0


def test_valid_consent_is_persisted_and_allows_worker_detection(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, tiny_video)

    response = _voice(client, job_id, consent=True)
    assert response.status_code == 200, response.text
    record = store.get(job_id)
    assert record.ready is True
    consent = record.subject_detection_consent
    assert consent is not None
    assert consent.job_id == job_id
    assert consent.source_video_hash == record.source_sha256
    assert consent.consent_given is True
    assert consent.disclosure_version == SUBJECT_DETECTION_DISCLOSURE_VERSION
    assert consent.provider == "meta-sam"
    assert consent.model == "sam-3.1"
    assert consent.segmentation_mode == "live"
    assert consent.consent_timestamp.tzinfo is not None

    assert worker.run_once() is True
    assert fake.calls == 1
    assert fake.consents[0] == consent
    assert store.get(job_id).status is JobStatus.AWAITING_APPROVAL


def test_changing_source_video_invalidates_consent_before_provider_call(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, tiny_video)
    assert _voice(client, job_id, consent=True).status_code == 200
    record = store.get(job_id)
    with store.source_path(record).open("ab") as handle:
        handle.write(b"changed")

    assert worker.run_once() is True
    failed = store.get(job_id)
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "subject_detection_consent_source_mismatch"
    assert fake.calls == 0


def test_consent_from_another_job_is_rejected(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    first_id = _upload(client, tiny_video, "first.mp4")
    assert _voice(client, first_id, consent=True).status_code == 200
    first_consent = store.get(first_id).subject_detection_consent
    assert first_consent is not None

    second_id = _upload(client, tiny_video, "second.mp4")
    store.update(
        second_id,
        ready=True,
        stage="queued",
        confirmed_transcript="Desfoca o fundo e mantém-me nítido.",
        transcript_is_mock=True,
        subject_detection_consent=first_consent,
    )
    store.update(first_id, status=JobStatus.FAILED, stage="failed")

    assert worker.run_once() is True
    failed = store.get(second_id)
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "subject_detection_consent_job_mismatch"
    assert fake.calls == 0


def test_plan_approval_does_not_substitute_for_sam_consent(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store, record = _job_record(
        tmp_path, tiny_video, job_id="approved-no-consent", approval_granted=True, with_plan=True
    )
    processor = JobProcessor(store, bundle)

    assert processor.process(record.job_id) == JobStatus.FAILED.value
    failed = store.get(record.job_id)
    assert failed.error is not None
    assert failed.error.code == "subject_detection_consent_required"
    assert fake.calls == 0


def test_worker_refuses_live_detection_without_persisted_consent(tmp_path, tiny_video):
    bundle, fake = _live_bundle()
    store, record = _job_record(tmp_path, tiny_video, job_id="worker-no-consent")
    processor = JobProcessor(store, bundle)

    assert processor.process(record.job_id) == JobStatus.FAILED.value
    failed = store.get(record.job_id)
    assert failed.error is not None
    assert failed.error.code == "subject_detection_consent_required"
    assert fake.calls == 0


def test_provider_refuses_consentless_call_before_upload(tmp_path, tiny_video):
    calls = {"upload": 0}

    def uploader(path: Path) -> str:
        calls["upload"] += 1
        return "file-should-not-be-used"

    provider = SamSegmentationProvider(
        "dummy-key",
        event_stream=lambda payload: [],
        file_uploader=uploader,
        file_deleter=lambda file_id: None,
    )
    storage = tmp_path / "provider-storage"
    authorization = LiveCallAuthorization(
        LiveCallBudget(storage, limits={"segmentation": 2}), "segmentation"
    )
    with pytest.raises(ConsentValidationError) as exc:
        provider.segment(
            job_id="provider-no-consent",
            source_video_id="provider-no-consent",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=10,
            fps=10.0,
            source_path=tiny_video,
            authorization=authorization,
        )
    assert exc.value.code == "subject_detection_consent_required"
    assert calls["upload"] == 0


def test_mock_segmentation_still_works_without_consent_or_key(tmp_path, tiny_video, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("CLIPFORGE_SEGMENTATION_MODE", "mock")
    bundle = get_providers("mock")
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, tiny_video)

    assert _voice(client, job_id).status_code == 200
    record = store.get(job_id)
    assert record.subject_detection_consent is None
    assert worker.run_once() is True
    assert store.get(job_id).status is JobStatus.AWAITING_APPROVAL
