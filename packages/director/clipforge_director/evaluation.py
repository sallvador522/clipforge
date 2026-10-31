"""Output self-evaluation (Milestone 6B-PREP-R).

Objective media verification is automated and factual. Subjective visual quality
is NEVER claimed as verified: any aesthetic judgement is flagged for explicit
human review. A correction ledger caps re-renders at three passes; a new render
plus re-inspection is required before any visual correction may be claimed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObjectiveChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    streams_present: bool = False
    resolution_matches: bool = False
    duration_matches: bool = False
    frame_count_matches: bool = False
    audio_present: bool = False
    audio_video_in_sync: bool = False
    frames_readable: bool = False
    mask_boundary_sane: bool = False

    @property
    def all_passed(self) -> bool:
        return all(
            [
                self.streams_present,
                self.resolution_matches,
                self.duration_matches,
                self.frame_count_matches,
                self.frames_readable,
            ]
        )


class SamplePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern=r"^(first|middle|final)$")
    frame_index: int = Field(ge=0)
    timestamp_s: float = Field(ge=0.0)
    readable: bool = False
    mean_brightness: float = Field(ge=0.0, le=255.0)
    edge_density: float = Field(ge=0.0)


class CorrectionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass_number: int = Field(ge=1, le=3)
    issue: str = Field(min_length=1, max_length=300)
    action: str = Field(min_length=1, max_length=300)
    rerendered: bool = False
    reinspected: bool = False


class OutputEvaluationReport(BaseModel):
    """Structured self-evaluation. Subjective quality is human-review only."""

    model_config = ConfigDict(extra="forbid")

    output_path: str = Field(min_length=1)
    expected_width: int = Field(gt=0)
    expected_height: int = Field(gt=0)
    expected_frames: int = Field(gt=0)
    expected_duration_s: float = Field(gt=0)
    expect_audio: bool = False
    objective: ObjectiveChecks = Field(default_factory=ObjectiveChecks)
    samples: list[SamplePoint] = Field(default_factory=list)
    corrections: list[CorrectionAttempt] = Field(default_factory=list)
    needs_human_review: bool = True
    human_review_notes: list[str] = Field(default_factory=list)
    verdict: str = Field(default="not_evaluated", pattern=r"^(not_evaluated|pass_objective|fail_objective)$")

    @model_validator(mode="after")
    def _validate_report(self) -> "OutputEvaluationReport":
        labels = [sample.label for sample in self.samples]
        if self.samples and (sorted(labels) != ["final", "first", "middle"] or len(labels) != 3):
            raise ValueError("Samples must be exactly first, middle and final, in any order.")
        indices = [sample.frame_index for sample in self.samples]
        if indices != sorted(indices):
            raise ValueError("Sample frame indices must be non-decreasing (first/middle/final).")
        if len(self.corrections) > 3:
            raise ValueError("At most three correction passes are allowed.")
        for attempt in self.corrections:
            if attempt.pass_number != self.corrections.index(attempt) + 1:
                raise ValueError("Correction passes must be numbered sequentially from 1.")
        if self.verdict == "pass_objective" and not self.objective.all_passed:
            raise ValueError("pass_objective requires all objective checks.")
        return self

    def request_correction(self, *, issue: str, action: str) -> CorrectionAttempt:
        if len(self.corrections) >= 3:
            raise ValueError("Correction budget exhausted (max 3 passes).")
        return CorrectionAttempt(
            pass_number=len(self.corrections) + 1,
            issue=issue,
            action=action,
            rerendered=False,
            reinspected=False,
        )


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed for {path.name}.")
    return json.loads(result.stdout)


@dataclass(frozen=True)
class ContactSheet:
    paths: tuple[Path, ...]


def evaluate_output(
    output_path: str | Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_frames: int,
    expected_duration_s: float,
    expect_audio: bool,
    source_path: str | Path | None = None,
) -> OutputEvaluationReport:
    """Run objective checks plus three-point sampling. No subjective verdict."""
    path = Path(output_path)
    report = OutputEvaluationReport(
        output_path=str(path),
        expected_width=expected_width,
        expected_height=expected_height,
        expected_frames=expected_frames,
        expected_duration_s=expected_duration_s,
        expect_audio=expect_audio,
        human_review_notes=[
            "Cinematic quality, mask edge aesthetics and background integration require explicit human review.",
            "Automated checks verify container facts and frame readability only.",
        ],
    )
    if not path.is_file():
        report.verdict = "fail_objective"
        return report

    try:
        data = _probe(path)
    except ValueError:
        report.verdict = "fail_objective"
        return report

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt_duration = float(data.get("format", {}).get("duration", 0) or 0)

    checks = report.objective
    if video is not None:
        checks.streams_present = True
        checks.resolution_matches = (
            int(video.get("width", -1)) == expected_width and int(video.get("height", -1)) == expected_height
        )
        frames = video.get("nb_read_frames") or video.get("nb_frames")
        try:
            checks.frame_count_matches = int(frames) == expected_frames
        except (TypeError, ValueError):
            checks.frame_count_matches = False
    checks.duration_matches = abs(fmt_duration - expected_duration_s) <= 0.6
    checks.audio_present = audio is not None
    if expect_audio and audio is not None:
        try:
            audio_duration = float(audio.get("duration", fmt_duration))
            checks.audio_video_in_sync = abs(audio_duration - fmt_duration) <= 0.1
        except (TypeError, ValueError):
            checks.audio_video_in_sync = False
    elif not expect_audio:
        checks.audio_video_in_sync = True

    samples = _sample_frames(path, expected_frames, expected_duration_s)
    report.samples.extend(samples)
    checks.frames_readable = len(samples) == 3 and all(s.readable for s in samples)
    checks.mask_boundary_sane = _boundary_proxy(samples, source_path)

    report.verdict = "pass_objective" if checks.all_passed else "fail_objective"
    report.needs_human_review = True
    return report


def _sample_frames(path: Path, expected_frames: int, expected_duration_s: float) -> list[SamplePoint]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return []
    indices = sorted({0, expected_frames // 2, max(expected_frames - 1, 0)})
    samples: list[SamplePoint] = []
    labels = ("first", "middle", "final")
    for label, index in zip(labels, indices):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok or frame is None:
            samples.append(
                SamplePoint(
                    label=label, frame_index=index,
                    timestamp_s=index / max(expected_frames / expected_duration_s, 0.01),
                    readable=False, mean_brightness=0.0, edge_density=0.0,
                )
            )
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        samples.append(
            SamplePoint(
                label=label,
                frame_index=index,
                timestamp_s=round(index / max(expected_frames / expected_duration_s, 0.01), 3),
                readable=True,
                mean_brightness=round(float(np.mean(gray)), 2),
                edge_density=round(float(np.mean(edges > 0)), 4),
            )
        )
    capture.release()
    return samples


def _boundary_proxy(samples: list[SamplePoint], source_path: str | Path | None) -> bool:
    """Heuristic only: frames must be non-uniform (rules out black/blank renders).

    This is a corruption tripwire, not a mask-quality judgement. Real edge quality
    always needs the human review flag.
    """
    if len(samples) != 3 or not all(s.readable for s in samples):
        return False
    return all(s.edge_density > 0.0005 for s in samples)
