"""EditingPlan contract (schema_version 1.0). Every generated plan is validated here."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditingIntent(str, Enum):
    BLUR_BACKGROUND = "blur_background"
    REPLACE_BACKGROUND = "replace_background"
    KEEP_SHARP_BLUR_REST = "keep_sharp_blur_rest"
    CLARIFICATION_NEEDED = "clarification_needed"
    UNSUPPORTED = "unsupported"


class KeepSubjectSharpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["keep_subject_sharp"] = "keep_subject_sharp"


class BlurBackgroundOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["blur_background"] = "blur_background"
    strength: float = Field(default=0.8, ge=0.0, le=1.0)


class ReplaceBackgroundOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["replace_background"] = "replace_background"
    prompt: str = Field(min_length=1)
    asset_id: str | None = None


Operation = Annotated[
    Union[KeepSubjectSharpOperation, BlurBackgroundOperation, ReplaceBackgroundOperation],
    Field(discriminator="type"),
]


class SubjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1)
    is_ambiguous: bool = False
    clarification_question: str | None = None

    @model_validator(mode="after")
    def _ambiguous_requires_question(self) -> "SubjectSpec":
        if self.is_ambiguous and not self.clarification_question:
            raise ValueError("Ambiguous subject requires a clarification_question (spoken clarification rule).")
        return self


class EditingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(min_length=1)
    raw_transcript: str = Field(min_length=1)
    language: str = "pt-BR"
    intent: EditingIntent
    subject: SubjectSpec
    operations: list[Operation] = Field(default_factory=list)
    preserve_audio: bool = True
    output_format: Literal["mp4"] = "mp4"

    @model_validator(mode="after")
    def _clarification_has_no_operations(self) -> "EditingPlan":
        if self.intent is EditingIntent.CLARIFICATION_NEEDED and self.operations:
            raise ValueError("A clarification plan must not contain editing operations.")
        if self.intent is EditingIntent.CLARIFICATION_NEEDED and not self.subject.is_ambiguous:
            raise ValueError("A clarification plan requires an ambiguous subject.")
        return self
