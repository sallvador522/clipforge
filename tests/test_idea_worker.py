"""Idea worker: mock plates, store claims and real encode/QA (no Playwright)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from clipforge_contracts.idea import AssetStatus, IdeaJobRecord, IdeaState, IdeaStatus
from clipforge_jobs.idea_store import IdeaNotFoundError, IdeaStore, new_idea_id
from clipforge_worker.idea_processor import IdeaProcessor
from clipforge_worker.idea_renderer import (
    IdeaRenderError,
    _url_ok,
    encode,
    frame_time_ms,
    qa_frames,
    sample_time_ms,
    verify_output,
)

BRIEF = "Como seria se os dinossauros vivessem hoje entre nós?"


def _has_ffmpeg() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
    except OSError:
        return False


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "mock")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "mock")
    monkeypatch.setenv("CLIPFORGE_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CLIPFORGE_STUDIO_URL", "http://127.0.0.1:1")
    store = IdeaStore(tmp_path / "storage")
    processor = IdeaProcessor(store)
    return store, processor


def _queued_record(**overrides) -> IdeaJobRecord:
    return IdeaJobRecord(
        idea_id=new_idea_id(),
        status=IdeaStatus.QUEUED,
        stage="planning",
        idea=IdeaState(brief=BRIEF),
        **overrides,
    )


def test_store_claim_is_exclusive_and_releasable(env):
    store, _ = env
    record = _queued_record()
    store.create(record)
    assert store.claim(record.idea_id) is True
    assert store.claim(record.idea_id) is False
    assert store.is_claimed(record.idea_id) is True
    store.release(record.idea_id)
    assert store.claim(record.idea_id) is True

    with pytest.raises(IdeaNotFoundError):
        store.get("idea_not_a_real_id")
    with pytest.raises(IdeaNotFoundError):
        store.get("../../etc/passwd")


def test_processor_plans_in_mock_and_builds_assets(env):
    store, processor = env
    record = _queued_record()
    record.idea.estimate = None
    store.create(record)

    from clipforge_contracts.idea import IdeaApproval, brief_hash

    record.idea.approvals.append(
        IdeaApproval(
            scope="storyboard",
            approved_usd=0.0,
            provider_modes={"director": "mock", "image": "mock"},
            brief_hash=brief_hash(record.idea.brief, record.idea.options),
        )
    )
    store.save(record)

    assert processor.run_once() is True
    planned = store.get(record.idea_id)
    assert planned.status == IdeaStatus.AWAITING_APPROVAL
    assert planned.stage == "awaiting_plan_approval"
    assert planned.idea.storyboard is not None
    assert len(planned.idea.assets) == 4
    assert planned.idea.spent_usd == 0.0
    assert all(asset.status.value == "planned" for asset in planned.idea.assets)
    assert store.claim_path(record.idea_id).exists() is False


def test_processor_generates_mock_plates_without_spending(env, monkeypatch):
    store, processor = env
    record = _queued_record()
    from clipforge_contracts.idea import AssetStatus, IdeaApproval, brief_hash

    record.idea.approvals.append(
        IdeaApproval(
            scope="storyboard",
            approved_usd=0.0,
            provider_modes={"director": "mock", "image": "mock"},
            brief_hash=brief_hash(record.idea.brief, record.idea.options),
        )
    )
    store.create(record)
    assert processor.run_once() is True

    planned = store.get(record.idea_id)
    selected = [asset.asset_id for asset in planned.idea.assets[:2]]
    approved = planned.model_copy(deep=True)
    approved.status = IdeaStatus.QUEUED
    approved.stage = "generating_assets"
    approved.idea.approvals.append(
        IdeaApproval(
            scope="assets",
            approved_usd=0.0,
            provider_modes={"director": "mock", "image": "mock"},
            brief_hash=brief_hash(approved.idea.brief, approved.idea.options),
            asset_ids=selected,
            prompt_hashes={
                asset.asset_id: asset.prompt_hash
                for asset in approved.idea.assets
                if asset.asset_id in selected
            },
        )
    )
    for asset in approved.idea.assets:
        asset.status = (
            AssetStatus.APPROVED if asset.asset_id in selected else AssetStatus.SKIPPED
        )
    store.save(approved)

    # Stop before the browser capture: this test covers planning + plates only.
    rendered: list[str] = []
    monkeypatch.setattr(processor, "_render", lambda record: rendered.append(record.idea_id))

    assert processor.run_once() is True
    generated = store.get(record.idea_id)
    assert rendered == [record.idea_id]
    assert generated.idea.spent_usd == 0.0
    for asset in generated.idea.assets:
        if asset.asset_id in selected:
            assert asset.status == AssetStatus.GENERATED
            assert asset.is_mock is True
            assert asset.width == 720 and asset.height == 1280
            path = store.asset_path(record.idea_id, asset.asset_id)
            assert path.is_file() and path.stat().st_size > 0
            assert asset.sha256
        else:
            assert asset.status == AssetStatus.SKIPPED


def test_encode_and_verify_produces_a_real_mp4(tmp_path):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg is not available")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for index in range(12):
        frame = np.full((36, 64, 3), (index * 15 + 20, 40, 90), dtype=np.uint8)
        assert cv2.imwrite(str(frames_dir / f"frame_{index:05d}.png"), frame)

    checks = qa_frames(frames_dir, expected=12)
    assert checks == {
        "captured": 12,
        "missing": 0,
        "black": 0,
        "frozen_frames": 0,
        "frozen_runs": 0,
    }

    output = tmp_path / "out.mp4"
    encode(frames_dir, output, fps=12, width=64, height=36)
    report = verify_output(output, width=64, height=36, fps=12, expected_frames=12)
    assert report["width"] == 64
    assert report["height"] == 36
    assert report["frame_count"] == 12
    assert report["pix_fmt"] == "yuv420p"
    assert report["codec"] == "h264"
    assert report["bytes"] > 0
    assert len(report["sha256"]) == 64


def test_verify_output_rejects_a_wrong_frame_count(tmp_path):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg is not available")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for index in range(8):
        frame = np.full((36, 64, 3), (index * 20 + 10, 60, 30), dtype=np.uint8)
        cv2.imwrite(str(frames_dir / f"frame_{index:05d}.png"), frame)
    output = tmp_path / "out.mp4"
    encode(frames_dir, output, fps=8, width=64, height=36)

    with pytest.raises(IdeaRenderError) as excinfo:
        verify_output(output, width=64, height=36, fps=8, expected_frames=9)
    assert excinfo.value.code == "render_not_verified"


def test_qa_flags_missing_and_black_frames(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    black = np.zeros((24, 32, 3), dtype=np.uint8)
    for index in range(3):
        cv2.imwrite(str(frames_dir / f"frame_{index:05d}.png"), black)
    checks = qa_frames(frames_dir, expected=5)
    assert checks["captured"] == 3
    assert checks["missing"] == 2
    assert checks["black"] == 3


def test_asset_paths_cannot_escape_the_idea_directory(env):
    store, _ = env
    record = _queued_record()
    store.create(record)
    with pytest.raises(IdeaNotFoundError):
        store.asset_path(record.idea_id, "asset_../../escape")
    assert store.asset_path(record.idea_id, "asset_scene_1").parent.name == "assets"


def test_frame_times_sample_centres_and_avoid_boundaries():    # 24 fps, 20 s: frame 0 starts at 20 ms (not 0), frame 120 lands at
    # 5020 ms (not the 5000 ms scene boundary that captured a flash frame).
    assert frame_time_ms(0, 24, 20000) == 20
    assert frame_time_ms(120, 24, 20000) == 5020
    assert frame_time_ms(479, 24, 20000) == 19979
    assert frame_time_ms(0, 30, 1000) < 1000


def test_sample_time_clamps_to_the_engine_timeline():
    # Regression: a board whose last animation ends at 19500 stalled the
    # old check (seek 19520 read back 19500). Sampling clamps instead.
    assert sample_time_ms(0, 24, 20000, 20000) == 20
    assert sample_time_ms(468, 24, 20000, 20000) == 19520
    assert sample_time_ms(468, 24, 20000, 19500) == 19500
    assert sample_time_ms(479, 24, 20000, 19500) == 19500
    with pytest.raises(IdeaRenderError):
        sample_time_ms(0, 24, 20000, 0)


def test_url_ok_uses_get_not_head(tmp_path):
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    (tmp_path / "plate.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _url_ok(f"http://127.0.0.1:{port}/plate.png") is True
        assert _url_ok(f"http://127.0.0.1:{port}/missing.png") is False
    finally:
        server.shutdown()
        thread.join()


def test_render_fails_fast_on_a_static_board(env):
    from clipforge_contracts.idea import IdeaOptions, storyboard_hash
    from clipforge_contracts.storyboard import AnimationPrimitive
    from clipforge_director.idea_director import MockIdeaDirector

    store, processor = env
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

    record = _queued_record()
    record.status = IdeaStatus.QUEUED
    record.stage = "rendering"
    record.idea.options = options
    record.idea.storyboard = board
    record.idea.storyboard_hash = storyboard_hash(board)
    record.idea.assets = []
    store.create(record)

    # The pre-check runs before any browser launch, so no Playwright is needed.
    IdeaProcessor._render(processor, store.get(record.idea_id))

    failed = store.get(record.idea_id)
    assert failed.status == IdeaStatus.FAILED
    assert failed.error is not None and failed.error.code == "storyboard_static"


def _mock_plate(path: Path, hue: int = 20) -> None:
    frame = np.full((128, 72, 3), (30, hue, 160), dtype=np.uint8)
    assert cv2.imwrite(str(path), frame)


def _make_mp4(path: Path, frames: int = 12, fps: int = 12) -> None:
    frames_dir = path.parent / "src_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        frame = np.full((36, 64, 3), (index * 15 + 20, 40, 90), dtype=np.uint8)
        cv2.imwrite(str(frames_dir / f"frame_{index:05d}.png"), frame)
    encode(frames_dir, path, fps=fps, width=64, height=36)


def test_build_idea_srt_has_one_cue_per_scene():
    from clipforge_contracts.idea import IdeaOptions
    from clipforge_director.idea_director import MockIdeaDirector
    from clipforge_worker.idea_publish import build_idea_srt

    board = MockIdeaDirector().create_storyboard(
        BRIEF, IdeaOptions(duration_seconds=5, use_generated_images=False)
    )
    raw = build_idea_srt(board).decode("utf-8")
    assert raw.count("-->") == 2
    assert "00:00:00,000 --> 00:00:02,500" in raw
    assert "00:00:02,500 --> 00:00:05,000" in raw
    assert all(line.strip() for line in raw.splitlines() if line.strip() and "-->" not in line and not line.strip().isdigit())


def test_probe_video_unrestricted_reads_beyond_mvp_caps(tmp_path):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg is not available")
    from clipforge_worker.idea_publish import probe_video_unrestricted

    out = tmp_path / "long.mp4"
    _make_mp4(out, frames=24, fps=8)
    meta = probe_video_unrestricted(out)
    assert meta["width"] == 64 and meta["height"] == 36
    assert meta["duration_seconds"] == pytest.approx(3.0)


def _publish_fixture(tmp_path, monkeypatch):
    from clipforge_contracts.idea import IdeaAsset, IdeaOptions
    from clipforge_contracts.storyboard import AssetSpec
    from clipforge_director.idea_director import MockIdeaDirector
    from clipforge_jobs.project_store import ProjectStore

    monkeypatch.setenv("CLIPFORGE_CREATIVE_DIRECTOR_MODE", "mock")
    monkeypatch.setenv("CLIPFORGE_IDEA_IMAGE_MODE", "mock")
    store = IdeaStore(tmp_path / "storage")
    projects = ProjectStore(tmp_path / "storage")
    project = projects.create_project("Projeto de teste")
    options = IdeaOptions(duration_seconds=5, use_generated_images=True)
    board = MockIdeaDirector().create_storyboard(BRIEF, options)
    plan = list(board.asset_plan)
    plan.append(
        AssetSpec(
            asset_id="asset_scene_1_fg",
            scene_ids=["scene_1"],
            description="Foreground band",
            orientation="portrait",
            role="foreground",
        )
    )
    board = board.model_copy(update={"asset_plan": plan})

    record = _queued_record()
    record.idea.options = options
    record.idea.storyboard = board
    record.project_id = project.project_id
    assets = []
    for spec in plan:
        path = store.asset_path(record.idea_id, spec.asset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _mock_plate(path)
        assets.append(
            IdeaAsset(
                asset_id=spec.asset_id,
                scene_ids=list(spec.scene_ids),
                prompt="plate",
                prompt_hash="0" * 64,
                orientation="portrait",
                status=AssetStatus.GENERATED,
            )
        )
    record.idea.assets = assets
    store.create(record)
    mp4 = tmp_path / "render.mp4"
    if _has_ffmpeg():
        _make_mp4(mp4)
    return store, projects, record, board, mp4


def test_publish_registers_plates_srt_and_mp4(tmp_path, monkeypatch):
    if not _has_ffmpeg():
        pytest.skip("ffmpeg is not available (mp4 probe needs it)")
    from clipforge_jobs.project_store import ProjectStore
    from clipforge_worker.idea_publish import publish_idea_outputs

    store, projects, record, board, mp4 = _publish_fixture(tmp_path, monkeypatch)
    created = publish_idea_outputs(
        store.root,
        idea_id=record.idea_id,
        project_id=record.project_id,
        idea=record.idea,
        board=board,
        mp4_path=mp4,
    )
    # 3 plates (2 cenários + 1 frente) + legendas + mp4 verificado.
    assert len(created) == 5
    from clipforge_contracts.project import AssetRecord

    kinds: dict[str, int] = {}
    seen: set[str] = set()
    for asset_file in projects.assets_dir(record.project_id).glob("*/asset.json"):
        entry = AssetRecord.model_validate_json(asset_file.read_text(encoding="utf-8"))
        assert entry.asset_id in created
        seen.add(entry.asset_id)
        assert entry.provenance.value == "generated"
        kinds[entry.kind.value] = kinds.get(entry.kind.value, 0) + 1
        assert (asset_file.parent / entry.stored_filename).is_file()
    assert seen == set(created)
    assert kinds == {"image": 3, "text": 1, "video": 1}
    assert len(list(projects.assets_dir(record.project_id).glob("*/asset.json"))) == 5

    # Second run is a no-op (idempotent per idea).
    again = publish_idea_outputs(
        store.root,
        idea_id=record.idea_id,
        project_id=record.project_id,
        idea=record.idea,
        board=board,
        mp4_path=mp4,
    )
    assert again == created
    assert len(list(projects.assets_dir(record.project_id).glob("*/asset.json"))) == 5


def test_publish_skips_without_project(tmp_path, monkeypatch):
    from clipforge_worker.idea_publish import publish_idea_outputs

    store, _, record, board, mp4 = _publish_fixture(tmp_path, monkeypatch)
    assert (
        publish_idea_outputs(
            store.root,
            idea_id=record.idea_id,
            project_id=None,
            idea=record.idea,
            board=board,
            mp4_path=mp4,
        )
        == []
    )
