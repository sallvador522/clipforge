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
from typing import Sequence

import numpy as np

from clipforge_contracts import (
    BackgroundResult,
    BlurBackgroundOperation,
    EditingIntent,
    EditingPlan,
    KeepSubjectSharpOperation,
    ReplaceBackgroundOperation,
    SegmentationResult,
    SegmentationSubject,
    SubjectSpec,
    TranscriptResult,
)
from clipforge_providers.subject_previews import write_subject_preview
from clipforge_worker.masks import MaskSequenceWriter

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

    def transcribe_audio(self, audio_path: str | Path, *, language_bias: Sequence[str] = ("Portuguese",)) -> TranscriptResult:
        raise ValueError(
            "Mock transcription cannot interpret audio. Select a mock fixture explicitly "
            "(the UI labels it as simulated); live transcription requires CLIPFORGE_TRANSCRIBE_MODE=live."
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
    """Writes two real synthetic per-object mask sequences via MaskSequenceWriter.

    This is NOT person detection and NOT SAM. It exists so the subject-selection
    contract and renderer can be exercised offline. Object "1" enters after the
    first frames and leaves before the end, exercising absent-frame handling.
    """

    provider_name = "mock-sam-segmentation"
    model = "mock-sam-3.1-fixture"
    execution_mode = "mock"

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
    ) -> SegmentationResult:
        if frame_count <= 0 or width <= 0 or height <= 0 or fps <= 0:
            raise ValueError("width, height, frame_count and fps must be positive.")
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        objects_dir = root / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)
        source_sha256 = _sha256(source_path) if source_path else None

        yy, xx = np.mgrid[0:height, 0:width]
        object_specs = {
            "0": {"cy": height * 0.50, "ry": height * 0.32, "rx": width * 0.11},
            "1": {"cy": height * 0.44, "ry": height * 0.22, "rx": width * 0.08},
        }
        first_visible = {"0": 0, "1": max(1, frame_count // 3)}
        last_visible = {"0": frame_count - 1, "1": max(first_visible["1"], frame_count - 2)}
        last_visible["1"] = min(last_visible["1"], frame_count - 1)
        first_mask: dict[str, np.ndarray] = {}

        object_writers = {
            object_id: MaskSequenceWriter(
                objects_dir / f"object_{object_id}",
                fps=fps,
                subject_id=object_id,
                source_video_id=source_video_id,
                source_sha256=source_sha256,
                sam_object_id=object_id,
                provider_name=self.provider_name,
                model=self.model,
            )
            for object_id in object_specs
        }
        root_writer = MaskSequenceWriter(
            root,
            fps=fps,
            subject_id="sam_union",
            source_video_id=source_video_id,
            source_sha256=source_sha256,
            sam_object_ids=list(object_specs),
            provider_name=self.provider_name,
            model=self.model,
        )

        for frame in range(frame_count):
            frame_masks: dict[str, np.ndarray] = {}
            for object_id, spec in object_specs.items():
                visible = first_visible[object_id] <= frame <= last_visible[object_id]
                if visible:
                    progress = frame / max(frame_count - 1, 1)
                    if object_id == "0":
                        cx = width * (0.18 + 0.64 * progress)
                    else:
                        cx = width * (0.82 - 0.58 * progress)
                    inside = (
                        ((yy - spec["cy"]) / spec["ry"]) ** 2
                        + ((xx - cx) / spec["rx"]) ** 2
                        <= 1.0
                    )
                    mask = np.where(inside, 255, 0).astype(np.uint8)
                else:
                    mask = np.zeros((height, width), dtype=np.uint8)
                frame_masks[object_id] = mask
                object_writers[object_id].write(mask)
                if visible and object_id not in first_mask:
                    first_mask[object_id] = mask
            root_writer.write(np.maximum.reduce(list(frame_masks.values())))

        root_manifest = root_writer.finalize()
        subjects: list[SegmentationSubject] = []
        for object_id in object_specs:
            object_writers[object_id].finalize()
            preview_path = None
            if object_id in first_mask:
                preview_path = write_subject_preview(
                    source_path=source_path,
                    mask=first_mask[object_id],
                    object_id=object_id,
                    frame_index=first_visible[object_id],
                    output_path=root / "previews" / f"object_{object_id}.png",
                )
            subjects.append(
                SegmentationSubject(
                    object_id=object_id,
                    label="Simulated person",
                    mask_manifest_path=str(objects_dir / f"object_{object_id}" / "manifest.json"),
                    preview_path=preview_path,
                    first_frame=first_visible[object_id],
                    last_frame=last_visible[object_id],
                    frames_detected=max(0, last_visible[object_id] - first_visible[object_id] + 1),
                )
            )

        return SegmentationResult(
            job_id=job_id,
            subject_id=root_manifest.subject_id,
            mask_manifest_path=str(root / "manifest.json"),
            frame_count=root_manifest.frame_count,
            width=root_manifest.video_width,
            height=root_manifest.video_height,
            fps=root_manifest.fps,
            provider_name=self.provider_name,
            is_mock=True,
            model=self.model,
            subjects=subjects,
            source_sha256=source_sha256,
            status="completed",
        )


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
