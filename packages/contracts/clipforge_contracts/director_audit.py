"""Audit record for a Muse Spark director call.

The record is created before the HTTP request and updated as metadata becomes
available. The worker persists it independently of plan validation, so a failed
or rejected model output still has a request id, token counts and an estimated
cost. Actual billing remains external (Meta panel); this record never invents it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DirectorExecutionMode(str, Enum):
    LIVE = "live"
    MOCK = "mock"


class DirectorServiceMode(str, Enum):
    STANDARD = "standard"
    CONTRIBUTOR = "contributor"


class DirectorValidationStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ERROR = "error"
    NOT_ATTEMPTED = "not_attempted"


class DirectorAudit(BaseModel):
    """One director call's observable metadata, independent of validation success."""

    model_config = ConfigDict(extra="forbid")

    job_id: str | None = None
    request_id: str = Field(pattern=r"^req_[a-z0-9]{8,32}$")
    server_request_id: str | None = None
    provider: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=120)
    execution_mode: DirectorExecutionMode = DirectorExecutionMode.LIVE
    service_mode: DirectorServiceMode
    wire_schema: Literal["lite", "full"] = "lite"

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    actual_cost_usd: float | None = Field(default=None, ge=0.0)

    validation_status: DirectorValidationStatus = DirectorValidationStatus.NOT_ATTEMPTED
    error_category: str | None = Field(default=None, max_length=80)
    error_code: str | None = Field(default=None, max_length=120)
    http_status: int | None = Field(default=None, ge=100, le=599)
    finish_reason: str | None = Field(default=None, max_length=40)
    recorded_at: datetime = Field(default_factory=utc_now)
