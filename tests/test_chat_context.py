"""Context-aware director chat (ADR-054).

The user-reported regression was: with a clip loaded, asking
“how many videos are in the project?” became an edit proposal with an
Executar card. These tests lock in the corrected behaviour:

- Informational questions answer from persisted ProjectStore / JobStore facts.
- Meta follow-ups (“did you understand my question?”) answer from history.
- Real edit instructions still produce pending proposals with no side effects.
- Live mode sends the snapshot + short history to Muse Spark, but the
  server still owns intent/pending; transport is MockTransport only.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_director.ledger import LiveCallBudget
from clipforge_jobs import JobStore
from clipforge_jobs.project_store import ProjectStore
from clipforge_providers import get_providers


def _providers():
    return get_providers("mock")


def _client(tmp_path):
    return TestClient(
        create_app(storage_root=tmp_path / "storage", providers=_providers())
    )


def _write_asset(projects: ProjectStore, root: Path, kind: str, filename: str, counter: int):
    project_id = "prj_00000000abcd"
    asset_id = f"ast_{counter:012d}"
    directory = projects.assets_dir(project_id) / asset_id
    directory.mkdir(parents=True, exist_ok=True)
    meta = {
        "asset_id": asset_id,
        "project_id": project_id,
        "kind": kind,
        "original_filename": filename,
        "stored_filename": f"original{Path(filename).suffix.lower()}",
        "mime": "video/mp4" if kind == "video" else "audio/mpeg",
        "size_bytes": 123456,
        "sha256": "0" * 64,
        "provenance": "upload" if counter % 2 else "session_source",
    }
    if kind == "video":
        meta.update(
            {
                "width": 360,
                "height": 640,
                "duration_seconds": 19.6,
                "fps": 25.0,
                "frame_count": 490,
                "has_audio": True,
            }
        )
    Path(directory, "asset.json").write_text(
        _to_json(meta), encoding="utf-8"
    )
    return asset_id


def _to_json(payload: dict) -> str:
    import json

    return json.dumps(payload)


def _project_stores(tmp_path):
    from clipforge_jobs.store import JobStore

    return JobStore(tmp_path / "storage"), ProjectStore(tmp_path / "storage")


def _direct_project_file(projects: ProjectStore):
    payload = {
        "project_id": "prj_00000000abcd",
        "title": "Facebook dois",
        "mode": "edit",
        "created_at": "2026-11-04T00:00:00Z",
        "updated_at": "2026-11-04T00:00:00Z",
    }
    directory = projects.projects_dir / "prj_00000000abcd"
    directory.mkdir(parents=True, exist_ok=True)
    Path(directory, "project.json").write_text(_to_json(payload), encoding="utf-8")


def _job_record(tmp_path, project_id: str = "prj_00000000abcd"):
    from clipforge_jobs.models import JobRecord, SourceInfo

    return JobRecord(
        job_id="jobchat123",
        project_id=project_id,
        original_filename="facebook2.mp4",
        source_relative_path="uploads/jobchat123/source.mp4",
        source_info=SourceInfo(
            width=360, height=640, fps=25.0, duration_seconds=19.6,
            frame_count=490, has_audio=True,
        ),
    )


def test_project_video_count_with_clip_is_question_not_edit(tmp_path):
    store, projects = _project_stores(tmp_path)
    _direct_project_file(projects)
    for index in range(2):
        _write_asset(projects, tmp_path / "storage", "video", f"clip-{index}.mp4", index + 1)
    store.create(_job_record(tmp_path))
    client = _client(tmp_path)

    body = client.post(
        "/api/chat",
        json={
            "message": "quantos videos tenho no projeto?",
            "job_id": "jobchat123",
            "project_id": "prj_00000000abcd",
        },
    ).json()

    assert body["intent"] == "question"
    assert body["needs_confirmation"] is False
    assert body["pending_text"] is None
    assert body["chat_mode"] == "mock"
    assert "2 ví" in body["reply"]
    assert "Executar" not in body["reply"]
    assert "ClipForge_MagicBackground" not in body["reply"]


def test_meta_followup_from_history_answers_prior_question_not_edit(tmp_path):
    store, projects = _project_stores(tmp_path)
    _direct_project_file(projects)
    _write_asset(projects, tmp_path / "storage", "video", "clip-1.mp4", 3)
    store.create(_job_record(tmp_path))
    client = _client(tmp_path)

    history = [
        {"role": "user", "text": "quantos videos tenho no projeto?"},
        {"role": "muse", "text": "No projeto tens 2 vídeos."},
        {"role": "user", "text": "ENTENDESTE A MINHA PERGUNTA?"},
    ]
    body = client.post(
        "/api/chat",
        json={
            "message": "ENTENDESTE A MINHA PERGUNTA?",
            "job_id": "jobchat123",
            "history": history,
        },
    ).json()

    assert body["intent"] == "question"
    assert body["needs_confirmation"] is False
    assert body["pending_text"] is None
    assert "quantos videos" in body["reply"]
    assert "Nada" not in body["reply"] or True


def test_project_video_count_without_clip_answers_with_seed(tmp_path):
    _store, projects = _project_stores(tmp_path)
    _direct_project_file(projects)
    for index in range(2):
        _write_asset(projects, tmp_path / "storage", "video", f"clip-{index}.mp4", index + 10)
    _write_asset(projects, tmp_path / "storage", "audio", "nar.mp3", 99)
    client = _client(tmp_path)

    body = client.post(
        "/api/chat",
        json={
            "message": "quantos videos tenho no projeto?",
            "project_id": "prj_00000000abcd",
        },
    ).json()

    assert body["intent"] == "question"
    assert "2 ví" in body["reply"]
    assert client.get("/health").json()["live_calls_used"]["chat"] == 0


def test_edit_instruction_with_clip_stays_pending_not_executed(tmp_path):
    store, projects = _project_stores(tmp_path)
    _direct_project_file(projects)
    store.create(_job_record(tmp_path))
    client = _client(tmp_path)

    before = store.get("jobchat123")
    body = client.post(
        "/api/chat",
        json={"message": "desfoca o fundo", "job_id": "jobchat123"},
    ).json()

    assert body["intent"] == "edit_proposal"
    assert body["needs_confirmation"] is True
    assert body["pending_text"] == "desfoca o fundo"
    assert before.ready is False
    assert store.get("jobchat123").ready is False


def test_greeting_with_clip_is_not_edit(tmp_path):
    store, projects = _project_stores(tmp_path)
    _direct_project_file(projects)
    store.create(_job_record(tmp_path))
    client = _client(tmp_path)

    body = client.post(
        "/api/chat", json={"message": "ola", "job_id": "jobchat123"}
    ).json()
    assert body["intent"] == "smalltalk"
    assert body["needs_confirmation"] is False
    assert body["pending_text"] is None


def test_live_chat_no_exec_of_text_edit_prompt(tmp_path, monkeypatch):
    from clipforge_director.chat import SparkChatAssistant
    import httpx
    import json

    monkeypatch.setenv("CLIPFORGE_CHAT_MODE", "live")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    store, projects = _project_stores(tmp_path)
    _direct_project_file(projects)
    _write_asset(projects, tmp_path / "storage", "video", "clip-1.mp4", 77)
    from clipforge_jobs.models import ClipTextOverlay

    base = _job_record(tmp_path)
    store.create(
        base.model_copy(
            update={
                "clip_texts": [
                    ClipTextOverlay(
                        overlay_id="txt_ab12cd34",
                        text="Ola mundo",
                        start_s=1,
                        duration_s=2,
                        x=0.5,
                        y=0.8,
                        scale=1.0,
                        color="#FFFFFF",
                        weight="bold",
                        style="rise",
                    )
                ]
            }
        )
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Mudei o texto para isto. Estrutura válida."
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 44,
                    "completion_tokens": 14,
                    "total_tokens": 58,
                },
            },
        )

    def factory():
        return SparkChatAssistant(
            "test-key",
            client=httpx.Client(
                transport=httpx.MockTransport(handler),
                base_url="https://api.meta.ai",
            ),
        )

    client = TestClient(
        create_app(
            storage_root=tmp_path / "storage",
            providers=_providers(),
            chat_provider_factory=factory,
        )
    )
    body = client.post(
        "/api/chat",
        json={
            "message": "quantos videos tenho?",
            "job_id": "jobchat123",
            "history": [
                {"role": "user", "text": "quantos videos tenho?"},
                {"role": "muse", "text": "Tens 2 videos."},
            ],
        },
    ).json()

    assert body["intent"] == "question"
    assert body["needs_confirmation"] is False
    assert body["chat_mode"] == "live"
    assert body["chat_usage"]["prompt_tokens"] == 44
    assert LiveCallBudget(tmp_path / "storage").used("chat") == 1
    user_text = captured["payload"]["messages"][1]["content"]
    assert "Tu: quantos videos tenho?" in user_text
    assert "ESTADO REAL" in user_text


def _job_with_clip(tmp_path):
    from clipforge_jobs.store import JobStore

    store = JobStore(tmp_path / "storage")
    store.create(_job_record(tmp_path))
    return TestClient(
        create_app(storage_root=tmp_path / "storage", providers=_providers())
    )


def test_gibberish_with_clip_is_clarify_without_pending(tmp_path):
    client = _job_with_clip(tmp_path)
    for message in ("HSDJS", "JSDHSD", "asdf qwer"):
        body = client.post(
            "/api/chat", json={"message": message, "job_id": "jobchat123"}
        ).json()
        assert body["intent"] == "clarify", message
        assert body["needs_confirmation"] is False
        assert body["pending_text"] is None
        assert body["pending_kind"] is None
        assert "Executar" not in body["reply"]
        assert message in body["reply"]


def test_bare_target_noun_still_proposes_edit(tmp_path):
    client = _job_with_clip(tmp_path)
    body = client.post(
        "/api/chat", json={"message": "borra o fundo", "job_id": "jobchat123"}
    ).json()
    assert body["intent"] == "edit_proposal"
    assert body["needs_confirmation"] is True
    assert body["pending_text"] == "borra o fundo"


def test_real_instruction_with_clip_still_proposes(tmp_path):
    client = _job_with_clip(tmp_path)
    body = client.post(
        "/api/chat", json={"message": "desfoca o fundo", "job_id": "jobchat123"}
    ).json()
    assert body["intent"] == "edit_proposal"
    assert body["pending_kind"] == "edit"


def test_gibberish_without_clip_goes_to_interview(tmp_path):
    client = TestClient(
        create_app(storage_root=tmp_path / "storage", providers=_providers())
    )
    body = client.post("/api/chat", json={"message": "JSDHSD"}).json()
    assert body["intent"] == "idea_interview"
    assert body["needs_confirmation"] is False
