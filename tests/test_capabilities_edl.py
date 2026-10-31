"""Capability registry EDL policy tests."""

from __future__ import annotations

import pytest

from clipforge_contracts.capabilities import (
    CAPABILITIES,
    edl_handler_for,
    edl_role_for,
    edl_timing_allowed,
    get_capability,
)
from clipforge_contracts.edl import EditHistoryEntry


def test_edl_roles_cover_every_capability():
    for capability_id in CAPABILITIES:
        role = edl_role_for(capability_id)
        assert role in {"prepare", "transform", "finalize", "planned", "unavailable"}


def test_executable_capabilities_have_prepare_transform_finalize_roles():
    assert edl_role_for("subject.isolate") == "prepare"
    assert edl_role_for("background.blur") == "transform"
    assert edl_role_for("background.replace") == "transform"
    assert edl_role_for("audio.preserve") == "finalize"
    assert edl_role_for("video.render_mp4") == "finalize"
    assert edl_role_for("output.verify") == "finalize"


def test_timing_forbidden_while_trim_disabled():
    assert get_capability("timeline.trim") is not None
    assert get_capability("timeline.trim").executable is False  # type: ignore[union-attr]
    assert edl_timing_allowed() is False


def test_handler_resolution_only_for_executable_capabilities():
    assert edl_handler_for("background.blur") == "clipforge_worker.renderer:render_video"
    assert edl_handler_for("output.verify") == "clipforge_worker.renderer:verify_render_output"
    with pytest.raises(ValueError):
        edl_handler_for("transition.apply")
    with pytest.raises(ValueError):
        edl_handler_for("background.generate")
    with pytest.raises(ValueError):
        edl_handler_for("does.not.exist")


def test_job_record_accepts_edit_history_without_breaking_contracts(tmp_path):
    from clipforge_jobs import JobRecord, JobStore
    from clipforge_jobs.models import SourceInfo
    from datetime import datetime, timezone

    store = JobStore(tmp_path / "storage")
    record = JobRecord(
        job_id="edlhistory01",
        original_filename="clip.mp4",
        source_relative_path="uploads/edlhistory01/source.mp4",
        source_info=SourceInfo(
            width=64, height=36, fps=10.0, duration_seconds=1.0, frame_count=10, has_audio=True
        ),
    )
    entry = EditHistoryEntry(
        entry_id="hist_abcdef123456",
        at=datetime.now(timezone.utc),
        stage="PLAN_READY",
        actor="director",
        summary="EDL projected.",
        refs=["subject.isolate"],
    )
    record = record.model_copy(update={"edit_history": [entry]})
    store.create(record)
    reloaded = store.get("edlhistory01")
    assert len(reloaded.edit_history) == 1
    assert reloaded.edit_history[0].entry_id == "hist_abcdef123456"
