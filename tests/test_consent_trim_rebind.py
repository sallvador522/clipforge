"""Consent re-binding to a timeline trecho (ADR-056).

Users mark Início/Fim on the timeline; live SAM may then process ONLY that
window. Consent binds (job, original hash, window); the worker verifies both
before any upload. All tests are offline: the "live" provider is a local
double and no request can leave the machine.
"""

import dataclasses
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_contracts.consent import (
    ConsentValidationError,
    sha256_file,
    validate_subject_detection_consent,
)
from clipforge_director import LiveCallAuthorization, LiveCallBudget
from clipforge_jobs import JobStore
from clipforge_jobs.models import JobStatus
from clipforge_providers import MockSegmentationProvider, get_providers
from clipforge_providers.sam import SamSegmentationProvider
from clipforge_worker.worker_process import PersistentWorker


def _consent(job_id, source_hash, start=None, end=None):
    from clipforge_contracts.consent import SubjectDetectionConsent

    return SubjectDetectionConsent(
        job_id=job_id,
        source_video_hash=source_hash,
        consent_given=True,
        consent_timestamp=datetime.now(timezone.utc),
        disclosure_version="sam31-external-video-v1",
        provider="meta-sam",
        model="sam-3.1",
        segmentation_mode="live",
        trim_start_s=start,
        trim_end_s=end,
    )


def test_window_mismatch_codes():
    h = "a" * 64
    with pytest.raises(ConsentValidationError) as exc:
        validate_subject_detection_consent(
            _consent("j", h), job_id="j", source_video_hash=h,
            provider="meta-sam", model="sam-3.1",
            trim_start_s=0.2, trim_end_s=0.8,
        )
    assert exc.value.code == "subject_detection_consent_trim_mismatch"
    with pytest.raises(ConsentValidationError) as exc:
        validate_subject_detection_consent(
            _consent("j", h, 0.2, 0.8), job_id="j", source_video_hash=h,
            provider="meta-sam", model="sam-3.1",
        )
    assert exc.value.code == "subject_detection_consent_trim_mismatch"
    with pytest.raises(ConsentValidationError) as exc:
        validate_subject_detection_consent(
            _consent("j", h, 0.2, 0.8), job_id="j", source_video_hash=h,
            provider="meta-sam", model="sam-3.1",
            trim_start_s=0.3, trim_end_s=0.8,
        )
    assert exc.value.code == "subject_detection_consent_trim_mismatch"
    # Exact same window validates.
    validate_subject_detection_consent(
        _consent("j", h, 0.2, 0.8), job_id="j", source_video_hash=h,
        provider="meta-sam", model="sam-3.1",
        trim_start_s=0.2, trim_end_s=0.8,
    )
    # Whole-video consent still validates without a window.
    validate_subject_detection_consent(
        _consent("j", h), job_id="j", source_video_hash=h,
        provider="meta-sam", model="sam-3.1",
    )


class FakeLiveSegmentation(MockSegmentationProvider):
    provider_name = "meta-sam"
    model = "sam-3.1"
    execution_mode = "live"

    def __init__(self) -> None:
        self.calls = 0
        self.paths: list[str] = []

    def segment(self, **kwargs):
        self.calls += 1
        self.paths.append(str(kwargs.get("source_path")))
        return super().segment(**kwargs)


def _live_bundle():
    fake = FakeLiveSegmentation()
    bundle = dataclasses.replace(
        get_providers("mock"),
        segmentation=fake,
        segmentation_mode="live",
    )
    return bundle, fake


def _tiny(tmp_path_factory, name="trim-consent.mp4"):
    path = tmp_path_factory.mktemp("trim-consent-media") / name
    result = subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg could not generate test clip: {result.stderr[-300:]}")
    return path


