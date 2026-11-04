"""Contracts, mock director and pricing for the idea-to-video flow (offline)."""

from __future__ import annotations

import pytest

from clipforge_contracts.idea import (
    IdeaOptions,
    brief_hash,
    scene_count_for,
    storyboard_hash,
)
from clipforge_contracts.storyboard import AnimationPrimitive, OverlaySpec
from clipforge_director.idea_director import (
    MAX_PLATES,
    MockIdeaDirector,
    build_assets,
    idea_modes,
    options_instructions,
    validate_board_for_options,
    validate_board_targets,
    validate_overlay_assets,
)
from clipforge_director.pricing import (
    DEFAULT_CAP_USD,
    DEFAULT_IMAGE_USD,
    DEFAULT_STORYBOARD_HIGH_USD,
    DEFAULT_STORYBOARD_USD,
    DEFAULT_STORYBOARD_XHIGH_USD,
    estimate_before_plan,
    estimate_from_storyboard,
    storyboard_price_usd,
)

BRIEF = "Como seria se os dinossauros vivessem hoje entre nós?"


def test_options_dimensions_and_frames():
    portrait = IdeaOptions(duration_seconds=20, aspect_ratio="9:16", fps=24)
    assert (portrait.width, portrait.height) == (720, 1280)
    assert portrait.frame_count == 480
    landscape = IdeaOptions(duration_seconds=10, aspect_ratio="16:9", fps=30)
    assert (landscape.width, landscape.height) == (1280, 720)
    assert landscape.frame_count == 300
    assert scene_count_for(20) == 4
    assert scene_count_for(10) == 3
    assert scene_count_for(5) == 2


def test_brief_hash_is_stable_and_covers_options():
    options = IdeaOptions()
    first = brief_hash(BRIEF, options)
    assert first == brief_hash(f"  {BRIEF}  ", options)
    assert first != brief_hash(BRIEF, options.model_copy(update={"fps": 30}))
    assert first != brief_hash("Outra ideia completamente diferente.", options)
    assert len(first) == 64


def test_options_instructions_demand_exact_duration_sum():
    # Regression: "aim for about X seconds" let the live director return
    # 25000 ms for a 20 s project (and 75000 ms for 60 s) — paid, then
    # rejected. The instruction must state the exact required sum.
    for duration in (20, 25, 60):
        instructions = options_instructions(IdeaOptions(duration_seconds=duration))
        assert str(duration * 1000) in instructions
        assert "MUST sum to exactly" in instructions


def test_mock_director_builds_a_valid_board_for_each_option_set():
    director = MockIdeaDirector()
    for options in (
        IdeaOptions(duration_seconds=20, aspect_ratio="9:16", fps=24),
        IdeaOptions(duration_seconds=10, aspect_ratio="16:9", fps=30, style_preset="product"),
        IdeaOptions(duration_seconds=5, aspect_ratio="9:16", fps=12, use_generated_images=False),
    ):
        board = director.create_storyboard(BRIEF, options)
        assert board.user_request == BRIEF
        assert board.duration_seconds == options.duration_seconds
        assert board.aspect_ratio == options.aspect_ratio
        assert board.output_fps == options.fps
        assert sum(scene.duration_ms for scene in board.scenes) == options.duration_seconds * 1000
        assert len(board.scenes) == scene_count_for(options.duration_seconds)
        assert board.scenes[0].on_screen_text[0]
        for scene in board.scenes:
            assert scene.animation_sequence
            for step in scene.animation_sequence:
                assert step.primitive in set(AnimationPrimitive)
                assert step.start_ms + step.duration_ms <= scene.duration_ms
        if options.use_generated_images:
            assert len(board.asset_plan) == len(board.scenes)
        else:
            assert board.asset_plan == []


def test_build_assets_keeps_one_plate_per_scene_and_respects_cap():
    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    assets = build_assets(board, options)
    assert len(assets) == len(board.scenes) <= MAX_PLATES
    seen: set[str] = set()
    for asset in assets:
        assert not (set(asset.scene_ids) & seen)
        seen.update(asset.scene_ids)
        assert asset.orientation == "portrait"
        assert asset.prompt_hash and len(asset.prompt_hash) == 64
        assert "No text" in asset.prompt
        assert "no recognizable real people" in asset.prompt

    landscape = IdeaOptions(aspect_ratio="16:9")
    landscape_board = MockIdeaDirector().create_storyboard(BRIEF, landscape)
    assert all(a.orientation == "landscape" for a in build_assets(landscape_board, landscape))


def test_build_assets_is_empty_when_images_are_disabled():
    options = IdeaOptions(use_generated_images=False)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    assert build_assets(board, options) == []


