"""Mask writer/loader with strict validation (ADR-005).

Canonical format: one lossless 8-bit grayscale PNG per frame plus manifest.json.
The loader never silently resizes a mask. Explicit resize is a separate,
deliberate operation using nearest-neighbour interpolation only. Edge smoothing
belongs to the renderer, not to this module.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from pydantic import ValidationError

from clipforge_contracts.mask_manifest import TIMESTAMP_RULE_DERIVED, MaskFrameEntry, MaskManifest, derived_timestamp_ms


class MaskValidationError(Exception):
    """Base class for mask validation failures."""


class MissingMaskFrameError(MaskValidationError):
    pass


class CorruptMaskError(MaskValidationError):
    pass


class MaskDimensionError(MaskValidationError):
    pass


class UnexpectedFrameIndexError(MaskValidationError):
    pass


@dataclass(frozen=True)
class MaskSequence:
    manifest: MaskManifest
    masks: np.ndarray  # shape (frame_count, height, width), dtype uint8

    def __len__(self) -> int:
        return int(self.masks.shape[0])


def _validate_mask_array(mask: np.ndarray, width: int, height: int) -> None:
    if mask.ndim != 2:
        raise MaskValidationError(f"Mask must be 2D grayscale; got shape {mask.shape}.")
    if mask.dtype != np.uint8:
        raise MaskValidationError(f"Mask must be uint8 (8-bit grayscale); got dtype {mask.dtype}.")
    if mask.shape != (height, width):
        raise MaskDimensionError(f"Mask dimensions {mask.shape[1]}x{mask.shape[0]} != expected {width}x{height}.")


class MaskWriter:
    """Writes a validated PNG mask sequence + manifest.json."""

    def write_sequence(
        self,
        directory: str | Path,
        masks: Iterable[np.ndarray],
        *,
        fps: float,
        subject_id: str,
        source_video_id: str,
        source_sha256: str | None = None,
    ) -> MaskManifest:
        mask_list = [np.asarray(m) for m in masks]
        if not mask_list:
            raise MaskValidationError("Cannot write an empty mask sequence.")
        height, width = mask_list[0].shape if mask_list[0].ndim == 2 else (0, 0)
        for mask in mask_list:
            _validate_mask_array(mask, width, height)

        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)

        frames: list[MaskFrameEntry] = []
        for index, mask in enumerate(mask_list):
            filename = f"frame_{index:06d}.png"
            Image.fromarray(mask).save(out_dir / filename, format="PNG")
            frames.append(
                MaskFrameEntry(index=index, filename=filename, timestamp_ms=derived_timestamp_ms(index, fps))
            )

        manifest = MaskManifest(
            video_width=width,
            video_height=height,
            frame_count=len(mask_list),
            fps=fps,
            timestamp_rule=TIMESTAMP_RULE_DERIVED,
            subject_id=subject_id,
            source_video_id=source_video_id,
            source_sha256=source_sha256,
            frames=frames,
        )
        (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest


class MaskLoader:
    """Loads and strictly validates a PNG mask sequence + manifest.json."""

    def load_manifest(self, directory: str | Path) -> tuple[Path, MaskManifest]:
        mask_dir = Path(directory)
        manifest_path = mask_dir / "manifest.json"
        if not manifest_path.is_file():
            raise MissingMaskFrameError(f"manifest.json not found in {mask_dir}.")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = MaskManifest.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise MaskValidationError(f"Invalid manifest.json in {mask_dir}: {exc}") from exc
        self._reject_unexpected_files(mask_dir, manifest)
        return mask_dir, manifest

    def iter_masks(self, directory: str | Path):
        """Yield (index, mask) one frame at a time, fully validated, bounded memory.

        Validation of each frame happens as it is yielded; a missing/corrupt/
        mis-sized frame raises at exactly that frame. Use this in the renderer
        instead of load() so 300-frame sequences are never held in RAM at once.
        """
        mask_dir, manifest = self.load_manifest(directory)
        for frame in manifest.frames:
            path = mask_dir / frame.filename
            if not path.is_file():
                raise MissingMaskFrameError(f"Mask frame missing: {frame.filename} (index {frame.index}).")
            yield frame.index, self._load_frame(path, manifest)

    def load(self, directory: str | Path) -> MaskSequence:
        _, manifest = self.load_manifest(directory)
        arrays = [mask for _, mask in self.iter_masks(directory)]
        return MaskSequence(manifest=manifest, masks=np.stack(arrays))

    @staticmethod
    def _reject_unexpected_files(mask_dir: Path, manifest: MaskManifest) -> None:
        expected = {f.filename for f in manifest.frames}
        for path in sorted(mask_dir.glob("frame_*.png")):
            if path.name not in expected:
                raise UnexpectedFrameIndexError(
                    f"Unexpected mask file {path.name} not listed in manifest (no silent acceptance of extra frames)."
                )

    @staticmethod
    def _load_frame(path: Path, manifest: MaskManifest) -> np.ndarray:
        try:
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise CorruptMaskError(f"Mask frame {path.name} is not a PNG file.")
                if image.size != (manifest.video_width, manifest.video_height):
                    raise MaskDimensionError(
                        f"Mask frame {path.name} dimensions {image.size[0]}x{image.size[1]}"
                        f" != manifest {manifest.video_width}x{manifest.video_height}."
                        " Masks are never silently resized; fix the source or call resize_mask_explicit deliberately."
                    )
                array = np.array(image.convert("L"), dtype=np.uint8)
        except MaskValidationError:
            raise
        except Exception as exc:  # corrupt or unreadable file: surface it, never swallow
            raise CorruptMaskError(f"Mask frame {path.name} is corrupt or unreadable: {exc}") from exc
        if array.shape != (manifest.video_height, manifest.video_width):
            raise MaskDimensionError(f"Mask frame {path.name} decoded shape {array.shape} does not match manifest.")
        return array


def resize_mask_explicit(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Explicit mask resize using nearest-neighbour only. Never called implicitly by the loader."""
    if mask.ndim != 2 or mask.dtype != np.uint8:
        raise MaskValidationError("resize_mask_explicit expects a 2D uint8 mask.")
    resized = Image.fromarray(mask).resize((width, height), resample=Image.Resampling.NEAREST)
    return np.array(resized, dtype=np.uint8)


def validate_mask_stack(masks: Sequence[np.ndarray], width: int, height: int) -> None:
    """Validate an in-memory stack against expected dimensions (renderer pre-flight)."""
    for i, mask in enumerate(masks):
        try:
            _validate_mask_array(np.asarray(mask), width, height)
        except MaskValidationError as exc:
            raise MaskValidationError(f"Frame {i}: {exc}") from exc
