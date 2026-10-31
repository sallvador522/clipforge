"""Live Meta provider placeholders.

No network code, no credentials, no assumed endpoints or schemas exist here.
Each adapter is implemented only after official documentation verification and
explicit user approval (ADR-004 live integration gate, Milestone 6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from clipforge_contracts import BackgroundResult, EditingPlan, SegmentationResult, TranscriptResult


class LiveProviderNotImplementedError(NotImplementedError):
    """Raised by every live adapter until the Milestone 6 gate is passed."""


_MESSAGE = (
    "Live Meta providers are not implemented. Meta request/response schemas are UNVERIFIED; "
    "implementation requires official documentation verification and explicit user approval (ADR-004)."
)


class LiveTranscriptionProvider:
    def transcribe(self, audio_fixture_id: str) -> TranscriptResult:
        raise LiveProviderNotImplementedError(_MESSAGE)

    def transcribe_audio(self, audio_path: str | Path, *, language_bias: Sequence[str] = ("Portuguese",)) -> TranscriptResult:
        raise LiveProviderNotImplementedError(_MESSAGE)


class LiveEditingPlannerProvider:
    def create_plan(self, transcript: TranscriptResult) -> EditingPlan:
        raise LiveProviderNotImplementedError(_MESSAGE)


class LiveSegmentationProvider:
    def segment(
        self,
        *,
        job_id: str,
        source_video_id: str,
        output_dir: str | Path,
        width: int,
        height: int,
        frame_count: int,
        fps: float,
    ) -> SegmentationResult:
        raise LiveProviderNotImplementedError(_MESSAGE)


class LiveBackgroundGenerationProvider:
    def generate(self, *, prompt: str, orientation: str = "landscape") -> BackgroundResult:
        raise LiveProviderNotImplementedError(_MESSAGE)
