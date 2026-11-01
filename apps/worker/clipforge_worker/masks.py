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

from clipforge_contracts import SegmentationSubject
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


class MaskSequenceWriter:
    """Streams one validated PNG mask at a time and finalizes manifest.json.

    This is the bounded-memory writer used for SAM per-object sequences and for
    the selected-subject union. It never holds the full sequence in RAM.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        fps: float,
        subject_id: str,
        source_video_id: str,
        source_sha256: str | None = None,
        sam_object_id: str | None = None,
        sam_object_ids: Sequence[str] = (),
        provider_name: str | None = None,
        model: str | None = None,
    ) -> None:
        if fps <= 0:
            raise MaskValidationError("fps must be positive.")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.subject_id = subject_id
        self.source_video_id = source_video_id
        self.source_sha256 = source_sha256
        self.sam_object_id = sam_object_id
        self.sam_object_ids = list(sam_object_ids)
        self.provider_name = provider_name
        self.model = model
        self.width: int | None = None
        self.height: int | None = None
        self.frames: list[MaskFrameEntry] = []
        self._finalized = False

    def write(self, mask: np.ndarray) -> None:
        if self._finalized:
            raise MaskValidationError("Cannot write after the manifest was finalized.")
        array = np.asarray(mask)
        if self.width is None or self.height is None:
            if array.ndim != 2:
                raise MaskValidationError(f"Mask must be 2D grayscale; got shape {array.shape}.")
            self.height, self.width = array.shape
        _validate_mask_array(array, self.width, self.height)
        index = len(self.frames)
        filename = f"frame_{index:06d}.png"
        Image.fromarray(array).save(self.directory / filename, format="PNG")
        self.frames.append(
            MaskFrameEntry(
                index=index,
                filename=filename,
                timestamp_ms=derived_timestamp_ms(index, self.fps),
            )
        )

    def finalize(self, *, segmentation_status: str = "completed") -> MaskManifest:
        if self._finalized:
            raise MaskValidationError("Manifest already finalized.")
        if not self.frames:
            raise MaskValidationError("Cannot write an empty mask sequence.")
        self._finalized = True
        manifest = MaskManifest(
            video_width=self.width or 0,
            video_height=self.height or 0,
            frame_count=len(self.frames),
            fps=self.fps,
            timestamp_rule=TIMESTAMP_RULE_DERIVED,
            subject_id=self.subject_id,
            source_video_id=self.source_video_id,
            source_sha256=self.source_sha256,
            sam_object_id=self.sam_object_id,
            sam_object_ids=self.sam_object_ids,
            provider_name=self.provider_name,
            model=self.model,
            segmentation_status=segmentation_status,  # type: ignore[arg-type]
            frames=self.frames,
        )
        (self.directory / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        return manifest


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
        sam_object_id: str | None = None,
        sam_object_ids: Sequence[str] = (),
        provider_name: str | None = None,
        model: str | None = None,
        segmentation_status: str = "completed",
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
            sam_object_id=sam_object_id,
            sam_object_ids=list(sam_object_ids),
            provider_name=provider_name,
            model=model,
            segmentation_status=segmentation_status,  # type: ignore[arg-type]
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
        if manifest.segmentation_status != "completed":
            raise MaskValidationError(
                f"Mask sequence in {mask_dir} is marked "
                f"{manifest.segmentation_status!r}; incomplete segmentation is never rendered."
            )
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


def combine_subject_masks(
    subjects: Sequence[SegmentationSubject],
    selected_object_ids: Sequence[str],
    output_dir: str | Path,
    *,
    fps: float,
    source_video_id: str,
    source_sha256: str | None = None,
) -> MaskManifest:
    """Union selected per-object SAM masks into one canonical sequence.

    Memory stays bounded: one validated mask per selected object is loaded per
    frame, then the union is written immediately. Selected ids must be exact
    stable SAM ids; position in the list is never used as identity.
    """
    selected = list(dict.fromkeys(selected_object_ids))
    if not selected:
        raise MaskValidationError("At least one subject must be selected.")
    by_id = {subject.object_id: subject for subject in subjects}
    unknown = [object_id for object_id in selected if object_id not in by_id]
    if unknown:
        raise MaskValidationError(f"Unknown SAM subject id(s): {unknown}.")
    if len(selected) > 16:
        raise MaskValidationError("SAM supports at most 16 selected subjects per frame.")

    loaders: list = []
    first_manifest = None
    for object_id in selected:
        subject = by_id[object_id]
        directory = Path(subject.mask_manifest_path).parent
        _, manifest = MaskLoader().load_manifest(directory)
        if first_manifest is None:
            first_manifest = manifest
        else:
            if (manifest.video_width, manifest.video_height) != (
                first_manifest.video_width,
                first_manifest.video_height,
            ):
                raise MaskValidationError("Selected subject mask dimensions do not match.")
            if manifest.frame_count != first_manifest.frame_count or manifest.fps != first_manifest.fps:
                raise MaskValidationError("Selected subject mask frame count/fps do not match.")
        loaders.append(iter(MaskLoader().iter_masks(directory)))

    assert first_manifest is not None
    writer = MaskSequenceWriter(
        output_dir,
        fps=first_manifest.fps,
        subject_id="selected_subjects",
        source_video_id=source_video_id,
        source_sha256=source_sha256,
        sam_object_ids=selected,
        provider_name="clipforge-selection",
    )
    for _ in range(first_manifest.frame_count):
        frame_masks = []
        for iterator in loaders:
            try:
                _, mask = next(iterator)
            except StopIteration as exc:
                raise MaskValidationError("Selected subject mask sequence ended early.") from exc
            frame_masks.append(mask)
        writer.write(np.maximum.reduce(frame_masks))
    for iterator in loaders:
        try:
            next(iterator)
        except StopIteration:
            continue
        raise MaskValidationError("Selected subject mask sequence has extra frames.")
    return writer.finalize()
