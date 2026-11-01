"""Provider mode factory (ADR-004, ADR-008, ADR-014).

CLIPFORGE_AI_MODE=mock is the default. Four providers can be enabled for live
inference, explicitly and in isolation:

    CLIPFORGE_TRANSCRIBE_MODE=live   +   MODEL_API_KEY=...
    CLIPFORGE_DIRECTOR_MODE=live     +   MODEL_API_KEY=...
    CLIPFORGE_SEGMENTATION_MODE=live +   MODEL_API_KEY=...
    CLIPFORGE_IMAGE_MODE=live        +   MODEL_API_KEY=...

The legacy planner stays mocked; there is never a silent fallback and no
automatic live activation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from clipforge_providers.base import (
    BackgroundGenerationProvider,
    EditingPlannerProvider,
    SegmentationProvider,
    TranscriptionProvider,
)
from clipforge_providers.live import LiveProviderNotImplementedError
from clipforge_providers.mock import (
    MockBackgroundGenerationProvider,
    MockEditingPlannerProvider,
    MockSegmentationProvider,
    MockTranscriptionProvider,
)
from clipforge_providers.muse_image import (
    DEFAULT_BASE_URL as IMAGE_DEFAULT_BASE_URL,
    DEFAULT_MODEL as IMAGE_DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS as IMAGE_DEFAULT_TIMEOUT_SECONDS,
    MuseImageBackgroundProvider,
)
from clipforge_providers.sam import (
    DEFAULT_BASE_URL as SAM_DEFAULT_BASE_URL,
    DEFAULT_MODEL as SAM_DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS as SAM_DEFAULT_TIMEOUT_SECONDS,
    SamSegmentationProvider,
)
from clipforge_providers.transcription_meta import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    MetaVoiceTranscriptionProvider,
    MissingCredentialsError,
)

ENV_VAR = "CLIPFORGE_AI_MODE"
TRANSCRIBE_ENV_VAR = "CLIPFORGE_TRANSCRIBE_MODE"
DIRECTOR_ENV_VAR = "CLIPFORGE_DIRECTOR_MODE"
SEGMENTATION_ENV_VAR = "CLIPFORGE_SEGMENTATION_MODE"
IMAGE_ENV_VAR = "CLIPFORGE_IMAGE_MODE"
API_KEY_ENV_VAR = "MODEL_API_KEY"


@dataclass(frozen=True)
class ProviderBundle:
    transcription: TranscriptionProvider
    planner: EditingPlannerProvider
    segmentation: SegmentationProvider
    background: BackgroundGenerationProvider
    mode: str
    transcription_mode: str = "mock"
    director: object | None = None
    director_mode: str = "mock"
    segmentation_mode: str = "mock"
    image_mode: str = "mock"


def _director_from_env() -> tuple[object, str]:
    selected = os.environ.get(DIRECTOR_ENV_VAR, "mock").strip().lower()
    if selected == "mock":
        from clipforge_director import MockProfessionalEditingDirector

        return MockProfessionalEditingDirector(), "mock"
    if selected == "live":
        api_key = os.environ.get(API_KEY_ENV_VAR, "")
        if not api_key.strip():
            raise MissingCredentialsError(
                f"{DIRECTOR_ENV_VAR}=live requires {API_KEY_ENV_VAR} (server-side only). "
                "No request was attempted."
            )
        # Local monorepo: the runtime playbook lives with the API app. The playbook
        # is loaded from disk only; no model call happens here.
        from clipforge_api.playbook import default_playbook
        from clipforge_contracts.director_lite import lite_capability_summary
        from clipforge_director import LiteMetaEditingDirectorProvider

        playbook = default_playbook()
        provider = LiteMetaEditingDirectorProvider(
            api_key,
            playbook.text,
            lite_capability_summary(),
            model="muse-spark-1.3-contributor",
            reasoning_effort="medium",
            require_contributor=True,
            max_output_tokens=int(os.environ.get("CLIPFORGE_DIRECTOR_MAX_TOKENS", "16000")),
            timeout_seconds=float(os.environ.get("CLIPFORGE_DIRECTOR_TIMEOUT_SECONDS", "180")),
        )
        return provider, "live"
    raise ValueError(f"Invalid {DIRECTOR_ENV_VAR}={selected!r}. Expected 'mock' (default) or 'live'.")


def _segmentation_from_env() -> tuple[SegmentationProvider, str]:
    selected = os.environ.get(SEGMENTATION_ENV_VAR, "mock").strip().lower()
    if selected == "mock":
        return MockSegmentationProvider(), "mock"
    if selected == "live":
        api_key = os.environ.get(API_KEY_ENV_VAR, "")
        if not api_key.strip():
            raise MissingCredentialsError(
                f"{SEGMENTATION_ENV_VAR}=live requires {API_KEY_ENV_VAR} (server-side only). "
                "No request was attempted."
            )
        provider = SamSegmentationProvider(
            api_key,
            base_url=os.environ.get("META_SAM_BASE_URL", SAM_DEFAULT_BASE_URL),
            model=os.environ.get("META_SAM_MODEL", SAM_DEFAULT_MODEL),
            timeout_seconds=float(
                os.environ.get("META_SAM_TIMEOUT_SECONDS", SAM_DEFAULT_TIMEOUT_SECONDS)
            ),
        )
        return provider, "live"
    raise ValueError(
        f"Invalid {SEGMENTATION_ENV_VAR}={selected!r}. Expected 'mock' (default) or 'live'."
    )


def _image_from_env() -> tuple[BackgroundGenerationProvider, str]:
    selected = os.environ.get(IMAGE_ENV_VAR, "mock").strip().lower()
    if selected == "mock":
        return MockBackgroundGenerationProvider(), "mock"
    if selected == "live":
        api_key = os.environ.get(API_KEY_ENV_VAR, "")
        if not api_key.strip():
            raise MissingCredentialsError(
                f"{IMAGE_ENV_VAR}=live requires {API_KEY_ENV_VAR} (server-side only). "
                "No request was attempted."
            )
        provider = MuseImageBackgroundProvider(
            api_key,
            base_url=os.environ.get("META_IMAGE_BASE_URL", IMAGE_DEFAULT_BASE_URL),
            model=os.environ.get("META_IMAGE_MODEL", IMAGE_DEFAULT_MODEL),
            timeout_seconds=float(
                os.environ.get("META_IMAGE_TIMEOUT_SECONDS", IMAGE_DEFAULT_TIMEOUT_SECONDS)
            ),
        )
        return provider, "live"
    raise ValueError(
        f"Invalid {IMAGE_ENV_VAR}={selected!r}. Expected 'mock' (default) or 'live'."
    )


def _transcription_from_env() -> tuple[TranscriptionProvider, str]:
    selected = os.environ.get(TRANSCRIBE_ENV_VAR, "mock").strip().lower()
    if selected == "mock":
        return MockTranscriptionProvider(), "mock"
    if selected == "live":
        api_key = os.environ.get(API_KEY_ENV_VAR, "")
        if not api_key.strip():
            raise MissingCredentialsError(
                f"{TRANSCRIBE_ENV_VAR}=live requires {API_KEY_ENV_VAR} (server-side only). "
                "No request was attempted."
            )
        provider = MetaVoiceTranscriptionProvider(
            api_key,
            base_url=os.environ.get("META_ASR_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("META_ASR_MODEL", DEFAULT_MODEL),
            timeout_seconds=float(os.environ.get("META_ASR_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        )
        return provider, "live"
    raise ValueError(f"Invalid {TRANSCRIBE_ENV_VAR}={selected!r}. Expected 'mock' (default) or 'live'.")


def get_providers(mode: str | None = None) -> ProviderBundle:
    selected = (mode if mode is not None else os.environ.get(ENV_VAR, "mock")).strip().lower()
    if selected == "live":
        raise LiveProviderNotImplementedError(
            "CLIPFORGE_AI_MODE=live is not available: live inference is scoped per function "
            f"({TRANSCRIBE_ENV_VAR}, {DIRECTOR_ENV_VAR}, {SEGMENTATION_ENV_VAR}, "
            f"{IMAGE_ENV_VAR}). The legacy planner remains mocked (ADR-008, ADR-014, ADR-019)."
        )
    if selected != "mock":
        raise ValueError(f"Invalid {ENV_VAR}={selected!r}. Expected 'mock' (default) or 'live'.")

    transcription, transcription_mode = _transcription_from_env()
    director, director_mode = _director_from_env()
    segmentation, segmentation_mode = _segmentation_from_env()
    background, image_mode = _image_from_env()
    bundle = ProviderBundle(
        transcription=transcription,
        planner=MockEditingPlannerProvider(),
        segmentation=segmentation,
        background=background,
        mode="mock",
        transcription_mode=transcription_mode,
        director=director,
        director_mode=director_mode,
        segmentation_mode=segmentation_mode,
        image_mode=image_mode,
    )
    return bundle
