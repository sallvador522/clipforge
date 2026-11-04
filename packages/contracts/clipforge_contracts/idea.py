"""Idea-to-video job contracts (product flow).

An idea job is created from a written brief, planned by the Creative Director
(mock or live), reviewed by the user, and only then rendered locally. This
module owns the non-executable state: options, cost estimates, approvals,
generated assets, render versions and the persisted job record.

Invariants:
- No field may carry executable code, shell commands, arbitrary paths or URLs.
- Paid work requires a recorded approval whose brief/prompt hashes and provider
  modes still match the job at execution time.
- A render version is only delivered after deterministic QA verified the file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts.storyboard import Storyboard, StoryboardPatch

ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
}

# Scene budget for a video of N seconds. Mirrors the mock director so the
# pre-planning estimate and the produced board stay in the same ballpark.
MAX_SCENES = 4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def scene_count_for(duration_seconds: int) -> int:
    if duration_seconds >= 16:
        return 4
    if duration_seconds >= 10:
        return 3
    return 2


class IdeaOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ADR-036: no fixed ceiling; the director's delivered duration wins.
    duration_seconds: int = Field(default=20, ge=5)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    fps: int = Field(default=24, ge=12, le=30)
    style_preset: Literal["cinematic", "documentary", "product", "bold"] = "cinematic"
    use_generated_images: bool = True
    language: Literal["pt-PT", "pt-BR", "en"] = "pt-PT"

    @property
    def width(self) -> int:
        return ASPECT_DIMENSIONS[self.aspect_ratio][0]

    @property
    def height(self) -> int:
        return ASPECT_DIMENSIONS[self.aspect_ratio][1]

    @property
    def frame_count(self) -> int:
        return self.duration_seconds * self.fps

    def canonical(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def brief_hash(brief: str, options: IdeaOptions) -> str:
    """Stable hash of everything the storyboard approval covers."""
    digest = hashlib.sha256()
    digest.update(brief.strip().encode("utf-8"))
    digest.update(b"\x00")
    digest.update(options.canonical().encode("utf-8"))
    return digest.hexdigest()


def storyboard_hash(board: Storyboard) -> str:
    payload = json.dumps(board.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CostEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard_usd: float = Field(default=0.0, ge=0.0)
    images_usd: float = Field(default=0.0, ge=0.0)
    transcription_usd: float = Field(default=0.0, ge=0.0)
    total_usd: float = Field(default=0.0, ge=0.0)
    cap_usd: float = Field(default=0.10, gt=0.0)
    # Upper bound, not generated count: the raw plan allows up to 12 plates
    # (multiplane foregrounds included); build_assets truncates to MAX_PLATES.
    image_count: int = Field(default=0, ge=0, le=12)

    def recompute_total(self) -> "CostEstimate":
        self.total_usd = round(self.storyboard_usd + self.images_usd + self.transcription_usd, 6)
        return self


class ApprovalScope(str, Enum):
    STORYBOARD = "storyboard"
    ASSETS = "assets"


class IdeaApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: ApprovalScope
    approved_usd: float = Field(ge=0.0, le=5.0)
    approved_at: datetime = Field(default_factory=utc_now)
    provider_modes: dict[str, str] = Field(default_factory=dict)
    brief_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_ids: list[str] = Field(default_factory=list)
    prompt_hashes: dict[str, str] = Field(default_factory=dict)


class AssetStatus(str, Enum):
    PLANNED = "planned"
    APPROVED = "approved"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"
    SKIPPED = "skipped"


class IdeaAsset(BaseModel):
    """One generated (or planned) scene plate.

    `prompt` is built server-side from the validated storyboard. The approval
    stores `prompt_hash`, so a prompt can never change silently after payment
    was authorised.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=r"^asset_[a-z0-9_]{1,40}$")
    scene_ids: list[str] = Field(min_length=1, max_length=8)
    prompt: str = Field(min_length=1, max_length=900)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    orientation: Literal["portrait", "landscape"] = "portrait"
    role: Literal["background", "foreground"] = "background"
    status: AssetStatus = AssetStatus.PLANNED
    filename: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    provider_name: str | None = None
    is_mock: bool = True
    request_id: str | None = None
    cost_usd: float = Field(default=0.0, ge=0.0)
    error: str | None = None
    generated_at: datetime | None = None


class RenderVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    storyboard_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_relative_path: str = Field(min_length=1)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(ge=1, le=60)
    frame_count: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    qa: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    is_delivered: bool = False


class IdeaError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=2000)


class IdeaProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=40)
    current: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class IdeaStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class IdeaStateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IdeaStatus
    stage: str
    at: datetime = Field(default_factory=utc_now)
    note: str | None = Field(default=None, max_length=300)


class IdeaState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(min_length=10, max_length=1000)
    options: IdeaOptions = Field(default_factory=IdeaOptions)
    estimate: CostEstimate | None = None
    approvals: list[IdeaApproval] = Field(default_factory=list)
    storyboard: Storyboard | None = None
    storyboard_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # ADR-036 refinement: a director patch waits here for explicit user
    # approval; it is applied to the storyboard only on /direct/apply.
    pending_patch: StoryboardPatch | None = None
    pending_patch_instruction: str | None = Field(default=None, max_length=1000)
    pending_clarification_question: str | None = Field(default=None, max_length=300)
    assets: list[IdeaAsset] = Field(default_factory=list)
    spent_usd: float = Field(default=0.0, ge=0.0)
    versions: list[RenderVersion] = Field(default_factory=list)
    correction_cycles: int = Field(default=0, ge=0, le=1)

    def approval(self, scope: ApprovalScope) -> IdeaApproval | None:
        for approval in reversed(self.approvals):
            if approval.scope == scope:
                return approval
        return None

    def delivered_version(self) -> RenderVersion | None:
        for version in reversed(self.versions):
            if version.is_delivered:
                return version
        return None


class IdeaJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea_id: str = Field(pattern=r"^idea_[a-z0-9]{12}$")
    project_id: str | None = None
    status: IdeaStatus = IdeaStatus.AWAITING_APPROVAL
    stage: str = Field(default="awaiting_storyboard_cost", min_length=1, max_length=40)
    idea: IdeaState
    error: IdeaError | None = None
    progress: IdeaProgress | None = None
    cancel_requested: bool = False
    history: list[IdeaStateEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
