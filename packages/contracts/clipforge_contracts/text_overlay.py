"""Clip text overlays + colour grade for the edit track (ADR-047).

Clip texts are real project data: validated overlays persisted on the job
record, editable in the Studio (preview selection, Properties Inspector,
timeline T1 lane, Muse tools) and burned into the timeline composition by
the worker with real OpenCV/PIL rendering — never preview-only. Colour
grade is a real local per-frame adjustment (contrast/brightness/saturation)
applied by the same composition; it is local image processing, not AI.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ClipTextStyleId = Literal["rise", "reveal", "pop", "kinetic", "tracking"]
ClipTextWeight = Literal["normal", "bold"]

CLIP_TEXT_STYLES: tuple[str, ...] = ("rise", "reveal", "pop", "kinetic", "tracking")
CLIP_TEXT_MAX = 20


class ClipTextOverlay(BaseModel):
    """One selectable text element. Times are global program seconds."""

    model_config = ConfigDict(extra="forbid")
    overlay_id: str = Field(pattern=r"^txt_[a-z0-9]{4,32}$")
    text: str = Field(min_length=1, max_length=140)
    style: ClipTextStyleId = "rise"
    start_s: float = Field(default=0.0, ge=0.0)
    duration_s: float = Field(default=2.5, ge=0.5, le=8.0)
    x: float = Field(default=0.5, ge=0.08, le=0.92)
    y: float = Field(default=0.78, ge=0.1, le=0.9)
    scale: float = Field(default=1.0, ge=0.7, le=1.6)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    weight: ClipTextWeight = "bold"

    @model_validator(mode="after")
    def _check_program_bounds(self) -> "ClipTextOverlay":
        from clipforge_contracts.timeline import TIMELINE_MAX_DURATION_S

        if self.start_s + self.duration_s > TIMELINE_MAX_DURATION_S + 1e-9:
            raise ValueError("text overlay ends past the program cap")
        return self


class ColourGrade(BaseModel):
    """Local colour adjustment applied per frame before text burn-in."""

    model_config = ConfigDict(extra="forbid")
    contrast: float = Field(default=1.0, ge=0.5, le=1.5)
    brightness: float = Field(default=0.0, ge=-0.3, le=0.3)
    saturation: float = Field(default=1.0, ge=0.0, le=2.0)

    def is_identity(self) -> bool:
        return self.contrast == 1.0 and self.brightness == 0.0 and self.saturation == 1.0
