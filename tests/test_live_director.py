"""Live director wiring tests: budget caps, approval gate, execution path."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge_contracts import TranscriptResult
from clipforge_director import LiveBudgetExceeded, LiveCallBudget, MockProfessionalEditingDirector
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
        self._text = transcript_text

    def create_plan(self, transcript: TranscriptResult, video=None):
        return MockProfessionalEditingDirector().create_plan(
            TranscriptResult(text=self._text, language="pt-BR", provider_name="t", is_mock=True)
        )


def _bundle(transcript_text: str) -> ProviderBundle:
    return ProviderBundle(
        transcription=MockTranscriptionProvider(),
        planner=MockEditingPlannerProvider(),
        segmentation=MockSegmentationProvider(),
        background=MockBackgroundGenerationProvider(),
        mode="mock",
        transcription_mode="mock",
        director=_FixedDirector(transcript_text),
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


def test_live_director_blur_executes_and_records_plan(tmp_path):
    text = "Keep me sharp and blur everything behind me."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text))
    assert processor.process(job_id) == JobStatus.COMPLETED.value
    record = store.get(job_id)
    assert record.stage == "completed"
    assert record.result is not None
    assert record.result.director_plan is not None
    assert record.result.render_status == "verified"
    assert (store.job_dir(job_id) / "output.mp4").is_file()
    assert LiveCallBudget(store.root).used("director") == 1


def test_live_director_replacement_waits_for_approval_without_render(tmp_path):
    text = "Replace the background with a professional recording studio."
    store, job_id = _job(tmp_path, text)
    processor = JobProcessor(store, _bundle(text))
    assert processor.process(job_id) == JobStatus.COMPLETED.value
    record = store.get(job_id)
    assert record.stage == "awaiting_approval"
    assert record.result is not None and record.result.requires_approval is True
    assert record.result.render_status == "awaiting_approval"
    assert not (store.job_dir(job_id) / "output.mp4").exists()
