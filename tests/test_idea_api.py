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


def _scale_steps(scene, new_ms):
    """Mirror ideas.ts scaleStepsToDuration for server-acceptance tests."""
    factor = new_ms / scene["duration_ms"]
    steps = []
    for step in scene["animation_sequence"]:
        start = min(round(step["start_ms"] * factor), max(0, new_ms - 100))
        dur = min(max(100, round(step["duration_ms"] * factor)), max(100, new_ms - start))
        steps.append({**step, "start_ms": start, "duration_ms": dur})
    return steps


def test_patch_trim_changes_duration_and_derives_total(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    board = planned["storyboard"]
    scene = board["scenes"][0]
    new_ms = scene["duration_ms"] + 2000
    assert new_ms <= 15000
    scene["animation_sequence"] = _scale_steps(scene, new_ms)
    scene["duration_ms"] = new_ms
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    total_ms = sum(s["duration_ms"] for s in updated["storyboard"]["scenes"])
    assert updated["storyboard"]["duration_seconds"] == round(total_ms / 1000)
    assert updated["storyboard"]["scenes"][0]["duration_ms"] == new_ms


def test_patch_split_and_reorder_accepted(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    board = planned["storyboard"]
    before = len(board["scenes"])
    original = board["scenes"][0]
    cut = original["duration_ms"] // 2
    first = {**original, "duration_ms": cut}
    first["animation_sequence"] = _scale_steps(original, cut)
    second = {**original, "scene_id": "scene_9", "duration_ms": original["duration_ms"] - cut}
    second["animation_sequence"] = _scale_steps(original, second["duration_ms"])
    board["scenes"] = [first, second, *board["scenes"][1:]]
    board["asset_plan"] = [
        {**spec, "scene_ids": [sid for sid in spec["scene_ids"]]}
        for spec in board["asset_plan"]
    ] + [
        {**spec, "asset_id": f"{spec['asset_id']}_b", "scene_ids": ["scene_9"]}
        for spec in planned["storyboard"]["asset_plan"]
        if "scene_1" in spec["scene_ids"]
    ]
    # Reorder: last scene first (order is free; durations/steps untouched).
    board["scenes"] = board["scenes"][::-1]
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert [s["scene_id"] for s in updated["storyboard"]["scenes"]][0] == board["scenes"][0]["scene_id"]
    assert len(updated["storyboard"]["scenes"]) == before + 1


def test_patch_rejects_scene_below_minimum(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    board = planned["storyboard"]
    board["scenes"][0]["duration_ms"] = 500
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "storyboard_invalid"


def test_patch_transition_change_accepted(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    board = planned["storyboard"]
    board["scenes"][0]["transition_out"] = "wipe"
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["storyboard"]["scenes"][0]["transition_out"] == "wipe"


def test_patch_overlay_accepted_and_bounds_rejected(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]
    total_ms = sum(s["duration_ms"] for s in planned["storyboard"]["scenes"])

    board = planned["storyboard"]
    board["overlays"] = [
        {"overlay_id": "overlay_1", "text": "Segue o canal", "start_ms": 500, "end_ms": 4000}
    ]
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert [o["overlay_id"] for o in updated["storyboard"]["overlays"]] == ["overlay_1"]

    board = updated["storyboard"]
    board["overlays"] = [
        {"overlay_id": "overlay_2", "text": "Longe demais", "start_ms": 0, "end_ms": total_ms + 5000}
    ]
    bad = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": updated["storyboard_hash"]},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "storyboard_invalid"

    board = updated["storyboard"]
    board["overlays"] = [
        {"overlay_id": f"overlay_{i}", "text": f"O{i}", "start_ms": 0, "end_ms": 1000}
        for i in range(1, 5)
    ]
    many = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": updated["storyboard_hash"]},
    )
    assert many.status_code == 422


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


def test_custom_duration_idea_plans_with_matching_sum(env):
    client, _, processor = env
    idea = _create(client, {**OPTIONS, "duration_seconds": 25})
    assert idea["estimate"]["image_count"] == 4
    idea_id = idea["idea_id"]

    approved = client.post(
        f"/api/ideas/{idea_id}/approve-storyboard", json={"max_cost_usd": 0}
    )
    assert approved.status_code == 202, approved.text
    assert processor.run_once() is True

    planned = client.get(f"/api/ideas/{idea_id}").json()
    assert planned["stage"] == "awaiting_plan_approval"
    assert planned["storyboard"]["duration_seconds"] == 25
    assert sum(scene["duration_ms"] for scene in planned["storyboard"]["scenes"]) == 25000


def test_patch_guarded_while_rendering(env):
    client, _, processor = env
    planned = _plan(client, processor)
    idea_id = planned["idea_id"]

    approved = client.post(
        f"/api/ideas/{idea_id}/approve-assets",
        json={"asset_ids": [], "max_cost_usd": 0, "programmatic_only": True},
    )
    assert approved.status_code == 202

    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": planned["storyboard"], "expected_hash": planned["storyboard_hash"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idea_stage_conflict"


def _complete_with_generated(client, store, planned):
    """Simulate a verified render: all plates GENERATED, job completed.

    Re-rendering itself needs a browser capture, so tests promote the record
    directly and exercise only the post-completion PATCH contract.
    """
    from clipforge_contracts.idea import AssetStatus, IdeaStatus

    record = store.get(planned["idea_id"])
    for asset in record.idea.assets:
        asset.status = AssetStatus.GENERATED
        asset.filename = f"{asset.asset_id}.png"
        asset.sha256 = "0" * 64
        asset.width = 720
        asset.height = 1280
        asset.provider_name = "mock"
        asset.is_mock = True
        asset.cost_usd = 0.0
        asset.error = None
    store.transition(record, status=IdeaStatus.COMPLETED, stage="completed", note="test")
    return client.get(f"/api/ideas/{planned['idea_id']}").json()


def test_post_completion_text_edit_preserves_generated_assets(env):
    client, store, processor = env
    planned = _plan(client, processor)
    completed = _complete_with_generated(client, store, planned)
    idea_id = completed["idea_id"]
    assert completed["can_render"] is True

    before = {
        asset["asset_id"]: (asset["width"], asset["height"], asset["cost_usd"])
        for asset in completed["assets"]
    }
    assert len(before) == 4

    board = completed["storyboard"]
    board["scenes"][0]["on_screen_text"][0] = "Um novo título, mesmo movimento"
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": completed["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["storyboard_hash"] != completed["storyboard_hash"]
    assert updated["storyboard"]["scenes"][0]["on_screen_text"][0] == (
        "Um novo título, mesmo movimento"
    )
    # Free edit: identical prompts keep their generated files, no new spend.
    assert updated["spent_usd"] == 0.0
    for asset in updated["assets"]:
        assert asset["status"] == "generated"
        assert (asset["width"], asset["height"], asset["cost_usd"]) == before[asset["asset_id"]]
        assert asset["url"] is not None
    internal = store.get(idea_id)
    assert all(asset.filename == f"{asset.asset_id}.png" for asset in internal.idea.assets)
    assert updated["can_render"] is True


def test_post_completion_patch_rejects_new_images(env):
    client, store, processor = env
    planned = _plan(client, processor)
    completed = _complete_with_generated(client, store, planned)
    idea_id = completed["idea_id"]

    board = completed["storyboard"]
    board["asset_plan"].append(
        {
            "asset_id": "asset_extra",
            "scene_ids": ["scene_1"],
            "description": "Uma imagem totalmente nova que custaria dinheiro",
            "orientation": "portrait",
            "role": "foreground",
        }
    )
    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": completed["storyboard_hash"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "storyboard_new_images"

    current = client.get(f"/api/ideas/{idea_id}").json()
    assert current["storyboard_hash"] == completed["storyboard_hash"]


def test_post_completion_delete_scene_redistributes_duration(env):
    client, store, processor = env
    planned = _plan(client, processor)
    completed = _complete_with_generated(client, store, planned)
    idea_id = completed["idea_id"]
    assert len(completed["storyboard"]["scenes"]) == 4

    board = completed["storyboard"]
    victim = board["scenes"][-1]
    removed = victim["duration_ms"]
    assert victim["scene_id"] == "scene_4"
    kept = board["scenes"][:-1]
    total = sum(scene["duration_ms"] for scene in kept)
    assigned = 0
    for index, scene in enumerate(kept):
        extra = removed - assigned if index == len(kept) - 1 else round(removed * scene["duration_ms"] / total)
        assigned += extra
        new_duration = scene["duration_ms"] + extra
        factor = new_duration / scene["duration_ms"]
        for step in scene["animation_sequence"]:
            start = round(step["start_ms"] * factor)
            scaled = max(100, round(step["duration_ms"] * factor))
            step["start_ms"] = start
            step["duration_ms"] = min(scaled, new_duration - start)
        scene["duration_ms"] = new_duration
    board["scenes"] = kept
    board["asset_plan"] = [
        {**spec, "scene_ids": [sid for sid in spec["scene_ids"] if sid != "scene_4"]}
        for spec in board["asset_plan"]
    ]
    board["asset_plan"] = [spec for spec in board["asset_plan"] if spec["scene_ids"]]

    response = client.patch(
        f"/api/ideas/{idea_id}/storyboard",
        json={"storyboard": board, "expected_hash": completed["storyboard_hash"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert [scene["scene_id"] for scene in updated["storyboard"]["scenes"]] == [
        "scene_1",
        "scene_2",
        "scene_3",
    ]
    assert sum(scene["duration_ms"] for scene in updated["storyboard"]["scenes"]) == (
        updated["storyboard"]["duration_seconds"] * 1000
    )
    for asset in updated["assets"]:
        assert "scene_4" not in asset["scene_ids"]
        assert asset["status"] == "generated"
    assert len(updated["assets"]) == 3
