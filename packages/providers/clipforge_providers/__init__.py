"""ClipForge AI provider adapters: typed interfaces, deterministic mocks, live placeholders (ADR-004)."""

from clipforge_providers.base import (
    BackgroundGenerationProvider,
    EditingPlannerProvider,
    SegmentationProvider,
    TranscriptionProvider,
)
from clipforge_providers.factory import ProviderBundle, get_providers
from clipforge_providers.live import LiveProviderNotImplementedError
from clipforge_providers.mock import (
    FixtureNotFoundError,
    MockBackgroundGenerationProvider,
    MockEditingPlannerProvider,
    MockSegmentationProvider,
    MockTranscriptionProvider,
)

__all__ = [
    "BackgroundGenerationProvider",
    "EditingPlannerProvider",
    "FixtureNotFoundError",
    "LiveProviderNotImplementedError",
    "MockBackgroundGenerationProvider",
    "MockEditingPlannerProvider",
    "MockSegmentationProvider",
    "MockTranscriptionProvider",
    "ProviderBundle",
    "SegmentationProvider",
    "TranscriptionProvider",
    "get_providers",
]
