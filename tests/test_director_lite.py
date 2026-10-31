"""ProfessionalEditingPlan v2-lite contract tests (LIVE-CALL 003 prep, mocked only)."""

from __future__ import annotations

import json

import httpx
import pytest

from clipforge_contracts import PlanOutcome, TranscriptResult, capability_summary_for_prompt
from clipforge_contracts.director_lite import (
    LITE_BRIEF,
    LITE_WIRE_SCHEMA,
    LitePlan,
    lite_capability_summary,
    lite_to_full_plan,
)
from clipforge_director import LiteMetaEditingDirectorProvider, MockProfessionalEditingDirector


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
        provider.create_plan(transcript(transcript_text))
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
    plan = provider.create_plan(transcript(text))
    assert calls["n"] == 1
    assert plan.outcome == PlanOutcome.PLAN_READY
    assert plan.approval_status.value == "not_required"
    assert provider.last_usage is not None
    assert provider.last_usage.prompt_tokens == 1500
    # Contributor rates: 1500*0.10/1e6 + 600*0.20/1e6 = 0.00015 + 0.00012
    assert provider.last_usage.cost_usd == pytest.approx(0.00027)


def test_full_capability_summary_still_available_for_audit():
    summary = capability_summary_for_prompt()
    assert "subject.isolate" in summary
    assert len(summary) > len(lite_capability_summary())
