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


class TextStyle(BaseModel):
    """Typography for a scene's on-screen text. Every field is rendered by
    the scene engine; nothing here is free-form CSS."""

    model_config = ConfigDict(extra="forbid")
    family: Literal["sans", "serif", "mono"] = "sans"
    weight: int = Field(default=800, ge=300, le=900)
    size_scale: float = Field(default=1.0, ge=0.6, le=2.0)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "lower"] = "top"
    letter_spacing_em: float = Field(default=0.0, ge=-0.05, le=0.6)


class TextStyleUpdate(BaseModel):
    """Partial TextStyle: only the fields the director wants to change."""

    model_config = ConfigDict(extra="forbid")
    family: Literal["sans", "serif", "mono"] | None = None
    weight: int | None = Field(default=None, ge=300, le=900)
    size_scale: float | None = Field(default=None, ge=0.6, le=2.0)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] | None = None
    valign: Literal["top", "middle", "lower"] | None = None
    letter_spacing_em: float | None = Field(default=None, ge=-0.05, le=0.6)


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
    text_style: TextStyle = Field(default_factory=TextStyle)
    # Hue rotation (degrees) applied to this scene's backdrop layer. None
    # keeps the deterministic per-scene gradient.
    backdrop_hue_deg: float | None = Field(default=None, ge=-180, le=180)
    narration_segment: str = Field(default="", max_length=600)
    animation_sequence: list[AnimationStep] = Field(min_length=1, max_length=12)
    transition_in: Transition = Transition.FADE
    transition_out: Transition = Transition.FADE
    # ADR-041: outgoing boundary length in ms (engine clamps to the adjacent
    # scene durations). transition_in stays legacy metadata.
    transition_ms: int = Field(default=400, ge=200, le=1000)
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


