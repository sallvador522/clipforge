"""Explicit consent for external SAM video processing (ADR-020, ADR-056).

Consent is bound to one job, one source-video hash, one disclosure version and
one provider/model. Since ADR-056 it may also bind a trim window: when the
user marks a trecho, only that window (seconds into the original source) may
be sent to Meta. It is separate from editing-plan approval.
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
    # ADR-056: optional trim window (seconds into the ORIGINAL source) the
    # consent covers. None/None = the whole video. A set window must match
    # the job's trim exactly, otherwise SAM stays refused.
    trim_start_s: float | None = Field(default=None, ge=0.0)
    trim_end_s: float | None = Field(default=None, gt=0.0)
    # Hash of the materialized trimmed working copy, when it already exists
    # at binding time (the /consent path). Voice-time binding happens before
    # materialization, so this stays None and the window binding governs.
    trimmed_video_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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


def _same_window(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1e-6


def validate_subject_detection_consent(
    consent: SubjectDetectionConsent | None,
    *,
    job_id: str,
    source_video_hash: str,
    provider: str,
    model: str,
    trim_start_s: float | None = None,
    trim_end_s: float | None = None,
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
    if not _same_window(consent.trim_start_s, trim_start_s) or not _same_window(
        consent.trim_end_s, trim_end_s
    ):
        raise ConsentValidationError(
            "subject_detection_consent_trim_mismatch",
            "The consent record covers a different trecho (or the whole video); "
            "re-authorize the current selection before SAM runs.",
        )
