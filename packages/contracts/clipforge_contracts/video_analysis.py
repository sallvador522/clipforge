"""Video-understanding contracts (ADR-057).

Muse Spark 1.3 receives the actual video (Responses API, input_file file_id)
and returns a real visual analysis. The model output is validated but never
trusted blindly:

- Every descriptive field is optional. Missing sections stay null — the
  server never fabricates summary text, subjects, timestamps or opportunities.
- Approximate times are explicitly marked as approximate and must never be
  presented as frame-accurate edit boundaries.
- No identity inference: subjects are neutral visual descriptions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VideoScene(BaseModel):
    """One approximately-bounded scene. Times are model estimates, not cuts."""

    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, ge=0)
    approximate: bool = True
    description: str | None = Field(default=None, max_length=500)
    main_subject: str | None = Field(default=None, max_length=200)
    main_action: str | None = Field(default=None, max_length=200)
    composition_note: str | None = Field(default=None, max_length=300)
    editing_opportunity: str | None = Field(default=None, max_length=300)


class VideoMoment(BaseModel):
    """One important moment. Timestamp is approximate by contract."""

    model_config = ConfigDict(extra="forbid")
    at_s: float | None = Field(default=None, ge=0)
    approximate: bool = True
    label: str = Field(min_length=1, max_length=200)


class VideoAnalysis(BaseModel):
    """Validated visual analysis of one asset version.

    `analysis_id` is server-generated. `raw_text` is the model's verbatim
    answer (kept even when section parsing fails). Structured fields are a
    best-effort lenient projection of that text; absent means absent.
    """

    model_config = ConfigDict(extra="forbid")
    analysis_id: str = Field(pattern=r"^van_[a-z0-9]{12}$")
    project_id: str = Field(pattern=r"^prj_[a-z0-9]{12}$")
    asset_id: str = Field(pattern=r"^ast_[a-z0-9]{12}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(default="meta-muse-spark", max_length=64)
    model: str = Field(default="muse-spark-1.3", max_length=64)
    provider_response_id: str | None = Field(default=None, max_length=128)
    video_duration_s: float | None = Field(default=None, gt=0)
    created_at: datetime = Field(default_factory=utc_now)
    raw_text: str = Field(min_length=1, max_length=12000)
    overall_summary: str | None = Field(default=None, max_length=2000)
    visual_style: str | None = Field(default=None, max_length=500)
    subjects: list[str] = Field(default_factory=list, max_length=20)
    objects_seen: list[str] = Field(default_factory=list, max_length=20)
    actions: list[str] = Field(default_factory=list, max_length=20)
    scenes: list[VideoScene] = Field(default_factory=list, max_length=12)
    important_moments: list[VideoMoment] = Field(default_factory=list, max_length=12)
    composition_observations: list[str] = Field(default_factory=list, max_length=12)
    editing_opportunities: list[str] = Field(default_factory=list, max_length=12)
    uncertainties: list[str] = Field(default_factory=list, max_length=12)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    is_mock: bool = False
    file_reused: bool = False


class ProviderFileRef(BaseModel):
    """Reusable Meta Files API reference bound to one exact asset version."""

    model_config = ConfigDict(extra="forbid")
    provider: str = Field(default="meta", max_length=32)
    model: str = Field(default="muse-spark-1.3", max_length=64)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_id: str = Field(pattern=r"^file-[A-Za-z0-9]+$", max_length=64)
    uploaded_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    purpose: str = Field(default="user_data", max_length=32)
