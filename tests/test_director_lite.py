"""ProfessionalEditingPlan v2-lite contract tests (LIVE-CALL 003 prep, mocked only)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from clipforge_contracts import (
    DirectorOperation,
    EditingIntent,
    PlanOutcome,
    TranscriptResult,
    capability_summary_for_prompt,
)
from clipforge_contracts.director_lite import (
    LITE_BRIEF,
    LITE_WIRE_SCHEMA,
    LitePlan,
    lite_capability_summary,
    lite_to_full_plan,
    lite_to_full_plan_with_mapping,
)
from clipforge_contracts.edl import compute_decision_hash, edl_from_professional_plan
from clipforge_director import (
    LiteMetaEditingDirectorProvider,
    LiveCallAuthorization,
    MockProfessionalEditingDirector,
)


class _TestAuthorization(LiveCallAuthorization):
    """Provider-level authorization double; the real ledger is tested separately."""

    def __init__(self, function: str = "director") -> None:
        self._function = function
        self._reserved = False

    def reserve(self) -> int:
        if self._reserved:
            raise RuntimeError("already reserved")
        self._reserved = True
        return 1


def transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, language="pt-BR", provider_name="t", is_mock=True)


def _schema_depths(node, depth=1):
    """Schema-object nesting depth (through properties/items only)."""
    depths = [depth]
    if isinstance(node, dict):
        for key in ("properties", "patternProperties"):
            children = node.get(key)
            if isinstance(children, dict):
                for child in children.values():
                    if isinstance(child, dict):
                        depths.extend(_schema_depths(child, depth + 1))
        for key in ("items", "additionalProperties", "contains", "propertyNames"):
            child = node.get(key)
            if isinstance(child, dict):
                depths.extend(_schema_depths(child, depth + 1))
            elif isinstance(child, list):
                depths.extend(
                    d for item in child if isinstance(item, dict) for d in _schema_depths(item, depth + 1)
                )
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            children = node.get(key)
            if isinstance(children, list):
                depths.extend(
                    d for item in children if isinstance(item, dict) for d in _schema_depths(item, depth + 1)
                )
    return depths


def _count_props(node) -> int:
    count = 0
    if isinstance(node, dict):
        if "properties" in node and isinstance(node["properties"], dict):
            count += len(node["properties"])
        count += sum(_count_props(value) for value in node.values())
    elif isinstance(node, list):
        count += sum(_count_props(value) for value in node)
    return count


def _count_refs(node) -> int:
    count = 0
    if isinstance(node, dict):
        count += sum(1 for key in node if key == "$ref")
        count += sum(_count_refs(value) for value in node.values())
    elif isinstance(node, list):
        count += sum(_count_refs(value) for value in node)
    return count


def test_lite_wire_schema_size_shape_and_refs():
    serialized = json.dumps(LITE_WIRE_SCHEMA)
    assert len(serialized) < 4096, f"lite schema must stay under 4KB, got {len(serialized)}"
    assert "$defs" not in LITE_WIRE_SCHEMA and "definitions" not in LITE_WIRE_SCHEMA
    assert _count_refs(LITE_WIRE_SCHEMA) == 0
    assert max(_schema_depths(LITE_WIRE_SCHEMA)) < 6
    assert _count_props(LITE_WIRE_SCHEMA) < 100
    for capability_id in (
        "subject.isolate",
        "background.blur",
        "background.replace",
        "audio.preserve",
        "video.render_mp4",
        "output.verify",
    ):
        assert capability_id in serialized


def test_lite_wire_schema_pins_capability_param_enums():
    """The wire schema must advertise the same enums the strict models accept.

    A free-form `strategy` string let the model copy prompt wording
    ("mock segmentation") straight into params.strategy, which then failed
    strict validation after the paid call.
    """
    params = LITE_WIRE_SCHEMA["properties"]["operations"]["items"]["properties"]["params"]
    assert params["properties"]["strategy"]["enum"] == [
        "largest_subject",
        "named_subject",
        "foreground",
    ]
    assert params["properties"]["asset_source"]["enum"] == ["local_asset", "mock_generated"]
    assert params["properties"]["composition"]["enum"] == ["centered", "rule_of_thirds"]


def test_lite_payload_budget_developer_under_8k_total_under_9k():
    transcript_text = "Keep me sharp, blur the people behind me and replace the background with a cinematic Luanda sunset."
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        calls["developer_chars"] = len(body["messages"][0]["content"])
        calls["user_chars"] = len(body["messages"][1]["content"])
        calls["payload_chars"] = len(request.content.decode())
        calls["schema_chars"] = len(json.dumps(body["response_format"]["json_schema"]["schema"]))
        raise AssertionError("not reached: validation of budget only")

    provider = LiteMetaEditingDirectorProvider(
        "test-key",
        LITE_BRIEF,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=800,
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"),
    )
    with pytest.raises(AssertionError, match="not reached"):
        provider.create_plan(
            transcript(transcript_text), authorization=_TestAuthorization()
        )
    assert calls["developer_chars"] < 8000, f"developer prompt {calls['developer_chars']} chars >= 8k"
    assert calls["payload_chars"] < 9216, f"total payload {calls['payload_chars']} chars >= 9k"
    assert calls["schema_chars"] < 4096


def test_lite_to_full_conversion_matches_mock_plan():
    director = MockProfessionalEditingDirector()
    full = director.create_plan(transcript("Keep me sharp and blur everything behind me."))
    lite_payload = {
        "request_id": full.request_id,
        "raw_instruction": full.raw_instruction,
        "interpreted_intention": full.interpreted_intention,
        "outcome": "plan_ready",
        "subject_description": full.subject.description,
        "subject_is_ambiguous": False,
        "clarification_question": "",
        "preserve_audio": True,
        "operations": [
            {
                "operation_id": op.operation_id,
                "capability_id": op.capability_id,
                "title": op.title,
                "explanation": op.explanation,
                "params": op.params.model_dump(mode="json"),
                "dependencies": list(op.dependencies),
                "expected_output": op.expected_output,
            }
            for op in full.operations
        ],
        "summary_explanation": full.summary_explanation,
        "clarification_questions": [],
        "unsupported_capabilities": [],
        "approval_status": full.approval_status.value,
    }
    lite = LitePlan.model_validate(lite_payload)
    converted = lite_to_full_plan(lite)
    assert converted.outcome == PlanOutcome.PLAN_READY
    assert [op.capability_id for op in converted.operations] == [op.capability_id for op in full.operations]
    assert converted.to_execution_plan().intent == full.to_execution_plan().intent


def test_lite_clarification_with_clear_subject_is_accepted():
    """Regression for the live job that asked about the background intent.

    The model returned needs_clarification with subject_is_ambiguous=false;
    the lite plan is valid and the v1 adapter still marks the clarification.
    """
    question = "Que fundo devo usar no lugar do original?"
    payload = {
        "request_id": "req_clarify0001",
        "raw_instruction": "Muda todo o fundo e mantém só o senhor de blazer preto.",
        "interpreted_intention": "Replace the background and keep the man in the black blazer sharp.",
        "outcome": "needs_clarification",
        "subject_description": "the man in the black blazer",
        "subject_is_ambiguous": False,
        "clarification_question": "",
        "preserve_audio": True,
        "operations": [],
        "summary_explanation": "The background change is broad; confirm the intended look.",
        "clarification_questions": [question],
        "unsupported_capabilities": [],
        "approval_status": "not_required",
    }
    plan = lite_to_full_plan(LitePlan.model_validate(payload))
    assert plan.outcome is PlanOutcome.NEEDS_CLARIFICATION
    assert plan.subject.is_ambiguous is False
    assert plan.clarification_questions == [question]

    v1 = plan.to_execution_plan()
    assert v1.intent is EditingIntent.CLARIFICATION_NEEDED
    assert v1.subject.is_ambiguous is True
    assert v1.subject.clarification_question == question


def test_lite_provider_roundtrip_single_post_contributor_cost():
    text = "Keep me sharp and blur everything behind me."
    director = MockProfessionalEditingDirector()
    full = director.create_plan(transcript(text))
    lite_json = {
        "request_id": full.request_id,
        "raw_instruction": full.raw_instruction,
        "interpreted_intention": full.interpreted_intention,
        "outcome": "plan_ready",
        "subject_description": full.subject.description,
        "subject_is_ambiguous": False,
        "clarification_question": "",
        "preserve_audio": True,
        "operations": [
            {
                "operation_id": op.operation_id,
                "capability_id": op.capability_id,
                "title": op.title,
                "explanation": op.explanation,
                "params": op.params.model_dump(mode="json"),
                "dependencies": list(op.dependencies),
                "expected_output": op.expected_output,
            }
            for op in full.operations
        ],
        "summary_explanation": full.summary_explanation,
        "clarification_questions": [],
        "unsupported_capabilities": [],
        "approval_status": full.approval_status.value,
    }
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content.decode())
        assert body["model"] == "muse-spark-1.3-contributor"
        assert body["reasoning_effort"] == "medium"
        assert body["max_completion_tokens"] == 800
        assert body["response_format"]["json_schema"]["name"] == "ProfessionalEditingPlanLite"
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-lite",
                "object": "chat.completion",
                "model": "muse-spark-1.3-contributor",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(lite_json)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1500, "completion_tokens": 600, "total_tokens": 2100},
            },
        )

    provider = LiteMetaEditingDirectorProvider(
        "test-key",
        LITE_BRIEF,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=800,
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"),
    )
    plan = provider.create_plan(transcript(text), authorization=_TestAuthorization())
    assert calls["n"] == 1
    assert plan.outcome == PlanOutcome.PLAN_READY
    assert plan.approval_status.value == "not_required"
    assert provider.last_usage is not None
    assert provider.last_usage.prompt_tokens == 1500
    # Contributor rates: 1500*0.10/1e6 + 600*0.20/1e6 = 0.00015 + 0.00012
    assert provider.last_usage.cost_usd == pytest.approx(0.00027)
    assert provider.last_audit is not None
    assert provider.last_audit.wire_schema == "lite"
    assert provider.last_audit.service_mode == "contributor"
    assert provider.last_audit.validation_status == "accepted"


def test_full_capability_summary_still_available_for_audit():
    summary = capability_summary_for_prompt()
    assert "subject.isolate" in summary
    assert len(summary) > len(lite_capability_summary())


def test_lite_provider_1500_cap_payload():
    provider = LiteMetaEditingDirectorProvider(
        "test-key",
        LITE_BRIEF,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=1500,
    )
    payload, _ = provider.request_payload(transcript("Keep me sharp and blur the background."), None)
    assert payload["max_completion_tokens"] == 1500
    assert payload["model"] == "muse-spark-1.3-contributor"
    assert payload["reasoning_effort"] == "medium"
    assert payload["response_format"]["json_schema"]["name"] == "ProfessionalEditingPlanLite"


# --- Operation-id normalisation (6B-LIVE-HARDENING) --------------------------


def _lite_payload_with_ids(text: str, ids: list[str]):
    """Build a valid lite payload from the mock plan, replacing operation ids."""
    full = MockProfessionalEditingDirector().create_plan(transcript(text))
    original_ids = [op.operation_id for op in full.operations]
    assert len(ids) == len(original_ids)
    id_map = {original: replacement for original, replacement in zip(original_ids, ids)}
    operations = []
    for op in full.operations:
        operations.append(
            {
                "operation_id": id_map[op.operation_id],
                "capability_id": op.capability_id,
                "title": op.title,
                "explanation": op.explanation,
                "params": op.params.model_dump(mode="json"),
                "dependencies": [id_map[dependency] for dependency in op.dependencies],
                "expected_output": op.expected_output,
            }
        )
    payload = {
        "request_id": full.request_id,
        "raw_instruction": full.raw_instruction,
        "interpreted_intention": full.interpreted_intention,
        "outcome": "plan_ready",
        "subject_description": full.subject.description,
        "subject_is_ambiguous": False,
        "clarification_question": "",
        "preserve_audio": True,
        "operations": operations,
        "summary_explanation": full.summary_explanation,
        "clarification_questions": [],
        "unsupported_capabilities": [],
        "approval_status": full.approval_status.value,
    }
    return payload, full


def test_operation_ids_are_canonicalised_in_order_and_dependencies_rewritten():
    text = "Keep me sharp and blur the background."
    ids = ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"]
    payload, full = _lite_payload_with_ids(text, ids)
    plan, id_map = lite_to_full_plan_with_mapping(LitePlan.model_validate(payload))

    assert id_map == {
        "op1_isolate": "op_1",
        "op2_blur": "op_2",
        "op3_audio": "op_3",
        "op4_render": "op_4",
        "op5_verify": "op_5",
    }
    assert [op.operation_id for op in plan.operations] == ["op_1", "op_2", "op_3", "op_4", "op_5"]
    assert plan.operations[1].dependencies == ["op_1"]
    assert plan.operations[3].dependencies == ["op_1", "op_2", "op_3"]
    assert plan.operations[4].dependencies == ["op_4"]
    assert [op.capability_id for op in plan.operations] == [
        op.capability_id for op in full.operations
    ]
    assert [op.params.model_dump(mode="json") for op in plan.operations] == [
        op.params.model_dump(mode="json") for op in full.operations
    ]
    assert plan.to_execution_plan().intent == full.to_execution_plan().intent


def test_canonical_and_mixed_ids_are_normalised_deterministically():
    text = "Keep me sharp and blur the background."

    canonical_payload, _ = _lite_payload_with_ids(
        text, ["op_1", "op_2", "op_3", "op_4", "op_5"]
    )
    canonical, canonical_map = lite_to_full_plan_with_mapping(
        LitePlan.model_validate(canonical_payload)
    )
    assert canonical_map == {
        "op_1": "op_1",
        "op_2": "op_2",
        "op_3": "op_3",
        "op_4": "op_4",
        "op_5": "op_5",
    }
    assert [op.operation_id for op in canonical.operations] == [
        "op_1",
        "op_2",
        "op_3",
        "op_4",
        "op_5",
    ]

    mixed_payload, _ = _lite_payload_with_ids(
        text, ["isolate", "op_2", "AudioStep", "render_4", "verify_5"]
    )
    mixed, mixed_map = lite_to_full_plan_with_mapping(LitePlan.model_validate(mixed_payload))
    assert mixed_map == {
        "isolate": "op_1",
        "op_2": "op_2",
        "AudioStep": "op_3",
        "render_4": "op_4",
        "verify_5": "op_5",
    }
    assert [op.operation_id for op in mixed.operations] == [
        "op_1",
        "op_2",
        "op_3",
        "op_4",
        "op_5",
    ]
    assert mixed.operations[1].dependencies == ["op_1"]


def test_duplicate_original_operation_ids_are_rejected():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["duplicate", "duplicate", "op3", "op4", "op5"],
    )
    lite = LitePlan.model_validate(payload)
    with pytest.raises(ValueError, match="Duplicate operation id"):
        lite_to_full_plan(lite)


def test_unknown_dependency_is_rejected():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    payload["operations"][1]["dependencies"] = ["missing_operation"]
    with pytest.raises(ValueError, match="unknown operation"):
        lite_to_full_plan(LitePlan.model_validate(payload))


def test_dependency_cycle_is_rejected():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    payload["operations"][0]["dependencies"] = ["op2_blur"]
    payload["operations"][1]["dependencies"] = ["op1_isolate"]
    with pytest.raises(ValueError, match="Dependency cycle"):
        lite_to_full_plan(LitePlan.model_validate(payload))


def test_forward_dependency_is_rejected():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    payload["operations"][0]["dependencies"] = ["op2_blur"]
    payload["operations"][1]["dependencies"] = []
    with pytest.raises(ValueError, match="must appear earlier"):
        lite_to_full_plan(LitePlan.model_validate(payload))


def test_invalid_capability_id_is_rejected():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    payload["operations"][0]["capability_id"] = "transition.apply"
    with pytest.raises(ValidationError):
        LitePlan.model_validate(payload)


def test_full_v2_contract_still_rejects_non_canonical_ids():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    plan = lite_to_full_plan(LitePlan.model_validate(payload))
    operation = plan.operations[0].model_dump(mode="json")
    operation["operation_id"] = "op1_isolate"
    with pytest.raises(ValidationError):
        DirectorOperation.model_validate(operation)


def test_invalid_operation_parameters_are_rejected():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    payload["operations"][1]["params"]["strength"] = 99.0
    lite = LitePlan.model_validate(payload)
    with pytest.raises(ValidationError):
        lite_to_full_plan(lite)


def test_provenance_hashes_are_recomputed_after_canonicalisation():
    payload, _ = _lite_payload_with_ids(
        "Keep me sharp and blur the background.",
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    plan = lite_to_full_plan(LitePlan.model_validate(payload))
    edl = edl_from_professional_plan(plan)

    assert [decision.operation_id for decision in edl.decisions] == [
        "op_1",
        "op_2",
        "op_3",
        "op_4",
        "op_5",
    ]
    for decision in edl.decisions:
        decision.verify_provenance(edl_id=edl.edl_id, request_id=edl.request_id)
        assert decision.provenance_hash == compute_decision_hash(
            edl_id=edl.edl_id,
            request_id=edl.request_id,
            decision=decision,
        )


def test_lite_provider_normalises_model_ids_and_audits_the_call():
    text = "Keep me sharp and blur the background."
    calls = {"n": 0}
    response_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            headers={"x-request-id": "srv-lite-normalised"},
            json={
                "id": "chatcmpl-lite-normalised",
                "object": "chat.completion",
                "model": "muse-spark-1.3-contributor",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(response_payload),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2781, "completion_tokens": 1856, "total_tokens": 4637},
            },
        )

    provider = LiteMetaEditingDirectorProvider(
        "test-key",
        LITE_BRIEF,
        lite_capability_summary(),
        model="muse-spark-1.3-contributor",
        reasoning_effort="medium",
        require_contributor=True,
        max_output_tokens=16000,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"
        ),
    )
    _, expected_request_id = provider.request_payload(transcript(text), None)
    payload, _ = _lite_payload_with_ids(
        text,
        ["op1_isolate", "op2_blur", "op3_audio", "op4_render", "op5_verify"],
    )
    payload["request_id"] = expected_request_id
    payload["raw_instruction"] = text
    response_payload.update(payload)

    plan = provider.create_plan(
        transcript(text),
        request_id=expected_request_id,
        authorization=_TestAuthorization(),
    )

    assert calls["n"] == 1
    assert [op.operation_id for op in plan.operations] == [
        "op_1",
        "op_2",
        "op_3",
        "op_4",
        "op_5",
    ]
    assert plan.operations[1].dependencies == ["op_1"]
    audit = provider.last_audit
    assert audit is not None
    assert audit.validation_status == "accepted"
    assert audit.wire_schema == "lite"
    assert audit.service_mode == "contributor"
    assert audit.server_request_id == "srv-lite-normalised"
    assert (audit.prompt_tokens, audit.completion_tokens) == (2781, 1856)
    assert audit.estimated_cost_usd == pytest.approx(0.000649)
    assert audit.actual_cost_usd is None
