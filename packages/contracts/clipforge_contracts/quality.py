"""Automatic quality review contracts for idea-to-video drafts (post-MVP slice).

Spark returns feedback, never modified video. The deterministic QA in
scripts/render_idea_to_video.py runs first; only QA-passed drafts reach the
critic. At most one automatic revision cycle is allowed (see correction.py
counter in the worker-side flow); image regeneration always needs approval.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Verdict(str, Enum):
    PASS = "pass"
    NEEDS_FIX = "needs_fix"
    REJECT = "reject"


class CorrectionType(str, Enum):
    ANIMATION_PATCH = "animation_patch"
    TEXT_FIX = "text_fix"
    ASSET_REGENERATION = "asset_regeneration"
    NO_FIX = "no_fix"


class SceneReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(min_length=1, max_length=40)
    severity: Literal["info", "warning", "error"] = "info"
    timestamp_ms: int = Field(ge=0)
    issue_category: str = Field(min_length=1, max_length=80)
    explanation: str = Field(min_length=1, max_length=500)
    suggested_fix: str = Field(default="", max_length=500)
    correction_type: CorrectionType = CorrectionType.NO_FIX
    requires_asset_regeneration: bool = False


class QualityReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    project_title: str = Field(min_length=1, max_length=120)
    overall_verdict: Verdict
    scene_reviews: list[SceneReview] = Field(default_factory=list, max_length=24)
    summary: str = Field(default="", max_length=1000)

    @property
    def needs_revision(self) -> bool:
        return self.overall_verdict == Verdict.NEEDS_FIX

    @property
    def auto_fixable(self) -> bool:
        """True only when every flagged issue is an animation/text patch."""
        flagged = [r for r in self.scene_reviews if r.severity in ("warning", "error")]
        if not flagged:
            return False
        return all(
            r.correction_type in (CorrectionType.ANIMATION_PATCH, CorrectionType.TEXT_FIX)
            and not r.requires_asset_regeneration
            for r in flagged
        )


class MockQualityCritic:
    """Deterministic fixture critic. Offline only."""

    def __init__(self, review: QualityReview | None = None) -> None:
        self._review = review or QualityReview(
            project_title="E se um asteroide gigante atingisse a Terra?",
            overall_verdict=Verdict.PASS,
            summary="Draft matches the storyboard; text readable; no defects found.",
        )

    def review_draft(self, project_title: str) -> QualityReview:
        review = self._review.model_copy(deep=True)
        return review.model_copy(update={"project_title": project_title})
