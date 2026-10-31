"""Operation execution status transitions (Milestone 6B-PREP)."""

from __future__ import annotations

import pytest

from clipforge_contracts import (
    InvalidOperationTransition,
    OperationStatus,
    can_transition_operation,
    require_operation_transition,
)


def test_operation_status_values():
    assert [status.value for status in OperationStatus] == [
        "proposed",
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
    ]


def test_happy_operation_path():
    path = [
        OperationStatus.PROPOSED,
        OperationStatus.PENDING,
        OperationStatus.RUNNING,
        OperationStatus.COMPLETED,
    ]
    for source, target in zip(path, path[1:]):
        assert can_transition_operation(source, target)
        require_operation_transition(source, target)


def test_terminal_operation_status_cannot_advance():
    for terminal in (OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.SKIPPED):
        with pytest.raises(InvalidOperationTransition):
            require_operation_transition(terminal, OperationStatus.RUNNING)


def test_cannot_run_without_pending():
    with pytest.raises(InvalidOperationTransition):
        require_operation_transition(OperationStatus.PROPOSED, OperationStatus.COMPLETED)
