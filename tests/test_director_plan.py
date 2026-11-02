"""ProfessionalEditingPlan v2 validation and v1 adapter tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipforge_contracts import (
    EditingIntent,
    PlanOutcome,
    ProfessionalEditingPlan,
    TranscriptResult,
)
from clipforge_contracts.capabilities import BlurBackgroundParams
from clipforge_contracts.director_plan import ApprovalStatus, DirectorOperation
from clipforge_director import MockProfessionalEditingDirector


def transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, language="pt-BR", provider_name="test", is_mock=True)


def blur_plan():
    return MockProfessionalEditingDirector().create_plan(
        transcript("Keep me sharp and blur everything behind me.")
    )


def replace_plan():
    return MockProfessionalEditingDirector().create_plan(
        transcript("Replace the background with a professional recording studio.")
    )


def reload(plan: ProfessionalEditingPlan, **updates) -> ProfessionalEditingPlan:
    data = plan.model_dump(mode="json")
    data.update(updates)
    return ProfessionalEditingPlan.model_validate(data)


def test_blur_plan_structure_and_order():
    plan = blur_plan()
    assert plan.schema_version == "2.0"
    assert plan.outcome is PlanOutcome.PLAN_READY
    assert [op.capability_id for op in plan.operations] == [
        "subject.isolate",
        "background.blur",
        "audio.preserve",
        "video.render_mp4",
        "output.verify",
    ]
    assert plan.operations[-1].dependencies == ["op_04_render"]
    assert plan.approval_status is ApprovalStatus.NOT_REQUIRED
    assert plan.required_providers == ["segmentation"]


def test_v1_adapter_maps_blur_plan():
    v1 = blur_plan().to_execution_plan()
    assert v1.intent is EditingIntent.BLUR_BACKGROUND
    assert [op.type for op in v1.operations] == ["keep_subject_sharp", "blur_background"]
    assert v1.preserve_audio is True


def test_v1_adapter_maps_replacement_plan():
    plan = replace_plan()
    assert plan.approval_status is ApprovalStatus.REQUIRED
    v1 = plan.to_execution_plan()
    assert v1.intent is EditingIntent.REPLACE_BACKGROUND
    assert [op.type for op in v1.operations] == ["keep_subject_sharp", "replace_background"]
    replace = next(op for op in v1.operations if op.type == "replace_background")
    assert "studio" in replace.prompt


def test_unknown_capability_is_rejected():
    plan = blur_plan()
    with pytest.raises(ValidationError):
        reload(plan, operations=[{**plan.operations[0].model_dump(mode="json"), "capability_id": "shell.exec"}])


def test_disabled_capability_is_rejected_at_operation_level():
    with pytest.raises(ValidationError):
        DirectorOperation(
            operation_id="op_bad",
            capability_id="transition.apply",
            title="Transition",
            explanation="Apply a transition.",
            params=BlurBackgroundParams(),
            expected_output="n/a",
        )


def test_arbitrary_parameters_are_rejected():
    plan = blur_plan()
    with pytest.raises(ValidationError):
        DirectorOperation(
            operation_id="op_bad",
            capability_id="background.blur",
            title="Blur",
            explanation="Blur.",
            params={"type": "blur_background", "strength": 0.5, "command": "rm -rf /"},
            expected_output="n/a",
        )


def test_dependency_must_appear_before_dependent_operation():
    plan = blur_plan()
    operations = [op.model_dump(mode="json") for op in plan.operations]
    operations.reverse()
    with pytest.raises(ValidationError):
        reload(plan, operations=operations)


def test_duplicate_operation_ids_rejected():
    plan = blur_plan()
    operations = [op.model_dump(mode="json") for op in plan.operations]
    operations[1]["operation_id"] = operations[0]["operation_id"]
    with pytest.raises(ValidationError):
        reload(plan, operations=operations)


def test_ready_plan_requires_render_and_verify():
    plan = blur_plan()
    without_verify = [op.model_dump(mode="json") for op in plan.operations if op.capability_id != "output.verify"]
    with pytest.raises(ValidationError):
        reload(plan, operations=without_verify, verification_requirements=[])


def test_clarification_plan_cannot_contain_operations():
    clarification = MockProfessionalEditingDirector().create_plan(
        transcript("Make my video more professional.")
    ).model_dump(mode="json")
    clarification["operations"] = [blur_plan().operations[0].model_dump(mode="json")]
    with pytest.raises(ValidationError):
        ProfessionalEditingPlan.model_validate(clarification)


def test_ambiguous_plan_needs_question():
    clarification = MockProfessionalEditingDirector().create_plan(
        transcript("Make my video more professional.")
    ).model_dump(mode="json")
    clarification["clarification_questions"] = []
    with pytest.raises(ValidationError):
        ProfessionalEditingPlan.model_validate(clarification)


def test_clarification_plan_may_target_ambiguous_intent():
    """A broad or conflicting request can need clarification with a clear subject.

    The live lite model followed the playbook ("ambiguous subject or intent")
    but the v2 contract required an ambiguous subject, so a paid plan was
    rejected. The subject flag must stay truthful; only the question is required.
    """
    clarification = MockProfessionalEditingDirector().create_plan(
        transcript("Make my video more professional.")
    ).model_dump(mode="json")
    clarification["subject"]["is_ambiguous"] = False
    clarification["subject"]["clarification_question"] = None

    plan = ProfessionalEditingPlan.model_validate(clarification)
    assert plan.outcome is PlanOutcome.NEEDS_CLARIFICATION
    assert plan.subject.is_ambiguous is False
    assert plan.clarification_questions


def test_approval_required_for_background_replacement():
    plan = replace_plan()
    with pytest.raises(ValidationError):
        reload(plan, approval_status="not_required")


def test_unsupported_plan_rejects_available_capability():
    unsupported = MockProfessionalEditingDirector().create_plan(
        transcript("Add a transition and keyframes.")
    ).model_dump(mode="json")
    unsupported["unsupported_capabilities"] = ["background.blur"]
    with pytest.raises(ValidationError):
        ProfessionalEditingPlan.model_validate(unsupported)


def test_v1_adapter_maps_clarification_and_unsupported():
    director = MockProfessionalEditingDirector()
    clarification = director.create_plan(transcript("Make my video more professional.")).to_execution_plan()
    assert clarification.intent is EditingIntent.CLARIFICATION_NEEDED
    assert clarification.subject.is_ambiguous is True
    assert clarification.operations == []

    unsupported = director.create_plan(transcript("Add a transition.")).to_execution_plan()
    assert unsupported.intent is EditingIntent.UNSUPPORTED
    assert unsupported.operations == []


def test_no_arbitrary_paths_in_plan_schema():
    plan = blur_plan().model_dump(mode="json")
    plan["output_path"] = "C:/Windows/system32"
    with pytest.raises(ValidationError):
        ProfessionalEditingPlan.model_validate(plan)
