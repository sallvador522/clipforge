"""ClipForge shared contracts: single source of truth for plans and normalized provider data."""

from clipforge_contracts.editing_plan import (
    BlurBackgroundOperation,
    EditingIntent,
    EditingPlan,
    KeepSubjectSharpOperation,
    Operation,
    ReplaceBackgroundOperation,
    SubjectSpec,
)
from clipforge_contracts.mask_manifest import MaskFrameEntry, MaskManifest
from clipforge_contracts.responses import BackgroundResult, SegmentationResult, TranscriptResult

__all__ = [
    "BackgroundResult",
    "BlurBackgroundOperation",
    "EditingIntent",
    "EditingPlan",
    "KeepSubjectSharpOperation",
    "MaskFrameEntry",
    "MaskManifest",
    "Operation",
    "ReplaceBackgroundOperation",
    "SegmentationResult",
    "SubjectSpec",
    "TranscriptResult",
]
