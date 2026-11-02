"""Meta SAM 3.1 segmentation provider (Milestone 6D).

Official contract implemented:
  POST https://api.meta.ai/v1/responses
  model: sam-3.1
  input: input_text noun phrase + input_video file_id
  stream: true
  output: special-token text in the output_text lane, parsed with the official
          `meta-sam-parser` Python package (0.1.0).

The provider uploads a temporary video-only copy through the Files API with
purpose=user_data and expires_after=3600 seconds, references it by file_id,
and deletes it in a finally block. No public URL is used.

No live network request is made by tests: `event_stream`, `file_uploader` and
`file_deleter` are injectable. The real path still requires a one-shot
LiveCallAuthorization and reserves the ledger immediately before the Responses
POST. There are no automatic retries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import tempfile
import time
from collections.abc import AsyncIterable, Callable, Iterable
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from meta_sam_parser import (
    InvalidSegmentationMaskError,
    ResponsesStreamError,
    decode_mask_to_raster,
    parse_responses_stream,
    video_segmentation_format,
)

from clipforge_contracts import (
    ConsentValidationError,
    SegmentationResult,
    SegmentationSubject,
    SubjectDetectionConsent,
    sha256_file,
    validate_subject_detection_consent,
)
from clipforge_providers.subject_previews import write_subject_preview
from clipforge_worker.masks import MaskSequenceWriter

logger = logging.getLogger("clipforge.sam")

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "sam-3.1"
DEFAULT_PROMPT = "person"
DEFAULT_TIMEOUT_SECONDS = 600.0
FILE_EXPIRY_SECONDS = 3600
_MAX_OBJECTS_PER_FRAME = 16
_ACCEPTED_VIDEO_CODECS = {"h264", "hevc", "mpeg4"}
_OBJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SamError(RuntimeError):
    """Base class for safe SAM provider failures."""


class SamMissingCredentialsError(SamError):
    pass


class SamNotAuthorizedError(SamError):
    pass


class SamTimeoutError(SamError):
    pass


class SamRateLimitedError(SamError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SamAPIError(SamError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        server_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.server_request_id = server_request_id


class SamIncompleteStreamError(SamError):
    pass


class SamStreamInterruptedError(SamError):
    """The Responses stream dropped before a terminal event arrived.

    Carries a stable `code` so a job record distinguishes a transport
    interruption from a provider rejection or a mask-validation failure.
    """

    code = "sam_stream_interrupted"


class SamValidationError(SamError):
    pass


def _stream_failure(exc: BaseException) -> tuple[str, str] | None:
    """Classify a dropped Responses stream, or return None for other errors.

    The SAM parser wraps the transport error, so the httpx cause is found by
    walking the exception chain. Anything without a transport cause is left
    untouched: this must never mask validation or HTTP status failures.
    """
    timeout = False
    transport = False
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, httpx.TimeoutException):
            timeout = True
            transport = True
        elif isinstance(cause, httpx.TransportError):
            transport = True
        cause = cause.__cause__
    if not transport:
        return None
    root: BaseException = exc
    while root.__cause__ is not None:
        root = root.__cause__
    return ("timeout" if timeout else "dropped", type(root).__name__)


def _probe(path: Path, *, count_frames: bool = False) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    if count_frames:
        command.insert(3, "-count_frames")
    command.append(str(path))
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise SamValidationError(f"ffprobe failed on {path.name}: {result.stderr.strip()[-300:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SamValidationError(f"ffprobe returned invalid JSON for {path.name}.") from exc


def _video_stream(data: dict[str, Any]) -> dict[str, Any]:
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise SamValidationError("The source has no video stream.")
    return stream


def _fps(stream: dict[str, Any]) -> float:
    raw = stream.get("avg_frame_rate", "0/1")
    try:
        numerator, denominator = raw.split("/")
        return float(numerator) / float(denominator) if float(denominator) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _frame_count(stream: dict[str, Any]) -> int:
    raw = stream.get("nb_read_frames") or stream.get("nb_frames")
    if raw is None or not str(raw).isdigit():
        return -1
    return int(raw)


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise SamValidationError(f"FFmpeg normalization failed: {result.stderr.strip()[-400:]}")


class SamSegmentationProvider:
    """Official SAM 3.1 Responses/Files implementation (no hidden fallback)."""

    provider_name = "meta-sam"
    execution_mode = "live"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        prompt: str = DEFAULT_PROMPT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        event_stream: Callable[[dict[str, Any]], Iterable[dict[str, Any]] | AsyncIterable[dict[str, Any]]] | None = None,
        file_uploader: Callable[[Path], str] | None = None,
        file_deleter: Callable[[str], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise SamMissingCredentialsError(
                "SAM live mode requires MODEL_API_KEY (server-side only). No request was attempted."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._prompt = prompt.strip() or DEFAULT_PROMPT
        self._timeout_seconds = timeout_seconds
        self._event_stream = event_stream
        self._file_uploader = file_uploader
        self._file_deleter = file_deleter
        self.last_request_id: str | None = None
        self.last_file_id: str | None = None
        self.last_file_cleanup: str = "not_applicable"

    @property
    def model(self) -> str:
        return self._model

    # -- public interface ----------------------------------------------------
    def segment(
        self,
        *,
        job_id: str,
        source_video_id: str,
        output_dir: str | Path,
        width: int,
        height: int,
        frame_count: int,
        fps: float,
        source_path: str | Path | None = None,
        prompt: str = "person",
        authorization=None,
        consent: SubjectDetectionConsent | None = None,
    ) -> SegmentationResult:
        if source_path is None:
            raise SamValidationError("SAM live segmentation requires the source video path.")
        if width <= 0 or height <= 0 or frame_count <= 0 or fps <= 0:
            raise SamValidationError("width, height, frame_count and fps must be positive.")
        source = Path(source_path)
        if not source.is_file():
            raise SamValidationError("Source video not found for SAM segmentation.")
        source_sha256 = sha256_file(source)
        validate_subject_detection_consent(
            consent,
            job_id=job_id,
            source_video_hash=source_sha256,
            provider=self.provider_name,
            model=self._model,
        )
        self._require_authorization(authorization)

        effective_prompt = (prompt or self._prompt).strip() or DEFAULT_PROMPT
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="clipforge-sam-") as temp_dir:
            normalized = Path(temp_dir) / "sam_input.mp4"
            self._prepare_video_only(
                source,
                normalized,
                width=width,
                height=height,
                frame_count=frame_count,
                fps=fps,
            )
            if sha256_file(source) != source_sha256:
                raise ConsentValidationError(
                    "subject_detection_consent_source_mismatch",
                    "The source video changed while the SAM input was being prepared; "
                    "no upload was attempted.",
                )
            file_id: str | None = None
            cleanup = "not_uploaded"
            try:
                file_id = self._upload(normalized)
                self.last_file_id = file_id
                authorization.reserve()  # immediately before the billable Responses POST
                payload = self._request_payload(file_id, effective_prompt)
                inference_start = time.perf_counter()
                parsed = asyncio.run(self._collect(payload))
                inference_seconds = time.perf_counter() - inference_start
                result = self._convert(
                    parsed,
                    job_id=job_id,
                    source_video_id=source_video_id,
                    output_dir=root,
                    width=width,
                    height=height,
                    frame_count=frame_count,
                    fps=fps,
                    source_sha256=source_sha256,
                    source_path=source,
                )
            finally:
                if file_id is not None:
                    try:
                        self._delete(file_id)
                        cleanup = "deleted"
                    except Exception as exc:  # cleanup failure is recorded, never hides the user error
                        cleanup = "failed"
                        logger.warning(
                            "sam_file_cleanup_failed file_id=%s error=%s", file_id, type(exc).__name__
                        )
            self.last_file_cleanup = cleanup
            logger.info(
                "sam_segmentation_completed job_id=%s request_id=%s subjects=%d "
                "inference_seconds=%.2f cleanup=%s",
                job_id,
                self.last_request_id,
                len(result.subjects),
                inference_seconds,
                cleanup,
            )
            diagnostics = list(result.diagnostics)
            if cleanup == "failed":
                diagnostics.append(
                    "Meta file cleanup failed; the uploaded copy was requested to expire after 1 hour."
                )
            return result.model_copy(update={"file_cleanup": cleanup, "diagnostics": diagnostics})

    # -- request building ----------------------------------------------------
    def _request_payload(self, file_id: str, prompt: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_video", "file_id": file_id},
                    ],
                }
            ],
            "stream": True,
            "metadata": {"mask_encoding": "one_bit"},
        }

    # -- Files API -----------------------------------------------------------
    def _upload(self, path: Path) -> str:
        if self._file_uploader is not None:
            return self._file_uploader(path)
        try:
            with path.open("rb") as handle:
                response = httpx.post(
                    f"{self._base_url}/files",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data={
                        "purpose": "user_data",
                        "expires_after[anchor]": "created_at",
                        "expires_after[seconds]": str(FILE_EXPIRY_SECONDS),
                    },
                    files={"file": (path.name, handle, "video/mp4")},
                    timeout=self._timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise SamTimeoutError("SAM file upload timed out. No retry was attempted.") from exc
        except httpx.HTTPError as exc:
            raise SamAPIError("SAM file upload failed before a response was received.") from exc
        self._raise_for_status(response, "SAM file upload")
        try:
            body = response.json()
            file_id = body["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SamAPIError("SAM file upload returned no file id.") from exc
        if not isinstance(file_id, str) or not file_id.startswith("file-"):
            raise SamAPIError("SAM file upload returned an invalid file id.")
        logger.info("sam_file_uploaded file_id=%s", file_id)
        return file_id

    def _delete(self, file_id: str) -> None:
        if self._file_deleter is not None:
            self._file_deleter(file_id)
            return
        try:
            response = httpx.delete(
                f"{self._base_url}/files/{file_id}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=60.0,
            )
        except httpx.TimeoutException as exc:
            raise SamTimeoutError("SAM file deletion timed out.") from exc
        except httpx.HTTPError as exc:
            raise SamAPIError("SAM file deletion failed before a response was received.") from exc
        if response.status_code == 404:
            return  # already expired/deleted
        self._raise_for_status(response, "SAM file deletion")

    # -- Responses stream ----------------------------------------------------
    def _require_authorization(self, authorization) -> None:
        from clipforge_director import LiveCallAuthorization

        if not isinstance(authorization, LiveCallAuthorization):
            raise SamNotAuthorizedError(
                "SAM live segmentation requires a one-shot LiveCallAuthorization. "
                "No upload or request was attempted."
            )
        if authorization.function != "segmentation":
            raise SamNotAuthorizedError("The authorization is not for segmentation.")

    def _event_source(
        self, payload: dict[str, Any]
    ) -> Iterable[dict[str, Any]] | AsyncIterable[dict[str, Any]]:
        if self._event_stream is not None:
            return self._event_stream(payload)
        return self._http_event_stream(payload)

    async def _collect(self, payload: dict[str, Any]):
        source = self._event_source(payload)
        received = 0

        async def counted():
            nonlocal received
            async for event in self._as_async(source):
                received += 1
                yield event

        parsed = parse_responses_stream(counted(), video_segmentation_format())
        started = time.perf_counter()
        try:
            return await parsed.final_result()
        except Exception as exc:
            failure = _stream_failure(exc)
            if failure is None:
                raise
            kind, root_cause = failure
            elapsed = time.perf_counter() - started
            logger.warning(
                "sam_stream_interrupted request_id=%s kind=%s events=%d elapsed=%.1fs cause=%s",
                self.last_request_id,
                kind,
                received,
                elapsed,
                root_cause,
            )
            plural = "" if received == 1 else "s"
            if kind == "timeout":
                reason = f"The SAM stream timed out after {elapsed:.0f}s"
            else:
                reason = f"The connection to SAM dropped after {elapsed:.0f}s"
            raise SamStreamInterruptedError(
                f"{reason} while receiving masks ({received} stream event{plural} received). "
                "No masks were written and no retry was attempted."
            ) from exc

    @staticmethod
    async def _as_async(source):
        if hasattr(source, "__aiter__"):
            async for event in source:
                yield event
        else:
            for event in source:
                yield event

    async def _http_event_stream(self, payload: dict[str, Any]):
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        timeout = httpx.Timeout(self._timeout_seconds, connect=30.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/responses", headers=headers, json=payload
                ) as response:
                    self._raise_for_status(response, "SAM Responses request")
                    self.last_request_id = response.headers.get("x-request-id")
                    logger.info(
                        "sam_responses_status status=%d request_id=%s",
                        response.status_code,
                        self.last_request_id,
                    )
                    async for event in self._iter_sse(response):
                        yield event
        except httpx.TimeoutException as exc:
            raise SamTimeoutError("SAM Responses stream timed out. No retry was attempted.") from exc
        except httpx.HTTPError as exc:
            raise SamAPIError("SAM Responses stream failed before completion.") from exc

    @staticmethod
    async def _iter_sse(response: httpx.Response):
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if line == "":
                if data_lines:
                    yield _decode_sse_event("\n".join(data_lines))
                    data_lines = []
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            yield _decode_sse_event("\n".join(data_lines))

    def _raise_for_status(self, response, operation: str) -> None:
        if response.status_code < 400:
            return
        request_id = response.headers.get("x-request-id")
        logger.warning(
            "%s failed status=%d request_id=%s",
            operation,
            response.status_code,
            request_id,
        )
        if response.status_code in (401, 403):
            raise SamAPIError(
                f"{operation} was rejected (HTTP {response.status_code}).",
                status_code=response.status_code,
                server_request_id=request_id,
            )
        if response.status_code == 429:
            raise SamRateLimitedError(
                f"{operation} was rate limited (HTTP 429). No retry was attempted.",
                retry_after=response.headers.get("retry-after"),
            )
        raise SamAPIError(
            f"{operation} failed with HTTP {response.status_code}.",
            status_code=response.status_code,
            server_request_id=request_id,
        )

    # -- validation and conversion ------------------------------------------
    def _convert(
        self,
        parsed,
        *,
        job_id: str,
        source_video_id: str,
        output_dir: Path,
        width: int,
        height: int,
        frame_count: int,
        fps: float,
        source_sha256: str,
        source_path: Path,
    ) -> SegmentationResult:
        if parsed.outcome.status != "completed":
            reason = getattr(parsed.outcome, "reason", "unknown")
            raise SamIncompleteStreamError(
                f"SAM returned an incomplete segmentation stream ({reason}); no masks were written."
            )
        error_diagnostics = [d for d in parsed.diagnostics if d.severity == "error"]
        if error_diagnostics:
            first = error_diagnostics[0]
            raise SamValidationError(f"SAM parser rejected output: {first.code}: {first.message}")
        warnings = [f"{d.code}: {d.message}" for d in parsed.diagnostics if d.severity == "warning"]

        text_records = [
            record for record in parsed.records if record.kind == "text" and record.text.strip()
        ]
        if text_records:
            raise SamValidationError("SAM output contained non-mask text records; refusing to infer masks.")
        records = [record for record in parsed.records if record.kind == "mask"]
        if not records and parsed.raw_output.strip():
            raise SamValidationError("SAM output was non-empty but contained no mask records.")
        if not records:
            return self._write_empty_result(
                job_id=job_id,
                source_video_id=source_video_id,
                output_dir=output_dir,
                width=width,
                height=height,
                frame_count=frame_count,
                fps=fps,
                source_sha256=source_sha256,
                diagnostics=warnings,
            )

        grouped: dict[str, dict[int, Any]] = {}
        per_frame_ids: dict[int, set[str]] = {}
        for record in records:
            object_id = record.object_id
            if not _OBJECT_ID_PATTERN.fullmatch(object_id):
                raise SamValidationError(f"Unsafe SAM object id {object_id!r}.")
            if record.frame is None:
                raise SamValidationError("SAM returned a mask without a frame reference.")
            frame = record.frame.frame_index
            if frame < 0 or frame >= frame_count:
                raise SamValidationError(
                    f"SAM frame {frame} is outside the expected 0..{frame_count - 1} range."
                )
            bounds = record.bounds
            if (
                bounds.left < 0
                or bounds.top < 0
                or bounds.right > width
                or bounds.bottom > height
                or bounds.right <= bounds.left
                or bounds.bottom <= bounds.top
            ):
                raise SamValidationError(f"SAM mask bounds are outside the {width}x{height} frame.")
            mask_width = int(round(bounds.right - bounds.left))
            mask_height = int(round(bounds.bottom - bounds.top))
            if (record.mask.width, record.mask.height) != (mask_width, mask_height):
                raise SamValidationError(
                    "SAM mask raster dimensions do not match its box bounds; refusing to resize."
                )
            previous = grouped.setdefault(object_id, {}).get(frame)
            if previous is not None and record.revision <= previous.revision:
                raise SamValidationError(
                    f"Duplicate SAM record for object {object_id} frame {frame}."
                )
            grouped[object_id][frame] = record
            per_frame_ids.setdefault(frame, set()).add(object_id)
            if len(per_frame_ids[frame]) > _MAX_OBJECTS_PER_FRAME:
                raise SamValidationError("SAM returned more than 16 objects on one frame.")

        # Preserve first appearance order, then stable wire order.
        object_ids = sorted(
            grouped,
            key=lambda oid: min(grouped[oid]),
        )
        object_root = output_dir / "objects"
        object_root.mkdir(parents=True, exist_ok=True)
        writers = {
            object_id: MaskSequenceWriter(
                object_root / f"object_{object_id}",
                fps=fps,
                subject_id=object_id,
                source_video_id=source_video_id,
                source_sha256=source_sha256,
                sam_object_id=object_id,
                provider_name=self.provider_name,
                model=self._model,
            )
            for object_id in object_ids
        }
        union_writer = MaskSequenceWriter(
            output_dir,
            fps=fps,
            subject_id="sam_union",
            source_video_id=source_video_id,
            source_sha256=source_sha256,
            sam_object_ids=object_ids,
            provider_name=self.provider_name,
            model=self._model,
        )

        first_frame: dict[str, int] = {}
        last_frame: dict[str, int] = {}
        detected: dict[str, int] = {}
        first_mask: dict[str, np.ndarray] = {}
        confidence: dict[str, float] = {}

        for frame in range(frame_count):
            union = np.zeros((height, width), dtype=np.uint8)
            for object_id in object_ids:
                record = grouped[object_id].get(frame)
                full = np.zeros((height, width), dtype=np.uint8)
                if record is not None:
                    try:
                        raster = decode_mask_to_raster(record.mask)
                    except InvalidSegmentationMaskError as exc:
                        raise SamValidationError(f"Invalid SAM mask payload: {exc}") from exc
                    expected = record.mask.width * record.mask.height
                    if len(raster) != expected:
                        raise SamValidationError("Decoded SAM mask length does not match its dimensions.")
                    left, top = int(record.bounds.left), int(record.bounds.top)
                    mask = np.frombuffer(raster, dtype=np.uint8).reshape(
                        record.mask.height, record.mask.width
                    )
                    full[top : top + record.mask.height, left : left + record.mask.width] = (
                        mask * 255
                    )
                    detected[object_id] = detected.get(object_id, 0) + 1
                    first_frame.setdefault(object_id, frame)
                    last_frame[object_id] = frame
                    first_mask.setdefault(object_id, full)
                    if record.confidence is not None:
                        confidence[object_id] = max(confidence.get(object_id, 0.0), record.confidence)
                writers[object_id].write(full)
                union = np.maximum(union, full)
            union_writer.write(union)

        union_manifest = union_writer.finalize()
        subjects: list[SegmentationSubject] = []
        preview_dir = output_dir / "previews"
        for object_id in object_ids:
            writers[object_id].finalize()
            preview_path = None
            if object_id in first_mask:
                preview_path = write_subject_preview(
                    source_path=source_path,
                    mask=first_mask[object_id],
                    object_id=object_id,
                    frame_index=first_frame[object_id],
                    output_path=preview_dir / f"object_{object_id}.png",
                )
            subjects.append(
                SegmentationSubject(
                    object_id=object_id,
                    label="Detected person",
                    mask_manifest_path=str(
                        object_root / f"object_{object_id}" / "manifest.json"
                    ),
                    preview_path=preview_path,
                    first_frame=first_frame.get(object_id),
                    last_frame=last_frame.get(object_id),
                    frames_detected=detected.get(object_id, 0),
                    confidence=confidence.get(object_id),
                )
            )

        return SegmentationResult(
            job_id=job_id,
            subject_id=union_manifest.subject_id,
            mask_manifest_path=str(output_dir / "manifest.json"),
            frame_count=union_manifest.frame_count,
            width=union_manifest.video_width,
            height=union_manifest.video_height,
            fps=union_manifest.fps,
            provider_name=self.provider_name,
            is_mock=False,
            model=self._model,
            subjects=subjects,
            source_sha256=source_sha256,
            status="completed",
            diagnostics=warnings,
        )

    def _write_empty_result(
        self,
        *,
        job_id: str,
        source_video_id: str,
        output_dir: Path,
        width: int,
        height: int,
        frame_count: int,
        fps: float,
        source_sha256: str,
        diagnostics: list[str],
    ) -> SegmentationResult:
        writer = MaskSequenceWriter(
            output_dir,
            fps=fps,
            subject_id="sam_union",
            source_video_id=source_video_id,
            source_sha256=source_sha256,
            sam_object_ids=[],
            provider_name=self.provider_name,
            model=self._model,
        )
        empty = np.zeros((height, width), dtype=np.uint8)
        for _ in range(frame_count):
            writer.write(empty)
        manifest = writer.finalize()
        return SegmentationResult(
            job_id=job_id,
            subject_id=manifest.subject_id,
            mask_manifest_path=str(output_dir / "manifest.json"),
            frame_count=manifest.frame_count,
            width=manifest.video_width,
            height=manifest.video_height,
            fps=manifest.fps,
            provider_name=self.provider_name,
            is_mock=False,
            model=self._model,
            subjects=[],
            source_sha256=source_sha256,
            status="completed",
            diagnostics=diagnostics,
        )

    # -- local video preparation --------------------------------------------
    def _prepare_video_only(
        self,
        source: Path,
        output: Path,
        *,
        width: int,
        height: int,
        frame_count: int,
        fps: float,
    ) -> None:
        """Create a video-only MP4 and verify it before upload.

        The original file is read-only here. Accepted containers/codecs use a
        stream copy (no frame/timestamp changes). Everything else is transcoded
        to H.264 and then verified frame-for-frame; a mismatch is a hard error.
        """
        source_probe = _probe(source, count_frames=True)
        source_stream = _video_stream(source_probe)
        if (int(source_stream.get("width", 0)), int(source_stream.get("height", 0))) != (
            width,
            height,
        ):
            raise SamValidationError("Source dimensions do not match the job metadata.")
        if abs(_fps(source_stream) - fps) > 0.01:
            raise SamValidationError("Source FPS does not match the job metadata.")
        if _frame_count(source_stream) != frame_count:
            raise SamValidationError("Source frame count does not match the job metadata.")
        if any(s.get("codec_type") == "audio" for s in source_probe.get("streams", [])):
            # Expected: the temporary input removes it; the source itself may keep it.
            pass

        container = str(source_probe.get("format", {}).get("format_name", ""))
        codec = str(source_stream.get("codec_name", ""))
        copy_compatible = codec in _ACCEPTED_VIDEO_CODECS and (
            "mp4" in container or "mov" in container
        )
        if copy_compatible:
            try:
                _run_ffmpeg(
                    [
                        "ffmpeg", "-y", "-i", str(source), "-map", "0:v:0",
                        "-c:v", "copy", "-an", "-movflags", "+faststart", str(output),
                    ]
                )
            except SamValidationError:
                copy_compatible = False
        if not copy_compatible:
            _run_ffmpeg(
                [
                    "ffmpeg", "-y", "-i", str(source), "-map", "0:v:0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                    "-movflags", "+faststart", "-r", str(fps), str(output),
                ]
            )

        normalized = _probe(output, count_frames=True)
        streams = normalized.get("streams", [])
        if any(s.get("codec_type") == "audio" for s in streams):
            raise SamValidationError("Temporary SAM input still contains audio.")
        stream = _video_stream(normalized)
        if (int(stream.get("width", 0)), int(stream.get("height", 0))) != (width, height):
            raise SamValidationError("Temporary SAM input changed dimensions.")
        if abs(_fps(stream) - fps) > 0.01:
            raise SamValidationError("Temporary SAM input changed FPS.")
        if _frame_count(stream) != frame_count:
            raise SamValidationError("Temporary SAM input changed frame count.")


def _decode_sse_event(payload: str) -> dict[str, Any]:
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SamIncompleteStreamError("SAM stream contained a malformed SSE data event.") from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise SamIncompleteStreamError("SAM stream contained an invalid Responses event.")
    return event
