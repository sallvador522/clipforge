"""Explicit consent for external SAM video processing (ADR-020).

Consent is bound to one job, one source-video hash, one disclosure version and
one provider/model. It is separate from editing-plan approval.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SUBJECT_DETECTION_DISCLOSURE_VERSION = "sam31-external-video-v1"
SUBJECT_DETECTION_PROVIDER = "meta-sam"
SUBJECT_DETECTION_MODEL = "sam-3.1"


class SubjectDetectionConsent(BaseModel):
    """Minimal audit record; no personal information beyond the job/source hash."""

    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)
    source_video_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent_given: bool
    consent_timestamp: datetime
    disclosure_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    segmentation_mode: Literal["live"]


class ConsentValidationError(ValueError):
    """Consent is missing, stale, or does not belong to this operation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_subject_detection_consent(
    consent: SubjectDetectionConsent | None,
    *,
    job_id: str,
    source_video_hash: str,
    provider: str,
    model: str,
) -> None:
    """Validate every binding before any upload or inference call."""
    if consent is None or not consent.consent_given:
        raise ConsentValidationError(
            "subject_detection_consent_required",
            "Live SAM subject detection requires explicit user consent before the "
            "video-only copy is sent to Meta.",
        )
    if consent.job_id != job_id:
        raise ConsentValidationError(
            "subject_detection_consent_job_mismatch",
            "The consent record belongs to a different job.",
        )
    if consent.source_video_hash != source_video_hash:
        raise ConsentValidationError(
            "subject_detection_consent_source_mismatch",
            "The source video changed after consent; consent is no longer valid.",
        )
    if consent.disclosure_version != SUBJECT_DETECTION_DISCLOSURE_VERSION:
        raise ConsentValidationError(
            "subject_detection_consent_disclosure_mismatch",
            "The consent record refers to a different disclosure version.",
        )
    if consent.provider != provider:
        raise ConsentValidationError(
            "subject_detection_consent_provider_mismatch",
            "The consent record was given for a different provider.",
        )
    if consent.model != model:
        raise ConsentValidationError(
            "subject_detection_consent_model_mismatch",
            "The consent record was given for a different model.",
        )
    if consent.segmentation_mode != "live":
        raise ConsentValidationError(
            "subject_detection_consent_mode_mismatch",
            "The consent record was not given for live segmentation.",
        )
