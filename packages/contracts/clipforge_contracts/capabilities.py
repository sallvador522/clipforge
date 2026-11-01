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

from pydantic import BaseModel, ConfigDict, Field


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


class ReplaceBackgroundParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["replace_background"] = "replace_background"
    prompt: str = Field(min_length=1, max_length=240)
    asset_source: Literal["local_asset", "mock_generated"] = "local_asset"
    asset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    composition: Literal["centered", "rule_of_thirds"] = "centered"


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


OperationParams = (
    IsolateSubjectParams
    | BlurBackgroundParams
    | ReplaceBackgroundParams
    | PreserveAudioParams
    | RenderMp4Params
    | VerifyOutputParams
)

PARAM_MODELS: dict[str, type[BaseModel]] = {
    "isolate_subject": IsolateSubjectParams,
    "blur_background": BlurBackgroundParams,
    "replace_background": ReplaceBackgroundParams,
    "preserve_audio": PreserveAudioParams,
    "render_mp4": RenderMp4Params,
    "verify_output": VerifyOutputParams,
}

CAPABILITY_BY_PARAM_TYPE: dict[str, str] = {
    "isolate_subject": "subject.isolate",
    "blur_background": "background.blur",
    "replace_background": "background.replace",
    "preserve_audio": "audio.preserve",
    "render_mp4": "video.render_mp4",
    "verify_output": "output.verify",
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
        "Composites the isolated subject over a background generated by the configured "
        "provider: Muse Image when live, or a deterministic local/mock asset otherwise. "
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
