import pytest
from pydantic import ValidationError

from clipforge_contracts import EditingIntent, EditingPlan, SubjectSpec, TranscriptResult
from clipforge_providers import FixtureNotFoundError, get_providers
from clipforge_providers.live import LiveSegmentationProvider, LiveProviderNotImplementedError
from clipforge_worker.masks import MaskLoader


def _providers():
    return get_providers("mock")


def test_transcription_fixtures_pt():
    p = _providers()
    assert p.transcription.transcribe("pt_blur_people_behind").text == "Desfoca todas as pessoas atrás de mim."
    assert p.transcription.transcribe("pt_replace_background_studio").text == "Substitui o fundo por um estúdio profissional."
    assert p.transcription.transcribe("pt_keep_me_sharp").text == "Mantém-me nítido e desfoca o resto."
    result = p.transcription.transcribe("pt_keep_me_sharp")
    assert result.is_mock is True and result.language == "pt-BR"
    with pytest.raises(FixtureNotFoundError):
        p.transcription.transcribe("does-not-exist")


def test_planner_deterministic_mappings():
    p = _providers()
    cases = {
        "pt_blur_people_behind": EditingIntent.BLUR_BACKGROUND,
        "pt_replace_background_studio": EditingIntent.REPLACE_BACKGROUND,
        "pt_keep_me_sharp": EditingIntent.KEEP_SHARP_BLUR_REST,
        "pt_unsupported_command": EditingIntent.UNSUPPORTED,
    }
    for fixture, intent in cases.items():
        plan = p.planner.create_plan(p.transcription.transcribe(fixture))
        assert plan.intent is intent
        assert plan.schema_version == "1.0" and plan.preserve_audio is True
    plan_a = p.planner.create_plan(p.transcription.transcribe("pt_blur_people_behind"))
    plan_b = p.planner.create_plan(p.transcription.transcribe("pt_blur_people_behind"))
    assert plan_a == plan_b  # deterministic


def test_planner_ambiguous_subject_asks_clarification():
    p = _providers()
    plan = p.planner.create_plan(p.transcription.transcribe("pt_ambiguous_person"))
    assert plan.intent is EditingIntent.CLARIFICATION_NEEDED
    assert plan.subject.is_ambiguous is True
    assert plan.subject.clarification_question
    assert plan.operations == []


def test_editing_plan_validation_rejects_bad_plans():
    with pytest.raises(ValidationError):
        SubjectSpec(description="alguém", is_ambiguous=True)  # clarification question required
    with pytest.raises(ValidationError):
        EditingPlan(
            plan_id="x", raw_transcript="Desfoca ele.", intent=EditingIntent.CLARIFICATION_NEEDED,
            subject=SubjectSpec(description="ele", is_ambiguous=True, clarification_question="Quem?"),
            operations=[{"type": "blur_background"}],  # type: ignore[list-item]
        )


def test_mock_segmentation_returns_real_loadable_masks(tmp_path):
    p = _providers()
    result = p.segmentation.segment(
        job_id="job-test", source_video_id="src-1", output_dir=tmp_path / "masks",
        width=64, height=36, frame_count=6, fps=30.0,
    )
    assert result.is_mock is True and result.frame_count == 6
    seq = MaskLoader().load(tmp_path / "masks")
    assert seq.masks.shape == (6, 36, 64)
    assert seq.masks.max() == 255  # actual mask data, not a success flag


def test_mock_background_returns_real_image_files():
    p = _providers()
    for orientation, size in [("landscape", (1280, 720)), ("portrait", (720, 1280))]:
        result = p.background.generate(prompt="estúdio profissional", orientation=orientation)
        assert result.is_mock is True
        assert result.orientation == orientation
        from pathlib import Path
        from PIL import Image

        path = Path(result.image_path)
        assert path.is_file()
        with Image.open(path) as img:
            assert img.size == size
    with pytest.raises(ValueError):
        p.background.generate(prompt="x", orientation="square")


def test_live_providers_are_explicit_placeholders():
    with pytest.raises(LiveProviderNotImplementedError):
        LiveSegmentationProvider().segment(
            job_id="j", source_video_id="s", output_dir="x", width=8, height=8, frame_count=1, fps=30.0
        )
    transcript = TranscriptResult(text="olá", confidence=1.0, provider_name="t", is_mock=True)
    assert transcript.text == "olá"
