"""Idea-to-video storyboard contract (post-MVP cinematic mode).

A Storyboard is the validated Creative Director output for "Create from an
Idea" projects. It carries no executable code: animation is described only
through the allowlisted AnimationPrimitive enum, which the web scene engine
maps to fixed Anime.js builders. Model output containing anything else is
rejected at validation time.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnimationPrimitive(str, Enum):
    """Allowlisted animation building blocks. Nothing else may execute."""

    CAMERA_ZOOM = "camera_zoom"
    CAMERA_PAN = "camera_pan"
    PARALLAX = "parallax"
    TEXT_REVEAL = "text_reveal"
    KINETIC_TYPOGRAPHY = "kinetic_typography"
    SVG_DRAW = "svg_draw"
    MOTION_PATH = "motion_path"
    PARTICLE_BURST = "particle_burst"
    SHOCKWAVE_RING = "shockwave_ring"
    FLASH = "flash"
    COUNTER = "counter"
    CHART_BAR = "chart_bar"
    FADE = "fade"
    SLIDE = "slide"
    MASK_REVEAL = "mask_reveal"
    ELASTIC_POP = "elastic_pop"
    SHAKE = "shake"
    GRADIENT_SHIFT = "gradient_shift"
    TRACKING = "tracking"


class Transition(str, Enum):
    FADE = "fade"
    CUT = "cut"
    DISSOLVE = "dissolve"
    WIPE = "wipe"
    ZOOM_BLUR = "zoom_blur"


class AnimationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primitive: AnimationPrimitive
    target: str = Field(min_length=1, max_length=80)
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=100, le=20000)
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)
    ease: str = Field(default="outQuad", max_length=40)


class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    duration_ms: int = Field(ge=1000, le=15000)
    narrative_purpose: str = Field(min_length=1, max_length=300)
    visual_description: str = Field(min_length=1, max_length=600)
    # Empty means "no image generation needed" (programmatic scene).
    image_generation_prompt: str = Field(default="", max_length=600)
    foreground_elements: list[str] = Field(default_factory=list, max_length=8)
    background_elements: list[str] = Field(default_factory=list, max_length=8)
    on_screen_text: list[str] = Field(default_factory=list, max_length=6)
    narration_segment: str = Field(default="", max_length=600)
    animation_sequence: list[AnimationStep] = Field(min_length=1, max_length=12)
    transition_in: Transition = Transition.FADE
    transition_out: Transition = Transition.FADE
    scientific_claims: list[str] = Field(default_factory=list, max_length=8)
    source_references: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _steps_fit_scene(self) -> "SceneSpec":
        for step in self.animation_sequence:
            if step.start_ms + step.duration_ms > self.duration_ms:
                raise ValueError(
                    f"Animation step {step.primitive.value} on {step.target} "
                    f"overruns scene {self.scene_id} duration."
                )
        return self


class AssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(pattern=r"^asset_[a-z0-9_]{1,40}$")
    scene_ids: list[str] = Field(min_length=1, max_length=8)
    description: str = Field(min_length=1, max_length=300)
    orientation: Literal["portrait", "landscape"] = "portrait"
    style_tags: list[str] = Field(default_factory=list, max_length=6)
    # Multiplane role: one "background" (full scene) plus at most one
    # "foreground" (bottom-anchored band drifting against the backdrop).
    role: Literal["background", "foreground"] = "background"


class Storyboard(BaseModel):
    """Validated Creative Director output for one idea-to-video project."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    project_title: str = Field(min_length=1, max_length=120)
    user_request: str = Field(min_length=1, max_length=1000)
    target_audience: str = Field(default="", max_length=200)
    tone: str = Field(default="", max_length=100)
    duration_seconds: int = Field(ge=5, le=60)
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    output_fps: int = Field(default=24, ge=12, le=30)
    resolution: str = Field(default="720x1280", max_length=20)
    visual_style_bible: str = Field(default="", max_length=1000)
    scientific_assumptions: list[str] = Field(default_factory=list, max_length=12)
    narration_script: str = Field(default="", max_length=4000)
    scenes: list[SceneSpec] = Field(min_length=1, max_length=12)
    asset_plan: list[AssetSpec] = Field(default_factory=list, max_length=16)
    source_references: list[str] = Field(default_factory=list, max_length=16)
    music_and_sound_cues: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _scenes_cover_duration(self) -> "Storyboard":
        total_ms = sum(scene.duration_ms for scene in self.scenes)
        expected_ms = self.duration_seconds * 1000
        if abs(total_ms - expected_ms) > 500:
            raise ValueError(
                f"Scene durations sum to {total_ms}ms but project duration is {expected_ms}ms."
            )
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("Scene ids must be unique.")
        for asset in self.asset_plan:
            unknown = [sid for sid in asset.scene_ids if sid not in scene_ids]
            if unknown:
                raise ValueError(f"Asset {asset.asset_id} references unknown scenes {unknown}.")
        return self

    @property
    def total_frames(self) -> int:
        return self.duration_seconds * self.output_fps
