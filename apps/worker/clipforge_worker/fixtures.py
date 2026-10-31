"""Deterministic synthetic mask fixtures (ADR-007).

These fixtures validate the rendering pipeline and mask-handling behaviour,
NOT real SAM tracking quality. All generation is local and seeded: the same
parameters always produce byte-identical masks.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from clipforge_worker.masks import MaskWriter

FIXTURE_WIDTH = 64
FIXTURE_HEIGHT = 36
FIXTURE_FRAMES = 12
FIXTURE_FPS = 30.0

CASES = (
    "static_subject",
    "moving_subject",
    "multiple_subjects_crossing",
    "partial_occlusion",
    "mask_holes",
    "irregular_edges",
    "temporal_jitter",
    "missing_masks",
    "corrupt_mask",
    "wrong_dimensions",
)


def _ellipse(height: int, width: int, cy: float, cx: float, ry: float, rx: float) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    return (((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2) <= 1.0


def _base_sequence(case: str) -> list[np.ndarray]:
    h, w, n = FIXTURE_HEIGHT, FIXTURE_WIDTH, FIXTURE_FRAMES
    rng = np.random.default_rng(42)
    frames: list[np.ndarray] = []
    for i in range(n):
        if case == "static_subject":
            mask = _ellipse(h, w, 18, 32, 12, 8)
        elif case == "moving_subject":
            mask = _ellipse(h, w, 18, 8 + i * 4, 12, 8)
        elif case == "multiple_subjects_crossing":
            subject = _ellipse(h, w, 18, 8 + i * 4, 12, 7)
            other = _ellipse(h, w, 18, 56 - i * 4, 12, 7)
            mask = subject | other  # combined foreground; subject_id tracks the left-to-right subject
        elif case == "partial_occlusion":
            mask = _ellipse(h, w, 18, 32, 13, 14)
            if 4 <= i <= 7:  # occluder bar cuts the subject
                mask[:, 26:38] = False
        elif case == "mask_holes":
            mask = _ellipse(h, w, 18, 32, 12, 9)
            mask &= ~_ellipse(h, w, 16, 30, 4, 3)
        elif case == "irregular_edges":
            yy, xx = np.mgrid[0:h, 0:w]
            angle = np.arctan2(yy - 18, xx - 32)
            radius = 10 + 3 * np.sin(angle * 7 + i) + rng.random() * 0.5
            dist = np.sqrt((yy - 18) ** 2 + (xx - 32) ** 2)
            mask = dist <= radius
        elif case == "temporal_jitter":
            offset = 2 if i % 2 == 0 else -2
            mask = _ellipse(h, w, 18 + offset, 32 - offset, 12, 8)
        else:
            mask = _ellipse(h, w, 18, 10 + i * 3, 12, 8)
        frames.append(np.where(mask, 255, 0).astype(np.uint8))
    return frames


def generate_fixture(case: str, root: str | Path) -> Path:
    """Generate one named fixture directory (masks/ + manifest via MaskWriter) and return its path."""
    if case not in CASES:
        raise ValueError(f"Unknown fixture case {case!r}. Known: {', '.join(CASES)}")
    out = Path(root) / case / "masks"
    writer = MaskWriter()
    writer.write_sequence(
        out,
        _base_sequence(case if case not in {"missing_masks", "corrupt_mask", "wrong_dimensions"} else "moving_subject"),
        fps=FIXTURE_FPS,
        subject_id="person_1",
        source_video_id=f"synthetic-fixture-{case}",
    )
    if case == "missing_masks":
        (out / "frame_000005.png").unlink()  # manifest still references it: loader must raise MissingMaskFrameError
    elif case == "corrupt_mask":
        (out / "frame_000003.png").write_bytes(b"not-a-png")
    elif case == "wrong_dimensions":
        from PIL import Image

        Image.new("L", (32, 18), 255).save(out / "frame_000002.png")  # loader must raise MaskDimensionError, never resize
    return out


def generate_all_fixtures(root: str | Path) -> list[Path]:
    return [generate_fixture(case, root) for case in CASES]


# Lighting variation is a property of source frames, not masks: the mask fixture is
# identical to moving_subject by design, and the renderer milestone pairs it with
# differently-lit synthetic source frames. See fixtures/README.md.
LIGHTING_NOTE = "lighting variation affects source frames, not mask geometry (ADR-007 fixture)."
