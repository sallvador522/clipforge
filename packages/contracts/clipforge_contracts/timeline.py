"""Post-MVP multitrack timeline assembly (ADR-044).

A timeline is an explicit user arrangement of project assets on four
single-purpose tracks (V1/V2 video, A1/A2 audio), up to a 15-minute program.
Every clip references a
project asset by id; the API resolves files and validates media bounds,
ownership and overlap. The worker composes the program with real
FFmpeg/OpenCV (never mocked); the director never invents timeline content.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TimelineTrack = Literal["V1", "V2", "A1", "A2"]

VIDEO_TRACKS: tuple[str, ...] = ("V1", "V2")
AUDIO_TRACKS: tuple[str, ...] = ("A1", "A2")

#: Post-MVP program cap: 15 minutes. Rendering streams frame-by-frame with
#: bounded memory, but wall-clock time grows linearly (~1.7 FPS at 720p, so a
#: full-length program takes hours — stated honestly, never promised fast).
TIMELINE_MAX_DURATION_S = 900.0
#: Minimum clip length, consistent with the ADR-041 trim rule.
TIMELINE_MIN_CLIP_S = 0.5
#: Upper bound on clips per timeline (keeps payloads and renders tractable).
TIMELINE_MAX_CLIPS = 64


class TimelineClip(BaseModel):
    """One placed media segment. Times are absolute seconds."""

    model_config = ConfigDict(extra="forbid")
    clip_id: str = Field(pattern=r"^clip_[a-z0-9]{12}$")
    asset_id: str = Field(pattern=r"^ast_[a-z0-9]{12}$")
    track: TimelineTrack
    timeline_start_s: float = Field(ge=0.0)
    source_in_s: float = Field(ge=0.0)
    source_out_s: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _check_bounds(self) -> "TimelineClip":
        duration = self.source_out_s - self.source_in_s
        if duration < TIMELINE_MIN_CLIP_S - 1e-9:
            raise ValueError(f"clip shorter than {TIMELINE_MIN_CLIP_S}s")
        if self.timeline_start_s + duration > TIMELINE_MAX_DURATION_S + 1e-9:
            raise ValueError(f"clip ends past the {TIMELINE_MAX_DURATION_S:.0f}s program cap")
        return self

    @property
    def duration_s(self) -> float:
        return self.source_out_s - self.source_in_s

    @property
    def timeline_end_s(self) -> float:
        return self.timeline_start_s + self.duration_s


class Timeline(BaseModel):
    """Explicit user arrangement. Empty timeline = no program."""

    model_config = ConfigDict(extra="forbid")
    clips: list[TimelineClip] = Field(default_factory=list, max_length=TIMELINE_MAX_CLIPS)

    @model_validator(mode="after")
    def _check_overlap(self) -> "Timeline":
        by_track: dict[str, list[TimelineClip]] = {}
        for clip in self.clips:
            by_track.setdefault(clip.track, []).append(clip)
        for track, clips in by_track.items():
            ordered = sorted(clips, key=lambda c: c.timeline_start_s)
            for first, second in zip(ordered, ordered[1:]):
                if second.timeline_start_s < first.timeline_end_s - 1e-9:
                    raise ValueError(f"clips overlap on track {track}")
        return self

    def program_duration_s(self) -> float:
        if not self.clips:
            return 0.0
        return max(c.timeline_end_s for c in self.clips)
