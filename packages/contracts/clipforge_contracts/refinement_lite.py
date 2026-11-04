"""StoryboardPatch-lite — minimal wire contract (ADR-037 fix for LIVE-CALL refine 001).

The full patch schema (11.5 KB, 15 $defs) failed exactly like the full v2 plan
schema once did (HTTP 500 on the Contributor tier), while the hand-written
lite plan schema (2.1 KB, zero $refs) succeeds. So the wire carries a
hand-written minimal schema: zero $refs, flat operation objects. Strictness is
NOT relaxed: the response is parsed into `LitePatch`, converted to a full
`StoryboardPatch`, and the full Pydantic validators run unchanged.

Two inherently nested payloads are flattened:
- add_animation_step carries flat step_* fields; the converter builds a full
  AnimationStep (validated).
- add_scene carries scene_json (a JSON string); the converter parses it into a
  full SceneSpec (validated). The wire schema stays tiny either way.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts.storyboard import (
    AddAnimationStepOp,
    AddOverlayOp,
    AddSceneOp,
    AnimationStep,
    DeleteSceneOp,
    MoveSceneOp,
    OverlaySpec,
    PatchOperation,
    RemoveAnimationStepOp,
    RemoveOverlayOp,
    SceneSpec,
    SetAnimationStepOp,
    SetOverlayTextOp,
    SetSceneDurationOp,
    SetSceneTextOp,
    SetSceneVisualOp,
    SetTextStyleOp,
    SetToneOp,
    SetTransitionOp,
    SplitSceneOp,
    StoryboardPatch,
    TextStyleUpdate,
)

_OPS = [
    "set_scene_text",
    "set_text_style",
    "set_animation_step",
    "add_animation_step",
    "remove_animation_step",
    "delete_scene",
    "add_scene",
    "set_scene_visual",
    "set_tone",
    "set_transition",
    "add_overlay",
    "set_overlay_text",
    "remove_overlay",
    "set_scene_duration",
    "split_scene",
    "move_scene",
]

_TRANSITIONS = ["cut", "fade", "dissolve", "wipe", "zoom_blur"]

_PRIMITIVES = [
    "camera_zoom",
    "camera_pan",
    "parallax",
    "text_reveal",
    "kinetic_typography",
    "svg_draw",
    "motion_path",
    "particle_burst",
    "shockwave_ring",
    "flash",
    "counter",
    "chart_bar",
    "fade",
    "slide",
    "mask_reveal",
    "elastic_pop",
    "shake",
    "gradient_shift",
    "tracking",
]

# Hand-written wire schema: zero $refs, all inline. Kept deliberately small.
PATCH_LITE_WIRE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "instruction": {"type": "string"},
        "outcome": {"type": "string", "enum": ["apply", "clarification"]},
        "summary": {"type": "string"},
        "clarification_question": {"type": "string"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": _OPS},
                    "scene_id": {"type": "string"},
                    "after_scene_id": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                    "style": {
                        "type": "object",
                        "properties": {
                            "family": {"type": "string", "enum": ["sans", "serif", "mono"]},
                            "weight": {"type": "number"},
                            "size_scale": {"type": "number"},
                            "color": {"type": "string"},
                            "align": {"type": "string", "enum": ["left", "center", "right"]},
                            "valign": {"type": "string", "enum": ["top", "middle", "lower"]},
                            "letter_spacing_em": {"type": "number"},
                        },
                        "additionalProperties": False,
                    },
                    "target": {"type": "string"},
                    "primitive": {"type": "string", "enum": _PRIMITIVES},
                    "start_ms": {"type": "number"},
                    "duration_ms": {"type": "number"},
                    "ease": {"type": "string"},
                    "params": {"type": "object"},
                    "step_primitive": {"type": "string", "enum": _PRIMITIVES},
                    "step_target": {"type": "string"},
                    "step_start_ms": {"type": "number"},
                    "step_duration_ms": {"type": "number"},
                    "step_ease": {"type": "string"},
                    "step_params": {"type": "object"},
                    "scene_json": {"type": "string"},
                    "tone": {"type": "string"},
                    "visual_style_bible": {"type": "string"},
                    "backdrop_hue_deg": {"type": "number"},
                    "visual_description": {"type": "string"},
                    "transition_out": {"type": "string", "enum": _TRANSITIONS},
                    "transition_ms": {"type": "number"},
                    "overlay_id": {"type": "string"},
                    "overlay_kind": {"type": "string", "enum": ["text", "image"]},
                    "overlay_asset_id": {"type": "string"},
                    "text": {"type": "string"},
                    "overlay_json": {"type": "string"},
                    "end_ms": {"type": "number"},
                    "at_ms": {"type": "number"},
                    "direction": {"type": "number", "enum": [-1, 1]},
                },
                "required": ["op"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["instruction", "outcome", "summary", "operations"],
    "additionalProperties": False,
}


class LiteRefinementOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal[
        "set_scene_text",
        "set_text_style",
        "set_animation_step",
        "add_animation_step",
        "remove_animation_step",
        "delete_scene",
        "add_scene",
        "set_scene_visual",
        "set_tone",
        "set_transition",
        "add_overlay",
        "set_overlay_text",
        "remove_overlay",
        "set_scene_duration",
        "split_scene",
        "move_scene",
    ]
    scene_id: str | None = None
    after_scene_id: str | None = None
    lines: list[str] | None = None
    style: dict[str, Any] | None = None
    target: str | None = None
    primitive: str | None = None
    start_ms: float | int | None = None
    duration_ms: float | int | None = None
    ease: str | None = None
    params: dict[str, Any] | None = None
    step_primitive: str | None = None
    step_target: str | None = None
    step_start_ms: float | int | None = None
    step_duration_ms: float | int | None = None
    step_ease: str | None = None
    step_params: dict[str, Any] | None = None
    scene_json: str | None = None
    tone: str | None = None
    visual_style_bible: str | None = None
    backdrop_hue_deg: float | int | None = None
    visual_description: str | None = None
    transition_out: str | None = None
    transition_ms: float | int | None = None
    overlay_id: str | None = None
    overlay_kind: str | None = None
    overlay_asset_id: str | None = None
    text: str | None = None
    overlay_json: str | None = None
    end_ms: float | int | None = None
    at_ms: float | int | None = None
    direction: Literal[-1, 1] | None = None


class LitePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0-lite"] = "1.0-lite"
    instruction: str = Field(min_length=1, max_length=1000)
    outcome: Literal["apply", "clarification"] = "apply"
    summary: str = Field(min_length=1, max_length=500)
    clarification_question: str | None = Field(default=None, max_length=300)
    operations: list[LiteRefinementOperation] = Field(default_factory=list, max_length=12)


def _require_scene_id(raw: LiteRefinementOperation) -> str:
    if not raw.scene_id:
        raise ValueError(f"Operation {raw.op!r} needs scene_id.")
    return raw.scene_id


def _typed_operation(raw: LiteRefinementOperation) -> PatchOperation:
    """Map one lite operation onto the strict patch operation model."""
    if raw.op == "set_scene_text":
        if raw.lines is None:
            raise ValueError("set_scene_text needs lines.")
        return SetSceneTextOp(scene_id=_require_scene_id(raw), lines=list(raw.lines))
    if raw.op == "set_text_style":
        changes = {k: v for k, v in (raw.style or {}).items() if v is not None}
        if not changes:
            raise ValueError("set_text_style needs at least one style field.")
        return SetTextStyleOp(
            scene_id=_require_scene_id(raw), style=TextStyleUpdate(**changes)
        )
    if raw.op == "set_animation_step":
        if not raw.target:
            raise ValueError("set_animation_step needs target.")
        update: dict[str, Any] = {}
        if raw.primitive is not None:
            update["primitive"] = raw.primitive
        if raw.start_ms is not None:
            update["start_ms"] = int(raw.start_ms)
        if raw.duration_ms is not None:
            update["duration_ms"] = int(raw.duration_ms)
        if raw.ease is not None:
            update["ease"] = raw.ease
        if raw.params is not None:
            update["params"] = dict(raw.params)
        if not update:
            raise ValueError("set_animation_step needs at least one field to change.")
        return SetAnimationStepOp(scene_id=_require_scene_id(raw), target=raw.target, **update)
    if raw.op == "add_animation_step":
        if not raw.step_primitive or not raw.step_target:
            raise ValueError("add_animation_step needs step_primitive and step_target.")
        if raw.step_start_ms is None or raw.step_duration_ms is None:
            raise ValueError("add_animation_step needs step_start_ms and step_duration_ms.")
        return AddAnimationStepOp(
            scene_id=_require_scene_id(raw),
            step=AnimationStep(
                primitive=raw.step_primitive,  # type: ignore[arg-type]
                target=raw.step_target,
                start_ms=int(raw.step_start_ms),
                duration_ms=int(raw.step_duration_ms),
                params=dict(raw.step_params or {}),
                ease=raw.step_ease or "outQuad",
            ),
        )
    if raw.op == "remove_animation_step":
        if not raw.target:
            raise ValueError("remove_animation_step needs target.")
        return RemoveAnimationStepOp(
            scene_id=_require_scene_id(raw),
            target=raw.target,
            primitive=raw.primitive,  # type: ignore[arg-type]
        )
    if raw.op == "delete_scene":
        return DeleteSceneOp(scene_id=_require_scene_id(raw))
    if raw.op == "add_scene":
        if not raw.scene_json:
            raise ValueError("add_scene needs scene_json (a full SceneSpec as JSON).")
        try:
            scene = SceneSpec.model_validate_json(raw.scene_json)
        except Exception as exc:
            raise ValueError(f"add_scene scene_json is not a valid SceneSpec: {exc}") from exc
        return AddSceneOp(scene=scene, after_scene_id=raw.after_scene_id)
    if raw.op == "set_scene_visual":
        if raw.backdrop_hue_deg is None and not raw.visual_description:
            raise ValueError("set_scene_visual needs at least one field.")
        return SetSceneVisualOp(
            scene_id=_require_scene_id(raw),
            backdrop_hue_deg=(
                float(raw.backdrop_hue_deg) if raw.backdrop_hue_deg is not None else None
            ),
            visual_description=raw.visual_description,
        )
    if raw.op == "set_tone":
        if not raw.tone and not raw.visual_style_bible:
            raise ValueError("set_tone needs at least one field.")
        return SetToneOp(tone=raw.tone, visual_style_bible=raw.visual_style_bible)
    if raw.op == "set_transition":
        if not raw.transition_out:
            raise ValueError("set_transition needs transition_out.")
        update: dict[str, Any] = {"transition_out": raw.transition_out}  # type: ignore[dict-item]
        if raw.transition_ms is not None:
            update["transition_ms"] = int(raw.transition_ms)
        return SetTransitionOp(scene_id=_require_scene_id(raw), **update)  # type: ignore[arg-type]
    if raw.op == "add_overlay":
        if not raw.overlay_json:
            raise ValueError("add_overlay needs overlay_json (a full OverlaySpec as JSON).")
        try:
            overlay = OverlaySpec.model_validate_json(raw.overlay_json)
        except Exception as exc:
            raise ValueError(f"add_overlay overlay_json is not a valid OverlaySpec: {exc}") from exc
        if raw.overlay_kind is not None or raw.overlay_asset_id is not None:
            changes: dict[str, Any] = {}
            if raw.overlay_kind is not None:
                changes["kind"] = raw.overlay_kind
            if raw.overlay_asset_id is not None:
                changes["asset_id"] = raw.overlay_asset_id
            try:
                overlay = overlay.model_copy(update=changes)
                OverlaySpec.model_validate(overlay.model_dump(mode="json"))
            except Exception as exc:
                raise ValueError(f"add_overlay overlay override is invalid: {exc}") from exc
        return AddOverlayOp(overlay=overlay)
    if raw.op == "set_overlay_text":
        if not raw.overlay_id or not raw.text:
            raise ValueError("set_overlay_text needs overlay_id and text.")
        return SetOverlayTextOp(overlay_id=raw.overlay_id, text=raw.text)
    if raw.op == "remove_overlay":
        if not raw.overlay_id:
            raise ValueError("remove_overlay needs overlay_id.")
        return RemoveOverlayOp(overlay_id=raw.overlay_id)
    if raw.op == "set_scene_duration":
        if raw.duration_ms is None:
            raise ValueError("set_scene_duration needs duration_ms.")
        return SetSceneDurationOp(
            scene_id=_require_scene_id(raw), duration_ms=int(raw.duration_ms)
        )
    if raw.op == "split_scene":
        if raw.at_ms is None:
            raise ValueError("split_scene needs at_ms.")
        return SplitSceneOp(scene_id=_require_scene_id(raw), at_ms=int(raw.at_ms))
    if raw.op == "move_scene":
        if raw.direction not in (-1, 1):
            raise ValueError("move_scene needs direction -1 or 1.")
        return MoveSceneOp(scene_id=_require_scene_id(raw), direction=raw.direction)  # type: ignore[arg-type]
    raise ValueError(f"Unknown patch operation {raw.op!r}.")


def lite_to_full_patch(lite: LitePatch) -> StoryboardPatch:
    """Convert a lite patch into a full StoryboardPatch. Full validators run."""
    operations = [_typed_operation(raw) for raw in lite.operations]
    return StoryboardPatch(
        instruction=lite.instruction,
        outcome=lite.outcome,
        summary=lite.summary,
        clarification_question=lite.clarification_question,
        operations=operations,  # type: ignore[arg-type]
    )