def _upload(client, path: Path, name: str = "clip.mp4"):
    with path.open("rb") as handle:
        response = client.post("/api/uploads", files={"file": (name, handle, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def _voice(client, job_id: str, consent: bool | None = None):
    payload = {"transcript": "Desfoca o fundo e mantém-me nítido."}
    if consent is not None:
        payload["subject_detection_consent"] = consent
    return client.post(f"/api/jobs/{job_id}/voice", json=payload)


def _drain(worker, limit=40):
    for _ in range(limit):
        if not worker.run_once():
            return


def test_trim_endpoint_allows_live_segmentation(tmp_path, tmp_path_factory):
    bundle, _ = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    job_id = _upload(client, _tiny(tmp_path_factory))
    resp = client.post(f"/api/jobs/{job_id}/trim", json={"start_s": 0.2, "end_s": 1.2})
    assert resp.status_code == 200, resp.text
    assert resp.json()["trim_start_s"] == 0.2
    assert resp.json()["trim_end_s"] == 1.2


def test_trim_plus_live_consent_runs_sam_on_trimmed_copy(tmp_path, tmp_path_factory):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, _tiny(tmp_path_factory))
    assert client.post(f"/api/jobs/{job_id}/trim", json={"start_s": 0.2, "end_s": 1.2}).status_code == 200

    assert _voice(client, job_id, consent=True).status_code == 200
    record = store.get(job_id)
    assert record.subject_detection_consent is not None
    assert record.subject_detection_consent.trim_start_s == 0.2
    assert record.subject_detection_consent.trim_end_s == 1.2

    _drain(worker)
    assert fake.calls == 1
    # SAM consumed the materialized trimmed working copy, not the original.
    assert fake.paths[0].endswith("trimmed_source.mp4"), fake.paths
    record = store.get(job_id)
    assert record.trimmed_sha256 is not None
    assert record.status is JobStatus.AWAITING_APPROVAL


def test_consent_endpoint_binds_window_and_trimmed_hash(tmp_path, tmp_path_factory):
    bundle, fake = _live_bundle()
    store = JobStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=bundle))
    worker = PersistentWorker(store, bundle, poll_seconds=0.05)
    job_id = _upload(client, _tiny(tmp_path_factory))
    assert client.post(f"/api/jobs/{job_id}/trim", json={"start_s": 0.2, "end_s": 1.2}).status_code == 200
    assert _voice(client, job_id).status_code == 200
    assert worker.run_once() is True
    assert store.get(job_id).status is JobStatus.AWAITING_CONSENT

    granted = client.post(f"/api/jobs/{job_id}/consent", json={"subject_detection_consent": True})
    assert granted.status_code == 200, granted.text
    consent = store.get(job_id).subject_detection_consent
    assert consent is not None
    # The trimmed copy was materialized before the gate, so its hash is bound.
    assert (consent.trim_start_s, consent.trim_end_s) == (0.2, 1.2)
    assert consent.trimmed_video_hash == store.get(job_id).trimmed_sha256

    _drain(worker)
    assert fake.calls == 1
    assert store.get(job_id).status is JobStatus.AWAITING_APPROVAL


def test_provider_refuses_unexpected_file_before_network(tmp_path):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        other = Path(tmp) / "other.mp4"
        other.write_bytes(b"not a video but hashing works")
        provider = SamSegmentationProvider(api_key="test-key")
        consent = _consent("job-x", sha256_file(other), 0.2, 0.8)
        with pytest.raises(ConsentValidationError) as exc:
            provider.segment(
                job_id="job-x",
                source_video_id="job-x",
                output_dir=tmp,
                width=64, height=36, frame_count=10, fps=10.0,
                source_path=other,
                authorization=LiveCallAuthorization(
                    LiveCallBudget(Path(tmp) / "ledger", limits={"segmentation": 2}), "segmentation"),
                consent=consent,
                trim_start_s=0.2, trim_end_s=0.8,
                expected_source_hash="b" * 64,
            )
        assert exc.value.code == "subject_detection_consent_source_mismatch"
