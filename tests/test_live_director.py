"""Live director wiring tests: budget caps, approval gate, execution path."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge_contracts import (
    DirectorAudit,
    DirectorValidationStatus,
    TranscriptResult,
)
from clipforge_director import (
    DirectorUsage,
    DirectorValidationError,
    LiveBudgetExceeded,
    LiveCallBudget,
    MockProfessionalEditingDirector,
)
from clipforge_jobs import JobRecord, JobStatus, JobStore
from clipforge_jobs.models import SourceInfo
from clipforge_providers import (
    MockBackgroundGenerationProvider,
    MockEditingPlannerProvider,
    MockSegmentationProvider,
    MockTranscriptionProvider,
    ProviderBundle,
)
from clipforge_worker.processor import JobProcessor


@pytest.fixture(autouse=True)
def _clear_live_limit_env(monkeypatch):
    monkeypatch.delenv("CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT", raising=False)
    monkeypatch.delenv("CLIPFORGE_LIVE_DIRECTOR_LIMIT", raising=False)


def test_live_budget_allows_two_then_refuses(tmp_path):
    budget = LiveCallBudget(tmp_path / "storage")
    assert budget.reserve("director") == 1
    assert budget.reserve("director") == 2
    with pytest.raises(LiveBudgetExceeded):
        budget.reserve("director")
    assert budget.used("director") == 2


def test_live_budget_is_per_function(tmp_path):
    budget = LiveCallBudget(tmp_path / "storage")
    budget.reserve("transcription")
    budget.reserve("transcription")
    assert budget.reserve("director") == 1


def test_live_budget_env_limit_is_applied(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT", "3")
    budget = LiveCallBudget(tmp_path / "storage")
    assert budget.limits == {"transcription": 3, "director": 2}
    assert [budget.reserve("transcription") for _ in range(3)] == [1, 2, 3]
    with pytest.raises(LiveBudgetExceeded):
        budget.reserve("transcription")
    assert budget.reserve("director") == 1  # other function keeps its default


def test_explicit_limits_override_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT", "99")
    budget = LiveCallBudget(tmp_path / "storage", limits={"transcription": 1})
    budget.reserve("transcription")
    with pytest.raises(LiveBudgetExceeded):
        budget.reserve("transcription")


def test_invalid_env_limit_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFORGE_LIVE_DIRECTOR_LIMIT", "zero")
    with pytest.raises(ValueError, match="CLIPFORGE_LIVE_DIRECTOR_LIMIT"):
        LiveCallBudget(tmp_path / "storage")


def test_director_factory_modes(monkeypatch):
    from clipforge_providers.factory import get_providers

    monkeypatch.setenv("CLIPFORGE_AI_MODE", "mock")
    monkeypatch.setenv("CLIPFORGE_TRANSCRIBE_MODE", "mock")
    monkeypatch.delenv("CLIPFORGE_DIRECTOR_MODE", raising=False)
    assert get_providers().director_mode == "mock"

    monkeypatch.setenv("CLIPFORGE_DIRECTOR_MODE", "live")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    from clipforge_providers.transcription_meta import MissingCredentialsError

    with pytest.raises(MissingCredentialsError):
        get_providers()

    monkeypatch.setenv("MODEL_API_KEY", "dummy")
    bundle = get_providers()
    assert bundle.director_mode == "live"
    assert type(bundle.director).__name__ == "LiteMetaEditingDirectorProvider"


def _tiny_video(path: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg unavailable")


class _FixedDirector:
    def __init__(self, transcript_text: str) -> None:
        self._plan = MockProfessionalEditingDirector().create_plan(
            TranscriptResult(text=transcript_text, language="pt-BR", provider_name="t", is_mock=True)
        )
        self.last_usage = DirectorUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=0.0001
        )
        self.last_request_id = self._plan.request_id
        self.last_audit = DirectorAudit(
            request_id=self._plan.request_id,
            provider="test-director",
            model="test-model",
            service_mode="standard",
            wire_schema="full",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.0001,
            validation_status="accepted",
            http_status=200,
            finish_reason="stop",
        )

    def create_plan(
        self,
        transcript: TranscriptResult,
        video=None,
        *,
        authorization=None,
        clarification_answer=None,
    ):
        if authorization is not None:
            authorization.reserve()
        return self._plan


class _FailingDirector:
    def __init__(self) -> None:
        self.last_usage = DirectorUsage(
            prompt_tokens=2781,
            completion_tokens=1500,
            total_tokens=4281,
            cost_usd=0.0005781,
        )
        self.last_request_id = "req_failing1234"
        self.last_server_request_id = "srv-failing-1"
        self.last_audit = DirectorAudit(
            request_id="req_failing1234",
            server_request_id="srv-failing-1",
            provider="meta-muse-spark-director-lite",
            model="muse-spark-1.3-contributor",
            service_mode="contributor",
            wire_schema="lite",
            prompt_tokens=2781,
            completion_tokens=1500,
            total_tokens=4281,
            estimated_cost_usd=0.0005781,
            validation_status="rejected",
            error_category="validation",
            error_code="DirectorValidationError",
            http_status=200,
            finish_reason="stop",
        )

    def create_plan(
        self,
        transcript: TranscriptResult,
        video=None,
        *,
        authorization=None,
        clarification_answer=None,
    ):
        if authorization is not None:
            authorization.reserve()
        raise DirectorValidationError(
            "Lite plan failed validation: invalid operation id",
            "srv-failing-1",
            category="validation",
        )


def _bundle(transcript_text: str, director=None) -> ProviderBundle:
    return ProviderBundle(
        transcription=MockTranscriptionProvider(),
        planner=MockEditingPlannerProvider(),
        segmentation=MockSegmentationProvider(),
        background=MockBackgroundGenerationProvider(),
        mode="mock",
        transcription_mode="mock",
        director=director or _FixedDirector(transcript_text),
        director_mode="live",
    )


def _job(tmp_path: Path, transcript_text: str) -> tuple[JobStore, str]:
    store = JobStore(tmp_path / "storage")
    source = store.uploads_dir / "job1" / "source.mp4"
    source.parent.mkdir(parents=True)
    _tiny_video(source)
    record = JobRecord(
        job_id="job1",
        original_filename="clip.mp4",
        source_relative_path="uploads/job1/source.mp4",
        source_info=SourceInfo(width=64, height=36, fps=10.0, duration_seconds=1.0, frame_count=10, has_audio=True),
        confirmed_transcript=transcript_text,
        ready=True,
    )
    store.create(record)
    return store, record.job_id


def _approve(store: JobStore, job_id: str) -> None:
    store.transition(
        job_id,
        expected=JobStatus.AWAITING_APPROVAL,
        status=JobStatus.QUEUED,
        stage="approved",
        actor="user",
        approval_granted=True,
    )


def test_live_director_blur_executes_and_records_plan(tmp_path):
    text = "Keep me sharp and blur everything behind me."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text))

    assert processor.process(job_id) == JobStatus.AWAITING_APPROVAL.value
    pending = store.get(job_id)
    assert pending.result is not None and pending.result.director_plan is not None
    assert pending.result.render_status == "awaiting_approval"
    assert not (store.job_dir(job_id) / "output.mp4").exists()
    assert LiveCallBudget(store.root).used("director") == 1

    _approve(store, job_id)
    assert processor.process(job_id) == JobStatus.COMPLETED.value
    record = store.get(job_id)
    assert record.stage == "completed"
    assert record.result is not None
    assert record.result.director_plan is not None
    assert record.result.render_status == "verified"
    assert (store.job_dir(job_id) / "output.mp4").is_file()
    assert LiveCallBudget(store.root).used("director") == 1
    assert record.result.director_audit is not None
    assert record.result.director_audit.job_id == job_id
    assert record.result.director_audit.validation_status == "accepted"
    assert record.result.director_request_id == record.result.director_audit.request_id


def test_live_director_validation_failure_persists_audit(tmp_path):
    text = "Keep me sharp and blur everything behind me."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text, _FailingDirector()))

    assert processor.process(job_id) == JobStatus.FAILED.value

    record = store.get(job_id)
    assert record.status == JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "DirectorValidationError"
    assert not (store.job_dir(job_id) / "output.mp4").exists()

    result = record.result
    assert result is not None
    audit = result.director_audit
    assert audit is not None
    assert audit.job_id == job_id
    assert audit.request_id == "req_failing1234"
    assert audit.server_request_id == "srv-failing-1"
    assert audit.provider == "meta-muse-spark-director-lite"
    assert audit.model == "muse-spark-1.3-contributor"
    assert audit.service_mode == "contributor"
    assert audit.wire_schema == "lite"
    assert audit.validation_status == DirectorValidationStatus.REJECTED
    assert audit.error_category == "validation"
    assert audit.error_code == "DirectorValidationError"
    assert audit.http_status == 200
    assert (audit.prompt_tokens, audit.completion_tokens, audit.total_tokens) == (2781, 1500, 4281)
    assert audit.estimated_cost_usd == pytest.approx(0.0005781)
    assert audit.actual_cost_usd is None
    assert result.director_request_id == "req_failing1234"
    assert result.director_usage is not None
    assert result.director_usage["prompt_tokens"] == 2781
    assert LiveCallBudget(store.root).used("director") == 1


def test_live_director_render_failure_preserves_audit(tmp_path, monkeypatch):
    text = "Keep me sharp and blur everything behind me."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text))

    assert processor.process(job_id) == JobStatus.AWAITING_APPROVAL.value
    _approve(store, job_id)

    def fail_render(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr("clipforge_worker.processor.render_video", fail_render)
    assert processor.process(job_id) == JobStatus.FAILED.value

    record = store.get(job_id)
    assert record.status == JobStatus.FAILED
    assert record.error is not None and record.error.code == "RuntimeError"
    assert record.result is not None
    audit = record.result.director_audit
    assert audit is not None
    assert audit.job_id == job_id
    assert audit.validation_status == "accepted"
    assert audit.prompt_tokens == 100
    assert record.result.director_usage is not None
    assert record.result.director_usage["completion_tokens"] == 50
    assert not (store.job_dir(job_id) / "output.mp4").exists()


def test_render_success_but_status_persistence_failure_never_claims_verified(
    tmp_path, monkeypatch
):
    text = "Keep me sharp and blur everything behind me."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text))

    assert processor.process(job_id) == JobStatus.AWAITING_APPROVAL.value
    _approve(store, job_id)

    original_update = store.update

    def fail_completion(target_job_id, **changes):
        if changes.get("status") is JobStatus.COMPLETED:
            raise RuntimeError("status persistence failed after render")
        return original_update(target_job_id, **changes)

    monkeypatch.setattr(store, "update", fail_completion)
    assert processor.process(job_id) == JobStatus.FAILED.value

    record = store.get(job_id)
    assert record.status is JobStatus.FAILED
    assert record.result is not None
    assert record.result.render_status == "failed"  # never "verified" without persisted success
    assert record.result.rendered is None
    assert (store.job_dir(job_id) / "output.mp4").is_file()  # render happened before persistence failed
    assert store.source_path(record).is_file()  # original untouched
    assert store.claim(job_id) is None  # a failed job cannot be claimed again


def test_live_director_replacement_waits_for_approval_without_render(tmp_path):
    text = "Replace the background with a professional recording studio."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text))

    assert processor.process(job_id) == JobStatus.AWAITING_APPROVAL.value
    record = store.get(job_id)
    assert record.status is JobStatus.AWAITING_APPROVAL
    assert record.stage == "awaiting_approval"
    assert record.result is not None and record.result.requires_approval is True
    assert record.result.render_status == "awaiting_approval"
    assert not (store.job_dir(job_id) / "output.mp4").exists()
    assert not (store.job_dir(job_id) / "masks").exists()

    _approve(store, job_id)
    assert processor.process(job_id) == JobStatus.COMPLETED.value
    record = store.get(job_id)
    assert record.stage == "completed"
    assert record.result is not None and record.result.render_status == "verified"
    assert (store.job_dir(job_id) / "output.mp4").is_file()
