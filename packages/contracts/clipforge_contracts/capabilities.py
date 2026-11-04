"""Capability registry — the single source of truth for what ClipForge can actually do.

Only capabilities listed here may appear in a ProfessionalEditingPlan. Disabled or
planned capabilities are documented so the director can explain their absence, but
they can never be planned or executed. Mock and local capabilities are labelled
honestly: mock segmentation is not SAM, and mock background assets are not Muse
Image generation.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CapabilityStatus(str, Enum):
    AVAILABLE_MOCK = "available_mock"
    AVAILABLE_LOCAL = "available_local"
    AVAILABLE_LIVE = "available_live"
    PLANNED = "planned"
    DISABLED = "disabled"


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    required_provider: str | None = None
    backend_handler: str | None = None
    dependencies: tuple[str, ...] = ()
    status: CapabilityStatus
    verification: str = Field(min_length=1)
    requires_approval: bool = False
    simulated: bool = False

    @property
    def executable(self) -> bool:
        return self.status in {
            CapabilityStatus.AVAILABLE_MOCK,
            CapabilityStatus.AVAILABLE_LOCAL,
            CapabilityStatus.AVAILABLE_LIVE,
        }

    @property
    def external_ai(self) -> bool:
        return self.status is CapabilityStatus.AVAILABLE_LIVE


# --- Typed operation parameters (no paths, commands or executable code) ---


class IsolateSubjectParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["isolate_subject"] = "isolate_subject"
    strategy: Literal["largest_subject", "named_subject", "foreground"] = "largest_subject"
    subject_description: str | None = Field(default=None, max_length=120)


class BlurBackgroundParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["blur_background"] = "blur_background"
    strength: float = Field(default=0.8, ge=0.0, le=1.0)
    feather_px: int = Field(default=5, ge=0, le=21)


class ProgrammaticShape(BaseModel):
    """One animated vector shape on the procedural backdrop.

    All motion is a deterministic function of time (seconds); the same
    timestamp always renders the same pixels in preview and export.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["circle", "ring", "bar", "line"] = "circle"
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    size: float = Field(default=0.12, ge=0.02, le=0.6)
    speed: float = Field(default=0.5, ge=0.0, le=3.0)
    phase: float = Field(default=0.0, ge=0.0, le=6.2832)


class ProgrammaticBackdrop(BaseModel):
    """A fully local, deterministic animated background.

    No AI call, no image generation: gradients + vector shapes rendered per
    frame by the worker with real OpenCV/PIL. The Studio preview shows the
    verified render, so preview and export share the exact composition.
    """

    model_config = ConfigDict(extra="forbid")
    gradient_top: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    gradient_bottom: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    shapes: list[ProgrammaticShape] = Field(default_factory=list, max_length=6)
    motion: Literal["subtle", "moderate"] = "subtle"


class ReplaceBackgroundParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["replace_background"] = "replace_background"
    prompt: str = Field(min_length=1, max_length=240)
    asset_source: Literal["local_asset", "mock_generated", "programmatic"] = "local_asset"
    asset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    composition: Literal["centered", "rule_of_thirds"] = "centered"
    backdrop: ProgrammaticBackdrop | None = None

    @model_validator(mode="after")
    def _backdrop_matches_source(self) -> "ReplaceBackgroundParams":
        if self.asset_source == "programmatic" and self.backdrop is None:
            raise ValueError("A programmatic backdrop spec is required with asset_source='programmatic'.")
        if self.asset_source in ("local_asset", "mock_generated") and self.backdrop is not None:
            raise ValueError("A backdrop spec is only allowed with asset_source='programmatic'.")
        return self


class PreserveAudioParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["preserve_audio"] = "preserve_audio"
    mode: Literal["original"] = "original"


class RenderMp4Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["render_mp4"] = "render_mp4"
    resolution: Literal["source", "720p"] = "source"
    format: Literal["mp4"] = "mp4"


class VerifyOutputParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["verify_output"] = "verify_output"
    checks: tuple[
        Literal["duration", "streams", "frame_count", "audio_presence", "resolution"], ...
    ] = ("duration", "streams", "frame_count", "audio_presence", "resolution")


