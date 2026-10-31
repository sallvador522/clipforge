"""Director transparency stages and validated transitions (Milestone 6B-PREP).

These stages describe the professional editing flow. They are prepared contracts;
the current worker still runs its v1 pipeline. No percentage is ever invented.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DirectorStage(str, Enum):
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    ANALYZING_REQUEST = "ANALYZING_REQUEST"
    PLAN_READY = "PLAN_READY"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    CANCELLED = "CANCELLED"


TERMINAL_STAGES = frozenset(
    {
        DirectorStage.COMPLETED,
        DirectorStage.FAILED,
        DirectorStage.NEEDS_CLARIFICATION,
        DirectorStage.CANCELLED,
    }
)

_ALLOWED: dict[DirectorStage, frozenset[DirectorStage]] = {
    DirectorStage.REQUEST_RECEIVED: frozenset({DirectorStage.ANALYZING_REQUEST, DirectorStage.CANCELLED}),
    DirectorStage.ANALYZING_REQUEST: frozenset(
        {
            DirectorStage.PLAN_READY,
            DirectorStage.NEEDS_CLARIFICATION,
            DirectorStage.FAILED,
            DirectorStage.CANCELLED,
        }
    ),
    DirectorStage.PLAN_READY: frozenset(
        {DirectorStage.WAITING_FOR_APPROVAL, DirectorStage.EXECUTING, DirectorStage.CANCELLED}
    ),
    DirectorStage.WAITING_FOR_APPROVAL: frozenset(
        {DirectorStage.EXECUTING, DirectorStage.PLAN_READY, DirectorStage.CANCELLED}
    ),
    DirectorStage.EXECUTING: frozenset(
        {DirectorStage.VERIFYING, DirectorStage.FAILED, DirectorStage.CANCELLED}
    ),
    DirectorStage.VERIFYING: frozenset({DirectorStage.COMPLETED, DirectorStage.FAILED}),
    DirectorStage.COMPLETED: frozenset(),
    DirectorStage.FAILED: frozenset(),
    DirectorStage.NEEDS_CLARIFICATION: frozenset(),
    DirectorStage.CANCELLED: frozenset(),
}


class InvalidStageTransition(ValueError):
    pass


def can_transition(source: DirectorStage, target: DirectorStage) -> bool:
    return target in _ALLOWED[source]


def require_transition(source: DirectorStage, target: DirectorStage) -> None:
    if not can_transition(source, target):
        raise InvalidStageTransition(f"Cannot move from {source.value} to {target.value}.")


class DirectorState(BaseModel):
    """Ordered, validated stage history for one editing request."""

    model_config = ConfigDict(extra="forbid")
    current: DirectorStage = DirectorStage.REQUEST_RECEIVED
    history: list[DirectorStage] = Field(default_factory=lambda: [DirectorStage.REQUEST_RECEIVED])

    def advance(self, target: DirectorStage) -> "DirectorState":
        require_transition(self.current, target)
        return DirectorState(current=target, history=[*self.history, target])

    @property
    def terminal(self) -> bool:
        return self.current in TERMINAL_STAGES


# Mapping from the existing worker stages to transparency stages. The worker keeps
# its v1 state machine; this function lets the future UI present truthful progress.
_JOB_STAGE_MAP: dict[str, DirectorStage] = {
    "awaiting_voice": DirectorStage.REQUEST_RECEIVED,
    "queued": DirectorStage.REQUEST_RECEIVED,
    "processing": DirectorStage.ANALYZING_REQUEST,
    "transcribing": DirectorStage.ANALYZING_REQUEST,
    "planning": DirectorStage.ANALYZING_REQUEST,
    "segmenting": DirectorStage.EXECUTING,
    "preparing_background": DirectorStage.EXECUTING,
    "rendering": DirectorStage.EXECUTING,
    "verifying": DirectorStage.VERIFYING,
    "completed": DirectorStage.COMPLETED,
    "pipeline_completed": DirectorStage.COMPLETED,
    "clarification_needed": DirectorStage.NEEDS_CLARIFICATION,
    # Unsupported requests end without an edit; surfacing them as FAILED is honest
    # (nothing was produced) while the plan itself carries the unsupported outcome.
    "unsupported_intent": DirectorStage.FAILED,
    "failed": DirectorStage.FAILED,
    "cancelled": DirectorStage.CANCELLED,
}


def stage_from_job_stage(job_stage: str) -> DirectorStage:
    try:
        return _JOB_STAGE_MAP[job_stage]
    except KeyError as exc:
        raise ValueError(f"Unknown job stage {job_stage!r}.") from exc
