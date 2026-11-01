"""Local subject preview rendering (no network, no model call).

A preview is the actual source frame with a tinted mask and contour for one
stable SAM object id, plus a compact label. It is presentation metadata only;
the renderer never consumes previews.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("clipforge.providers.previews")


def _color_for(object_id: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(object_id.encode("utf-8")).digest()
    return (
        60 + digest[0] % 160,
        80 + digest[1] % 150,
        100 + digest[2] % 140,
    )


def write_subject_preview(
    *,
    source_path: str | Path | None,
    mask: np.ndarray,
    object_id: str,
    frame_index: int,
    output_path: str | Path,
) -> str | None:
    """Write a PNG preview; returns None when the source frame cannot be read."""
    if source_path is None:
        return None
    try:
        import cv2  # worker-only dependency, imported lazily
    except ImportError:
        logger.warning("subject_preview_skipped reason=opencv_unavailable")
        return None

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source_path))
    try:
        if not capture.isOpened():
            logger.warning("subject_preview_skipped reason=source_unreadable")
            return None
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        logger.warning("subject_preview_skipped reason=frame_unreadable frame=%d", frame_index)
        return None

    mask_bool = np.asarray(mask) > 127
    color = _color_for(object_id)
    overlay = frame.copy()
    overlay[mask_bool] = color
    preview = cv2.addWeighted(overlay, 0.38, frame, 0.62, 0)
    contours, _ = cv2.findContours(
        mask_bool.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(preview, contours, -1, color, 2)
    cv2.putText(
        preview,
        f"SUBJECT {object_id}",
        (8, max(18, preview.shape[0] - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    if preview.shape[1] > 320:
        scale = 320 / preview.shape[1]
        preview = cv2.resize(
            preview,
            (320, max(1, round(preview.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    if not cv2.imwrite(str(path), preview):
        logger.warning("subject_preview_write_failed path=%s", path.name)
        return None
    return str(path)
