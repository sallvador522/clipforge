"""Output evaluation tests: objective vs subjective, 3-pass cap, no network."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge_director.evaluation import (
    OutputEvaluationReport,
    evaluate_output,
)


@pytest.fixture(scope="module")
def rendered_clip(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("eval") / "clip.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg unavailable: {result.stderr[-200:]}")
    return out


def test_evaluate_passes_objective_on_real_render(rendered_clip):
    report = evaluate_output(
        rendered_clip,
        expected_width=64,
        expected_height=36,
        expected_frames=10,
        expected_duration_s=1.0,
        expect_audio=True,
    )
    assert report.verdict == "pass_objective"
    assert report.objective.all_passed
    assert [s.label for s in report.samples] == ["first", "middle", "final"]
    assert all(s.readable for s in report.samples)
    # Subjective quality is never auto-verified.
    assert report.needs_human_review is True
    assert any("human review" in note.lower() for note in report.human_review_notes)


def test_wrong_expectations_fail_objective(rendered_clip):
    report = evaluate_output(
        rendered_clip,
        expected_width=1280,
        expected_height=720,
        expected_frames=300,
        expected_duration_s=10.0,
        expect_audio=True,
    )
    assert report.verdict == "fail_objective"
    assert not report.objective.all_passed


def test_missing_file_fails_safely(tmp_path):
    report = evaluate_output(
        tmp_path / "missing.mp4",
        expected_width=64,
        expected_height=36,
        expected_frames=10,
        expected_duration_s=1.0,
        expect_audio=True,
    )
    assert report.verdict == "fail_objective"


def test_correction_ledger_caps_at_three(tmp_path):
    report = OutputEvaluationReport(
        output_path=str(tmp_path / "x.mp4"),
        expected_width=64,
        expected_height=36,
        expected_frames=10,
        expected_duration_s=1.0,
        expect_audio=False,
    )
    for i in range(3):
        attempt = report.request_correction(issue=f"issue {i}", action="re-render and re-inspect")
        assert attempt.pass_number == i + 1
        report.corrections.append(attempt)
    with pytest.raises(ValueError):
        report.request_correction(issue="fourth", action="not allowed")


def test_pass_objective_requires_all_checks(tmp_path):
    from pydantic import ValidationError

    report = OutputEvaluationReport(
        output_path=str(tmp_path / "x.mp4"),
        expected_width=64,
        expected_height=36,
        expected_frames=10,
        expected_duration_s=1.0,
        expect_audio=False,
    )
    data = report.model_dump(mode="json")
    data["verdict"] = "pass_objective"
    with pytest.raises(ValidationError):
        OutputEvaluationReport.model_validate(data)