class OverlaySpec(BaseModel):
    """Global overlay (multitrack layer 1, ADR-040/041): styled content rendered
    above the scenes over a video-global time window.

    kind=text is fully local/programmatic. kind=image reuses an already
    GENERATED plate from the idea's assets (no new generation, $0.00);
    asset_id must reference a generated plate or rendering fails closed."""

    model_config = ConfigDict(extra="forbid")
    overlay_id: str = Field(pattern=r"^overlay_[a-z0-9_]{1,24}$")
    kind: Literal["text", "image"] = "text"
    text: str = Field(default="", max_length=140)
    asset_id: str | None = Field(default=None, pattern=r"^asset_[a-z0-9_]{1,40}$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    style: TextStyle = Field(default_factory=TextStyle)

    @model_validator(mode="after")
    def _kind_shape(self) -> "OverlaySpec":
        if self.kind == "text" and not self.text:
            raise ValueError("A text overlay needs text.")
        if self.kind == "image" and not self.asset_id:
            raise ValueError("An image overlay needs asset_id of a generated plate.")
        return self


class Storyboard(BaseModel):
    """Validated Creative Director output for one idea-to-video project."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    project_title: str = Field(min_length=1, max_length=120)
    user_request: str = Field(min_length=1, max_length=1000)
    target_audience: str = Field(default="", max_length=200)
    tone: str = Field(default="", max_length=100)
    # No fixed ceiling (ADR-036): the director's scene durations are
    # authoritative and duration_seconds is derived from them below. The
    # practical bound is 12 scenes x 15 s from the SceneSpec limits.
    duration_seconds: int = Field(ge=5)
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    output_fps: int = Field(default=24, ge=12, le=30)
    resolution: str = Field(default="720x1280", max_length=20)
    visual_style_bible: str = Field(default="", max_length=1000)
    scientific_assumptions: list[str] = Field(default_factory=list, max_length=12)
    narration_script: str = Field(default="", max_length=4000)
    scenes: list[SceneSpec] = Field(min_length=1, max_length=12)
    asset_plan: list[AssetSpec] = Field(default_factory=list, max_length=16)
    # ADR-040 multitrack layer 1: global text overlays above the scenes.
    overlays: list[OverlaySpec] = Field(default_factory=list, max_length=3)
    source_references: list[str] = Field(default_factory=list, max_length=16)
    music_and_sound_cues: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _scenes_cover_duration(self) -> "Storyboard":
        # ADR-036: the scenes are authoritative. duration_seconds is derived
        # from their sum (the last scene absorbs the sub-second remainder),
        # never a reason to reject a board the director delivered.
        total_ms = sum(scene.duration_ms for scene in self.scenes)
        derived = max(1, round(total_ms / 1000))
        if derived != self.duration_seconds:
            self.duration_seconds = derived
        delta = self.duration_seconds * 1000 - total_ms
        if delta and self.scenes:
            last = self.scenes[-1]
            adjusted = last.duration_ms + delta
            if adjusted >= 1000:
                self.scenes[-1] = last.model_copy(update={"duration_ms": adjusted})
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("Scene ids must be unique.")
        for asset in self.asset_plan:
            unknown = [sid for sid in asset.scene_ids if sid not in scene_ids]
            if unknown:
                raise ValueError(f"Asset {asset.asset_id} references unknown scenes {unknown}.")
        overlay_ids = [overlay.overlay_id for overlay in self.overlays]
        if len(set(overlay_ids)) != len(overlay_ids):
            raise ValueError("Overlay ids must be unique.")
        for overlay in self.overlays:
            if overlay.start_ms >= overlay.end_ms:
                raise ValueError(f"Overlay {overlay.overlay_id} ends before it starts.")
            if overlay.end_ms > self.duration_seconds * 1000:
                raise ValueError(
                    f"Overlay {overlay.overlay_id} overruns the video duration."
                )
        return self

    @property
    def total_frames(self) -> int:
        return self.duration_seconds * self.output_fps


# --- Voice/text refinement patch (ADR-036) ---------------------------------
# The refinement director never returns a whole board: it returns typed
# operations against the persisted board, which the backend applies and
# revalidates. No operation carries code, paths or arbitrary parameters.

from typing import Annotated, Union  # noqa: E402


class SetSceneTextOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_scene_text"] = "set_scene_text"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    lines: list[str] = Field(max_length=6)


class SetTextStyleOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_text_style"] = "set_text_style"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    style: TextStyleUpdate


class SetAnimationStepOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_animation_step"] = "set_animation_step"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    target: str = Field(min_length=1, max_length=80)
    primitive: AnimationPrimitive | None = None
    start_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=100, le=20000)
    ease: str | None = Field(default=None, max_length=40)
    params: dict[str, float | int | str | bool] | None = None


class AddAnimationStepOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add_animation_step"] = "add_animation_step"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    step: AnimationStep


class RemoveAnimationStepOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["remove_animation_step"] = "remove_animation_step"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    target: str = Field(min_length=1, max_length=80)
    primitive: AnimationPrimitive | None = None


class DeleteSceneOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["delete_scene"] = "delete_scene"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")


class AddSceneOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add_scene"] = "add_scene"
    scene: SceneSpec
    after_scene_id: str | None = Field(default=None, pattern=r"^scene_[1-9][0-9]*$")


class SetSceneVisualOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_scene_visual"] = "set_scene_visual"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    backdrop_hue_deg: float | None = Field(default=None, ge=-180, le=180)
    visual_description: str | None = Field(default=None, min_length=1, max_length=600)


class SetToneOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_tone"] = "set_tone"
    tone: str | None = Field(default=None, min_length=1, max_length=100)
    visual_style_bible: str | None = Field(default=None, min_length=1, max_length=1000)


class SetSceneDurationOp(BaseModel):
    """ADR-042 voice trim: change one scene's duration (steps scale along)."""

    model_config = ConfigDict(extra="forbid")
    op: Literal["set_scene_duration"] = "set_scene_duration"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    duration_ms: int = Field(ge=1000, le=15000)


class SetTransitionOp(BaseModel):
    """ADR-040/041: editable outgoing transition of one scene (boundary N→N+1).
    The last scene's transition is inert (no outgoing boundary)."""

    model_config = ConfigDict(extra="forbid")
    op: Literal["set_transition"] = "set_transition"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    transition_out: Transition
    transition_ms: int | None = Field(default=None, ge=200, le=1000)


class AddOverlayOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add_overlay"] = "add_overlay"
    overlay: OverlaySpec


class SetOverlayTextOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["set_overlay_text"] = "set_overlay_text"
    overlay_id: str = Field(pattern=r"^overlay_[a-z0-9_]{1,24}$")
    text: str = Field(min_length=1, max_length=140)


class RemoveOverlayOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["remove_overlay"] = "remove_overlay"
    overlay_id: str = Field(pattern=r"^overlay_[a-z0-9_]{1,24}$")


class SplitSceneOp(BaseModel):
    """ADR-042 voice split: divide one scene at at_ms. Each half repeats the
    animation compressed to its duration (same rule as the manual editor)."""

    model_config = ConfigDict(extra="forbid")
    op: Literal["split_scene"] = "split_scene"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    at_ms: int = Field(ge=1000)


class MoveSceneOp(BaseModel):
    """ADR-042 voice reorder: move one scene one position (-1 back, +1 forward)."""

    model_config = ConfigDict(extra="forbid")
    op: Literal["move_scene"] = "move_scene"
    scene_id: str = Field(pattern=r"^scene_[1-9][0-9]*$")
    direction: Literal[-1, 1]


PatchOperation = Annotated[
    Union[
        SetSceneTextOp,
        SetTextStyleOp,
        SetAnimationStepOp,
        AddAnimationStepOp,
        RemoveAnimationStepOp,
        DeleteSceneOp,
        AddSceneOp,
        SetSceneVisualOp,
        SetToneOp,
        SetTransitionOp,
        AddOverlayOp,
        SetOverlayTextOp,
        RemoveOverlayOp,
        SetSceneDurationOp,
        SplitSceneOp,
        MoveSceneOp,
    ],
    Field(discriminator="op"),
]


class StoryboardPatch(BaseModel):
    """Refinement director output: typed operations or one clarification."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    instruction: str = Field(min_length=1, max_length=1000)
    outcome: Literal["apply", "clarification"] = "apply"
    summary: str = Field(min_length=1, max_length=500)
    clarification_question: str | None = Field(default=None, max_length=300)
    operations: list[PatchOperation] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _outcome_shape(self) -> "StoryboardPatch":
        if self.outcome == "apply":
            if not self.operations:
                raise ValueError("An apply patch needs at least one operation.")
            if self.clarification_question:
                raise ValueError("An apply patch must not ask a clarification question.")
        else:
            if self.operations:
                raise ValueError("A clarification patch must not contain operations.")
            if not self.clarification_question:
                raise ValueError("A clarification patch needs one focused question.")
        return self
