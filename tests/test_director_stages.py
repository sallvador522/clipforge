"""Director transparency stages and mapping tests."""

from __future__ import annotations

import pytest

from clipforge_contracts import (
    DirectorStage,
    DirectorState,
    InvalidStageTransition,
    can_transition,
    require_transition,
    stage_from_job_stage,
)


def test_exactly_ten_stages():
    assert [stage.value for stage in DirectorStage] == [
        "REQUEST_RECEIVED",
        "ANALYZING_REQUEST",
        "PLAN_READY",
        "WAITING_FOR_APPROVAL",
        "EXECUTING",
        "VERIFYING",
        "COMPLETED",
        "FAILED",
        "NEEDS_CLARIFICATION",
        "CANCELLED",
    ]


def test_valid_transition_path():
    state = DirectorState()
    state = state.advance(DirectorStage.ANALYZING_REQUEST)
    state = state.advance(DirectorStage.PLAN_READY)
    state = state.advance(DirectorStage.WAITING_FOR_APPROVAL)
    state = state.advance(DirectorStage.EXECUTING)
    state = state.advance(DirectorStage.VERIFYING)
    state = state.advance(DirectorStage.COMPLETED)
    assert state.current is DirectorStage.COMPLETED
    assert state.terminal is True
    assert len(state.history) == 7


def test_invalid_transition_rejected():
    assert can_transition(DirectorStage.REQUEST_RECEIVED, DirectorStage.COMPLETED) is False
    with pytest.raises(InvalidStageTransition):
        require_transition(DirectorStage.REQUEST_RECEIVED, DirectorStage.COMPLETED)
    with pytest.raises(InvalidStageTransition):
        DirectorState().advance(DirectorStage.COMPLETED)


def test_terminal_stage_cannot_advance():
    state = DirectorState(current=DirectorStage.COMPLETED, history=[DirectorStage.COMPLETED])
    with pytest.raises(InvalidStageTransition):
        state.advance(DirectorStage.EXECUTING)


def test_cancellation_from_active_stages():
    state = DirectorState().advance(DirectorStage.ANALYZING_REQUEST)
    assert state.advance(DirectorStage.CANCELLED).terminal is True


@pytest.mark.parametrize(
    ("job_stage", "expected"),
    [
        ("awaiting_voice", DirectorStage.REQUEST_RECEIVED),
        ("planning", DirectorStage.ANALYZING_REQUEST),
        ("rendering", DirectorStage.EXECUTING),
        ("verifying", DirectorStage.VERIFYING),
        ("completed", DirectorStage.COMPLETED),
        ("clarification_needed", DirectorStage.NEEDS_CLARIFICATION),
        ("failed", DirectorStage.FAILED),
    ],
)
def test_job_stage_mapping(job_stage, expected):
    assert stage_from_job_stage(job_stage) is expected


def test_unknown_job_stage_rejected():
    with pytest.raises(ValueError):
        stage_from_job_stage("mystery")