def test_validate_board_rejects_options_it_does_not_match():
    options = IdeaOptions(duration_seconds=20, aspect_ratio="9:16", fps=24)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    validate_board_for_options(board, BRIEF, options)

    # ADR-036: a different requested duration never rejects the board; the
    # delivered scene durations define the final video length.
    validate_board_for_options(
        board, BRIEF, options.model_copy(update={"duration_seconds": 10})
    )
    with pytest.raises(ValueError, match="aspect ratio"):
        validate_board_for_options(
            board, BRIEF, options.model_copy(update={"aspect_ratio": "16:9"})
        )
    with pytest.raises(ValueError, match="fps"):
        validate_board_for_options(board, BRIEF, options.model_copy(update={"fps": 30}))
    with pytest.raises(ValueError, match="user_request"):
        validate_board_for_options(board, "Outro pedido diferente.", options)


def test_overlay_contract_and_missing_assets():
    options = IdeaOptions(duration_seconds=20)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    total_ms = sum(s.duration_ms for s in board.scenes)

    text = OverlaySpec(overlay_id="overlay_1", kind="text", text="Segue", start_ms=0, end_ms=1000)
    assert text.kind == "text"
    with pytest.raises(ValueError, match="needs text"):
        OverlaySpec(overlay_id="overlay_2", kind="text", text="", start_ms=0, end_ms=1000)
    with pytest.raises(ValueError, match="asset_id"):
        OverlaySpec(overlay_id="overlay_3", kind="image", start_ms=0, end_ms=1000)
    image = OverlaySpec(
        overlay_id="overlay_4", kind="image", asset_id="asset_scene_1", start_ms=0, end_ms=1000
    )

    board = board.model_copy(update={"overlays": [text, image]})
    assert validate_overlay_assets(board, {"asset_scene_1"}) == []
    assert validate_overlay_assets(board, set()) == ["overlay_4"]
    assert validate_overlay_assets(board, {"other"}) == ["overlay_4"]

    bad = board.model_copy(
        update={
            "overlays": [
                OverlaySpec(
                    overlay_id="overlay_x", kind="text", text="x",
                    start_ms=0, end_ms=total_ms + 5000,
                )
            ]
        }
    )
    from clipforge_contracts.storyboard import Storyboard

    with pytest.raises(ValueError, match="overruns"):
        Storyboard.model_validate(bad.model_dump(mode="json"))


def test_storyboard_hash_is_deterministic_and_sensitive():
    options = IdeaOptions()
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    first = storyboard_hash(board)
    assert first == storyboard_hash(board.model_copy(deep=True))
    changed = board.model_copy(update={"project_title": "Outro título"})
    assert storyboard_hash(changed) != first


def test_idea_modes_default_to_mock_and_require_explicit_live(monkeypatch):
    monkeypatch.delenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", raising=False)
    monkeypatch.delenv("CLIPFORGE_IDEA_IMAGE_MODE", raising=False)
    monkeypatch.delenv("CLIPFORGE_CREATIVE_DIRECTOR_EFFORT", raising=False)
    assert idea_modes() == {"director": "mock", "image": "mock", "effort": "medium"}

    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "LIVE")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "live")
    assert idea_modes() == {"director": "live", "image": "live", "effort": "medium"}

    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_EFFORT", "xhigh")
    assert idea_modes() == {"director": "live", "image": "live", "effort": "xhigh"}

    # A typo can never enable a paid provider.
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "liv")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "true")
    assert idea_modes() == {"director": "mock", "image": "mock", "effort": "medium"}


def test_creative_effort_defaults_and_rejects_unknown(monkeypatch):
    from clipforge_director.idea_director import creative_effort

    monkeypatch.delenv("CLIPFORGE_CREATIVE_DIRECTOR_EFFORT", raising=False)
    assert creative_effort() == "medium"
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_EFFORT", "XHIGH")
    assert creative_effort() == "xhigh"
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_EFFORT", "ultra")
    with pytest.raises(RuntimeError, match="verified values"):
        creative_effort()


def test_estimates_are_zero_in_mock_and_priced_in_live(monkeypatch):
    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    mock = estimate_before_plan(options, director_mode="mock", image_mode="mock")
    assert mock.total_usd == 0.0
    assert mock.image_count == 4
    assert mock.cap_usd == DEFAULT_CAP_USD

    live = estimate_before_plan(options, director_mode="live", image_mode="live")
    assert live.storyboard_usd == DEFAULT_STORYBOARD_USD
    assert live.images_usd == pytest.approx(4 * DEFAULT_IMAGE_USD)
    assert live.total_usd == pytest.approx(DEFAULT_STORYBOARD_USD + 4 * DEFAULT_IMAGE_USD)

    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    selected = estimate_from_storyboard(
        board, options, director_mode="live", image_mode="live", selected_assets=2
    )
    assert selected.image_count == 2
    assert selected.images_usd == pytest.approx(2 * DEFAULT_IMAGE_USD)

    monkeypatch.setenv("CLIPFORGE_IDEA_CAP_USD", "0.01")
    capped = estimate_before_plan(options, director_mode="live", image_mode="live")
    assert capped.cap_usd == pytest.approx(0.01)


