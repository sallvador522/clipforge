"""Project workspace contracts (P0).

Project = persistent workspace. Asset = imported resource. Job = single AI
processing operation (see clipforge_jobs.models.JobRecord.project_id).

No database: persistence is filesystem JSON under storage/projects/.
IDs are generated server-side; user-supplied paths are never trusted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AssetKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    TEXT = "text"
    GRAPHICS = "graphics"


class AssetProvenance(str, Enum):
    UPLOAD = "upload"
    SESSION_SOURCE = "session_source"
    GENERATED = "generated"
    LOCAL_RENDER = "local_render"


class ProjectMode(str, Enum):
    EDIT = "edit"
    IDEA = "idea"


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern=r"^prj_[a-z0-9]{12}$")
    title: str = Field(min_length=1, max_length=80)
    mode: ProjectMode = ProjectMode.EDIT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AssetRecord(BaseModel):
    """Metadata sidecar for one imported asset. The binary lives beside it."""

    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(pattern=r"^ast_[a-z0-9]{12}$")
    project_id: str = Field(pattern=r"^prj_[a-z0-9]{12}$")
    kind: AssetKind
    original_filename: str = Field(min_length=1, max_length=255)
    stored_filename: str = Field(min_length=1, max_length=255)
    mime: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: AssetProvenance = AssetProvenance.UPLOAD
    created_at: datetime = Field(default_factory=utc_now)
    # Optional media metadata (only the relevant subset is set per kind).
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    frame_count: int | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    audio_codec: str | None = Field(default=None, max_length=40)
    audio_channels: int | None = Field(default=None, gt=0)
    text_lines: int | None = Field(default=None, ge=0)
    cue_count: int | None = Field(default=None, ge=0)
    text_encoding: str | None = Field(default=None, max_length=20)
    sanitized: bool = False
