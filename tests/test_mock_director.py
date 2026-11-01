"""Deterministic Mock Professional Editing Director scenarios A–E."""

from __future__ import annotations

import socket
from contextlib import contextmanager

import pytest

from clipforge_contracts import ApprovalStatus, PlanOutcome, TranscriptResult
from clipforge_contracts.capabilities import get_capability
from clipforge_director import MockProfessionalEditingDirector


def transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, language="pt-BR", provider_name="test", is_mock=True)


def plan(text: str):
    return MockProfessionalEditingDirector().create_plan(transcript(text))


def capabilities(plan) -> list[str]:
    return [operation.capability_id for operation in plan.operations]


class TestScenarioA:
    def test_keeps_subject_sharp_and_blurs_background(self):
        p = plan("Keep me sharp and blur everything behind me.")
        assert p.outcome is PlanOutcome.PLAN_READY
        assert capabilities(p) == [
            "subject.isolate",
            "background.blur",
            "audio.preserve",
            "video.render_mp4",
            "output.verify",
        ]
        assert p.approval_status is ApprovalStatus.NOT_REQUIRED

    def test_explains_why(self):
        p = plan("Keep me sharp and blur everything behind me.")
        assert "isolate" in p.summary_explanation.lower()
        assert any("depth-of-field" in explanation for explanation in p.explanations)

    def test_portuguese_instruction(self):
        p = plan("Mantém-me nítido e desfoca o resto.")
        assert p.outcome is PlanOutcome.PLAN_READY
        assert "background.blur" in capabilities(p)


class TestScenarioB:
    def test_replaces_background_with_local_asset(self):
        p = plan("Replace the background with a professional recording studio.")
        assert p.outcome is PlanOutcome.PLAN_READY
        assert capabilities(p) == [
            "subject.isolate",
            "background.replace",
            "audio.preserve",
            "video.render_mp4",
            "output.verify",
        ]
        replace = next(op for op in p.operations if op.capability_id == "background.replace")
        assert replace.params.asset_source == "local_asset"

    def test_requires_approval(self):
        p = plan("Substitui o fundo por um estúdio profissional.")
        assert p.approval_status is ApprovalStatus.REQUIRED
        assert p.estimated_stages[1].value == "WAITING_FOR_APPROVAL"


class TestScenarioC:
    def test_cinematic_sunset_uses_generated_background(self):
        p = plan("Put me in a cinematic sunset in Luanda, keep my face sharp.")
        assert p.outcome is PlanOutcome.PLAN_READY
        replace = next(op for op in p.operations if op.capability_id == "background.replace")
        assert replace.params.asset_source == "mock_generated"
        assert "luanda" in replace.params.prompt.lower()
        assert "after approval" in p.summary_explanation.lower()
        assert "muse image when live" in p.summary_explanation.lower()
        assert "local mock" in p.summary_explanation.lower()

    def test_does_not_claim_generation_already_happened(self):
        p = plan("Put me in a cinematic sunset in Luanda, keep my face sharp.")
        assert all("already generated" not in exp.lower() for exp in p.explanations)
        assert any("after approval" in exp.lower() for exp in p.explanations)


class TestScenarioD:
    def test_vague_request_asks_clarification(self):
        p = plan("Make my video more professional.")
        assert p.outcome is PlanOutcome.NEEDS_CLARIFICATION
        assert p.operations == []
        assert len(p.clarification_questions) == 1
        assert p.subject.is_ambiguous is True

    def test_ambiguous_subject_asks_who(self):
        p = plan("Desfoca ele, por favor.")
        assert p.outcome is PlanOutcome.NEEDS_CLARIFICATION
        assert "which person" in p.clarification_questions[0].lower()


class TestScenarioE:
    def test_unsupported_capabilities_are_named(self):
        p = plan("Add a transition and animate keyframes.")
        assert p.outcome is PlanOutcome.UNSUPPORTED
        assert p.operations == []
        assert set(p.unsupported_capabilities) == {"transition.apply", "keyframe.animate"}
        assert "cannot" in p.summary_explanation.lower()

    def test_unsupported_never_executes(self):
        p = plan("Trim the clip and add speed ramps.")
        assert p.outcome is PlanOutcome.UNSUPPORTED
        assert all(
            get_capability(cid).status.value == "disabled" for cid in p.unsupported_capabilities  # type: ignore[union-attr]
        )


def test_deterministic_output():
    director = MockProfessionalEditingDirector()
    first = director.create_plan(transcript("Keep me sharp and blur the background."))
    second = director.create_plan(transcript("Keep me sharp and blur the background."))
    assert first == second


def test_operation_ids_unique_and_ordered():
    p = plan("Keep me sharp and blur the background.")
    ids = [op.operation_id for op in p.operations]
    assert len(ids) == len(set(ids))
    seen: set[str] = set()
    for operation in p.operations:
        assert all(dep in seen for dep in operation.dependencies)
        seen.add(operation.operation_id)


@contextmanager
def no_network():
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def blocked(*args, **kwargs):
        raise AssertionError("Network access attempted by the mock director")

    socket.socket.connect = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[assignment]
        socket.create_connection = real_create  # type: ignore[assignment]


def test_mock_director_is_offline():
    director = MockProfessionalEditingDirector()
    with no_network():
        for text in (
            "Keep me sharp and blur everything behind me.",
            "Replace the background with a studio.",
            "Put me in a sunset in Luanda.",
            "Make my video more professional.",
            "Add a transition.",
        ):
            director.create_plan(transcript(text))