class TextOverlayParams(BaseModel):
    """ADR-047 selectable text element. Validated tool/director params; the
    worker burns the persisted overlay into the timeline composition."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["text_overlay"] = "text_overlay"
    overlay_id: str = Field(pattern=r"^txt_[a-z0-9]{4,32}$")
    text: str = Field(min_length=1, max_length=140)
    style: Literal["rise", "reveal", "pop", "kinetic", "tracking"] = "rise"
    start_s: float = Field(default=0.0, ge=0.0)
    duration_s: float = Field(default=2.5, ge=0.5, le=8.0)
    x: float = Field(default=0.5, ge=0.08, le=0.92)
    y: float = Field(default=0.78, ge=0.1, le=0.9)
    scale: float = Field(default=1.0, ge=0.7, le=1.6)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    weight: Literal["normal", "bold"] = "bold"


class ColourAdjustParams(BaseModel):
    """ADR-047 local colour grade. Real per-frame OpenCV adjustment."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["colour_adjust"] = "colour_adjust"
    contrast: float = Field(default=1.0, ge=0.5, le=1.5)
    brightness: float = Field(default=0.0, ge=-0.3, le=0.3)
    saturation: float = Field(default=1.0, ge=0.0, le=2.0)


OperationParams = (
    IsolateSubjectParams
    | BlurBackgroundParams
    | ReplaceBackgroundParams
    | PreserveAudioParams
    | RenderMp4Params
    | VerifyOutputParams
    | TextOverlayParams
    | ColourAdjustParams
)

PARAM_MODELS: dict[str, type[BaseModel]] = {
    "isolate_subject": IsolateSubjectParams,
    "blur_background": BlurBackgroundParams,
    "replace_background": ReplaceBackgroundParams,
    "preserve_audio": PreserveAudioParams,
    "render_mp4": RenderMp4Params,
    "verify_output": VerifyOutputParams,
    "text_overlay": TextOverlayParams,
    "colour_adjust": ColourAdjustParams,
}

CAPABILITY_BY_PARAM_TYPE: dict[str, str] = {
    "isolate_subject": "subject.isolate",
    "blur_background": "background.blur",
    "replace_background": "background.replace",
    "preserve_audio": "audio.preserve",
    "render_mp4": "video.render_mp4",
    "verify_output": "output.verify",
    "text_overlay": "text.overlay",
    "colour_adjust": "colour.adjust",
}


def _capability(
    capability_id: str,
    name: str,
    description: str,
    input_schema: str,
    output_schema: str,
    status: CapabilityStatus,
    verification: str,
    *,
    provider: str | None = None,
    handler: str | None = None,
    dependencies: tuple[str, ...] = (),
    requires_approval: bool = False,
    simulated: bool = False,
) -> Capability:
    return Capability(
        capability_id=capability_id,
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        required_provider=provider,
        backend_handler=handler,
        dependencies=dependencies,
        status=status,
        verification=verification,
        requires_approval=requires_approval,
        simulated=simulated,
    )


_RENDER_HANDLER = "clipforge_worker.renderer:render_video"
_VERIFY_HANDLER = "clipforge_worker.renderer:verify_render_output"

