"""Mock director EDL projection tests (A–E, offline)."""

from __future__ import annotations

import pytest

from clipforge_contracts import PlanOutcome, TranscriptResult
from clipforge_director import MockProfessionalEditingDirector


def transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, language="pt-BR", provider_name="t", is_mock=True)


def test_create_edl_matches_plan_operations():
    director = MockProfessionalEditingDirector()
    plan = director.create_plan(transcript("Keep me sharp and blur everything behind me."))
    edl = director.create_edl(transcript("Keep me sharp and blur everything behind me."))
    assert edl.request_id == plan.request_id
    assert [d.capability_id for d in edl.decisions] == [op.capability_id for op in plan.operations]
    assert [d.operation_id for d in edl.decisions] == [op.operation_id for op in plan.operations]


def test_replacement_edl_requires_approval_per_decision():
    director = MockProfessionalEditingDirector()
    text = "Replace the background with a professional recording studio."
    edl = director.create_edl(transcript(text))
    by_capability = {d.capability_id: d for d in edl.decisions}
    assert by_capability["background.replace"].transparency.approval_required is True
    assert by_capability["background.replace"].transparency.approval_state.value == "required"
    assert by_capability["subject.isolate"].transparency.approval_required is False


def test_cinematic_edl_labels_simulation():
    edl = MockProfessionalEditingDirector().create_edl(
        transcript("Put me in a cinematic sunset in Luanda, keep my face sharp.")
    )
    replace = next(d for d in edl.decisions if d.capability_id == "background.replace")
    assert replace.params.asset_source == "mock_generated"  # type: ignore[attr-defined]
    assert "simulated" in replace.transparency.why.lower() or "simulated" in replace.transparency.operator_message.lower()


def test_non_ready_transcripts_have_no_edl():
    director = MockProfessionalEditingDirector()
    with pytest.raises(ValueError):
        director.create_edl(transcript("Make my video more professional."))
    with pytest.raises(ValueError):
        director.create_edl(transcript("Add a transition."))


def test_edl_is_deterministic():
    director = MockProfessionalEditingDirector()
    first = director.create_edl(transcript("Keep me sharp and blur the background."))
    second = director.create_edl(transcript("Keep me sharp and blur the background."))
    assert first.model_dump(exclude={"created_at"}) == second.model_dump(exclude={"created_at"})


def test_edl_offline_no_network():
    import socket

    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def blocked(*args, **kwargs):
        raise AssertionError("network used")

    socket.socket.connect = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    try:
        MockProfessionalEditingDirector().create_edl(transcript("Keep me sharp and blur the background."))
    finally:
        socket.socket.connect = real_connect  # type: ignore[assignment]
        socket.create_connection = real_create  # type: ignore[assignment]
