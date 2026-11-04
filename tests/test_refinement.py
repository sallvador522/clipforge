"""ADR-036: director-authoritative duration + voice/text refinement patches.

Offline only: the refinement provider is a test stub injected into the
router; no network or paid call happens here.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipforge_api.ideas import create_ideas_router
from clipforge_contracts.idea import IdeaOptions, IdeaStatus
from clipforge_contracts.storyboard import Storyboard, StoryboardPatch
from clipforge_director.creative import apply_storyboard_patch
from clipforge_director.idea_director import MockIdeaDirector
from clipforge_jobs.idea_store import IdeaStore

BRIEF = "Um vídeo sobre o impacto de um asteroide na Terra."


def _board(duration_seconds: int = 20) -> Storyboard:
    options = IdeaOptions(duration_seconds=duration_seconds)
    return MockIdeaDirector().create_storyboard(BRIEF, options)


def test_director_duration_wins_over_declared_duration():
    """The reported failure: scenes sum to 75000ms, header said 60s."""
    data = _board(20).model_dump(mode="json")
    # Six scenes of 12.5s each (per-scene cap is 15s): the real failure shape.
    scenes = []
    for index in range(6):
        scene = dict(data["scenes"][index % len(data["scenes"])])
        scene["scene_id"] = f"scene_{index + 1}"
        scene["duration_ms"] = 12500
        scenes.append(scene)
    data["scenes"] = scenes
    data["duration_seconds"] = 60
    board = Storyboard.model_validate(data)
    assert board.duration_seconds == 75
    assert sum(s.duration_ms for s in board.scenes) == 75000
    assert board.total_frames == 75 * board.output_fps


def test_no_sixty_second_ceiling():
    assert IdeaOptions(duration_seconds=90).duration_seconds == 90
    data = _board(20).model_dump(mode="json")
    data["duration_seconds"] = 120
    for scene in data["scenes"]:
        scene["duration_ms"] = 30000 // len(data["scenes"])
    # 30s of scenes derive a 30s board even when the header said 120.
    assert Storyboard.model_validate(data).duration_seconds == 30


def _patch(board: Storyboard, operations: list[dict], **extra) -> StoryboardPatch:
    return StoryboardPatch.model_validate(
        {
            "instruction": extra.get("instruction", "ajusta"),
            "summary": extra.get("summary", "Ajuste de teste."),
            "outcome": extra.get("outcome", "apply"),
            "clarification_question": extra.get("clarification_question"),
            "operations": operations,
        }
    )


def test_patch_changes_typography_and_animation():
    board = _board()
    scene_id = board.scenes[0].scene_id
    target = board.scenes[0].animation_sequence[0].target
    patched = apply_storyboard_patch(
        board,
        _patch(
            board,
            [
                {
                    "op": "set_text_style",
                    "scene_id": scene_id,
                    "style": {"family": "serif", "size_scale": 1.4, "color": "#FFE9C9"},
                },
                {
                    "op": "set_animation_step",
                    "scene_id": scene_id,
                    "target": target,
                    "duration_ms": 3000,
                    "ease": "outExpo",
                },
            ],
        ),
    )
    scene = patched.scenes[0]
    assert scene.text_style.family == "serif"
    assert scene.text_style.size_scale == pytest.approx(1.4)
    step = next(s for s in scene.animation_sequence if s.target == target)
    assert step.duration_ms == 3000
    assert step.ease == "outExpo"
    # Original board untouched.
    assert board.scenes[0].text_style.family == "sans"


def test_patch_delete_scene_rederives_duration():
    board = _board()
    total_before = board.duration_seconds
    removed = board.scenes[0].duration_ms // 1000
    patched = apply_storyboard_patch(
        board, _patch(board, [{"op": "delete_scene", "scene_id": board.scenes[0].scene_id}])
    )
    assert len(patched.scenes) == len(board.scenes) - 1
    assert patched.duration_seconds == total_before - removed


def test_patch_rejects_unknown_scene_and_clarification_with_ops():
    board = _board()
    with pytest.raises(ValueError, match="unknown scene"):
        apply_storyboard_patch(
            board,
            _patch(board, [{"op": "set_scene_text", "scene_id": "scene_9", "lines": ["x"]}]),
        )
    with pytest.raises(ValueError, match="clarification"):
        _patch(
            board,
            [{"op": "delete_scene", "scene_id": board.scenes[0].scene_id}],
            outcome="clarification",
            clarification_question="Qual cena?",
        )


def test_refinement_provider_single_post_and_echo():
    import json

    import httpx

    from clipforge_director.creative import RefinementDirectorProvider
    from clipforge_director.ledger import LiveCallNotAuthorizedError
    from clipforge_director.spark import CHAT_COMPLETIONS_PATH
    from test_director_spark import _TestAuthorization

    board = _board()
    instruction = "Torna o título mais elegante e maior."
    calls = {"n": 0, "payload": None}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path == CHAT_COMPLETIONS_PATH
        calls["payload"] = json.loads(request.content)
        # Lite wire: flat operations, zero $refs (the 11.5 KB full patch
        # schema failed once with HTTP 500, like the full v2 plan schema).
        assert "$defs" not in json.dumps(calls["payload"]["response_format"])
        body = {
            "instruction": instruction,
            "summary": "Título serifado e maior.",
            "operations": [
                {
                    "op": "set_text_style",
                    "scene_id": board.scenes[0].scene_id,
                    "style": {"family": "serif", "size_scale": 1.25},
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(body)}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
    provider = RefinementDirectorProvider(
        api_key="k", playbook_text="x", capability_summary="storyboard-patch-only", client=client
    )
    with pytest.raises(LiveCallNotAuthorizedError):
        provider.create_patch(board, instruction, authorization=None)
    patch = provider.create_patch(
        board, instruction, authorization=_TestAuthorization("director")
    )
    assert calls["n"] == 1
    assert patch.operations[0].style.family == "serif"
    # The current board is in the request context (sequential refinements).
    user_content = calls["payload"]["messages"][1]["content"]
    assert board.scenes[0].scene_id in user_content
    assert instruction in user_content
    provider.close()


def test_patch_lite_wire_schema_stays_small():
    import json

    from clipforge_contracts.refinement_lite import PATCH_LITE_WIRE_SCHEMA

    size = len(json.dumps(PATCH_LITE_WIRE_SCHEMA))
    assert size < 4000, f"lite wire schema grew to {size} bytes"
    assert "$defs" not in json.dumps(PATCH_LITE_WIRE_SCHEMA)
    assert "$ref" not in json.dumps(PATCH_LITE_WIRE_SCHEMA)


def _lite(instruction: str, operations: list[dict], **extra) -> dict:
    body = {
        "instruction": instruction,
        "summary": extra.get("summary", "Ajuste."),
        "outcome": extra.get("outcome", "apply"),
        "operations": operations,
    }
    if extra.get("clarification_question"):
        body["clarification_question"] = extra["clarification_question"]
    return body


def test_lite_to_full_covers_all_operations():
    import json

    from clipforge_contracts.refinement_lite import LitePatch, lite_to_full_patch

    board = _board()
    scene_id = board.scenes[0].scene_id
    target = board.scenes[0].animation_sequence[0].target
    new_scene = board.scenes[0].model_dump(mode="json")
    new_scene["scene_id"] = "scene_9"
    lite = LitePatch.model_validate(
        _lite(
            "ajusta tudo",
            [
                {"op": "set_scene_text", "scene_id": scene_id, "lines": ["Novo titulo"]},
                {"op": "set_text_style", "scene_id": scene_id, "style": {"align": "center"}},
                {
                    "op": "set_animation_step",
                    "scene_id": scene_id,
                    "target": target,
                    "duration_ms": 2500,
                    "ease": "outExpo",
                },
                {
                    "op": "add_animation_step",
                    "scene_id": scene_id,
                    "step_primitive": "fade",
                    "step_target": "line1",
                    "step_start_ms": 500,
                    "step_duration_ms": 1200,
                },
                {"op": "remove_animation_step", "scene_id": scene_id, "target": target},
                {"op": "delete_scene", "scene_id": board.scenes[1].scene_id},
                {"op": "add_scene", "scene_json": json.dumps(new_scene)},
                {
                    "op": "set_scene_visual",
                    "scene_id": scene_id,
                    "backdrop_hue_deg": -20,
                },
                {"op": "set_tone", "tone": "Cinematografico calmo"},
            ],
        )
    )
    patch = lite_to_full_patch(lite)
    assert [op.op for op in patch.operations] == [
        "set_scene_text",
        "set_text_style",
        "set_animation_step",
        "add_animation_step",
        "remove_animation_step",
        "delete_scene",
        "add_scene",
        "set_scene_visual",
        "set_tone",
    ]
    applied = apply_storyboard_patch(board, patch)
    assert applied.scenes[0].on_screen_text == ["Novo titulo"]
    assert applied.scenes[0].text_style.align == "center"
    assert any(s.scene_id == "scene_9" for s in applied.scenes)


def test_lite_to_full_covers_transition_and_overlays():
    import json

    from clipforge_contracts.refinement_lite import LitePatch, lite_to_full_patch

    board = _board()
    scene_id = board.scenes[0].scene_id
    lite = LitePatch.model_validate(
        _lite(
            "transicoes e sobreposicao",
            [
                {"op": "set_transition", "scene_id": scene_id, "transition_out": "dissolve"},
                {
                    "op": "add_overlay",
                    "overlay_json": json.dumps(
                        {
                            "overlay_id": "overlay_1",
                            "text": "Segue o canal",
                            "start_ms": 1000,
                            "end_ms": 6000,
                        }
                    ),
                },
                {"op": "set_overlay_text", "overlay_id": "overlay_1", "text": "Segue ja"},
                {"op": "remove_overlay", "overlay_id": "overlay_1"},
            ],
        )
    )
    patch = lite_to_full_patch(lite)
    assert [op.op for op in patch.operations] == [
        "set_transition",
        "add_overlay",
        "set_overlay_text",
        "remove_overlay",
    ]
    applied = apply_storyboard_patch(board, patch)
    assert applied.scenes[0].transition_out == "dissolve"
    assert applied.overlays == []
    keep = lite_to_full_patch(
        LitePatch.model_validate(
            _lite(
                "mantem",
                [
                    {
                        "op": "add_overlay",
                        "overlay_json": json.dumps(
                            {
                                "overlay_id": "overlay_9",
                                "text": "Ola",
                                "start_ms": 0,
                                "end_ms": 2000,
                            }
                        ),
                    }
                ],
            )
        )
    )
    kept = apply_storyboard_patch(board, keep)
    assert [o.overlay_id for o in kept.overlays] == ["overlay_9"]
    assert kept.overlays[0].text == "Ola"


def test_lite_to_full_covers_timeline_ops():
    from clipforge_contracts.refinement_lite import LitePatch, lite_to_full_patch

    board = _board()
    assert len(board.scenes) == 4
    first, second = board.scenes[0].scene_id, board.scenes[1].scene_id
    half = board.scenes[0].duration_ms // 2
    lite = LitePatch.model_validate(
        _lite(
            "encurta a primeira, divide a primeira, troca as duas",
            [
                {"op": "set_scene_duration", "scene_id": first, "duration_ms": 3000},
                {"op": "split_scene", "scene_id": first, "at_ms": 1500},
                {"op": "move_scene", "scene_id": second, "direction": -1},
            ],
        )
    )
    patch = lite_to_full_patch(lite)
    assert [op.op for op in patch.operations] == [
        "set_scene_duration",
        "split_scene",
        "move_scene",
    ]
    applied = apply_storyboard_patch(board, patch)
    # Trim applied, split added a scene, move pulled scene_2 before scene_5.
    assert len(applied.scenes) == 5
    assert [s.scene_id for s in applied.scenes] == [
        board.scenes[0].scene_id,
        second,
        "scene_5",
        board.scenes[2].scene_id,
        board.scenes[3].scene_id,
    ]
    assert applied.scenes[0].duration_ms == 1500
    assert applied.scenes[2].duration_ms == 1500
    for scene in applied.scenes:
        for step in scene.animation_sequence:
            assert step.start_ms + step.duration_ms <= scene.duration_ms
    from clipforge_director.idea_director import validate_board_targets

    validate_board_targets(applied)

    with pytest.raises(ValueError, match="1000"):
        lite_to_full_patch(
            LitePatch.model_validate(
                _lite("x", [{"op": "split_scene", "scene_id": first, "at_ms": 500}])
            )
        )
    with pytest.raises(ValueError, match="-1 or 1"):
        lite_to_full_patch(
            LitePatch.model_validate(
                _lite("x", [{"op": "move_scene", "scene_id": first, "direction": 0}])
            )
        )


def test_lite_rejects_bad_transition_and_overlay():
    from clipforge_contracts.refinement_lite import LitePatch, lite_to_full_patch

    with pytest.raises(ValueError, match="transition_out"):
        lite_to_full_patch(
            LitePatch.model_validate(
                _lite("x", [{"op": "set_transition", "scene_id": "scene_1"}])
            )
        )
    with pytest.raises(ValueError, match="not a valid OverlaySpec"):
        lite_to_full_patch(
            LitePatch.model_validate(
                _lite("x", [{"op": "add_overlay", "overlay_json": "{broken"}])
            )
        )


def test_lite_rejects_bad_scene_json_and_empty_ops():
    from clipforge_contracts.refinement_lite import LitePatch, lite_to_full_patch

    with pytest.raises(ValueError, match="not a valid SceneSpec"):
        lite_to_full_patch(
            LitePatch.model_validate(
                _lite("x", [{"op": "add_scene", "scene_json": "{broken"}])
            )
        )
    with pytest.raises(ValueError, match="at least one style field"):
        lite_to_full_patch(
            LitePatch.model_validate(
                _lite(
                    "x",
                    [{"op": "set_text_style", "scene_id": "scene_1", "style": {}}],
                )
            )
        )
    with pytest.raises(ValueError, match="set_scene_text"):
        LitePatch.model_validate(_lite("x", [{"op": "teleport"}]))


class _StubRefinementProvider:
    """Test double for the live provider: deterministic, zero network."""

    last_cost_usd = 0.0

    def __init__(self):
        self.seen_styles: list[str] = []

    def create_patch(self, board, instruction, authorization=None, clarification_context=None):
        self.seen_styles.append(board.scenes[0].text_style.family)
        if "aquele" in instruction:
            return StoryboardPatch.model_validate(
                {
                    "instruction": instruction,
                    "outcome": "clarification",
                    "summary": "Preciso de saber qual texto.",
                    "clarification_question": "Qual cena queres mudar: a 1 ou a 2?",
                    "operations": [],
                }
            )
        return StoryboardPatch.model_validate(
            {
                "instruction": instruction,
                "summary": "Título maior e mais elegante.",
                "operations": [
                    {
                        "op": "set_text_style",
                        "scene_id": board.scenes[0].scene_id,
                        "style": {"family": "serif", "size_scale": 1.3},
                    }
                ],
            }
        )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "mock")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "mock")
    stub = _StubRefinementProvider()
    app = FastAPI()
    app.include_router(
        create_ideas_router(tmp_path / "storage", refinement_provider_factory=lambda: stub)
    )
    client = TestClient(app)
    store = IdeaStore(tmp_path / "storage")
    created = client.post(
        "/api/ideas",
        json={
            "brief": BRIEF,
            "options": {
                "duration_seconds": 20,
                "aspect_ratio": "9:16",
                "fps": 24,
                "style_preset": "cinematic",
                "use_generated_images": False,
                "language": "pt-PT",
            },
        },
    )
    assert created.status_code == 201, created.text
    idea_id = created.json()["idea_id"]
    record = store.get(idea_id)
    record.idea.storyboard = _board()
    from clipforge_contracts.idea import storyboard_hash

    record.idea.storyboard_hash = storyboard_hash(record.idea.storyboard)
    record.status = IdeaStatus.AWAITING_APPROVAL
    record.stage = "awaiting_plan_approval"
    store.save(record)
    return client, idea_id, stub


def test_direct_apply_and_sequential_context(env):
    client, idea_id, stub = env
    proposed = client.post(
        f"/api/ideas/{idea_id}/direct",
        json={"instruction": "Aumenta o título e torna-o elegante.", "approved_cost_usd": 0},
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["pending_patch"]["summary"] == "Título maior e mais elegante."
    # Nothing applied before approval.
    assert body["storyboard"]["scenes"][0].get("text_style", {}).get("family", "sans") == "sans"

    applied = client.post(f"/api/ideas/{idea_id}/direct/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json()["storyboard"]["scenes"][0]["text_style"]["family"] == "serif"
    assert applied.json()["pending_patch"] is None

    # Sequential command: the director receives the updated board.
    client.post(
        f"/api/ideas/{idea_id}/direct",
        json={"instruction": "Agora ainda maior.", "approved_cost_usd": 0},
    )
    assert stub.seen_styles[-1] == "serif"


def test_direct_clarification_and_reject(env):
    client, idea_id, _ = env
    asked = client.post(
        f"/api/ideas/{idea_id}/direct",
        json={"instruction": "Muda aquele texto para azul.", "approved_cost_usd": 0},
    )
    assert asked.status_code == 200, asked.text
    assert "Qual cena" in asked.json()["pending_clarification_question"]
    assert asked.json()["pending_patch"] is None

    client.post(
        f"/api/ideas/{idea_id}/direct",
        json={"instruction": "Aumenta o título.", "approved_cost_usd": 0},
    )
    rejected = client.post(f"/api/ideas/{idea_id}/direct/reject")
    assert rejected.json()["pending_patch"] is None
    assert rejected.json()["storyboard"]["scenes"][0]["text_style"]["family"] == "sans"
