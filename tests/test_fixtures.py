import pytest

from clipforge_worker.fixtures import CASES, generate_fixture
from clipforge_worker.masks import (
    CorruptMaskError,
    MaskDimensionError,
    MaskLoader,
    MissingMaskFrameError,
)

VALID_CASES = [c for c in CASES if c not in {"missing_masks", "corrupt_mask", "wrong_dimensions"}]


@pytest.mark.parametrize("case", VALID_CASES)
def test_valid_fixtures_load(tmp_path, case):
    seq = MaskLoader().load(generate_fixture(case, tmp_path))
    assert len(seq) == 12
    assert seq.masks.shape[1:] == (36, 64)


def test_fixtures_are_deterministic(tmp_path):
    a = MaskLoader().load(generate_fixture("irregular_edges", tmp_path / "a"))
    b = MaskLoader().load(generate_fixture("irregular_edges", tmp_path / "b"))
    assert (a.masks == b.masks).all()


def test_missing_masks_fixture_rejected(tmp_path):
    with pytest.raises(MissingMaskFrameError):
        MaskLoader().load(generate_fixture("missing_masks", tmp_path))


def test_corrupt_fixture_rejected(tmp_path):
    with pytest.raises(CorruptMaskError):
        MaskLoader().load(generate_fixture("corrupt_mask", tmp_path))


def test_wrong_dimensions_fixture_rejected(tmp_path):
    with pytest.raises(MaskDimensionError):
        MaskLoader().load(generate_fixture("wrong_dimensions", tmp_path))
