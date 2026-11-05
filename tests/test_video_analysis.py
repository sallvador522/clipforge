"""Native video understanding (ADR-057).

Offline only: deterministic mock + httpx MockTransport providers.
No paid calls: every live path is exercised against mocked transports,
exactly one POST per billable step, no retries.
"""

import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_director.ledger import LiveCallBudget
from clipforge_providers import get_providers
from clipforge_providers.video_analysis import (
    SparkVideoAnalysisProvider,
    VideoAnalysisAPIError,
    VideoAnalysisMissingCredentialsError,
    VideoAnalysisNotAuthorizedError,
    VideoAnalysisRateLimitedError,
    VideoAnalysisValidationError,
    parse_analysis_sections,
    prepare_analysis_copy,
)


SAMPLE_ANALYSIS = """RESUMO: Um cão castanho corre num parque ao pôr-do-sol.
ACONTECE: O cão corre. Depois para junto a uma árvore.
ELEMENTOS:
- um cão castanho de porte médio
- relva verde e uma árvore grande
MOMENTOS:
- 00:01 - o cão entra a correr
- 00:04 - o cão para junto à árvore
OBSERVACOES:
- luz quente lateral
MELHORIAS:
- desfocar ligeiramente o fundo para destacar o cão
INCERTEZAS:
- a raça exacta não é clara
"""


def _mock_client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"
    )


def _responses_body(text=SAMPLE_ANALYSIS, *, in_tokens=900, out_tokens=120):
    return {
        "id": "resp_test123",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": in_tokens + out_tokens,
        },
    }


# -- section parser -----------------------------------------------------------

def test_parse_full_sections():
    parsed = parse_analysis_sections(SAMPLE_ANALYSIS)
    assert parsed["overall_summary"].startswith("Um cão castanho")
    assert parsed["subjects"] == []
    assert any("cão" in o for o in parsed["objects_seen"])
    assert parsed["moments"][0]["at_s"] == 1
    assert parsed["moments"][1]["at_s"] == 4
    assert all(m["approximate"] for m in parsed["moments"])
    assert parsed["composition_observations"] == ["luz quente lateral"]
    assert len(parsed["editing_opportunities"]) == 1
    assert len(parsed["uncertainties"]) == 1


def test_parse_empty_and_garbage_never_invents():
    parsed = parse_analysis_sections("")
    assert parsed["overall_summary"] is None
    assert parsed["moments"] == []
    assert parsed["editing_opportunities"] == []
    parsed = parse_analysis_sections("bla bla\n12345\n???")
    assert parsed["overall_summary"] is None
    assert parsed["subjects"] == []


def test_parse_truncates_long_lists():
    many = "ELEMENTOS:\n" + "\n".join(f"- coisa {i}" for i in range(50))
    parsed = parse_analysis_sections(many)
    assert len(parsed["objects_seen"]) <= 20


# -- provider with mocked transport -------------------------------------------

def test_provider_sends_reasoning_effort_minimal(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_responses_body())

    from clipforge_director.ledger import LiveCallAuthorization, LiveCallBudget
    import tempfile

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    with tempfile.TemporaryDirectory() as tmp:
        budget = LiveCallBudget(tmp)
        auth = LiveCallAuthorization(budget, "video_analysis")
        provider.analyze_file(
            file_id="file-1", instruction="Descreve.", authorization=auth
        )
    assert seen["body"]["reasoning"] == {"effort": "minimal"}
    assert seen["body"]["max_output_tokens"] == 2000
    provider.close()


def test_provider_rejects_unknown_reasoning_effort():
    with pytest.raises(ValueError):
        SparkVideoAnalysisProvider("test-key", reasoning_effort="ultra")


def test_provider_upload_then_analyze_one_post_each(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"id": "file-123"})
        return httpx.Response(200, json=_responses_body())

    from clipforge_director.ledger import LiveCallAuthorization

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00" * 64)
    file_id = provider.upload_file(clip)
    assert file_id == "file-123"
    budget = LiveCallBudget(tmp_path / "storage")
    auth = LiveCallAuthorization(budget, "video_analysis")
    text, usage = provider.analyze_file(
        file_id=file_id, instruction="Descreve.", authorization=auth
    )
    assert "cão" in text
    assert usage.prompt_tokens == 900
    assert usage.cost_usd == round(900 * 0.10 / 1_000_000 + 120 * 0.20 / 1_000_000, 6)
    assert usage.response_id == "resp_test123"
    assert calls == ["/v1/files", "/v1/responses"]
    assert budget.used("video_analysis") == 1
    provider.close()