def test_live_director_timeout_scales_with_effort(monkeypatch):
    from clipforge_director.idea_director import create_live_director

    monkeypatch.setenv("MODEL_API_KEY", "test-key-never-sent")
    assert create_live_director("medium")._timeout_seconds == 60.0
    assert create_live_director("high")._timeout_seconds == 300.0
    assert create_live_director("xhigh")._timeout_seconds == 600.0
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        monkeypatch.delenv("MODEL_API_KEY")
        create_live_director("high")


def test_xhigh_storyboard_price_is_a_documented_ceiling(monkeypatch):
    assert storyboard_price_usd() == DEFAULT_STORYBOARD_USD
    assert storyboard_price_usd("high") == DEFAULT_STORYBOARD_HIGH_USD
    assert storyboard_price_usd("xhigh") == DEFAULT_STORYBOARD_XHIGH_USD
    assert DEFAULT_STORYBOARD_USD < DEFAULT_STORYBOARD_HIGH_USD < DEFAULT_STORYBOARD_XHIGH_USD

    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    high = estimate_before_plan(
        options, director_mode="live", image_mode="live", effort="high"
    )
    assert high.storyboard_usd == pytest.approx(DEFAULT_STORYBOARD_HIGH_USD)
    assert high.total_usd <= high.cap_usd

    xhigh = estimate_before_plan(
        options, director_mode="live", image_mode="live", effort="xhigh"
    )
    assert xhigh.storyboard_usd == pytest.approx(DEFAULT_STORYBOARD_XHIGH_USD)
    assert xhigh.total_usd <= xhigh.cap_usd

    monkeypatch.setenv("CLIPFORGE_PRICE_STORYBOARD_XHIGH_USD", "0.05")
    assert storyboard_price_usd("xhigh") == pytest.approx(0.05)


def _board_with_replaced_step(step_index: int, **updates):
    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    scene = board.scenes[0]
    steps = list(scene.animation_sequence)
    steps[step_index] = steps[step_index].model_copy(update=updates)
    board.scenes[0] = scene.model_copy(update={"animation_sequence": steps})
    return board


def test_validate_board_targets_accepts_the_mock_board():
    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    validate_board_targets(board)


def test_validate_board_targets_rejects_descriptive_targets():
    # Regression: a live board targeted "titulo de abertura" instead of the
    # engine id "title" and rendered a fully static scene.
    board = _board_with_replaced_step(1, target="titulo de abertura")
    with pytest.raises(ValueError, match="unknown target"):
        validate_board_targets(board)

    # Camera steps ignore their target (they move the backdrop), so any
    # label is accepted there as long as the params move.
    board = _board_with_replaced_step(0, target="ceu com asteroide")
    validate_board_targets(board)


def test_validate_board_targets_rejects_a_static_scene():
    options = IdeaOptions(duration_seconds=5, use_generated_images=False)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    scene = board.scenes[0]
    noop = scene.animation_sequence[0].model_copy(
        update={
            "primitive": AnimationPrimitive.CAMERA_PAN,
            "target": "camera",
            "params": {},
        }
    )
    board.scenes[0] = scene.model_copy(update={"animation_sequence": [noop]})
    with pytest.raises(ValueError, match="at least 2 motion-producing steps"):
        validate_board_targets(board)


def test_validate_board_targets_enforces_fixed_targets_and_line_range():
    board = _board_with_replaced_step(
        1, primitive=AnimationPrimitive.FLASH, target="clarão"
    )
    with pytest.raises(ValueError, match="must target 'flash'"):
        validate_board_targets(board)

    board = _board_with_replaced_step(1, target="line5")
    with pytest.raises(ValueError, match="has no text line"):
        validate_board_targets(board)


def test_validate_board_targets_enforces_motion_budget():
    options = IdeaOptions(duration_seconds=20, use_generated_images=True)

    # Single step per scene: valid target and real motion, but lonely.
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    solo = board.scenes[0].animation_sequence[0].model_copy()
    board.scenes[0] = board.scenes[0].model_copy(update={"animation_sequence": [solo]})
    with pytest.raises(ValueError, match="at least 2 motion-producing steps"):
        validate_board_targets(board)

    # Motion that quits early: static tail longer than 500 ms.
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    scene = board.scenes[0]
    early = scene.animation_sequence[1].model_copy(
        update={"start_ms": 0, "duration_ms": 600}
    )
    early2 = scene.animation_sequence[2].model_copy(
        update={"start_ms": 0, "duration_ms": 600}
    )
    still = scene.animation_sequence[0].model_copy(
        update={"duration_ms": 1000, "params": {"from_scale": 1.0, "to_scale": 1.08}}
    )
    board.scenes[0] = scene.model_copy(update={"animation_sequence": [still, early, early2]})
    with pytest.raises(ValueError, match="ends too early"):
        validate_board_targets(board)


