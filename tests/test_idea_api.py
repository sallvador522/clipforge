"""Idea API: approvals, stage guards and the render manifest (offline)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clipforge_api.main import create_app
from clipforge_jobs.idea_store import IdeaStore
from clipforge_worker.idea_processor import IdeaProcessor

BRIEF = "Como seria se os dinossauros vivessem hoje entre nós?"
OPTIONS = {
    "duration_seconds": 20,
    "aspect_ratio": "9:16",
    "fps": 24,
    "style_preset": "cinematic",
    "use_generated_images": True,
    "language": "pt-PT",
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "mock")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "mock")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    store = IdeaStore(tmp_path / "storage")
    client = TestClient(create_app(storage_root=tmp_path / "storage"))
    processor = IdeaProcessor(
        store,
        studio_url="http://127.0.0.1:1",
        api_url="http://127.0.0.1:1",
    )
    return client, store, processor


def _create(client, options=None):
    response = client.post(
        "/api/ideas", json={"brief": BRIEF, "options": options or OPTIONS}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _plan(client, processor):
    idea = _create(client)
    approved = client.post(
        f"/api/ideas/{idea['idea_id']}/approve-storyboard", json={"max_cost_usd": 0}
    )
    assert approved.status_code == 202, approved.text
    assert processor.run_once() is True
    planned = client.get(f"/api/ideas/{idea['idea_id']}").json()
    assert planned["stage"] == "awaiting_plan_approval"
    return planned


def test_create_reports_cost_and_waits_for_approval(env):
    client, _, _ = env
    body = client.get("/api/ideas/config").json()
    assert body["modes"] == {"director": "mock", "image": "mock", "effort": "medium"}
    assert body["cap_usd"] == pytest.approx(0.10)

    idea = _create(client)
    assert idea["status"] == "awaiting_approval"
    assert idea["stage"] == "awaiting_storyboard_cost"
    assert idea["estimate"]["total_usd"] == 0.0
    assert idea["estimate"]["image_count"] == 4
    assert idea["can_approve_storyboard"] is True
    assert idea["can_approve_assets"] is False
    assert idea["storyboard"] is None

    listed = client.get("/api/ideas").json()["ideas"]
    assert [item["idea_id"] for item in listed] == [idea["idea_id"]]


def test_brief_is_validated(env):
    client, _, _ = env
    too_short = client.post("/api/ideas", json={"brief": "curto", "options": OPTIONS})
    assert too_short.status_code == 422
    unknown_option = client.post(
        "/api/ideas",
        json={"brief": BRIEF, "options": {**OPTIONS, "resolution": "4k"}},
    )
    assert unknown_option.status_code == 422


def test_storyboard_approval_is_stage_guarded(env):
    client, _, _ = env
    idea = _create(client)
    idea_id = idea["idea_id"]

    premature = client.post(f"/api/ideas/{idea_id}/approve-assets", json={"asset_ids": []})
    assert premature.status_code == 409
    assert premature.json()["error"]["code"] == "idea_stage_conflict"

    approved = client.post(
        f"/api/ideas/{idea_id}/approve-storyboard", json={"max_cost_usd": 0}
    )
    assert approved.status_code == 202
    assert approved.json()["status"] == "queued"
    assert approved.json()["stage"] == "planning"

    repeated = client.post(
        f"/api/ideas/{idea_id}/approve-storyboard", json={"max_cost_usd": 0}
    )
    assert repeated.status_code == 409


def test_plan_then_programmatic_render_queue_and_manifest(env):
    client, store, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    assert planned["status"] == "awaiting_approval"
    assert len(planned["storyboard"]["scenes"]) == 4
    assert len(planned["assets"]) == 4
    assert planned["can_approve_assets"] is True
    assert planned["spent_usd"] == 0.0

    approved = client.post(
        f"/api/ideas/{idea_id}/approve-assets",
        json={"asset_ids": [], "max_cost_usd": 0, "programmatic_only": True},
    )
    assert approved.status_code == 202, approved.text
    queued = approved.json()
    assert queued["status"] == "queued"
    assert queued["stage"] == "rendering"
    assert [asset["status"] for asset in queued["assets"]] == ["skipped"] * 4

    manifest = client.get(f"/api/ideas/{idea_id}/render-manifest")
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["width"] == 720
    assert body["height"] == 1280
    assert body["fps"] == 24
    assert body["frame_count"] == 480
    assert body["asset_urls"] == {}

    download = client.get(f"/api/ideas/{idea_id}/download")
    assert download.status_code == 409
    assert download.json()["error"]["code"] == "render_not_verified"

    result = client.get(f"/api/ideas/{idea_id}/result").json()
    assert result["render"] is None
    assert result["versions"] == []


def test_unknown_asset_cannot_be_approved(env):
    client, _, processor = env
    planned = _plan(client, processor)
    response = client.post(
        f"/api/ideas/{planned['idea_id']}/approve-assets",
        json={"asset_ids": ["asset_not_in_plan"], "max_cost_usd": 0},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "asset_unknown"


def test_patch_rejects_unresolvable_targets(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    board = planned["storyboard"]
    board["scenes"][0]["animation_sequence"][1]["target"] = "titulo de abertura"
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "storyboard_invalid"

    # The stored board is untouched by the rejected patch.
    current = client.get(f"/api/ideas/{idea_id}").json()
    assert current["storyboard_hash"] == planned["storyboard_hash"]


def test_patch_accepts_foreground_plate_and_rebuilds_assets(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    board = planned["storyboard"]
    board["asset_plan"].append(
        {
            "asset_id": "asset_scene_1_fg",
            "scene_ids": ["scene_1"],
            "description": "Close dinosaurs in the lower frame",
            "orientation": "portrait",
            "role": "foreground",
        }
    )
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["storyboard_hash"] != planned["storyboard_hash"]
    roles = {
        asset["asset_id"]: asset["role"]
        for asset in updated["assets"]
        if "scene_1" in asset["scene_ids"]
    }
    assert roles == {"asset_scene_1": "background", "asset_scene_1_fg": "foreground"}


def test_reject_stops_the_job(env):
    client, _, _ = env
    idea = _create(client)
    idea_id = idea["idea_id"]
    rejected = client.post(f"/api/ideas/{idea_id}/reject")
    assert rejected.status_code == 202
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["error"]["code"] == "rejected_by_user"

    late = client.post(f"/api/ideas/{idea_id}/approve-storyboard", json={"max_cost_usd": 0})
    assert late.status_code == 409


def test_cancel_queued_job_marks_it_failed(env):
    client, _, _ = env
    idea = _create(client)
    idea_id = idea["idea_id"]
    client.post(f"/api/ideas/{idea_id}/approve-storyboard", json={"max_cost_usd": 0})
    cancelled = client.post(f"/api/ideas/{idea_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "failed"
    assert cancelled.json()["error"]["code"] == "cancelled_by_user"


def test_worker_rejects_a_mode_change_after_approval(env, monkeypatch):
    client, _, processor = env
    idea = _create(client)
    idea_id = idea["idea_id"]
    client.post(f"/api/ideas/{idea_id}/approve-storyboard", json={"max_cost_usd": 0})

    # The user approved a free mock plan; flipping the env must not turn it
    # into a paid call behind their back.
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "live")
    assert processor.run_once() is True

    failed = client.get(f"/api/ideas/{idea_id}").json()
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "provider_mode_mismatch"


def test_live_estimate_above_cap_is_refused_before_any_call(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_PRICE_IMAGE_USD", "0.05")
    response = client.post("/api/ideas", json={"brief": BRIEF, "options": OPTIONS})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cost_cap_exceeded"


def test_live_estimate_is_reported_without_calling_a_provider(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "live")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "live")
    idea = _create(client)
    assert idea["modes"] == {"director": "live", "image": "live", "effort": "medium"}
    assert idea["estimate"]["storyboard_usd"] == pytest.approx(0.002)
    assert idea["estimate"]["images_usd"] == pytest.approx(0.04)
    assert idea["status"] == "awaiting_approval"
