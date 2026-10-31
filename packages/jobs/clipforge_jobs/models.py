"""Job state machine models.

Status is exactly one of queued / processing / completed / failed.
`stage` is a finer-grained progress detail (awaiting_voice, transcribing,
planning, segmenting, preparing_background, done, ...) and never replaces status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts import BackgroundResult, EditingPlan, RenderResult, SegmentationResult, TranscriptResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
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


class JobResult(BaseModel):
    """Result of the mock AI pipeline. Rendering is Milestone 4: render_status is explicit."""

    model_config = ConfigDict(extra="forbid")
    transcript: TranscriptResult | None = None
    plan: EditingPlan | None = None
    segmentation: SegmentationResult | None = None
    background: BackgroundResult | None = None
    rendered: RenderResult | None = None  # set only after output verification passes
    requires_clarification: bool = False
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
    audio_fixture_id: str | None = None
    result: JobResult | None = None
    error: JobError | None = None
    attempts: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