def test_provider_rejects_tool_calls_and_empty_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_responses_body(text="   "))

    from clipforge_director.ledger import LiveCallAuthorization, LiveCallBudget
    import tempfile

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    with tempfile.TemporaryDirectory() as tmp:
        budget = LiveCallBudget(tmp)
        auth = LiveCallAuthorization(budget, "video_analysis")
        with pytest.raises(VideoAnalysisAPIError):
            provider.analyze_file(
                file_id="file-1", instruction="x", authorization=auth
            )
    provider.close()


def test_provider_requires_authorization_before_network():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_responses_body())

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    with pytest.raises(VideoAnalysisNotAuthorizedError):
        provider.analyze_file(
            file_id="file-1", instruction="x", authorization=None
        )
    assert calls == []
    provider.close()


def test_provider_sends_section_rules_in_request():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_responses_body())

    from clipforge_director.ledger import LiveCallAuthorization, LiveCallBudget
    import tempfile

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    with tempfile.TemporaryDirectory() as tmp:
        budget = LiveCallBudget(tmp)
        auth = LiveCallAuthorization(budget, "video_analysis")
        provider.analyze_file(
            file_id="file-1", instruction="Descreve.", authorization=auth
        )
    user_text = seen["body"]["input"][0]["content"][0]["text"]
    assert "RESUMO:" in user_text and "MELHORIAS:" in user_text
    assert seen["body"]["reasoning"] == {"effort": "minimal"}
    provider.close()


def test_provider_no_retry_on_server_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "boom"})

    from clipforge_director.ledger import LiveCallAuthorization, LiveCallBudget
    import tempfile

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    with tempfile.TemporaryDirectory() as tmp:
        budget = LiveCallBudget(tmp)
        auth = LiveCallAuthorization(budget, "video_analysis")
        with pytest.raises(VideoAnalysisAPIError):
            provider.analyze_file(
                file_id="file-1", instruction="x", authorization=auth
            )
    assert len(calls) == 1
    provider.close()


def test_provider_missing_key_before_network():
    with pytest.raises(VideoAnalysisMissingCredentialsError):
        SparkVideoAnalysisProvider("   ")


def test_provider_rate_limited_maps_to_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    from clipforge_director.ledger import LiveCallAuthorization, LiveCallBudget
    import tempfile

    provider = SparkVideoAnalysisProvider(
        "test-key", client=_mock_client(handler)
    )
    with tempfile.TemporaryDirectory() as tmp:
        budget = LiveCallBudget(tmp)
        auth = LiveCallAuthorization(budget, "video_analysis")
        with pytest.raises(VideoAnalysisRateLimitedError):
            provider.analyze_file(
                file_id="file-1", instruction="x", authorization=auth
            )
    provider.close()


# -- normalization (real ffmpeg, tiny fixture) ---------------------------------

def _make_clip(path, *, duration=2, size="64x36", fps=10):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("ffmpeg could not generate test clip")


def test_prepare_analysis_copy_strips_audio_keeps_frames(tmp_path):
    src = tmp_path / "src.mp4"
    _make_clip(src)
    out = tmp_path / "analysis.mp4"
    meta = prepare_analysis_copy(src, out)
    assert meta["width"] == 64 and meta["height"] == 36
    assert out.is_file()
    import json as _json

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        capture_output=True, text=True,
    )
    streams = _json.loads(probe.stdout)["streams"]
    assert all(s["codec_type"] != "audio" for s in streams)


def test_prepare_analysis_copy_rejects_non_video(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("not a video")
    with pytest.raises(VideoAnalysisValidationError):
        prepare_analysis_copy(target, tmp_path / "out.mp4")


# -- API endpoints (mock mode default) -----------------------------------------

def _client(tmp_path, **kwargs):
    providers = get_providers("mock")
    client = TestClient(
        create_app(storage_root=tmp_path / "storage", providers=providers, **kwargs)
    )
    return client


def _project_with_video_asset(client, tmp_path, name="clip.mp4"):
    project = client.post("/api/projects", json={"title": "Vis"}).json()
    pid = project["project_id"]
    src = tmp_path / name
    _make_clip(src)
    with open(src, "rb") as fh:
        uploaded = client.post(
            f"/api/projects/{pid}/assets", files={"file": (name, fh, "video/mp4")}
        )
    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    return pid, asset["asset_id"]


def test_analyze_mock_mode_zero_cost_no_ledger(tmp_path):
    client = _client(tmp_path)
    pid, aid = _project_with_video_asset(client, tmp_path)
    resp = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"instruction": "Descreve.", "approved_cost_usd": 0.10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["video_mode"] == "mock"
    assert body["analysis"]["is_mock"] is True
    assert body["usage"]["estimated_cost_usd"] == 0.0
    assert body["analysis"]["source_sha256"]
    assert "simulada" in body["analysis"]["raw_text"]
    assert client.get("/health").json()["live_calls_used"]["video_analysis"] == 0
    # Cached: GET returns the same persisted analysis.
    cached = client.get(f"/api/projects/{pid}/assets/{aid}/analysis").json()
    assert cached["analysis"]["analysis_id"] == body["analysis"]["analysis_id"]


def test_analyze_requires_explicit_approval(tmp_path):
    client = _client(tmp_path)
    pid, aid = _project_with_video_asset(client, tmp_path)
    resp = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"instruction": "Descreve.", "approved_cost_usd": 0.01},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "cost_cap_exceeded"


