"""ADR-061: the chat follows the Recursos selection, with same-project guards.

- /api/chat accepts selected_asset_id; the backend only honors it when the
  asset belongs to the effective project (no cross-project leakage, no crash
  on unknown ids).
- Video questions answer from the selected asset's cached analysis; a
  selected asset without analysis points at «Analisar vídeo» instead of
  answering about another video silently.
- Without a selection, several analysed videos trigger a clarification
  asking which one (no silent pick); a single one keeps working.
- A sha256 fallback reuses an analysis for byte-identical re-imports in the
  same project.
- Attaching a video while a job is loaded imports it as a library asset
  (frontend path, covered by typecheck + browser e2e).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs import JobStore
from clipforge_jobs.project_store import ProjectStore
from clipforge_providers import get_providers


PROJECT_ID = "prj_111111111111"


def _providers():
    return get_providers("mock")


def _client(tmp_path):
    return TestClient(
        create_app(storage_root=tmp_path / "storage", providers=_providers())
    )


def _write_project(projects: ProjectStore):
    payload = {
        "project_id": PROJECT_ID,
        "title": "Seleção",
        "mode": "edit",
        "created_at": "2026-11-04T00:00:00Z",
        "updated_at": "2026-11-04T00:00:00Z",
    }
    directory = projects.projects_dir / PROJECT_ID
    directory.mkdir(parents=True, exist_ok=True)
    Path(directory, "project.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_asset(projects: ProjectStore, name: str, sha: str, counter: int) -> str:
    asset_id = f"ast_{counter:012d}"
    directory = projects.assets_dir(PROJECT_ID) / asset_id
    directory.mkdir(parents=True, exist_ok=True)
    meta = {
        "asset_id": asset_id,
        "project_id": PROJECT_ID,
        "kind": "video",
        "original_filename": name,
        "stored_filename": f"original{Path(name).suffix.lower()}",
        "mime": "video/mp4",
        "size_bytes": 123456,
        "sha256": sha,
        "provenance": "upload",
        "width": 360,
        "height": 640,
        "duration_seconds": 19.6,
        "fps": 25.0,
        "frame_count": 490,
        "has_audio": True,
    }
    Path(directory, "asset.json").write_text(json.dumps(meta), encoding="utf-8")
    return asset_id


def _write_analysis(projects: ProjectStore, asset_id: str, sha: str, summary: str) -> None:
    payload = {
        "analysis_id": "van_0123456789ab",
        "project_id": PROJECT_ID,
        "asset_id": asset_id,
        "source_sha256": sha,
        "provider": "meta-muse-spark",
        "model": "muse-spark-1.3-contributor",
        "provider_response_id": "resp-test",
        "video_duration_s": 19.6,
        "created_at": "2026-11-04T00:00:00Z",
        "raw_text": f"RESUMO: {summary}",
        "overall_summary": summary,
        "visual_style": None,
        "subjects": [],
        "objects_seen": ["um cão castanho"],
        "scenes": [],
        "important_moments": [{"at_s": 1.0, "approximate": True, "label": "o cão entra a correr"}],
        "composition_observations": [],
        "editing_opportunities": [],
        "uncertainties": [],
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "estimated_cost_usd": 0.00002,
        "is_mock": False,
        "file_reused": False,
    }
    directory = projects.assets_dir(PROJECT_ID) / asset_id
    Path(directory, "analysis.json").write_text(json.dumps(payload), encoding="utf-8")


def _job_record(project_id: str, sha: str | None = None):
    from clipforge_jobs.models import JobRecord, SourceInfo

    return JobRecord(
        job_id="jobchat999",
        project_id=project_id,
        original_filename="facebook2.mp4",
        source_relative_path="uploads/jobchat999/source.mp4",
        source_sha256=sha,
        source_info=SourceInfo(
            width=360, height=640, fps=25.0, duration_seconds=19.6,
            frame_count=490, has_audio=True,
        ),
    )


def _setup(tmp_path):
    from clipforge_jobs.store import JobStore

    store = JobStore(tmp_path / "storage")
    projects = ProjectStore(tmp_path / "storage")
    _write_project(projects)
    return store, projects


def test_selected_analysed_asset_wins_over_other_analyses(tmp_path):
    store, projects = _setup(tmp_path)
    _write_asset(projects, "praia.mp4", "a" * 64, 1)
    other = _write_asset(projects, "montanha.mp4", "b" * 64, 2)
    _write_analysis(projects, other, "b" * 64, "Um passeio na montanha.")
    store.create(_job_record(PROJECT_ID))
    client = _client(tmp_path)
    body = client.post(
        "/api/chat",
        json={
            "message": "o que acontece neste vídeo?",
            "job_id": "jobchat999",
            "project_id": PROJECT_ID,
            "selected_asset_id": other,
        },
    ).json()
    assert body["intent"] == "question"
    assert body["pending_text"] is None
    assert "montanha" in body["reply"]
    assert "praia" not in body["reply"]
    assert "Executar" not in body["reply"]


def test_selected_asset_without_analysis_points_to_analyze(tmp_path):
    store, projects = _setup(tmp_path)
    chosen = _write_asset(projects, "praia.mp4", "a" * 64, 1)
    other = _write_asset(projects, "montanha.mp4", "b" * 64, 2)
    _write_analysis(projects, other, "b" * 64, "Um passeio na montanha.")
    store.create(_job_record(PROJECT_ID))
    client = _client(tmp_path)
    body = client.post(
        "/api/chat",
        json={
            "message": "sabes sobre oque é o video?",
            "job_id": "jobchat999",
            "project_id": PROJECT_ID,
            "selected_asset_id": chosen,
        },
    ).json()
    assert body["intent"] == "question"
    assert body["pending_text"] is None
    assert "Analisar vídeo" in body["reply"]
    assert "praia.mp4" in body["reply"]
    # Must not silently answer about the other analysed video.
    assert "montanha" not in body["reply"]
    assert "Executar" not in body["reply"]


def test_no_selection_multiple_analyses_asks_which(tmp_path):
    store, projects = _setup(tmp_path)
    _write_asset(projects, "praia.mp4", "a" * 64, 1)
    _write_asset(projects, "montanha.mp4", "b" * 64, 2)
    # analyses exist for both, no selection, no job link
    store.create(_job_record(PROJECT_ID))
    client = _client(tmp_path)
    # give both assets an analysis
    for aid, sha, text in (
        ("ast_000000000001", "a" * 64, "Um dia na praia."),
        ("ast_000000000002", "b" * 64, "Um passeio na montanha."),
    ):
        _write_analysis(projects, aid, sha, text)
    body = client.post(
        "/api/chat",
        json={
            "message": "o que acontece neste vídeo?",
            "job_id": "jobchat999",
            "project_id": PROJECT_ID,
        },
    ).json()
    assert body["intent"] == "question"
    assert body["pending_text"] is None
    assert "praia.mp4" in body["reply"] and "montanha.mp4" in body["reply"]
    assert "Executar" not in body["reply"]


def test_job_linked_asset_wins_without_selection(tmp_path):
    store, projects = _setup(tmp_path)
    _write_asset(projects, "praia.mp4", "a" * 64, 1)
    linked = _write_asset(projects, "entrevista.mp4", "c" * 64, 3)
    _write_analysis(projects, linked, "c" * 64, "Uma entrevista no estúdio.")
    store.create(_job_record(PROJECT_ID, sha="c" * 64))
    client = _client(tmp_path)
    body = client.post(
        "/api/chat",
        json={
            "message": "descreve este vídeo",
            "job_id": "jobchat999",
            "project_id": PROJECT_ID,
        },
    ).json()
    assert body["intent"] == "question"
    assert "entrevista" in body["reply"]
    assert "praia" not in body["reply"]


def test_foreign_selected_asset_id_is_ignored_safely(tmp_path):
    store, projects = _setup(tmp_path)
    _write_asset(projects, "praia.mp4", "a" * 64, 1)
    store.create(_job_record(PROJECT_ID))
    client = _client(tmp_path)
    for foreign in ("ast_999999999999", "prj_000000000000", "!!!", "ast_000000000001' OR '1'='1"):
        resp = client.post(
            "/api/chat",
            json={
                "message": "quantos videos tenho no projeto?",
                "job_id": "jobchat999",
                "project_id": PROJECT_ID,
                "selected_asset_id": foreign,
            },
        )
        assert resp.status_code == 200, foreign
        body = resp.json()
        assert body["intent"] == "question"
        assert "1 vídeo" in body["reply"] or "1 video" in body["reply"].lower()


def test_sha_fallback_reuses_analysis_for_reimport(tmp_path):
    store, projects = _setup(tmp_path)
    _write_asset(projects, "original.mp4", "d" * 64, 1)
    copy_id = _write_asset(projects, "copia.mp4", "d" * 64, 2)
    _write_analysis(projects, "ast_000000000001", "d" * 64, "Um cão no parque.")
    store.create(_job_record(PROJECT_ID))
    client = _client(tmp_path)
    body = client.post(
        "/api/chat",
        json={
            "message": "o que acontece neste vídeo?",
            "job_id": "jobchat999",
            "project_id": PROJECT_ID,
            "selected_asset_id": copy_id,
        },
    ).json()
    assert body["intent"] == "question"
    assert "cão no parque" in body["reply"]


def test_analyze_request_prefers_selection(tmp_path):
    store, projects = _setup(tmp_path)
    chosen = _write_asset(projects, "praia.mp4", "a" * 64, 1)
    _write_analysis(projects, chosen, "a" * 64, "Um dia na praia.")
    store.create(_job_record(PROJECT_ID))
    client = _client(tmp_path)
    body = client.post(
        "/api/chat",
        json={
            "message": "analisa este vídeo",
            "job_id": "jobchat999",
            "project_id": PROJECT_ID,
            "selected_asset_id": chosen,
        },
    ).json()
    assert body["intent"] == "question"
    assert body["pending_text"] is None
    assert "praia" in body["reply"]


def test_reported_analysis_conjugations_never_ask_style(tmp_path):
    # 2026-11-05: "analise o video para mim", "estou a (a)pedir para
    # analisar" e "quero que analises ele" caíam na entrevista de ideia
    # ("Que estilo queres?") em vez de apontar «Analisar vídeo».
    _, projects = _setup(tmp_path)
    chosen = _write_asset(projects, "praia.mp4", "a" * 64, 1)
    client = _client(tmp_path)
    for message in (
        "analise o video para mim",
        "estou a pedir para analisar",
        "estou a apedir para analisar",
        "quero que analises ele",
    ):
        body = client.post(
            "/api/chat",
            json={
                "message": message,
                "project_id": PROJECT_ID,
                "selected_asset_id": chosen,
            },
        ).json()
        assert body["intent"] == "question", message
        assert body["pending_text"] is None, message
        assert "Analisar vídeo" in body["reply"], message
        assert "Que estilo" not in body["reply"], message
        assert "Executar" not in body["reply"], message


def test_selection_question_names_selected_asset(tmp_path):
    _, projects = _setup(tmp_path)
    chosen = _write_asset(projects, "praia.mp4", "a" * 64, 1)
    client = _client(tmp_path)
    body = client.post(
        "/api/chat",
        json={
            "message": "qual video tenho selecionado",
            "project_id": PROJECT_ID,
            "selected_asset_id": chosen,
        },
    ).json()
    assert body["intent"] == "question"
    assert "praia.mp4" in body["reply"]
    assert "Que estilo" not in body["reply"]
    assert "Executar" not in body["reply"]
