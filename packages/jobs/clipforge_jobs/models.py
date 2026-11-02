"""Job state machine models.

Status is exactly one of queued / processing / awaiting_approval /
awaiting_clarification / rejected / unsupported / completed / failed.
`stage` is a finer-grained progress detail (awaiting_voice, planning,
awaiting_approval, approved, segmenting, rendering, ...) and never replaces
status. Every status/stage change is appended to `state_history`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts import (
    BackgroundResult,
    DirectorAudit,
    EditingPlan,
    ProfessionalEditingPlan,
    RenderResult,
    SegmentationResult,
    SubjectDetectionConsent,
    TranscriptResult,
)
from clipforge_contracts.edl import EditHistoryEntry


MAX_CLARIFICATIONS = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_CONSENT = "awaiting_consent"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    has_audio: bool


class JobError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str


class JobStateEntry(BaseModel):
    """Auditable state transition. Persisted in job.json; no media or secrets."""

    model_config = ConfigDict(extra="forbid")
    at: datetime = Field(default_factory=utc_now)
    from_status: str
    to_status: str
    from_stage: str
    to_stage: str
    actor: Literal["user", "worker", "system"]
    note: str | None = Field(default=None, max_length=300)


class JobResult(BaseModel):
    """Result of the mock AI pipeline. Rendering is Milestone 4: render_status is explicit."""

    model_config = ConfigDict(extra="forbid")
    transcript: TranscriptResult | None = None
    plan: EditingPlan | None = None
    segmentation: SegmentationResult | None = None
    background: BackgroundResult | None = None
    background_generation_attempted: bool = False
    rendered: RenderResult | None = None  # set only after output verification passes
    director_plan: ProfessionalEditingPlan | None = None
    director_usage: dict | None = None
    director_request_id: str | None = None
    director_audit: DirectorAudit | None = None
    requires_clarification: bool = False
    requires_approval: bool = False
    render_status: str = "not_implemented"  # becomes "verified" only with a verified output file


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = "awaiting_voice"
    ready: bool = False  # becomes True when a voice instruction is attached
    original_filename: str
    source_relative_path: str  # relative to the storage root, forward slashes
    source_info: SourceInfo
    source_sha256: str | None = None
    subject_detection_consent: SubjectDetectionConsent | None = None
    audio_fixture_id: str | None = None
    confirmed_transcript: str | None = None
    transcript_is_mock: bool = False
    transcription_session_id: str | None = None
    edit_history: list[EditHistoryEntry] = Field(default_factory=list)
    state_history: list[JobStateEntry] = Field(default_factory=list)
    approval_granted: bool = False
    selected_subject_ids: list[str] = Field(default_factory=list)
    clarification_answer: str | None = Field(default=None, max_length=300)
    clarification_count: int = Field(default=0, ge=0)
    result: JobResult | None = None
    error: JobError | None = None
    attempts: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