def test_validate_board_targets_rejects_unknown_ease_and_enforces_diversity():
    options = IdeaOptions(duration_seconds=5, use_generated_images=False)

    board = _board_with_replaced_step(1, ease="outBounce")
    validate_board_targets(board)

    board = _board_with_replaced_step(1, ease="superSmooth")
    with pytest.raises(ValueError, match="unknown ease"):
        validate_board_targets(board)

    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    for scene in board.scenes:
        fade = scene.animation_sequence[0].model_copy(
            update={"primitive": AnimationPrimitive.FADE, "target": "title"}
        )
        board.scenes[board.scenes.index(scene)] = scene.model_copy(
            update={"animation_sequence": [fade, fade.model_copy()]}
        )
    with pytest.raises(ValueError, match="at least 3 distinct"):
        validate_board_targets(board)


def test_validate_board_targets_accepts_new_text_primitives():
    options = IdeaOptions(duration_seconds=5, use_generated_images=False)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    scene = board.scenes[0]
    extra = scene.animation_sequence[0].model_copy(
        update={"primitive": AnimationPrimitive.TRACKING, "target": "title", "params": {"spread": 0.4}}
    )
    extra2 = scene.animation_sequence[0].model_copy(
        update={"primitive": AnimationPrimitive.MASK_REVEAL, "target": "line1"}
    )
    board.scenes[0] = scene.model_copy(
        update={"animation_sequence": [scene.animation_sequence[0], extra, extra2]}
    )
    validate_board_targets(board)

    bad = extra.model_copy(update={"params": {"spread": "wide"}})
    board.scenes[0] = scene.model_copy(
        update={"animation_sequence": [scene.animation_sequence[0], bad]}
    )
    with pytest.raises(ValueError, match="must be numeric"):
        validate_board_targets(board)


def test_build_assets_supports_one_backdrop_plus_one_foreground():
    from clipforge_contracts.storyboard import AssetSpec

    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    plan = list(board.asset_plan)
    plan.append(
        AssetSpec(
            asset_id="asset_scene_1_fg",
            scene_ids=["scene_1"],
            description="Close dinosaurs in the lower frame",
            orientation="portrait",
            role="foreground",
        )
    )
    board = board.model_copy(update={"asset_plan": plan})

    assets = build_assets(board, options)
    by_scene_1 = [a for a in assets if "scene_1" in a.scene_ids]
    assert [(a.asset_id, a.role) for a in by_scene_1] == [
        ("asset_scene_1", "background"),
        ("asset_scene_1_fg", "foreground"),
    ]
    fg = next(a for a in assets if a.asset_id == "asset_scene_1_fg")
    assert "band" in fg.prompt or "foreground" in fg.prompt.lower()


def test_build_assets_rejects_duplicate_role_per_scene():
    from clipforge_contracts.storyboard import AssetSpec

    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    plan = list(board.asset_plan)
    plan.append(
        AssetSpec(
            asset_id="asset_scene_1_dup",
            scene_ids=["scene_1"],
            description="Another backdrop",
            orientation="portrait",
            role="background",
        )
    )
    board = board.model_copy(update={"asset_plan": plan})

    assets = build_assets(board, options)
    assert [a.asset_id for a in assets].count("asset_scene_1_dup") == 0
    assert len([a for a in assets if "scene_1" in a.scene_ids]) == 1


def test_validate_board_rejects_too_many_plates_per_scene():
    from clipforge_contracts.storyboard import AssetSpec

    options = IdeaOptions(duration_seconds=20, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    validate_board_for_options(board, BRIEF, options)

    plan = list(board.asset_plan)
    plan.append(
        AssetSpec(
            asset_id="asset_scene_1_fg",
            scene_ids=["scene_1"],
            description="Foreground",
            orientation="portrait",
            role="foreground",
        )
    )
    board = board.model_copy(update={"asset_plan": plan})
    validate_board_for_options(board, BRIEF, options)

    plan.append(
        AssetSpec(
            asset_id="asset_scene_1_extra",
            scene_ids=["scene_1"],
            description="Third plate",
            orientation="portrait",
            role="foreground",
        )
    )
    board = board.model_copy(update={"asset_plan": plan})
    with pytest.raises(ValueError, match="at most one backdrop"):
        validate_board_for_options(board, BRIEF, options)

    plan[-1] = plan[-1].model_copy(update={"scene_ids": ["scene_404"]})
    board = board.model_copy(update={"asset_plan": plan})
    with pytest.raises(ValueError, match="unknown scene_404"):
        validate_board_for_options(board, BRIEF, options)
