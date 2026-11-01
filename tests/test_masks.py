import numpy as np
import pytest
from PIL import Image

from clipforge_contracts.mask_manifest import MaskManifest
from clipforge_providers import MockSegmentationProvider
from clipforge_worker.masks import (
    CorruptMaskError,
    MaskDimensionError,
    MaskLoader,
    MaskSequenceWriter,
    MaskValidationError,
    MaskWriter,
    MissingMaskFrameError,
    UnexpectedFrameIndexError,
    combine_subject_masks,
    resize_mask_explicit,
)


def _masks(n=4, h=18, w=32):
    yy, xx = np.mgrid[0:h, 0:w]
    return [np.where(((yy - 9) ** 2 + (xx - (6 + i * 5)) ** 2) <= 36, 255, 0).astype(np.uint8) for i in range(n)]


def _write(tmp_path, masks=None):
    directory = tmp_path / "masks"
    manifest = MaskWriter().write_sequence(
        directory, masks if masks is not None else _masks(), fps=30.0,
        subject_id="person_1", source_video_id="test-source",
    )
    return directory, manifest


def test_writer_loader_roundtrip(tmp_path):
    directory, manifest = _write(tmp_path)
    loaded = MaskLoader().load(directory)
    assert loaded.manifest == manifest
    assert loaded.masks.shape == (4, 18, 32)
    assert loaded.masks.dtype == np.uint8
    assert set(np.unique(loaded.masks)).issubset({0, 255})


def test_writer_rejects_empty_and_mismatched(tmp_path):
    with pytest.raises(MaskValidationError):
        MaskWriter().write_sequence(tmp_path / "a", [], fps=30.0, subject_id="s", source_video_id="v")
    bad = _masks(2) + [np.zeros((9, 16), dtype=np.uint8)]
    with pytest.raises(MaskValidationError):
        MaskWriter().write_sequence(tmp_path / "b", bad, fps=30.0, subject_id="s", source_video_id="v")
    with pytest.raises(MaskValidationError):
        MaskWriter().write_sequence(
            tmp_path / "c", [np.zeros((8, 8), dtype=np.float32)], fps=30.0, subject_id="s", source_video_id="v"
        )


def test_missing_frame_rejected(tmp_path):
    directory, _ = _write(tmp_path)
    (directory / "frame_000002.png").unlink()
    with pytest.raises(MissingMaskFrameError):
        MaskLoader().load(directory)


def test_corrupt_frame_rejected(tmp_path):
    directory, _ = _write(tmp_path)
    (directory / "frame_000001.png").write_bytes(b"not-a-png")
    with pytest.raises(CorruptMaskError):
        MaskLoader().load(directory)


def test_wrong_dimensions_rejected_not_resized(tmp_path):
    directory, _ = _write(tmp_path)
    Image.new("L", (16, 9), 255).save(directory / "frame_000001.png")
    with pytest.raises(MaskDimensionError):
        MaskLoader().load(directory)


def test_unexpected_frame_rejected(tmp_path):
    directory, _ = _write(tmp_path)
    Image.new("L", (32, 18), 0).save(directory / "frame_000099.png")
    with pytest.raises(UnexpectedFrameIndexError):
        MaskLoader().load(directory)


def test_missing_manifest_rejected(tmp_path):
    with pytest.raises(MissingMaskFrameError):
        MaskLoader().load(tmp_path)


def test_manifest_frame_count_mismatch_rejected():
    data = {
        "video_width": 32, "video_height": 18, "frame_count": 3, "fps": 30.0,
        "subject_id": "person_1", "source_video_id": "v",
        "frames": [{"index": 0, "filename": "frame_000000.png", "timestamp_ms": 0}],
    }
    with pytest.raises(Exception):
        MaskManifest.model_validate(data)


def test_grayscale_soft_alpha_accepted(tmp_path):
    soft = [np.tile(np.linspace(0, 255, 32, dtype=np.uint8), (18, 1)) for _ in range(3)]
    directory, _ = _write(tmp_path, soft)
    loaded = MaskLoader().load(directory)
    assert loaded.masks.max() == 255 and loaded.masks.min() == 0
    assert len(np.unique(loaded.masks)) > 2  # intermediate alpha values preserved


def test_explicit_resize_uses_nearest_neighbour(tmp_path):
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[0, 0] = 255
    resized = resize_mask_explicit(mask, 8, 8)
    assert resized.shape == (8, 8)
    assert set(np.unique(resized)).issubset({0, 255})  # no interpolated grey values
    with pytest.raises(MaskValidationError):
        resize_mask_explicit(np.zeros((4, 4), dtype=np.float32), 8, 8)


def test_streaming_writer_roundtrip_and_provenance(tmp_path):
    writer = MaskSequenceWriter(
        tmp_path / "streamed",
        fps=30.0,
        subject_id="0",
        source_video_id="sam-source",
        source_sha256="a" * 64,
        sam_object_id="0",
        provider_name="meta-sam",
        model="sam-3.1",
    )
    for mask in _masks(3):
        writer.write(mask)
    manifest = writer.finalize()
    assert manifest.sam_object_id == "0"
    assert manifest.provider_name == "meta-sam"
    assert manifest.model == "sam-3.1"
    assert manifest.source_sha256 == "a" * 64
    loaded = MaskLoader().load(tmp_path / "streamed")
    assert loaded.masks.shape == (3, 18, 32)


def test_loader_rejects_incomplete_segmentation_manifest(tmp_path):
    directory = tmp_path / "incomplete"
    writer = MaskSequenceWriter(
        directory, fps=30.0, subject_id="0", source_video_id="v"
    )
    for mask in _masks(2):
        writer.write(mask)
    writer.finalize(segmentation_status="incomplete")
    with pytest.raises(MaskValidationError, match="incomplete"):
        MaskLoader().load(directory)


def test_combine_selected_subject_masks_preserves_absent_frames(tmp_path):
    result = MockSegmentationProvider().segment(
        job_id="job-select",
        source_video_id="source-select",
        output_dir=tmp_path / "masks",
        width=64,
        height=36,
        frame_count=6,
        fps=10.0,
    )
    selected_one = next(subject for subject in result.subjects if subject.object_id == "1")
    manifest = combine_subject_masks(
        result.subjects,
        ["1"],
        tmp_path / "selected",
        fps=10.0,
        source_video_id="source-select",
        source_sha256=result.source_sha256,
    )
    assert manifest.sam_object_ids == ["1"]
    masks = MaskLoader().load(tmp_path / "selected").masks
    assert masks[0].max() == 0  # object 1 enters on frame 2
    assert masks[selected_one.first_frame].max() == 255
    with pytest.raises(MaskValidationError, match="Unknown SAM subject"):
        combine_subject_masks(
            result.subjects,
            ["does-not-exist"],
            tmp_path / "unknown",
            fps=10.0,
            source_video_id="source-select",
        )
