"""Normalized internal provider responses. Providers map their native data into these shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentationSubject(BaseModel):
    """One tracked SAM object with its own validated mask sequence.

    `object_id` is the SAM wire id (stable within one response), kept as a
    string and never inferred from list position. `preview_path` is an optional
    local PNG with the actual source frame and a mask overlay.
    """

    model_config = ConfigDict(extra="forbid")
    object_id: str = Field(min_length=1)
    label: str = "Detected person"
    mask_manifest_path: str = Field(min_length=1)
    preview_path: str | None = None
    first_frame: int | None = Field(default=None, ge=0)
    last_frame: int | None = Field(default=None, ge=0)
    frames_detected: int = Field(default=0, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TranscriptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    language: str = "pt-BR"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provider_name: str
    is_mock: bool
    session_id: str | None = None
    audio_duration_ms: int | None = Field(default=None, ge=0)


class SegmentationResult(BaseModel):
    """Backed by real local mask files (ADR-005), never a bare success flag."""

    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    mask_manifest_path: str = Field(min_length=1)
    frame_count: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    provider_name: str
    is_mock: bool
    model: str | None = None
    subjects: list[SegmentationSubject] = Field(default_factory=list)
    source_sha256: str | None = None
    status: Literal["completed", "incomplete"] = "completed"
    diagnostics: list[str] = Field(default_factory=list)
    file_cleanup: Literal["not_applicable", "not_uploaded", "deleted", "failed"] = "not_applicable"


class RenderResult(BaseModel):
    """Verified facts about a rendered output file. Emitted only after ffprobe verification."""

    model_config = ConfigDict(extra="forbid")
    output_relative_path: str
    mode: Literal["blur_background", "replace_background"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    file_size_bytes: int = Field(gt=0)
    has_audio: bool


class BackgroundResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    orientation: Literal["landscape", "portrait"]
    simulated_prompt: str
    provider_name: str
    is_mock: bool
    model: str | None = None
    request_id: str | None = None
    prompt: str | None = None
    effective_prompt: str | None = None
    revised_prompt: str | None = None
    output_format: str | None = None
    size_requested: str | None = None
    image_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime | None = None
    usage: dict | None = None
