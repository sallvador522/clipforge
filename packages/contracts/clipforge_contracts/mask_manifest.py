"""Mask manifest contract (ADR-005): PNG sequence + manifest.json."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TIMESTAMP_RULE_DERIVED = "timestamp_ms = round(index * 1000 / fps)"


def derived_timestamp_ms(index: int, fps: float) -> int:
    return round(index * 1000 / fps)


class MaskFrameEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    filename: str = Field(min_length=1)
    timestamp_ms: int = Field(ge=0)


class MaskManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    video_width: int = Field(gt=0)
    video_height: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    fps: float = Field(gt=0)
    timestamp_rule: str = TIMESTAMP_RULE_DERIVED
    subject_id: str = Field(min_length=1)
    encoding: Literal["png-grayscale-8bit"] = "png-grayscale-8bit"
    source_video_id: str = Field(min_length=1)
    source_sha256: str | None = None
    # SAM provenance. Optional so every pre-6D manifest stays valid.
    sam_object_id: str | None = None
    sam_object_ids: list[str] = Field(default_factory=list)
    provider_name: str | None = None
    model: str | None = None
    segmentation_status: Literal["completed", "incomplete"] = "completed"
    frames: list[MaskFrameEntry]

    @model_validator(mode="after")
    def _frames_consistent(self) -> "MaskManifest":
        if len(self.frames) != self.frame_count:
            raise ValueError(
                f"Manifest lists {len(self.frames)} frames but frame_count is {self.frame_count}."
            )
        expected = list(range(self.frame_count))
        actual = [f.index for f in self.frames]
        if actual != expected:
            raise ValueError(f"Frame indices must be contiguous 0..{self.frame_count - 1} in order; got {actual}.")
        for frame in self.frames:
            expected_name = f"frame_{frame.index:06d}.png"
            if frame.filename != expected_name:
                raise ValueError(f"Frame {frame.index} filename must be {expected_name}; got {frame.filename}.")
            if self.timestamp_rule == TIMESTAMP_RULE_DERIVED:
                expected_ts = derived_timestamp_ms(frame.index, self.fps)
                if frame.timestamp_ms != expected_ts:
                    raise ValueError(
                        f"Frame {frame.index} timestamp_ms must be {expected_ts} per derivation rule;"
                        f" got {frame.timestamp_ms}."
                    )
        return self
