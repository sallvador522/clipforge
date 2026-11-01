"""Typed provider interfaces. Application logic depends only on these protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from clipforge_contracts import BackgroundResult, EditingPlan, SegmentationResult, TranscriptResult


@runtime_checkable
class TranscriptionProvider(Protocol):
    def transcribe(self, audio_fixture_id: str) -> TranscriptResult: ...

    def transcribe_audio(self, audio_path: str | Path, *, language_bias: Sequence[str] = ...) -> TranscriptResult: ...


@runtime_checkable
class EditingPlannerProvider(Protocol):
    def create_plan(self, transcript: TranscriptResult) -> EditingPlan: ...


@runtime_checkable
class SegmentationProvider(Protocol):
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
        source_path: str | Path | None = None,
        prompt: str = "person",
        authorization=None,
        consent=None,
    ) -> SegmentationResult: ...


@runtime_checkable
class BackgroundGenerationProvider(Protocol):
    def generate(self, *, prompt: str, orientation: str = "landscape") -> BackgroundResult: ...