def test_analyze_rejects_non_video(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"title": "Docs"}).json()
    pid = project["project_id"]
    path = tmp_path / "notes.txt"
    path.write_text("hello world, this is a text asset for testing")
    with open(path, "rb") as fh:
        uploaded = client.post(
            f"/api/projects/{pid}/assets", files={"file": ("notes.txt", fh, "text/plain")}
        )
    assert uploaded.status_code == 201, uploaded.text
    aid = uploaded.json()["asset_id"]
    resp = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"approved_cost_usd": 0.10},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "analysis_not_video"


def test_analyze_missing_asset_404(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"title": "Empty"}).json()
    resp = client.post(
        f"/api/projects/{project['project_id']}/assets/ast_000000000000/analyze",
        json={"approved_cost_usd": 0.10},
    )
    assert resp.status_code == 404, resp.text


def test_analysis_stale_after_source_change(tmp_path):
    client = _client(tmp_path)
    pid, aid = _project_with_video_asset(client, tmp_path)
    first = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"approved_cost_usd": 0.10},
    )
    assert first.status_code == 200, first.text
    # Tamper with the stored bytes: same asset, different content.
    from pathlib import Path

    stored = sorted(Path(tmp_path, "storage", "projects", pid, "assets", aid).glob("original.*"))
    assert stored, "stored asset file missing"
    stored[0].write_bytes(b"\x00" * 2048)
    stale = client.get(f"/api/projects/{pid}/assets/{aid}/analysis")
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "analysis_stale"


def test_delete_asset_removes_analysis_sidecars(tmp_path):
    client = _client(tmp_path)
    pid, aid = _project_with_video_asset(client, tmp_path)
    resp = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"approved_cost_usd": 0.10},
    )
    assert resp.status_code == 200, resp.text
    assert client.get(f"/api/projects/{pid}/assets/{aid}/analysis").status_code == 200
    deleted = client.delete(f"/api/projects/{pid}/assets/{aid}")
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/projects/{pid}/assets/{aid}/analysis").status_code == 404


# -- API live path with mocked transports -------------------------------------

def test_live_analyze_uploads_once_then_reuses_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_VIDEO_MODE", "live")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    uploads: list[str] = []
    analyses = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/files":
            uploads.append(request.url.path)
            return httpx.Response(200, json={"id": "file-xyz"})
        analyses["count"] += 1
        return httpx.Response(200, json={
            "id": f"resp-{analyses['count']}",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": SAMPLE_ANALYSIS}]}],
            "usage": {"input_tokens": 800, "output_tokens": 100, "total_tokens": 900},
        })

    def factory():
        from clipforge_providers.video_analysis import SparkVideoAnalysisProvider

        return SparkVideoAnalysisProvider(
            "test-key",
            client=httpx.Client(
                transport=httpx.MockTransport(handler), base_url="https://api.meta.ai"
            ),
        )

    client = _client(tmp_path, video_analysis_provider_factory=factory)
    pid, aid = _project_with_video_asset(client, tmp_path)
    first = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"instruction": "Descreve.", "approved_cost_usd": 0.10},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["video_mode"] == "live"
    assert body["analysis"]["is_mock"] is False
    assert body["analysis"]["provider_response_id"] == "resp-1"
    assert body["usage"]["prompt_tokens"] == 800
    assert body["usage"]["file_reused"] is False
    assert body["usage"]["cost_usd"] > 0
    assert "cão" in body["analysis"]["overall_summary"]
    assert uploads == ["/v1/files"]
    assert analyses["count"] == 1

    second = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"instruction": "Descreve de novo.", "approved_cost_usd": 0.10},
    )
    assert second.status_code == 200, second.text
    assert uploads == ["/v1/files"], "file must be reused, not re-uploaded"
    assert analyses["count"] == 2
    assert second.json()["usage"]["file_reused"] is True
    assert second.json()["analysis"]["provider_response_id"] == "resp-2"
    ledger = client.get("/health").json()["live_calls_used"]
    assert ledger["video_analysis"] == 2


def test_live_analyze_requires_key_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_VIDEO_MODE", "live")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = _client(tmp_path)
    pid, aid = _project_with_video_asset(client, tmp_path)
    resp = client.post(
        f"/api/projects/{pid}/assets/{aid}/analyze",
        json={"approved_cost_usd": 0.10},
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] in ("analysis_not_configured", "analysis_not_configured")
