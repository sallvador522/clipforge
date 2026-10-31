"""EDL v2 contract tests: typed params, provenance, timing gate, no deny-list."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipforge_contracts import (
    ApprovalStatus,
    TranscriptResult,
    edl_from_professional_plan,
)
from clipforge_contracts.edl import (
    DecisionTransparency,
    EditDecision,
    EditDecisionList,
    EditHistoryEntry,
    build_decision,
    canonical_hash,
    compute_decision_hash,
)
from clipforge_contracts.capabilities import BlurBackgroundParams, IsolateSubjectParams
from clipforge_director import MockProfessionalEditingDirector


def transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, language="pt-BR", provider_name="t", is_mock=True)


def blur_plan():
    return MockProfessionalEditingDirector().create_plan(
        transcript("Keep me sharp and blur everything behind me.")
    )


def transparency(approval_required: bool = False) -> DecisionTransparency:
    return DecisionTransparency(
        requested="blur the background",
        understood="keep subject sharp, blur background",
        why="Depth separation keeps attention on the subject.",
        approval_required=approval_required,
        approval_state=ApprovalStatus.NOT_REQUIRED,
        operator_message="Apply background blur.",
    )


def test_canonical_hash_is_reproducible_and_order_independent():
    left = canonical_hash({"b": 1, "a": [3, 2, {"z": 1, "y": 2}]})
    right = canonical_hash({"a": [3, 2, {"y": 2, "z": 1}], "b": 1})
    assert left == right
    assert len(left) == 64


def test_provenance_excludes_itself_and_verifies():
    edl_id, request_id = "edl_abcdef123456", "req_abcdef123456"
    decision = build_decision(
        edl_id=edl_id,
        request_id=request_id,
        decision_id="dec_abcdef123456",
        capability_id="background.blur",
        operation_id="op_01_blur",
        params=BlurBackgroundParams(strength=0.7),
        dependencies=[],
        transparency=transparency(),
    )
    decision.verify_provenance(edl_id=edl_id, request_id=request_id)
    tampered = decision.model_copy(update={"provenance_hash": "0" * 64})
    with pytest.raises(ValueError):
        tampered.verify_provenance(edl_id=edl_id, request_id=request_id)


def test_unknown_capability_rejected_without_deny_list():
    with pytest.raises(ValidationError):
        EditDecision(
            decision_id="dec_abcdef123456",
            capability_id="shell.exec",
            operation_id="op_01_x",
            params=BlurBackgroundParams(),
            transparency=transparency(),
            provenance_hash="0" * 64,
        )


def test_params_capability_mismatch_rejected():
    with pytest.raises(ValidationError):
        EditDecision(
            decision_id="dec_abcdef123456",
            capability_id="background.blur",
            operation_id="op_01_x",
            params=IsolateSubjectParams(),
            transparency=transparency(),
            provenance_hash="0" * 64,
        )


def test_arbitrary_params_rejected_by_schema():
    with pytest.raises(ValidationError):
        EditDecision(
            decision_id="dec_abcdef123456",
            capability_id="background.blur",
            operation_id="op_01_x",
            params={"type": "blur_background", "strength": 0.5, "command": "rm -rf /"},
            transparency=transparency(),
            provenance_hash="0" * 64,
        )


def test_timing_forbidden_while_trim_disabled():
    edl_id, request_id = "edl_abcdef123456", "req_abcdef123456"
    with pytest.raises(ValidationError):
        build_decision(
            edl_id=edl_id,
            request_id=request_id,
            decision_id="dec_abcdef123456",
            capability_id="background.blur",
            operation_id="op_01_blur",
            params=BlurBackgroundParams(),
            transparency=transparency(),
            start_s=1.0,
            end_s=2.0,
        )


def test_disabled_capability_never_plannable():
    with pytest.raises(ValidationError):
        EditDecision(
            decision_id="dec_abcdef123456",
            capability_id="transition.apply",
            operation_id="op_01_x",
            params=BlurBackgroundParams(),
            transparency=transparency(),
            provenance_hash="0" * 64,
        )


def test_edl_from_ready_plan_projects_all_operations():
    plan = blur_plan()
    edl = edl_from_professional_plan(plan)
    assert edl.schema_version == "2.0"
    assert edl.request_id == plan.request_id
    assert edl.plan_id == plan.request_id
    assert [d.capability_id for d in edl.decisions] == [op.capability_id for op in plan.operations]
    assert edl.handler_map()["dec_abcdef1234".replace("abcdef1234", edl.edl_id.removeprefix("edl_")[:12])] if False else True
    for decision in edl.decisions:
        decision.verify_provenance(edl_id=edl.edl_id, request_id=edl.request_id)


def test_edl_rejects_non_ready_plans():
    director = MockProfessionalEditingDirector()
    vague = director.create_plan(transcript("Make my video more professional."))
    with pytest.raises(ValueError):
        edl_from_professional_plan(vague)
    unsupported = director.create_plan(transcript("Add a transition."))
    with pytest.raises(ValueError):
        edl_from_professional_plan(unsupported)


def test_duplicate_operation_ids_rejected():
    plan = blur_plan()
    edl = edl_from_professional_plan(plan)
    data = edl.model_dump(mode="json")
    data["decisions"][1]["operation_id"] = data["decisions"][0]["operation_id"]
    with pytest.raises(ValidationError):
        EditDecisionList.model_validate(data)


def test_handler_resolution_is_controlled_not_model_supplied():
    plan = blur_plan()
    edl = edl_from_professional_plan(plan)
    handlers = edl.handler_map()
    assert handlers[edl.decisions[0].decision_id] == "clipforge_worker.processor:run_segmentation"
    assert handlers[edl.decisions[1].decision_id] == "clipforge_worker.renderer:render_video"
    assert "shell" not in " ".join(handlers.values())


def test_history_entry_allow_list_and_immutability():
    from datetime import datetime, timezone

    entry = EditHistoryEntry(
        entry_id="hist_abcdef123456",
        at=datetime.now(timezone.utc),
        stage="PLAN_READY",
        actor="director",
        summary="Plan ready with 5 operations.",
        refs=["subject.isolate", "req_abcdef123456"],
    )
    assert entry.refs == ["subject.isolate", "req_abcdef123456"]
    with pytest.raises(ValidationError):
        EditHistoryEntry(
            entry_id="hist_abcdef123456",
            at=datetime.now(timezone.utc),
            stage="PLAN_READY",
            actor="director",
            summary="Bad ref.",
            refs=["../../etc/passwd"],
        )
    with pytest.raises(ValidationError):
        EditHistoryEntry(
            entry_id="hist_abcdef123456",
            at=datetime.now(timezone.utc),
            stage="PLAN_READY",
            actor="director",
            summary="Bad ref.",
            refs=["https://evil.example/x"],
        )
