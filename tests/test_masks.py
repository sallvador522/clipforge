import numpy as np
import pytest
from PIL import Image

from clipforge_contracts.mask_manifest import MaskManifest
from clipforge_worker.masks import (
    CorruptMaskError,
    MaskDimensionError,
    MaskLoader,
    MaskValidationError,
    MaskWriter,
    MissingMaskFrameError,
    UnexpectedFrameIndexError,
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
