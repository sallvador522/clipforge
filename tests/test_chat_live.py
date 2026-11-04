"""Live chat rewrite via Muse Spark (ADR-053).

Mock (default) keeps the deterministic router with zero side effects.
Live reuses the verified Chat Completions contract: one POST, one `chat`
ledger slot, no retries. The router still decides intent/pending — the
model only rewrites `reply`. All transport here is httpx MockTransport;
no request may reach api.meta.ai.
"""

import json

import httpx
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_director.chat import SparkChatAssistant
from clipforge_director.ledger import LiveCallBudget, LiveCallNotAuthorizedError
from clipforge_jobs import JobStore
from clipforge_providers import get_providers
from clipforge_worker.worker_process import PersistentWorker


def _mock_client(reply_text: str, *, in_tokens: int = 120, out_tokens: int = 25) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers.get("authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode())
        assert body["model"] == "muse-spark-1.3-contributor"
        assert body["reasoning_effort"] == "minimal"
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": reply_text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": in_tokens, "completion_tokens": out_tokens,
                           "total_tokens": in_tokens + out_tokens},
            },
            headers={"x-request-id": "chat-test-1"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")


def _live_client(tmp_path, reply_text: str, **kwargs):
    providers = get_providers("mock")

    def factory():
        return SparkChatAssistant("test-key", client=_mock_client(reply_text), **kwargs)

    return TestClient(
        create_app(storage_root=tmp_path / "storage", providers=providers,
                   chat_provider_factory=factory)
    )


def _mock_client_only(tmp_path):
    store = JobStore(tmp_path / "storage")
    providers = get_providers("mock")
    client = TestClient(create_app(storage_root=tmp_path / "storage", providers=providers))
    worker = PersistentWorker(store, providers, poll_seconds=0.05)
    return client, store, worker


def test_chat_mock_marks_chat_mode_mock_without_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CHAT_MODE", "mock")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client, _, _ = _mock_client_only(tmp_path)
    resp = client.post("/api/chat", json={"message": "ola"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "smalltalk"
    assert body["chat_mode"] == "mock"
    assert not (tmp_path / "storage" / "live-call-ledger.json").exists()


def test_chat_live_rewrites_greeting_preserving_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CHAT_MODE", "live")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    client = _live_client(tmp_path, "Olá! Eu trato do resto — queres editar o clipe ou criar um vídeo novo?")
    before = LiveCallBudget(tmp_path / "storage").used("chat")
    resp = client.post("/api/chat", json={"message": "ola"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "smalltalk"
    assert body["needs_confirmation"] is False
    assert body["reply"].startswith("Olá! Eu trato")
    assert body["chat_mode"] == "live"
    assert body["chat_usage"]["prompt_tokens"] == 120
    assert body["chat_usage"]["completion_tokens"] == 25
    assert body["chat_usage"]["cost_usd"] > 0
    assert LiveCallBudget(tmp_path / "storage").used("chat") == before + 1


def test_chat_live_keeps_interview_slots_and_proposal_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CHAT_MODE", "live")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    client = _live_client(tmp_path, "Que estilo queres para o vídeo? Escolhe um chip.")
    resp = client.post("/api/chat", json={"message": "cria um video sobre o mar"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "idea_interview"
    assert body["interview"]["needed"] == ["style"]
    assert body["needs_confirmation"] is False
    assert body["chat_mode"] == "live"
    # Model rewrote the words but the gate data is untouched.
    assert "chip" in body["reply"].lower()


def test_chat_live_requires_key_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CHAT_MODE", "live")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client, _, _ = _mock_client_only(tmp_path)
    resp = client.post("/api/chat", json={"message": "ola"})
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "chat_not_configured"


def test_chat_live_empty_model_reply_is_502(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CHAT_MODE", "live")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
        )

    providers = get_providers("mock")

    def factory():
        return SparkChatAssistant(
            "test-key",
            client=httpx.Client(transport=httpx.MockTransport(handler),
                                base_url="https://api.meta.ai"),
        )

    client = TestClient(
        create_app(storage_root=tmp_path / "storage", providers=providers,
                   chat_provider_factory=factory)
    )
    resp = client.post("/api/chat", json={"message": "ola"})
    assert resp.status_code == 502, resp.text
    assert resp.json()["error"]["code"] == "chat_live_failed"


def test_chat_provider_requires_authorization():
    assistant = SparkChatAssistant("k", client=_mock_client("oi"))
    try:
        assistant.rewrite_reply(message="ola", base_reply="Olá!",
                                intent="smalltalk", has_clip=False,
                                authorization=None)
    except LiveCallNotAuthorizedError:
        return
    raise AssertionError("expected LiveCallNotAuthorizedError")