CAPABILITIES: dict[str, Capability] = {
    "subject.isolate": _capability(
        "subject.isolate",
        "Isolate primary subject",
        "Builds a per-frame subject alpha using the segmentation provider. In this build the "
        "provider returns synthetic mock masks; it is NOT SAM inference. Live SAM is planned.",
        "IsolateSubjectParams",
        "SubjectMaskSequence",
        CapabilityStatus.AVAILABLE_MOCK,
        "MaskLoader validates every frame, dimensions, indices and manifest count (ADR-005).",
        provider="segmentation",
        handler="clipforge_worker.processor:run_segmentation",
        simulated=True,
    ),
    "background.blur": _capability(
        "background.blur",
        "Background blur",
        "Keeps the isolated subject sharp while applying a controlled Gaussian blur to the background.",
        "BlurBackgroundParams",
        "CompositedVideoFrames",
        CapabilityStatus.AVAILABLE_LOCAL,
        "Real FFmpeg/OpenCV render; pixel checks confirm subject detail and background smoothing.",
        handler=_RENDER_HANDLER,
        dependencies=("subject.isolate",),
    ),
    "background.replace": _capability(
        "background.replace",
        "Background replacement",
        "Composites the isolated subject over a replacement background: a "
        "deterministic local programmatic backdrop (animated gradient + vector "
        "shapes, no AI call) when asset_source is programmatic, else a background "
        "generated by the configured provider (Muse Image when live, or a "
        "deterministic local/mock asset otherwise). "
        "The composite itself runs locally.",
        "ReplaceBackgroundParams",
        "CompositedVideoFrames",
        CapabilityStatus.AVAILABLE_LOCAL,
        "Real composite render plus visual inspection; output is ffprobe-verified.",
        provider="background_generation",
        handler=_RENDER_HANDLER,
        dependencies=("subject.isolate",),
        requires_approval=True,
        simulated=True,
    ),
    "audio.preserve": _capability(
        "audio.preserve",
        "Preserve original audio",
        "Muxes the source audio into the rendered MP4 without external processing.",
        "PreserveAudioParams",
        "AudioStream",
        CapabilityStatus.AVAILABLE_LOCAL,
        "ffprobe confirms an audio stream and matching duration.",
        handler=_RENDER_HANDLER,
    ),
    "video.render_mp4": _capability(
        "video.render_mp4",
        "Render MP4",
        "Encodes frames and audio into a playable H.264/AAC MP4 on CPU.",
        "RenderMp4Params",
        "RenderedVideo",
        CapabilityStatus.AVAILABLE_LOCAL,
        "Output must exist, be readable and contain video; frame count/resolution/duration checked.",
        handler=_RENDER_HANDLER,
    ),
    "output.verify": _capability(
        "output.verify",
        "Verify output",
        "Independently verifies the exported file with ffprobe before exposing a download.",
        "VerifyOutputParams",
        "VerifiedRenderResult",
        CapabilityStatus.AVAILABLE_LOCAL,
        "ffprobe frame counting, duration, resolution and audio stream equality.",
        handler=_VERIFY_HANDLER,
        dependencies=("video.render_mp4",),
    ),
    # ADR-047 selectable text overlays: real project elements persisted on the
    # job, edited in the Studio / via Muse tools, burned into the timeline
    # composition by the worker. Entrance animation in the export is a
    # fade + rise (240 ms); per-style preview choreography stays richer.
    "text.overlay": _capability(
        "text.overlay",
        "Text overlay",
        "Selectable text element with content, size, colour, weight, position "
        "and timing. Persisted on the job and burned into the timeline MP4 by "
        "the worker with real PIL/OpenCV rendering.",
        "TextOverlayParams",
        "CompositedVideoFrames",
        CapabilityStatus.AVAILABLE_LOCAL,
        "Pixel-diff QA proves the text is present in the exported frames; "
        "ffprobe verifies the MP4.",
        handler="clipforge_worker.timeline_render:compose_timeline",
    ),
    # ADR-047 local colour grade: real per-frame OpenCV contrast/brightness/
    # saturation applied by the timeline composition. Local image processing,
    # never described as AI.
    "colour.adjust": _capability(
        "colour.adjust",
        "Colour adjustment",
        "Local contrast/brightness/saturation grade applied per frame before "
        "text burn-in. Operated by the user in Properties or by Muse tools.",
        "ColourAdjustParams",
        "GradedVideoFrames",
        CapabilityStatus.AVAILABLE_LOCAL,
        "Frame statistics shift in the expected direction; ffprobe verifies "
        "the MP4.",
        handler="clipforge_worker.timeline_render:compose_timeline",
    ),
    # Planned: documented for the director, never executable.
    "background.generate": _capability(
        "background.generate",
        "Generate background (Muse Image)",
        "Generates a clean background plate through the configured image provider. It is an "
        "internal step of background.replace, not a separately plannable operation; Muse Image "
        "is used only in live mode.",
        "ReplaceBackgroundParams",
        "BackgroundResult",
        CapabilityStatus.PLANNED,
        "The generated PNG is decoded, format-checked, dimension-checked, hashed and fed to the "
        "existing compositor.",
        provider="muse_image",
    ),
    # Explicitly unavailable editing features.
    "scene.detect_cuts": _capability(
        "scene.detect_cuts", "Automatic scene cuts", "Detect and cut between scenes.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "timeline.trim": _capability(
        "timeline.trim", "Complex trimming", "Trim or ripple-edit clips.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "transition.apply": _capability(
        "transition.apply", "Transitions", "Apply crossfades, wipes or other transitions.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "keyframe.animate": _capability(
        "keyframe.animate", "Keyframes", "Animate parameters over time.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "multitrack.edit": _capability(
        "multitrack.edit", "Multi-track editing", "Edit multiple video/audio tracks.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "colour.grade": _capability(
        "colour.grade", "Advanced colour grading", "Primary/secondary colour correction.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "speed.ramp": _capability(
        "speed.ramp", "Speed ramps", "Constant or ramped speed changes.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "audio.mix": _capability(
        "audio.mix", "Professional audio mixing", "Multi-track mixing, EQ and compression.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
    "captions.animate": _capability(
        "captions.animate", "Animated captions", "Burn-in animated subtitles.",
        "N/A", "N/A", CapabilityStatus.DISABLED, "Not implemented.",
    ),
}


class CapabilityRegistryError(ValueError):
    pass


def _validate_registry() -> None:
    ids = set(CAPABILITIES)
    if len(ids) != len(CAPABILITIES):
        raise CapabilityRegistryError("Duplicate capability ids.")
    for capability in CAPABILITIES.values():
        for dependency in capability.dependencies:
            if dependency not in ids:
                raise CapabilityRegistryError(
                    f"{capability.capability_id} depends on unknown capability {dependency}."
                )
        if capability.executable:
            if not capability.backend_handler:
                raise CapabilityRegistryError(
                    f"Executable capability {capability.capability_id} has no backend handler."
                )
            if not capability.verification:
                raise CapabilityRegistryError(
                    f"Executable capability {capability.capability_id} has no verification method."
                )
        elif capability.backend_handler:
            raise CapabilityRegistryError(
                f"Non-executable capability {capability.capability_id} must not expose a handler."
            )
        if capability.status is CapabilityStatus.AVAILABLE_LIVE and not capability.required_provider:
            raise CapabilityRegistryError(
                f"Live capability {capability.capability_id} must declare its provider."
            )
    # dependency cycle check (DFS)
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        if state.get(node) == 1:
            raise CapabilityRegistryError(f"Dependency cycle involving {node}.")
        if state.get(node) == 2:
            return
        state[node] = 1
        for dep in CAPABILITIES[node].dependencies:
            visit(dep)
        state[node] = 2

    for capability_id in CAPABILITIES:
        visit(capability_id)

    for param_type, capability_id in CAPABILITY_BY_PARAM_TYPE.items():
        if param_type not in PARAM_MODELS:
            raise CapabilityRegistryError(f"Missing params model for {param_type}.")
        if capability_id not in CAPABILITIES:
            raise CapabilityRegistryError(f"Params type {param_type} maps to unknown capability.")
        if CAPABILITIES[capability_id].input_schema != PARAM_MODELS[param_type].__name__:
            raise CapabilityRegistryError(
                f"{capability_id} input_schema does not match {PARAM_MODELS[param_type].__name__}."
            )


_validate_registry()


def get_capability(capability_id: str) -> Capability | None:
    return CAPABILITIES.get(capability_id)


def executable_capabilities() -> tuple[Capability, ...]:
    return tuple(c for c in CAPABILITIES.values() if c.executable)


def disabled_capability_ids() -> tuple[str, ...]:
    return tuple(c.capability_id for c in CAPABILITIES.values() if c.status is CapabilityStatus.DISABLED)


def capability_summary_for_prompt() -> str:
    lines = []
    for capability in CAPABILITIES.values():
        marker = "ENABLED" if capability.executable else capability.status.value.upper()
        simulated = " (simulated)" if capability.simulated else ""
        lines.append(f"- {capability.capability_id} [{marker}{simulated}]: {capability.description}")
    return "\n".join(lines)


# --- EDL projection policy -------------------------------------------------
# The EDL is a declarative projection of registered capabilities. Timing fields are
# only legal when the timeline capability that owns them is executable. While
# `timeline.trim` is disabled, every EDL timing field is forbidden.

EDL_ROLE: dict[str, str] = {
    "subject.isolate": "prepare",
    "background.blur": "transform",
    "background.replace": "transform",
    "text.overlay": "transform",
    "colour.adjust": "transform",
    "audio.preserve": "finalize",
    "video.render_mp4": "finalize",
    "output.verify": "finalize",
    "background.generate": "planned",
    "scene.detect_cuts": "unavailable",
    "timeline.trim": "unavailable",
    "transition.apply": "unavailable",
    "keyframe.animate": "unavailable",
    "multitrack.edit": "unavailable",
    "colour.grade": "unavailable",
    "speed.ramp": "unavailable",
    "audio.mix": "unavailable",
    "captions.animate": "unavailable",
}

TIMING_OWNER_CAPABILITY_ID = "timeline.trim"


def edl_role_for(capability_id: str) -> str:
    return EDL_ROLE.get(capability_id, "unavailable")


def edl_timing_allowed() -> bool:
    """Timing is legal only when the owning timeline capability is executable."""
    owner = CAPABILITIES.get(TIMING_OWNER_CAPABILITY_ID)
    return bool(owner and owner.executable)


def edl_handler_for(capability_id: str) -> str:
    """Controlled handler resolution. Never accept a handler from model output."""
    capability = CAPABILITIES.get(capability_id)
    if capability is None or not capability.executable or not capability.backend_handler:
        raise CapabilityRegistryError(
            f"Capability {capability_id!r} has no executable backend handler."
        )
    return capability.backend_handler
