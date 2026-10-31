"""Normalized internal provider responses. Providers map their native data into these shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
