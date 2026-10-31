"""Meta Muse Spark director provider tests — mocked transport only.

No request leaves the machine: every test injects httpx.MockTransport and asserts
exactly one POST per create_plan (no retries, no tool execution).
"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from clipforge_contracts import PlanOutcome, TranscriptResult, capability_summary_for_prompt
from clipforge_director import MockProfessionalEditingDirector
from clipforge_director.spark import (
    CHAT_COMPLETIONS_PATH,
    DEFAULT_MODEL,
    DirectorAPIError,
    DirectorRateLimitedError,
    DirectorTimeoutError,
    DirectorValidationError,
    DirectorVideoMetadata,
    InvalidModelError,
    MetaEditingDirectorProvider,
    MissingCredentialsError,
    calculate_cost_usd,
    estimate_tokens,
)

PLAYBOOK = "Test playbook. Follow the capability registry. Emit v2 JSON only."
SUMMARY = capability_summary_for_prompt()


def transcript(text: str) -> TranscriptResult:
    return TranscriptResult(text=text, language="pt-BR", provider_name="t", is_mock=True)


def video_meta() -> DirectorVideoMetadata:
    return DirectorVideoMetadata(
        width=1280, height=720, fps=30.0, duration_seconds=10.0, frame_count=300, has_audio=True
    )


def mock_plan_json(text: str) -> dict:
    plan = MockProfessionalEditingDirector().create_plan(transcript(text))
    assert plan.outcome == PlanOutcome.PLAN_READY
    return plan.model_dump(mode="json")


def provider(handler, **kwargs) -> MetaEditingDirectorProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
    defaults = dict(
        api_key="test-key",
        playbook_text=PLAYBOOK,
        capability_summary=SUMMARY,
    )
    defaults.update(kwargs)
    return MetaEditingDirectorProvider(client=client, **defaults)


def ok_response(plan_json: dict, usage: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": DEFAULT_MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(plan_json)},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        },
    )


def test_missing_credentials_and_contributor_rejected():
    with pytest.raises(MissingCredentialsError):
        MetaEditingDirectorProvider(api_key="  ", playbook_text=PLAYBOOK, capability_summary=SUMMARY)
    with pytest.raises(InvalidModelError):
        MetaEditingDirectorProvider(
            api_key="k", playbook_text=PLAYBOOK, capability_summary=SUMMARY, model="muse-spark-1.3-contributor"
        )


def test_init_makes_no_request():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={})

    provider(handler)
    assert calls["n"] == 0


def test_request_contract_and_single_call():
    text = "Keep me sharp and blur the background."
    plan_json = mock_plan_json(text)
    captured: dict = {}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        body = json.loads(request.content.decode())
        captured["body"] = body
        return ok_response(plan_json)

    result = provider(handler).create_plan(transcript(text), video_meta())

    assert calls["n"] == 1
    assert captured["method"] == "POST"
    assert captured["url"] == f"https://api.meta.ai{CHAT_COMPLETIONS_PATH}"
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert body["model"] == DEFAULT_MODEL
    assert body["max_completion_tokens"] == 1500
    assert [m["role"] for m in body["messages"]] == ["developer", "user"]
    assert "tools" not in body
    assert "web_search" not in json.dumps(body)
    # No raw audio: messages are plain text; no audio content blocks or encodings.
    assert "input_audio" not in json.dumps(body)
    assert "base64" not in json.dumps(body).lower()
    for message in body["messages"]:
        assert isinstance(message["content"], str)
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "ProfessionalEditingPlan"
    assert fmt["json_schema"]["strict"] is False
    assert "ProfessionalEditingPlan" in json.dumps(fmt["json_schema"]["schema"])
    user_content = body["messages"][1]["content"]
    assert text in user_content
    assert result.outcome == PlanOutcome.PLAN_READY
    assert result.raw_instruction == text


def test_no_audio_bytes_in_request():
    text = "Keep me sharp and blur the background."
    plan_json = mock_plan_json(text)

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"RIFF" not in request.content
        assert b"base64" not in request.content.lower()
        return ok_response(plan_json)

    provider(handler).create_plan(transcript(text))


def test_clarification_plan_passes_through():
    text = "Make my video more professional."
    vague = MockProfessionalEditingDirector().create_plan(transcript(text))
    assert vague.outcome == PlanOutcome.NEEDS_CLARIFICATION

    def handler(request: httpx.Request) -> httpx.Response:
        return ok_response(vague.model_dump(mode="json"))

    result = provider(handler).create_plan(transcript(text))
    assert result.outcome == PlanOutcome.NEEDS_CLARIFICATION
    assert result.operations == []
    assert result.clarification_questions


def test_unsupported_capability_rejected():
    text = "Keep me sharp and blur the background."
    plan_json = mock_plan_json(text)
    plan_json["operations"][1]["capability_id"] = "transition.apply"

    def handler(request: httpx.Request) -> httpx.Response:
        return ok_response(plan_json)

    with pytest.raises(DirectorValidationError):
        provider(handler).create_plan(transcript(text))


def test_malformed_outputs_rejected():
    text = "Keep me sharp and blur the background."
    good = mock_plan_json(text)

    cases = {
        "invalid_json": "{not json",
        "schema_violation": {**good, "operations": []},
        "wrong_request_id": {**good, "request_id": "req_deadbeefcafe"},
        "raw_mismatch": {**good, "raw_instruction": "something else entirely"},
    }
    for name, payload in cases.items():
        content = payload if isinstance(payload, str) else json.dumps(payload)

        def handler(request: httpx.Request, content=content) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "x",
                    "object": "chat.completion",
                    "model": DEFAULT_MODEL,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                },
            )

        with pytest.raises(DirectorValidationError):  # case: {name}
            provider(handler).create_plan(transcript(text))

    def truncated(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "model": DEFAULT_MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(good)}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    with pytest.raises(DirectorValidationError):
        provider(truncated).create_plan(transcript(text))

    def tool_calls(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "model": DEFAULT_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    with pytest.raises(DirectorValidationError):
        provider(tool_calls).create_plan(transcript(text))


def test_timeout_rate_limit_and_api_errors_no_retry():
    text = "Keep me sharp and blur the background."
    calls = {"n": 0}

    def timeout(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DirectorTimeoutError):
        provider(timeout, timeout_seconds=2).create_plan(transcript(text))
    assert calls["n"] == 1

    def rate_limited(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "slow down", "type": "rate_limit"}})

    with pytest.raises(DirectorRateLimitedError) as exc:
        provider(rate_limited).create_plan(transcript(text))
    assert exc.value.retry_after == "2"
    assert calls["n"] == 2

    def server_error(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": {"message": "boom", "type": "server_error"}})

    with pytest.raises(DirectorAPIError) as exc:
        provider(server_error, api_key="super-secret").create_plan(transcript(text))
    assert exc.value.status_code == 500
    assert "super-secret" not in str(exc.value)
    assert calls["n"] == 3


def test_token_accounting_and_estimate():
    assert estimate_tokens("abcd" * 100) == 100
    assert calculate_cost_usd(1000, 500) == pytest.approx(0.003375)

    text = "Keep me sharp and blur the background."
    plan_json = mock_plan_json(text)

    def handler(request: httpx.Request) -> httpx.Response:
        return ok_response(plan_json, usage={"prompt_tokens": 2000, "completion_tokens": 400, "total_tokens": 2400})

    instance = provider(handler)
    instance.create_plan(transcript(text))
    assert instance.last_usage is not None
    assert instance.last_usage.prompt_tokens == 2000
    assert instance.last_usage.completion_tokens == 400
    assert instance.last_usage.cost_usd == pytest.approx(calculate_cost_usd(2000, 400))


def test_exactly_one_request_even_on_validation_failure():
    text = "Keep me sharp and blur the background."
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "nope"}, "finish_reason": "stop"}]})

    with pytest.raises(DirectorValidationError):
        provider(handler).create_plan(transcript(text))
    assert calls["n"] == 1


def test_mock_path_makes_zero_external_calls(monkeypatch):
    real_create = socket.create_connection

    def blocked(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "create_connection", blocked)
    MockProfessionalEditingDirector().create_plan(transcript("Keep me sharp and blur the background."))
    monkeypatch.setattr(socket, "create_connection", real_create)
