"""Provider mode factory (ADR-004).

CLIPFORGE_AI_MODE=mock is the default. Mock mode requires no credentials and
makes no external calls. Live mode is an explicit configuration change and
currently raises: live adapters are placeholders until the Milestone 6 gate.
There is never a silent fallback from live to mock or mock to live.
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

ENV_VAR = "CLIPFORGE_AI_MODE"


@dataclass(frozen=True)
class ProviderBundle:
    transcription: TranscriptionProvider
    planner: EditingPlannerProvider
    segmentation: SegmentationProvider
    background: BackgroundGenerationProvider
    mode: str


def get_providers(mode: str | None = None) -> ProviderBundle:
    selected = (mode if mode is not None else os.environ.get(ENV_VAR, "mock")).strip().lower()
    if selected == "mock":
        return ProviderBundle(
            transcription=MockTranscriptionProvider(),
            planner=MockEditingPlannerProvider(),
            segmentation=MockSegmentationProvider(),
            background=MockBackgroundGenerationProvider(),
            mode="mock",
        )
    if selected == "live":
        raise LiveProviderNotImplementedError(
            "CLIPFORGE_AI_MODE=live is not available: live Meta adapters are placeholders until "
            "official documentation is verified and a controlled test is explicitly approved (ADR-004)."
        )
    raise ValueError(f"Invalid {ENV_VAR}={selected!r}. Expected 'mock' (default) or 'live'.")
