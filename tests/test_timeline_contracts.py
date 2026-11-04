"""ADR-044 timeline contract: explicit multitrack arrangement validation."""

import pytest
from pydantic import ValidationError

from clipforge_contracts import Timeline, TimelineClip
from clipforge_contracts.timeline import TIMELINE_MAX_DURATION_S


def _clip(clip_id="clip_aaaaaaaaaaaa", asset_id="ast_bbbbbbbbbbbb", track="V1",
          start=0.0, inn=0.0, out=2.0):
    return TimelineClip(
        clip_id=clip_id, asset_id=asset_id, track=track,
        timeline_start_s=start, source_in_s=inn, source_out_s=out,
    )


def test_valid_multitrack_program_duration():
    tl = Timeline(clips=[
        _clip("clip_aaaaaaaaaaaa", track="V1", start=0.0, inn=0.0, out=2.0),
        _clip("clip_bbbbbbbbbbbb", track="V2", start=1.0, inn=0.0, out=2.0),
        _clip("clip_cccccccccccc", track="A1", start=0.5, inn=0.0, out=1.0),
    ])
    assert tl.program_duration_s() == pytest.approx(3.0)


def test_empty_timeline_program_is_zero():
    assert Timeline(clips=[]).program_duration_s() == 0.0


def test_overlap_same_track_rejected():
    with pytest.raises(ValidationError):
        Timeline(clips=[
            _clip("clip_aaaaaaaaaaaa", track="V1", start=0.0, inn=0.0, out=2.0),
            _clip("clip_bbbbbbbbbbbb", track="V1", start=1.5, inn=0.0, out=2.0),
        ])


def test_touching_edges_allowed():
    tl = Timeline(clips=[
        _clip("clip_aaaaaaaaaaaa", track="V1", start=0.0, inn=0.0, out=2.0),
        _clip("clip_bbbbbbbbbbbb", track="V1", start=2.0, inn=0.0, out=1.0),
    ])
    assert tl.program_duration_s() == pytest.approx(3.0)


def test_source_range_must_grow():
    with pytest.raises(ValidationError):
        _clip(inn=1.0, out=1.0)


def test_minimum_clip_length():
    with pytest.raises(ValidationError):
        _clip(inn=0.0, out=0.4)


def test_program_cap():
    with pytest.raises(ValidationError):
        _clip(start=TIMELINE_MAX_DURATION_S - 1.0, inn=0.0, out=2.0)


def test_ids_are_validated():
    with pytest.raises(ValidationError):
        _clip(clip_id="nope")
    with pytest.raises(ValidationError):
        _clip(asset_id="nope")


def test_track_literal():
    with pytest.raises(ValidationError):
        TimelineClip(clip_id="clip_aaaaaaaaaaaa", asset_id="ast_bbbbbbbbbbbb",
                     track="V3", timeline_start_s=0.0, source_in_s=0.0, source_out_s=1.0)


def test_max_clips():
    clips = [
        _clip(f"clip_{i:012d}", track="V1", start=float(i * 2), inn=0.0, out=1.0)
        for i in range(65)
    ]
    with pytest.raises(ValidationError):
        Timeline(clips=clips)
