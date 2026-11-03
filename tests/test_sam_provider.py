"""Offline SAM 3.1 provider tests.

No live request is made. The provider's Responses stream, Files upload and
delete transport are injected; fixture events are protocol-compatible JSON
recorded under tests/fixtures/sam.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from clipforge_director import LiveCallAuthorization, LiveCallBudget
from clipforge_contracts import (
    SUBJECT_DETECTION_DISCLOSURE_VERSION,
    SubjectDetectionConsent,
    sha256_file,
)
from clipforge_providers import (
    SamIncompleteStreamError,
    SamNotAuthorizedError,
    SamSegmentationProvider,
    SamStreamInterruptedError,
    SamValidationError,
)
from clipforge_worker.masks import MaskLoader

FIXTURES = Path(__file__).parent / "fixtures" / "sam"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _source_video(tmp_path: Path) -> Path:
    path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _auth(tmp_path: Path) -> LiveCallAuthorization:
    return LiveCallAuthorization(
        LiveCallBudget(tmp_path / "storage", limits={"segmentation": 2}), "segmentation"
    )


def _consent(video: Path, job_id: str) -> SubjectDetectionConsent:
    return SubjectDetectionConsent(
        job_id=job_id,
        source_video_hash=sha256_file(video),
        consent_given=True,
        consent_timestamp=datetime.now(timezone.utc),
        disclosure_version=SUBJECT_DETECTION_DISCLOSURE_VERSION,
        provider="meta-sam",
        model="sam-3.1",
        segmentation_mode="live",
    )


def _provider(
    fixture_name: str,
    *,
    uploaded: list[Path],
    deleted: list[str],
    on_upload=None,
    fail_stream: bool = False,
    fail_delete: bool = False,
) -> tuple[SamSegmentationProvider, list[dict]]:
    payloads: list[dict] = []

    def upload(path: Path) -> str:
        uploaded.append(path)
        if on_upload:
            on_upload(path)
        return "file-test123"

    def delete(file_id: str) -> None:
        deleted.append(file_id)
        if fail_delete:
            raise RuntimeError("delete failed")

    def stream(payload: dict):
        payloads.append(payload)
        if fail_stream:
            raise RuntimeError("stream failed")
        return _fixture(fixture_name)["events"]

    return (
        SamSegmentationProvider(
            "test-key",
            event_stream=stream,
            file_uploader=upload,
            file_deleter=delete,
        ),
        payloads,
    )


def test_sam_request_contract_and_mask_conversion(tmp_path):
    video = _source_video(tmp_path)
    before = hashlib.sha256(video.read_bytes()).hexdigest()
    uploaded: list[Path] = []
    deleted: list[str] = []
    uploaded_info: dict = {}
    provider, payloads = _provider(
        "one_person",
        uploaded=uploaded,
        deleted=deleted,
        on_upload=lambda path: uploaded_info.update(_probe(path)),
    )
    result = provider.segment(
        job_id="job-sam",
        source_video_id="src-sam",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-sam"),
    )

    assert result.provider_name == "meta-sam"
    assert result.model == "sam-3.1"
    assert result.is_mock is False
    assert result.status == "completed"
    assert result.file_cleanup == "deleted"
    assert [s.object_id for s in result.subjects] == ["0"]
    assert Path(result.subjects[0].mask_manifest_path).parts[-2:] == ("object_0", "manifest.json")
    assert result.subjects[0].preview_path is not None
    assert Path(result.subjects[0].preview_path).is_file()
    with Image.open(result.subjects[0].preview_path) as preview:
        assert preview.format == "PNG"
    assert hashlib.sha256(video.read_bytes()).hexdigest() == before

    payload = payloads[0]
    assert payload["model"] == "sam-3.1"
    assert payload["stream"] is True
    assert payload["metadata"] == {"mask_encoding": "one_bit"}
    content = payload["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "person"}
    assert content[1] == {"type": "input_video", "file_id": "file-test123"}

    assert len(uploaded) == 1 and deleted == ["file-test123"]
    assert not any(s["codec_type"] == "audio" for s in uploaded_info["streams"])
    video_stream = next(s for s in uploaded_info["streams"] if s["codec_type"] == "video")
    assert (video_stream["width"], video_stream["height"]) == (64, 36)
    assert required_fps(video_stream) == pytest.approx(10.0)
    assert provider.last_file_cleanup == "deleted"

    sequence = MaskLoader().load(tmp_path / "masks")
    assert sequence.masks.shape == (5, 36, 64)
    assert sequence.manifest.sam_object_ids == ["0"]
    assert sequence.manifest.segmentation_status == "completed"
    per_object = MaskLoader().load(Path(result.subjects[0].mask_manifest_path).parent)
    assert per_object.manifest.sam_object_id == "0"
    assert per_object.masks.max() == 255


def required_fps(stream: dict) -> float:
    numerator, denominator = stream["avg_frame_rate"].split("/")
    return float(numerator) / float(denominator)


def test_sam_preserves_sparse_object_ids_and_out_of_order_frames(tmp_path):
    video = _source_video(tmp_path)
    provider, _ = _provider("out_of_order", uploaded=[], deleted=[])
    result = provider.segment(
        job_id="job-order",
        source_video_id="src-order",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-order"),
    )
    assert [s.object_id for s in result.subjects] == ["0"]
    masks = MaskLoader().load(Path(result.subjects[0].mask_manifest_path).parent).masks
    boxes = []
    for mask in masks:
        ys, xs = np.where(mask > 0)
        boxes.append((int(xs.min()), int(xs.max())))
    assert boxes[0][0] < boxes[1][0] < boxes[2][0] < boxes[3][0] < boxes[4][0]


def test_sam_preserves_sparse_non_contiguous_object_ids(tmp_path):
    video = _source_video(tmp_path)
    provider, _ = _provider("sparse_ids", uploaded=[], deleted=[])
    result = provider.segment(
        job_id="job-sparse",
        source_video_id="src-sparse",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-sparse"),
    )
    assert [s.object_id for s in result.subjects] == ["0", "2"]
    object_two = next(s for s in result.subjects if s.object_id == "2")
    masks = MaskLoader().load(Path(object_two.mask_manifest_path).parent).masks
    assert masks[0].max() == 255 and masks[1].max() == 255
    assert masks[3].max() == 0 and masks[4].max() == 0


def test_sam_enter_leave_and_occlusion_fill_absent_frames(tmp_path):
    video = _source_video(tmp_path)
    provider, _ = _provider("enter_leave_occlusion", uploaded=[], deleted=[])
    result = provider.segment(
        job_id="job-enter",
        source_video_id="src-enter",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-enter"),
    )
    assert [s.object_id for s in result.subjects] == ["0", "1"]
    object_one = next(s for s in result.subjects if s.object_id == "1")
    assert (object_one.first_frame, object_one.last_frame, object_one.frames_detected) == (1, 3, 2)
    masks = MaskLoader().load(Path(object_one.mask_manifest_path).parent).masks
    assert masks[0].max() == 0 and masks[2].max() == 0 and masks[4].max() == 0
    assert masks[1].max() == 255 and masks[3].max() == 255


def test_sam_zero_detections_is_explicit_empty_result(tmp_path):
    video = _source_video(tmp_path)
    provider, _ = _provider("empty", uploaded=[], deleted=[])
    result = provider.segment(
        job_id="job-empty",
        source_video_id="src-empty",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-empty"),
    )
    assert result.status == "completed"
    assert result.subjects == []
    sequence = MaskLoader().load(tmp_path / "masks")
    assert sequence.masks.max() == 0


@pytest.mark.parametrize(
    ("fixture", "error"),
    [
        ("incomplete", SamIncompleteStreamError),
        ("malformed_mask", SamValidationError),
        ("wrong_dimensions", SamValidationError),
    ],
)
def test_sam_rejects_incomplete_or_malformed_output(tmp_path, fixture, error):
    video = _source_video(tmp_path)
    provider, _ = _provider(fixture, uploaded=[], deleted=[])
    out = tmp_path / "masks"
    with pytest.raises(error):
        provider.segment(
            job_id="job-bad",
            source_video_id="src-bad",
            output_dir=out,
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_path=video,
            authorization=_auth(tmp_path),
            consent=_consent(video, "job-bad"),
        )
    assert not (out / "manifest.json").exists()


def test_sam_stream_drop_reports_event_count_and_stable_code(tmp_path):
    """A dropped SSE stream must say so, with how far it got.

    The 2026-11-02 live job surfaced the parser's generic `source_error`
    ("The Responses event source failed during next.") with no hint that the
    transport had died mid-transfer. This pins the actionable message.
    """
    video = _source_video(tmp_path)
    events = _fixture("one_person")["events"]
    # Skip response.created: with no observed response id there is nothing to
    # retrieve, so the original interruption must surface untouched (and no
    # network retrieval may be attempted with the dummy key).
    deltas = [e for e in events if e.get("type") == "response.output_text.delta"][:2]
    deleted: list[str] = []

    def stream(payload: dict):
        def generator():
            for event in deltas:
                yield event
            raise httpx.ReadError("connection reset by peer")

        return generator()

    provider = SamSegmentationProvider(
        "test-key",
        event_stream=stream,
        file_uploader=lambda path: "file-drop",
        file_deleter=lambda file_id: deleted.append(file_id),
    )
    with pytest.raises(SamStreamInterruptedError) as excinfo:
        provider.segment(
            job_id="job-drop",
            source_video_id="src-drop",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_path=video,
            authorization=_auth(tmp_path),
            consent=_consent(video, "job-drop"),
        )

    message = str(excinfo.value)
    assert "connection to SAM dropped" in message
    assert "2 stream events received" in message
    assert "no retry was attempted" in message
    assert excinfo.value.code == "sam_stream_interrupted"
    # Fase 0: the stored Responses id survives the drop for later retrieval.
    assert excinfo.value.response_id is None
    assert provider.last_response_id is None
    assert deleted == ["file-drop"]
    assert not (tmp_path / "masks" / "manifest.json").exists()


def test_drop_with_response_id_attempts_retrieval_before_failing(tmp_path):
    """With an observed id, recovery must try the stored response first.

    Here retrieval reports a terminal failure, so the interruption still
    surfaces — but only after the no-cost GET was attempted.
    """
    video = _source_video(tmp_path)
    events = _fixture("one_person")["events"]
    attempted: list[str] = []

    def stream(payload: dict):
        def generator():
            for event in events[:2]:
                yield event
            raise httpx.ReadError("connection reset by peer")

        return generator()

    def retriever(response_id: str) -> dict:
        attempted.append(response_id)
        return {"status": "failed"}

    provider = SamSegmentationProvider(
        "test-key",
        event_stream=stream,
        file_uploader=lambda path: "file-drop",
        file_deleter=lambda file_id: None,
        response_retriever=retriever,
    )
    with pytest.raises(SamIncompleteStreamError):
        provider.segment(
            job_id="job-drop-retrieve",
            source_video_id="src-drop-retrieve",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_path=video,
            authorization=_auth(tmp_path),
            consent=_consent(video, "job-drop-retrieve"),
        )
    assert attempted == ["resp_fixture"]
    assert provider.last_response_id == "resp_fixture"


def test_frame_marker_extraction_for_drop_diagnostics():
    from clipforge_providers.sam import _frame_marker

    assert _frame_marker("text<0f>0<|box;x") == 0
    assert _frame_marker("text<176f>0<|box;x") == 176
    assert _frame_marker("no marker here") is None
    assert _frame_marker(None) is None
    assert _frame_marker(123) is None


def test_dropped_stream_recovers_via_response_retrieval(tmp_path):
    """LIVE-CALL 009 proved the server keeps the result after our socket dies.

    The stream drops with a response id; recovery GETs the stored completed
    response (no second POST, no new ledger slot) and writes the real masks.
    """
    video = _source_video(tmp_path)
    fixture = _fixture("one_person")
    done_text = next(
        e["text"] for e in fixture["events"] if e.get("type") == "response.output_text.done"
    )
    deleted: list[str] = []
    retrieved: list[str] = []

    def stream(payload: dict):
        def generator():
            for event in fixture["events"][:2]:
                yield event
            raise httpx.ReadError("connection reset by peer")

        return generator()

    def retriever(response_id: str) -> dict:
        retrieved.append(response_id)
        return {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": done_text}]}
            ],
        }

    provider = SamSegmentationProvider(
        "test-key",
        event_stream=stream,
        file_uploader=lambda path: "file-recovered",
        file_deleter=lambda file_id: deleted.append(file_id),
        response_retriever=retriever,
    )
    result = provider.segment(
        job_id="job-recovered",
        source_video_id="src-recovered",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-recovered"),
    )

    assert retrieved == ["resp_fixture"]
    assert [s.object_id for s in result.subjects] == ["0"]
    assert result.subjects[0].frames_detected == 5
    assert (tmp_path / "masks" / "manifest.json").exists()
    assert any("retrieval" in d for d in result.diagnostics)
    assert deleted == ["file-recovered"]


def test_recovery_refuses_when_stored_response_failed(tmp_path):
    video = _source_video(tmp_path)
    events = _fixture("one_person")["events"]

    def stream(payload: dict):
        def generator():
            yield events[0]
            raise httpx.ReadError("connection reset by peer")

        return generator()

    provider = SamSegmentationProvider(
        "test-key",
        event_stream=stream,
        file_uploader=lambda path: "file-failed",
        file_deleter=lambda file_id: None,
        response_retriever=lambda response_id: {"status": "failed"},
    )
    with pytest.raises(SamIncompleteStreamError):
        provider.segment(
            job_id="job-stored-failed",
            source_video_id="src-stored-failed",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_path=video,
            authorization=_auth(tmp_path),
            consent=_consent(video, "job-stored-failed"),
        )


def test_sam_file_upload_uses_user_data_and_minimum_expiration(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(200, json={"id": "file-expiry123"})

    monkeypatch.setattr(httpx, "post", fake_post)
    path = tmp_path / "sam_input.mp4"
    path.write_bytes(b"video-only")
    provider = SamSegmentationProvider("test-key")
    assert provider._upload(path) == "file-expiry123"
    assert captured["url"] == "https://api.meta.ai/v1/files"
    assert captured["data"]["purpose"] == "user_data"
    assert captured["data"]["expires_after[anchor]"] == "created_at"
    assert captured["data"]["expires_after[seconds]"] == "3600"
    assert "file" in captured["files"]
    assert "video_url" not in captured


def test_sam_requires_authorization_before_upload(tmp_path):
    video = _source_video(tmp_path)
    uploaded: list[Path] = []
    provider, _ = _provider("one_person", uploaded=uploaded, deleted=[])
    with pytest.raises(SamNotAuthorizedError):
        provider.segment(
            job_id="job-noauth",
            source_video_id="src-noauth",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_path=video,
            authorization=None,
            consent=_consent(video, "job-noauth"),
        )
    assert uploaded == []


def test_sam_cleanup_runs_after_stream_failure(tmp_path):
    video = _source_video(tmp_path)
    deleted: list[str] = []
    provider, _ = _provider(
        "one_person", uploaded=[], deleted=deleted, fail_stream=True
    )
    with pytest.raises(RuntimeError):
        provider.segment(
            job_id="job-fail",
            source_video_id="src-fail",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_path=video,
            authorization=_auth(tmp_path),
            consent=_consent(video, "job-fail"),
        )
    assert deleted == ["file-test123"]


def test_sam_cleanup_failure_is_recorded_but_does_not_hide_masks(tmp_path):
    video = _source_video(tmp_path)
    provider, _ = _provider(
        "one_person", uploaded=[], deleted=[], fail_delete=True
    )
    result = provider.segment(
        job_id="job-cleanup",
        source_video_id="src-cleanup",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=5,
        fps=10.0,
        source_path=video,
        authorization=_auth(tmp_path),
        consent=_consent(video, "job-cleanup"),
    )
    assert result.file_cleanup == "failed"
    assert any("cleanup" in message.lower() for message in result.diagnostics)
    assert (tmp_path / "masks" / "manifest.json").is_file()


def _parsed_from_fixture(name: str):
    import asyncio

    from meta_sam_parser import parse_responses_stream, video_segmentation_format

    events = _fixture(name)["events"]

    async def source():
        for event in events:
            yield event

    async def parse():
        parsed = parse_responses_stream(source(), video_segmentation_format())
        return await parsed.final_result()

    return asyncio.run(parse())


def test_sam_rejects_duplicate_records_without_a_newer_revision(tmp_path):
    video = _source_video(tmp_path)
    parsed = _parsed_from_fixture("one_person")
    masks = [record for record in parsed.records if record.kind == "mask"]
    duplicate = dataclasses.replace(masks[0])
    parsed_with_duplicate = dataclasses.replace(parsed, records=parsed.records + (duplicate,))
    provider, _ = _provider("one_person", uploaded=[], deleted=[])
    with pytest.raises(SamValidationError):
        provider._convert(
            parsed_with_duplicate,
            job_id="job-dup",
            source_video_id="src-dup",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_sha256="a" * 64,
            source_path=video,
        )


def test_sam_rejects_non_mask_text_output(tmp_path):
    from meta_sam_parser import SegmentationTextRecord

    video = _source_video(tmp_path)
    parsed = _parsed_from_fixture("one_person")
    text_only = dataclasses.replace(
        parsed,
        records=(SegmentationTextRecord(order=0, text="not a mask record"),),
        raw_output="not a mask record\n",
    )
    provider, _ = _provider("one_person", uploaded=[], deleted=[])
    with pytest.raises(SamValidationError, match="non-mask"):
        provider._convert(
            text_only,
            job_id="job-text",
            source_video_id="src-text",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_sha256="a" * 64,
            source_path=video,
        )


def test_sam_rejects_more_than_sixteen_objects_on_a_frame(tmp_path):
    video = _source_video(tmp_path)
    parsed = _parsed_from_fixture("one_person")
    first_mask = next(record for record in parsed.records if record.kind == "mask")
    many = tuple(
        dataclasses.replace(first_mask, object_id=str(index))
        for index in range(17)
    )
    parsed_many = dataclasses.replace(parsed, records=many)
    provider, _ = _provider("one_person", uploaded=[], deleted=[])
    with pytest.raises(SamValidationError):
        provider._convert(
            parsed_many,
            job_id="job-many",
            source_video_id="src-many",
            output_dir=tmp_path / "masks",
            width=64,
            height=36,
            frame_count=5,
            fps=10.0,
            source_sha256="a" * 64,
            source_path=video,
        )
