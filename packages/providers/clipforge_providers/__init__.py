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
from clipforge_providers.muse_image import (
    MuseImageAPIError,
    MuseImageBackgroundProvider,
    MuseImageError,
    MuseImageMissingCredentialsError,
    MuseImageNotAuthorizedError,
    MuseImageRateLimitedError,
    MuseImageTimeoutError,
    MuseImageValidationError,
)
from clipforge_providers.sam import (
    SamAPIError,
    SamError,
    SamIncompleteStreamError,
    SamMissingCredentialsError,
    SamNotAuthorizedError,
    SamRateLimitedError,
    SamSegmentationProvider,
    SamTimeoutError,
    SamValidationError,
)
from clipforge_providers.transcription_meta import (
    InvalidAudioError,
    MetaVoiceTranscriptionProvider,
    MissingCredentialsError,
    TranscriptionAPIError,
    TranscriptionError,
    TranscriptionRateLimitedError,
    TranscriptionTimeoutError,
)

__all__ = [
    "BackgroundGenerationProvider",
    "EditingPlannerProvider",
    "FixtureNotFoundError",
    "InvalidAudioError",
    "LiveProviderNotImplementedError",
    "MetaVoiceTranscriptionProvider",
    "MissingCredentialsError",
    "MockBackgroundGenerationProvider",
    "MockEditingPlannerProvider",
    "MockSegmentationProvider",
    "MockTranscriptionProvider",
    "MuseImageAPIError",
    "MuseImageBackgroundProvider",
    "MuseImageError",
    "MuseImageMissingCredentialsError",
    "MuseImageNotAuthorizedError",
    "MuseImageRateLimitedError",
    "MuseImageTimeoutError",
    "MuseImageValidationError",
    "ProviderBundle",
    "SamAPIError",
    "SamError",
    "SamIncompleteStreamError",
    "SamMissingCredentialsError",
    "SamNotAuthorizedError",
    "SamRateLimitedError",
    "SamSegmentationProvider",
    "SamTimeoutError",
    "SamValidationError",
    "SegmentationProvider",
    "TranscriptionAPIError",
    "TranscriptionError",
    "TranscriptionProvider",
    "TranscriptionRateLimitedError",
    "TranscriptionTimeoutError",
    "get_providers",
]
