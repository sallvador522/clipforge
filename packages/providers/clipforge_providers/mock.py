"""Deterministic local mock providers (ADR-004).

No network access, no credentials, no randomness without a fixed seed.
Mock segmentation returns REAL local mask files written through the ADR-005
mask writer; mock background generation returns REAL local image files.
Simulated results are always flagged with is_mock=True.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

from clipforge_contracts import (
    BackgroundResult,
    BlurBackgroundOperation,
    EditingIntent,
    EditingPlan,
    KeepSubjectSharpOperation,
    ReplaceBackgroundOperation,
    SegmentationResult,
    SubjectSpec,
    TranscriptResult,
)
from clipforge_worker.masks import MaskWriter

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKGROUND_ASSETS_DIR = _REPO_ROOT / "assets" / "backgrounds"


class FixtureNotFoundError(LookupError):
    pass


TRANSCRIPTION_FIXTURES: dict[str, str] = {
    "pt_blur_people_behind": "Desfoca todas as pessoas atrás de mim.",
    "pt_replace_background_studio": "Substitui o fundo por um estúdio profissional.",
    "pt_keep_me_sharp": "Mantém-me nítido e desfoca o resto.",
    "pt_ambiguous_person": "Desfoca ele, por favor.",
    "pt_unsupported_command": "Adiciona legendas amarelas ao vídeo.",
}

_BACKGROUNDS: dict[str, tuple[str, int, int, str]] = {
    # orientation -> (filename, width, height, simulated prompt)
    "landscape": ("studio_landscape.png", 1280, 720, "professional studio background, warm light"),
    "portrait": ("studio_portrait.png", 720, 1280, "professional studio background, warm light, portrait"),
}


def _plan_id(text: str) -> str:
    return "mock-plan-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class MockTranscriptionProvider:
    provider_name = "mock-transcription"

    def transcribe(self, audio_fixture_id: str) -> TranscriptResult:
        try:
            text = TRANSCRIPTION_FIXTURES[audio_fixture_id]
        except KeyError as exc:
            raise FixtureNotFoundError(
                f"Unknown transcription fixture {audio_fixture_id!r}. "
                f"Available: {', '.join(sorted(TRANSCRIPTION_FIXTURES))}"
            ) from exc
        return TranscriptResult(
            text=text, language="pt-BR", confidence=0.99, provider_name=self.provider_name, is_mock=True
        )


class MockEditingPlannerProvider:
    """Deterministic command-to-plan mapping. No LLM is called."""

    provider_name = "mock-planner"

    def create_plan(self, transcript: TranscriptResult) -> EditingPlan:
        text = _normalize(transcript.text)
        primary = SubjectSpec(description="pessoa principal em primeiro plano", is_ambiguous=False)

        if "desfoca ele" in text:
            return EditingPlan(
                plan_id=_plan_id(transcript.text),
                raw_transcript=transcript.text,
                language=transcript.language,
                intent=EditingIntent.CLARIFICATION_NEEDED,
                subject=SubjectSpec(
                    description="pessoa referida por 'ele' (não identificada)",
                    is_ambiguous=True,
                    clarification_question="Quem devo manter nítido no vídeo?",
                ),
                operations=[],
            )
        if "substitui o fundo" in text or "substitui o fundo" in text.replace("í", "i"):
            prompt = "estúdio profissional" if "estúdio" in text or "estudio" in text else "novo fundo"
            return EditingPlan(
                plan_id=_plan_id(transcript.text),
                raw_transcript=transcript.text,
                language=transcript.language,
                intent=EditingIntent.REPLACE_BACKGROUND,
                subject=primary,
                operations=[
                    KeepSubjectSharpOperation(),
                    ReplaceBackgroundOperation(prompt=prompt),
                ],
            )
        if "mantém-me nítido" in text or "mantem-me nitido" in text.replace("é", "e"):
            return EditingPlan(
                plan_id=_plan_id(transcript.text),
                raw_transcript=transcript.text,
                language=transcript.language,
                intent=EditingIntent.KEEP_SHARP_BLUR_REST,
                subject=primary,
                operations=[KeepSubjectSharpOperation(), BlurBackgroundOperation(strength=0.85)],
            )
        if "desfoca" in text:
            return EditingPlan(
                plan_id=_plan_id(transcript.text),
                raw_transcript=transcript.text,
                language=transcript.language,
                intent=EditingIntent.BLUR_BACKGROUND,
                subject=primary,
                operations=[KeepSubjectSharpOperation(), BlurBackgroundOperation(strength=0.8)],
            )
        return EditingPlan(
            plan_id=_plan_id(transcript.text),
            raw_transcript=transcript.text,
            language=transcript.language,
            intent=EditingIntent.UNSUPPORTED,
            subject=SubjectSpec(description="instrução sem edição suportada identificada", is_ambiguous=False),
            operations=[],
        )


class MockSegmentationProvider:
    """Writes a real synthetic mask sequence (moving ellipse subject) via MaskWriter."""

    provider_name = "mock-segmentation"

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
        if frame_count <= 0 or width <= 0 or height <= 0 or fps <= 0:
            raise ValueError("width, height, frame_count and fps must be positive.")
        yy, xx = np.mgrid[0:height, 0:width]
        masks: list[np.ndarray] = []
        cy, ry, rx = height / 2, height * 0.34, width * 0.13
        for i in range(frame_count):
            cx = width * (0.2 + 0.6 * (i / max(frame_count - 1, 1)))
            inside = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0
            masks.append(np.where(inside, 255, 0).astype(np.uint8))
        manifest = MaskWriter().write_sequence(
            output_dir,
            masks,
            fps=fps,
            subject_id="person_1",
            source_video_id=source_video_id,
        )
        return SegmentationResult(
            job_id=job_id,
            subject_id=manifest.subject_id,
            mask_manifest_path=str(Path(output_dir) / "manifest.json"),
            frame_count=manifest.frame_count,
            width=manifest.video_width,
            height=manifest.video_height,
            fps=manifest.fps,
            provider_name=self.provider_name,
            is_mock=True,
        )


class MockBackgroundGenerationProvider:
    """Returns a real local background image file plus simulated generation metadata."""

    provider_name = "mock-background-generation"

    def __init__(self, assets_dir: str | Path = DEFAULT_BACKGROUND_ASSETS_DIR) -> None:
        self._assets_dir = Path(assets_dir)

    def generate(self, *, prompt: str, orientation: str = "landscape") -> BackgroundResult:
        if orientation not in _BACKGROUNDS:
            raise ValueError(f"orientation must be one of {sorted(_BACKGROUNDS)}; got {orientation!r}.")
        filename, width, height, simulated_prompt = _BACKGROUNDS[orientation]
        path = self._assets_dir / filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Mock background asset missing: {path}. Run scripts/generate_background_assets.py first."
            )
        return BackgroundResult(
            asset_id=f"mock-bg-{orientation}",
            image_path=str(path),
            width=width,
            height=height,
            orientation=orientation,  # type: ignore[arg-type]
            simulated_prompt=prompt or simulated_prompt,
            provider_name=self.provider_name,
            is_mock=True,
        )
