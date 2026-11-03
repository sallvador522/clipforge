"""Idea-to-video storyboard contract and creative director tests (mocked only).

No request leaves the machine: the live provider path is exercised through
httpx.MockTransport with exactly one POST asserted per call.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from clipforge_contracts import (
    CorrectionType,
    MockQualityCritic,
    QualityReview,
    SceneReview,
    Verdict,
)
from clipforge_contracts.storyboard import AnimationPrimitive, Storyboard
from clipforge_director import (
    CreativeDirectorProvider,
    LiveCallNotAuthorizedError,
    MockCreativeDirector,
    apply_correction,
    asteroid_reels_storyboard,
)
from clipforge_director.spark import DirectorValidationError

IDEA = "E se um asteroide gigante atingisse a Terra?"


def test_asteroid_fixture_is_valid_reels_board():
    board = asteroid_reels_storyboard()
    assert board.duration_seconds == 20
    assert board.aspect_ratio == "9:16"
    assert len(board.scenes) == 4
    assert sum(s.duration_ms for s in board.scenes) == 20000
    assert board.total_frames == 20 * board.output_fps
    assert {a.asset_id for a in board.asset_plan} == {
        "asset_space",
        "asset_entry",
        "asset_impact",
        "asset_chart_bg",
    }


def test_test_a_fixture_is_valid_programmatic_board():
    """TEST A Promo: 15 s, 9:16, 3 scenes, validated by the same contract."""
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "idea_to_video" / "test_a_promo.json").read_text(
            encoding="utf-8"
        )
    )
    board = Storyboard.model_validate(raw)
    assert board.duration_seconds == 15
    assert board.aspect_ratio == "9:16"
    assert [s.scene_id for s in board.scenes] == ["scene_1", "scene_2", "scene_3"]
    assert sum(s.duration_ms for s in board.scenes) == 15000
    assert board.total_frames == 15 * board.output_fps


def test_scene_durations_must_cover_project_duration():
    raw = asteroid_reels_storyboard().model_dump(mode="json")
    raw["scenes"][0]["duration_ms"] = 4000
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)


def test_step_overrun_rejected():
    raw = asteroid_reels_storyboard().model_dump(mode="json")
    raw["scenes"][0]["animation_sequence"][0]["start_ms"] = 4900
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)


def test_unknown_primitive_rejected():
    raw = asteroid_reels_storyboard().model_dump(mode="json")
    raw["scenes"][0]["animation_sequence"][0]["primitive"] = "free_form_js"
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)


def test_asset_unknown_scene_rejected():
    raw = asteroid_reels_storyboard().model_dump(mode="json")
    raw["asset_plan"][0]["scene_ids"] = ["scene_99"]
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)


def test_mock_director_echoes_idea():
    board = MockCreativeDirector().create_storyboard(IDEA)
    assert board.user_request == IDEA
    assert board.duration_seconds == 20


def test_quality_review_pass_and_correction_gate():
    review = MockQualityCritic().review_draft("Asteroid")
    assert review.overall_verdict is Verdict.PASS
    assert review.project_title == "Asteroid"
    assert not review.needs_revision

    fixable = QualityReview(
        project_title="Asteroid",
        overall_verdict=Verdict.NEEDS_FIX,
        scene_reviews=[
            SceneReview(
                scene_id="scene_1",
                severity="warning",
                timestamp_ms=2500,
                issue_category="text_readability",
                explanation="Title fades too fast.",
                suggested_fix="Extend the title reveal by 500ms.",
                correction_type=CorrectionType.TEXT_FIX,
            )
        ],
    )
    assert fixable.needs_revision and fixable.auto_fixable

    blocked = QualityReview(
        project_title="Asteroid",
        overall_verdict=Verdict.NEEDS_FIX,
        scene_reviews=[
            SceneReview(
                scene_id="scene_2",
                severity="error",
                timestamp_ms=7000,
                issue_category="missing_asset",
                explanation="Entry backdrop does not match the scene.",
                correction_type=CorrectionType.ASSET_REGENERATION,
                requires_asset_regeneration=True,
            )
        ],
    )
    assert blocked.needs_revision and not blocked.auto_fixable


def test_one_revision_cycle_applies_critic_patch():
    """The bounded correction loop: critic flags -> validated patch -> revalid storyboard."""
    board = asteroid_reels_storyboard()
    review = MockQualityCritic(
        QualityReview(
            project_title=board.project_title,
            overall_verdict=Verdict.NEEDS_FIX,
            scene_reviews=[
                SceneReview(
                    scene_id="scene_1",
                    severity="warning",
                    timestamp_ms=500,
                    issue_category="timing",
                    explanation="Title reveal is too short.",
                    suggested_fix="Extend to 2000ms.",
                    correction_type=CorrectionType.TEXT_FIX,
                )
            ],
        )
    ).review_draft(board.project_title)
    assert review.needs_revision and review.auto_fixable

    revised = apply_correction(
        board,
        {
            "scene_id": "scene_1",
            "steps": [
                {"primitive": "text_reveal", "target": "title", "start_ms": 500, "duration_ms": 2000},
                {"primitive": "camera_zoom", "target": "camera", "start_ms": 0, "duration_ms": 5000,
                 "params": {"from_scale": 1.0, "to_scale": 1.15}},
            ],
        },
    )
    # Revalidated storyboard: durations still cover the project, steps fit.
    assert revised.duration_seconds == 20
    assert sum(s.duration_ms for s in revised.scenes) == 20000


def test_apply_correction_replaces_steps():
    board = asteroid_reels_storyboard()
    patched = apply_correction(
        board,
        {
            "scene_id": "scene_1",
            "steps": [
                {
                    "primitive": "fade",
                    "target": "asteroid",
                    "start_ms": 0,
                    "duration_ms": 2000,
                }
            ],
        },
    )
    scene = next(s for s in patched.scenes if s.scene_id == "scene_1")
    assert [(s.primitive, s.duration_ms) for s in scene.animation_sequence] == [
        (AnimationPrimitive.FADE, 2000)
    ]
    # Other scenes untouched.
    assert len(patched.scenes) == 4


def test_apply_correction_rejects_unknown_scene_and_bad_primitive():
    board = asteroid_reels_storyboard()
    with pytest.raises(ValueError):
        apply_correction(board, {"scene_id": "scene_99", "steps": []})
    with pytest.raises((ValueError, ValidationError)):
        apply_correction(
            board,
            {
                "scene_id": "scene_1",
                "steps": [{"primitive": "eval_js", "target": "x", "start_ms": 0, "duration_ms": 500}],
            },
        )


def _board_json(idea: str) -> dict:
    board = asteroid_reels_storyboard().model_copy(update={"user_request": idea})
    return board.model_dump(mode="json")


def test_live_provider_single_post_and_echo_check():
    from clipforge_director.spark import CHAT_COMPLETIONS_PATH

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path == CHAT_COMPLETIONS_PATH
        body = _board_json(IDEA)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": __import__("json").dumps(body)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1500, "completion_tokens": 2500, "total_tokens": 4000},
            },
        )

    from test_director_spark import _TestAuthorization

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
    provider = CreativeDirectorProvider(
        api_key="k", playbook_text="x", capability_summary="storyboard-only", client=client
    )
    board = provider.create_storyboard(IDEA, authorization=_TestAuthorization("director"))
    assert calls["n"] == 1
    assert board.project_title and board.user_request == IDEA
    assert provider.last_usage is not None and provider.last_usage.total_tokens == 4000


def test_live_provider_rejects_echo_mismatch():
    import json as _json

    def handler(request: httpx.Request) -> httpx.Response:
        body = _board_json("a different idea")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _json.dumps(body)}, "finish_reason": "stop"}]},
        )

    from test_director_spark import _TestAuthorization

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai")
    provider = CreativeDirectorProvider(
        api_key="k", playbook_text="x", capability_summary="storyboard-only", client=client
    )
    with pytest.raises(DirectorValidationError):
        provider.create_storyboard(IDEA, authorization=_TestAuthorization("director"))


def test_live_provider_requires_authorization():
    provider = CreativeDirectorProvider(api_key="k", playbook_text="x", capability_summary="storyboard-only")
    with pytest.raises(LiveCallNotAuthorizedError):
        provider.create_storyboard(IDEA, authorization=None)
    provider.close()
