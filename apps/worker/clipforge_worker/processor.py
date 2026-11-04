"""Job processor: plan review, approval, clarification and real rendering.

Pipeline: confirmed transcript -> v2 Director (mock or live) -> persisted plan ->
explicit user consent when live segmentation is required -> segmentation ->
explicit user approval -> optional local/mock background -> real
FFmpeg/OpenCV render -> verified output. A plan never renders before approval.
SAM never runs before explicit consent. Clarification and unsupported plans
never render. Every exception is logged and recorded as a structured job error;
the original upload is preserved.
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from PIL import Image

from clipforge_contracts import (
    ApprovalStatus,
    BackgroundResult,
    ConsentValidationError,
    EditingIntent,
    PlanOutcome,
    TranscriptResult,
    sha256_file,
    validate_subject_detection_consent,
)
from clipforge_director import DirectorVideoMetadata, LiveCallAuthorization, LiveCallBudget
from clipforge_jobs import MAX_CLARIFICATIONS, JobError, JobResult, JobStatus, JobStore
from clipforge_jobs.project_store import ProjectNotFoundError, ProjectStore
from clipforge_providers import ProviderBundle
from clipforge_worker.masks import MaskLoader, combine_subject_masks
from clipforge_worker.timeline_render import TimelineMedia, compose_timeline
from clipforge_worker.renderer import RenderRequest, render_video

logger = logging.getLogger("clipforge.worker")


class JobProcessor:
    def __init__(self, store: JobStore, providers: ProviderBundle) -> None:
        self.store = store
        self.providers = providers

    def _director_metadata(self, job_id: str, provider):
        usage = getattr(provider, "last_usage", None)
        usage_dict = usage.model_dump(mode="json") if usage is not None else None
        request_id = getattr(provider, "last_request_id", None)
        audit = getattr(provider, "last_audit", None)
        if audit is not None:
            audit = audit.model_copy(update={"job_id": job_id})
        return usage_dict, request_id, audit

    def _persist_plan_result(
        self,
        job_id: str,
        *,
        transcript: TranscriptResult,
        director_plan,
        director_usage,
        director_request_id,
        director_audit,
        plan=None,
        **extra,
    ) -> JobResult:
        result = JobResult(
            transcript=transcript,
            plan=plan or director_plan.to_execution_plan(),
            director_plan=director_plan,
            director_usage=director_usage,
            director_request_id=director_request_id,
            director_audit=director_audit,
            **extra,
        )
        self.store.update(job_id, result=result)
        return result

    def _canonical_source_path(self, record):
        """The original upload is the only legal consent/audit source; never a SAM derivative."""
        path = self.store.source_path(record)
        if not path.is_file():
            raise ValueError("Canonical original upload is missing; refusing to render.")
        return path

    def _effective_source_path(self, record):
        """The clip the pipeline actually consumes: trimmed copy when set, else original."""
        if record.trimmed_relative_path:
            path = self.store.root / record.trimmed_relative_path
            if path.is_file():
                return path
        return self._canonical_source_path(record)

    def _probe_trimmed_source(self, path: Path):
        """Re-probe a materialized trimmed copy (no MVP limit re-check needed)."""
        from clipforge_jobs.models import SourceInfo

        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=width,height,avg_frame_rate,codec_type",
                "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise ValueError(f"Trimmed clip could not be probed: {result.stderr.strip()[-200:]}")
        data = json.loads(result.stdout)
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        if video is None:
            raise ValueError("Trimmed clip has no video stream.")
        num, _, den = (video.get("avg_frame_rate", "0/1") + "/1").split("/")[:3]
        fps = float(num) / float(den) if float(den) else 0.0
        duration = float(data.get("format", {}).get("duration", 0) or 0)
        frame_count = max(1, round(duration * fps)) if fps > 0 else 0
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
        return SourceInfo(
            width=int(video.get("width", 0)),
            height=int(video.get("height", 0)),
            fps=fps,
            duration_seconds=duration,
            frame_count=frame_count,
            has_audio=has_audio,
        )

    def _materialize_trim(self, job_id: str, record):
        """ADR-041: build the trimmed working copy once (idempotent via marker).

        The original upload is never modified. Live SAM consent binds the
        ORIGINAL hash, so trim + live segmentation is refused outright.
        Clearing a previously materialized trim re-probes the original and
        restores source_info.
        """
        start = record.trim_start_s or 0.0
        end = record.trim_end_s if record.trim_end_s is not None else None
        duration = record.source_info.duration_seconds
        if end is None:
            end = duration
        if start <= 0 and end >= duration - 1e-6:
            if record.trimmed_relative_path or record.trimmed_sha256:
                # Trim was cleared after materialization: restore original info.
                original = self._canonical_source_path(record)
                info = self._probe_trimmed_source(original)
                return self.store.update(
                    job_id,
                    source_info=info,
                    trimmed_relative_path=None,
                    trimmed_sha256=None,
                )
            return record
        if self.providers.segmentation_mode == "live":
            raise ValueError(
                "Trim is not supported with live SAM segmentation: consent binds the "
                "original source hash. Clear the trim or use mock segmentation."
            )
        job_dir = self.store.job_dir(job_id)
        trimmed_path = job_dir / "trimmed_source.mp4"
        marker_path = job_dir / "trimmed.json"
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else {}
        except ValueError:
            marker = {}
        if (
            trimmed_path.is_file()
            and marker.get("start_s") == start
            and marker.get("end_s") == end
        ):
            if record.trimmed_relative_path and record.trimmed_sha256:
                return record
        else:
            original = self._canonical_source_path(record)
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                    "-i", str(original),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    str(trimmed_path),
                ],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0 or not trimmed_path.is_file() or trimmed_path.stat().st_size == 0:
                raise ValueError(
                    f"Trimmed clip could not be rendered: {result.stderr.strip()[-200:]}"
                )
            marker_path.write_text(
                json.dumps({"start_s": start, "end_s": end}), encoding="utf-8"
            )
        info = self._probe_trimmed_source(trimmed_path)
        digest = sha256_file(trimmed_path)
        return self.store.update(
            job_id,
            source_info=info,
            trimmed_relative_path=str(trimmed_path.relative_to(self.store.root)).replace("\\", "/"),
            trimmed_sha256=digest,
        )

    def _validate_render_provenance(self, record, segmentation):
        """Bind the persisted masks to the effective render source before rendering.

        The original upload is verified unchanged first (audit + live-consent
        anchor); masks then bind the trimmed working copy when a trim is set.
        """
        original_path = self._canonical_source_path(record)
        if record.source_sha256 and sha256_file(original_path) != record.source_sha256:
            raise ValueError(
                "The original upload changed after ingestion; refusing to render stale masks."
            )
        source_path = self._effective_source_path(record)
        expected_hash = (
            record.trimmed_sha256 if record.trimmed_relative_path else record.source_sha256
        )
        source_hash = sha256_file(source_path)
        if expected_hash and source_hash != expected_hash:
            raise ValueError(
                "The render source does not match the ingested clip; refusing to render."
            )
        if segmentation.source_sha256 and segmentation.source_sha256 != source_hash:
            raise ValueError(
                "Segmentation masks do not belong to the render source; refusing to render."
            )
        info = record.source_info
        if (segmentation.width, segmentation.height) != (info.width, info.height):
            raise ValueError(
                "Segmentation dimensions do not match the original upload; refusing to render."
            )
        if segmentation.frame_count != info.frame_count:
            raise ValueError(
                "Segmentation frame count does not match the original upload; refusing to render."
            )
        if abs(segmentation.fps - info.fps) > 0.01:
            raise ValueError(
                "Segmentation FPS does not match the original upload; refusing to render."
            )
        for subject in segmentation.subjects:
            _, manifest = MaskLoader().load_manifest(Path(subject.mask_manifest_path).parent)
            if manifest.source_sha256 and manifest.source_sha256 != source_hash:
                raise ValueError(
                    "A subject mask manifest does not belong to the original upload; "
                    "refusing to render."
                )
            if (manifest.video_width, manifest.video_height) != (info.width, info.height):
                raise ValueError(
                    "A subject mask manifest has the wrong dimensions; refusing to render."
                )
            if manifest.frame_count != info.frame_count:
                raise ValueError(
                    "A subject mask manifest has the wrong frame count; refusing to render."
                )
            if abs(manifest.fps - info.fps) > 0.01:
                raise ValueError(
                    "A subject mask manifest has the wrong FPS; refusing to render."
                )
        return source_path

    @staticmethod
    def _validate_background_asset(background: BackgroundResult) -> None:
        path = Path(background.image_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("Generated background image is missing or empty; refusing to render.")
        try:
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise ValueError(
                        f"Generated background must be PNG; got {image.format or 'unknown'}."
                    )
                width, height = image.size
                image.verify()
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                "Generated background image is corrupt or unreadable; refusing to render."
            ) from exc
        if (width, height) != (background.width, background.height):
            raise ValueError(
                "Generated background dimensions do not match its provenance record."
            )
        if background.image_sha256 and sha256_file(path) != background.image_sha256:
            raise ValueError(
                "Generated background hash does not match its provenance record."
            )

    def _background_sidecar_path(self, job_id: str) -> Path:
        return self.store.job_dir(job_id) / "background" / "background.json"

    def _recover_background(self, job_id: str) -> BackgroundResult | None:
        sidecar = self._background_sidecar_path(job_id)
        if not sidecar.is_file():
            return None
        try:
            background = BackgroundResult.model_validate_json(
                sidecar.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ValueError(
                "Persisted background provenance is unreadable; refusing to regenerate."
            ) from exc
        self._validate_background_asset(background)
        return background

    def _get_or_generate_background(
        self,
        job_id: str,
        base: JobResult,
        *,
        prompt: str,
        orientation: str,
    ) -> tuple[BackgroundResult, JobResult]:
        if base.background is not None:
            self._validate_background_asset(base.background)
            return base.background, base

        recovered = self._recover_background(job_id)
        if recovered is not None:
            base = base.model_copy(update={"background": recovered})
            self.store.update(job_id, result=base)
            return recovered, base

        if base.background_generation_attempted:
            raise ValueError(
                "Background generation was already attempted for this job; refusing to "
                "regenerate. No local fallback asset will be used."
            )

        # Persist the one-shot marker before any billable request.
        base = base.model_copy(update={"background_generation_attempted": True})
        self.store.update(job_id, result=base)

        authorization = None
        if getattr(self.providers, "image_mode", "mock") == "live":
            authorization = LiveCallAuthorization(
                LiveCallBudget(self.store.root), "image"
            )
        background = self.providers.background.generate(
            prompt=prompt,
            orientation=orientation,
            output_dir=self.store.job_dir(job_id) / "background",
            job_id=job_id,
            authorization=authorization,
        )
        self._validate_background_asset(background)
        base = base.model_copy(update={"background": background})
        self.store.update(job_id, result=base)
        return background, base

    def _get_or_generate_programmatic_background(
        self,
        job_id: str,
        base: JobResult,
        *,
        backdrop_spec: dict,
        orientation: Literal["landscape", "portrait"],
    ) -> tuple[BackgroundResult, JobResult]:
        """Build the deterministic local programmatic backdrop (ADR-052).

        No provider call, no image generation, no billing: renders the poster
        frame (t=0) at the source dimensions and persists it as the validated
        BackgroundResult artifact. The worker renders every output frame from
        the same spec, so the poster always matches the video.
        """
        from clipforge_contracts import BackgroundResult
        from clipforge_worker.programmatic_bg import render_frame as render_backdrop_frame

        info = self.store.get(job_id).source_info
        width, height = int(info.width), int(info.height)
        if width <= 0 or height <= 0:
            raise ValueError("Source dimensions are unknown; refusing to render a backdrop.")
        frame_bgr = render_backdrop_frame(0.0, width, height, backdrop_spec)
        bg_dir = self.store.job_dir(job_id) / "background"
        bg_dir.mkdir(parents=True, exist_ok=True)
        poster_path = bg_dir / "programmatic_poster.png"
        import cv2 as _cv2

        ok = _cv2.imwrite(str(poster_path), frame_bgr)
        if not ok or not poster_path.is_file() or poster_path.stat().st_size == 0:
            raise ValueError("Programmatic backdrop poster could not be written.")
        from clipforge_contracts import sha256_file

        background = BackgroundResult(
            asset_id=f"bg_programmatic_{job_id[:12]}",
            image_path=str(poster_path),
            width=width,
            height=height,
            orientation=orientation,
            simulated_prompt="programmatic animated backdrop (local procedural render, no AI)",
            provider_name="clipforge-programmatic",
            is_mock=False,
            model=None,
            prompt=None,
            image_sha256=sha256_file(poster_path),
        )
        self._validate_background_asset(background)
        base = base.model_copy(update={"background": background})
        self.store.update(job_id, result=base)
        return background, base

    @staticmethod
    def _plan_requires_segmentation(plan) -> bool:
        """Segmentation runs only for plans that isolate a subject."""
        return any(operation.type == "keep_subject_sharp" for operation in plan.operations)

    def _live_consent_is_valid(self, record) -> bool:
        """Check the persisted consent without reserving, uploading or inferring."""
        if self.providers.segmentation_mode != "live":
            return True
        try:
            source_hash = sha256_file(self.store.source_path(record))
            provider_name = getattr(self.providers.segmentation, "provider_name", None)
            model = getattr(self.providers.segmentation, "model", None)
            if not provider_name or not model:
                return False
            validate_subject_detection_consent(
                record.subject_detection_consent,
                job_id=record.job_id,
                source_video_hash=source_hash,
                provider=provider_name,
                model=model,
            )
        except (OSError, ConsentValidationError, ValueError, AttributeError):
            return False
        return True

    def _run_segmentation(self, job_id: str, record):
        info = record.source_info
        # Consent always binds the ORIGINAL upload; segmentation consumes the
        # effective (possibly trimmed) source.
        original_path = self._canonical_source_path(record)
        source_path = self._effective_source_path(record)
        authorization = None
        consent = None
        if self.providers.segmentation_mode == "live":
            source_hash = sha256_file(original_path)
            if record.source_sha256 and source_hash != record.source_sha256:
                raise ConsentValidationError(
                    "subject_detection_consent_source_mismatch",
                    "The source video changed after upload; live subject detection is refused.",
                )
            provider_name = getattr(self.providers.segmentation, "provider_name", None)
            model = getattr(self.providers.segmentation, "model", None)
            if not provider_name or not model:
                raise RuntimeError("Live segmentation provider is missing provider/model identity.")
            validate_subject_detection_consent(
                record.subject_detection_consent,
                job_id=job_id,
                source_video_hash=source_hash,
                provider=provider_name,
                model=model,
            )
            consent = record.subject_detection_consent
            authorization = LiveCallAuthorization(
                LiveCallBudget(self.store.root), "segmentation"
            )
        return self.providers.segmentation.segment(
            job_id=job_id,
            source_video_id=record.job_id,
            output_dir=self.store.job_dir(job_id) / "masks",
            width=info.width,
            height=info.height,
            frame_count=info.frame_count,
            fps=info.fps,
            source_path=source_path,
            prompt="person",
            authorization=authorization,
            consent=consent,
        )

    def _execute_approved_plan(self, job_id: str, record, transcript: TranscriptResult) -> str:
        base = record.result
        if base is None or base.plan is None:
            raise ValueError("Approved job has no persisted plan; refusing to render.")
        plan = base.plan
        info = record.source_info
        job_masks_dir = self.store.job_dir(job_id) / "masks"

        segmentation = base.segmentation
        if segmentation is None:
            # Backward compatibility with jobs approved before 6D.
            self.store.update(job_id, stage="segmenting")
            segmentation = self._run_segmentation(job_id, record)
            base = base.model_copy(update={"segmentation": segmentation})
            self.store.update(job_id, result=base)

        source_path = self._validate_render_provenance(record, segmentation)

        masks_dir = job_masks_dir
        if segmentation.subjects:
            selected = list(record.selected_subject_ids)
            if not selected:
                raise ValueError(
                    "Approved job has detected subjects but no subject selection; refusing to render."
                )
            self.store.update(job_id, stage="preparing_masks")
            masks_dir = job_masks_dir / "selected"
            combine_subject_masks(
                segmentation.subjects,
                selected,
                masks_dir,
                fps=info.fps,
                source_video_id=record.job_id,
                source_sha256=segmentation.source_sha256,
            )

        loaded = MaskLoader().load(masks_dir)
        if len(loaded) != segmentation.frame_count:
            raise ValueError("Segmentation mask count does not match the segmentation result.")

        background = None
        background_spec = None
        mode = "blur_background"
        blur_strength = next(
            (op.strength for op in plan.operations if op.type == "blur_background"), 0.8
        )
        if plan.intent is EditingIntent.REPLACE_BACKGROUND:
            mode = "replace_background"
            self.store.update(job_id, stage="preparing_background")
            replace_op = next(
                (op for op in plan.operations if op.type == "replace_background"), None
            )
            prompt = replace_op.prompt if replace_op else "professional studio background"
            asset_source = replace_op.asset_source if replace_op else "mock_generated"
            if asset_source == "programmatic":
                if replace_op is None or not isinstance(replace_op.backdrop, dict):
                    raise ValueError(
                        "Programmatic background requires a validated backdrop spec; refusing to render."
                    )
                background, base = self._get_or_generate_programmatic_background(
                    job_id, base, backdrop_spec=replace_op.backdrop,
                    orientation="landscape" if info.width >= info.height else "portrait",
                )
                background_spec = replace_op.backdrop
            else:
                background, base = self._get_or_generate_background(
                    job_id,
                    base,
                    prompt=prompt,
                    orientation="landscape" if info.width >= info.height else "portrait",
                )

        self.store.update(job_id, stage="rendering")
        rendered = render_video(
            RenderRequest(
                source_path=source_path,
                masks_dir=masks_dir,
                output_path=self.store.job_dir(job_id) / "output.mp4",
                output_relative_path=f"jobs/{job_id}/output.mp4",
                mode=mode,
                background_path=background.image_path if background and background_spec is None else None,
                background_spec=background_spec,
                blur_strength=blur_strength,
                expect_audio=info.has_audio,
                audio_gain_db=record.audio_gain_db,
                audio_fade_in_s=record.audio_fade_in_s,
                audio_fade_out_s=record.audio_fade_out_s,
            ),
            on_stage=lambda stage: self.store.update(job_id, stage=stage),
        )

        result = base.model_copy(
            update={
                "segmentation": segmentation,
                "background": background,
                "rendered": rendered,
                "render_status": "verified",
            }
        )
        self.store.update(job_id, status=JobStatus.COMPLETED, stage="completed", result=result)
        self._publish_output_asset(job_id, record)
        logger.info(
            "job_completed job_id=%s outcome=rendered_and_verified frames=%d",
            job_id,
            rendered.frame_count,
        )
        return JobStatus.COMPLETED.value

    def _publish_output_asset(self, job_id: str, record) -> None:
        """Register the verified edit output as a project asset (ADR-052).

        The user can reuse the finished video (e.g. as a replacement
        background) straight from the Asset Library. Idempotent per job via a
        `published.json` marker. Publish failures are recorded in the marker
        and logged loudly — they never silently discard the verified render,
        which stays downloadable either way.
        """
        from clipforge_contracts import AssetKind, AssetProvenance, AssetRecord

        marker = self.store.job_dir(job_id) / "published.json"
        if marker.is_file():
            return
        status: dict = {"published": False, "error": None, "asset_id": None}
        try:
            if not record.project_id:
                raise ValueError("Job has no project workspace; skipping asset publication.")
            projects = ProjectStore(self.store.root)
            projects.get_project(record.project_id)
            output_path = self.store.job_dir(job_id) / "output.mp4"
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise ValueError("Verified output is missing; skipping asset publication.")
            rendered = record.result.rendered if record.result else None
            asset_id = "ast_" + secrets.token_hex(6)
            asset_dir = projects.asset_dir(record.project_id, asset_id)
            asset_dir.mkdir(parents=True, exist_ok=False)
            stored = asset_dir / "edited.mp4"
            shutil.copyfile(output_path, stored)
            meta = AssetRecord(
                asset_id=asset_id,
                project_id=record.project_id,  # type: ignore[arg-type]
                kind=AssetKind.VIDEO,
                original_filename=f"{Path(record.original_filename).stem[:200]}-editado.mp4",
                stored_filename="edited.mp4",
                mime="video/mp4",
                size_bytes=stored.stat().st_size,
                sha256=sha256_file(stored),
                provenance=AssetProvenance.LOCAL_RENDER,
                width=rendered.width if rendered else None,
                height=rendered.height if rendered else None,
                duration_seconds=rendered.duration_seconds if rendered else None,
                fps=rendered.fps if rendered else None,
                frame_count=rendered.frame_count if rendered else None,
                has_audio=rendered is not None and bool(record.source_info.has_audio),
            )
            projects.write_asset_record(record.project_id, asset_id, meta.model_dump_json(indent=2))
            status = {"published": True, "error": None, "asset_id": asset_id}
            logger.info("output_published job_id=%s asset_id=%s", job_id, asset_id)
        except Exception as exc:
            status = {"published": False, "error": f"{type(exc).__name__}: {exc}", "asset_id": None}
            logger.warning("output_publish_failed job_id=%s error=%s", job_id, status["error"])
        finally:
            try:
                marker.write_text(json.dumps(status, indent=2), encoding="utf-8")
            except OSError as exc:
                logger.warning("publish_marker_failed job_id=%s error=%s", job_id, exc)

    def _render_timeline(self, job_id: str, record) -> str:
        """ADR-044: compose the explicit user timeline into a verified MP4.

        No voice instruction, no director call. Video z-order is V2 over V1
        letterboxed on 1280x720@30; audio mixes every sounding clip (A1+A2
        plus audio of placed video clips). The originals are never modified.
        """
        from clipforge_contracts import AssetKind

        timeline = record.timeline
        if timeline is None or not timeline.clips:
            raise ValueError("Timeline render requested with an empty timeline.")
        if not record.project_id:
            raise ValueError("Timeline render requires a project workspace.")
        self.store.update(job_id, stage="timeline_composing", timeline_render_requested=False)
        projects = ProjectStore(self.store.root)
        media_cache: dict[str, TimelineMedia] = {}

        def resolve_asset(asset_id: str) -> TimelineMedia:
            cached = media_cache.get(asset_id)
            if cached is not None:
                return cached
            sidecar = projects.asset_dir(record.project_id, asset_id) / "asset.json"
            if not sidecar.is_file():
                raise ValueError(f"Timeline asset not found: {asset_id}")
            try:
                from clipforge_contracts import AssetRecord

                meta = AssetRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"Timeline asset unreadable: {asset_id}") from exc
            if meta.project_id != record.project_id:
                raise ValueError(f"Timeline asset not found: {asset_id}")
            if meta.kind not in (AssetKind.VIDEO, AssetKind.AUDIO):
                raise ValueError(f"Timeline asset is not placeable media: {asset_id}")
            path = projects.asset_dir(record.project_id, asset_id) / meta.stored_filename
            if not path.is_file():
                raise ValueError(f"Timeline asset file missing: {asset_id}")
            media = TimelineMedia(
                path=path,
                kind="video" if meta.kind == AssetKind.VIDEO else "audio",
                duration=float(meta.duration_seconds or 0.0),
                width=int(meta.width or 0),
                height=int(meta.height or 0),
                fps=float(meta.fps or 0.0),
                has_audio=bool(meta.has_audio),
            )
            media_cache[asset_id] = media
            return media

        output_path = self.store.job_dir(job_id) / "output_timeline.mp4"
        canvas = None
        if record.timeline_format == "landscape":
            canvas = (1280, 720)
        elif record.timeline_format == "portrait":
            canvas = (720, 1280)
        rendered = compose_timeline(
            timeline,
            resolve_asset,
            output_path,
            f"jobs/{job_id}/output_timeline.mp4",
            on_stage=lambda stage: self.store.update(job_id, stage=stage),
            texts=list(record.clip_texts or []),
            colour=record.colour,
            caption_cover=bool(record.caption_cover),
            canvas=canvas,
        )
        base = record.result or JobResult()
        result = base.model_copy(update={"rendered": rendered, "render_status": "verified"})
        self.store.update(job_id, status=JobStatus.COMPLETED, stage="completed", result=result)
        logger.info(
            "timeline_completed job_id=%s frames=%d program=%.2f",
            job_id, rendered.frame_count, timeline.program_duration_s(),
        )
        return JobStatus.COMPLETED.value

    def _await_approval_after_detection(        self,
        job_id: str,
        record,
        transcript: TranscriptResult,
        plan,
        director_plan,
        director_usage,
        director_request_id,
        director_audit,
    ) -> str:
        """Run segmentation when the plan needs it, then wait for user review.

        Detection happens before review so the user can choose who stays
        sharp. Rendering still cannot start before explicit approval.
        """
        segmentation = None
        if self._plan_requires_segmentation(plan):
            self.store.update(job_id, stage="segmenting")
            segmentation = self._run_segmentation(job_id, record)
            if not segmentation.subjects:
                result = self._persist_plan_result(
                    job_id,
                    transcript=transcript,
                    director_plan=director_plan,
                    director_usage=director_usage,
                    director_request_id=director_request_id,
                    director_audit=director_audit,
                    plan=plan,
                    segmentation=segmentation,
                    requires_approval=False,
                    render_status="no_subjects",
                )
                self.store.update(
                    job_id,
                    status=JobStatus.UNSUPPORTED,
                    stage="no_subjects",
                    result=result,
                    error=JobError(
                        code="NoSubjectsDetected",
                        message=(
                            "No people were detected in this clip. Use a clip with a visible "
                            "person or choose a different edit."
                        ),
                    ),
                )
                logger.info("job_no_subjects job_id=%s", job_id)
                return JobStatus.UNSUPPORTED.value

        # Every ready plan, including blur-only plans, requires explicit user review.
        result = self._persist_plan_result(
            job_id,
            transcript=transcript,
            director_plan=director_plan,
            director_usage=director_usage,
            director_request_id=director_request_id,
            director_audit=director_audit,
            plan=plan,
            segmentation=segmentation,
            requires_approval=True,
            render_status="awaiting_approval",
        )
        self.store.update(
            job_id, status=JobStatus.AWAITING_APPROVAL, stage="awaiting_approval", result=result
        )
        logger.info(
            "job_awaiting_approval job_id=%s ops=%d subjects=%d",
            job_id,
            len(plan.operations),
            len(segmentation.subjects) if segmentation else 0,
        )
        return JobStatus.AWAITING_APPROVAL.value

    def process(self, job_id: str) -> str:
        """Process one claimed job. Returns the resulting status value."""
        record = self.store.get(job_id)
        transcript: TranscriptResult | None = None
        plan = None
        # ADR-044: explicit user timeline composition — no voice, no director,
        # real FFmpeg/OpenCV compose. Branches before the voice requirement.
        if record.timeline_render_requested:
            return self._render_timeline(job_id, record)
        director_plan = None
        director_usage = None
        director_request_id = None
        director_audit = None
        try:
            if not record.audio_fixture_id and not record.confirmed_transcript:
                raise ValueError("Job has no voice instruction attached.")
            if record.confirmed_transcript:
                transcript = TranscriptResult(
                    text=record.confirmed_transcript,
                    language="pt-BR",
                    provider_name="user-confirmed",
                    is_mock=record.transcript_is_mock,
                    session_id=record.transcription_session_id,
                )
            else:
                self.store.update(job_id, stage="transcribing")
                transcript = self.providers.transcription.transcribe(record.audio_fixture_id or "")

            # ADR-041: materialize the trim before planning/segmentation so the
            # director metadata, masks, render and verification all bind the
            # trimmed clip. Idempotent; the original upload is never modified.
            if record.trim_start_s is not None or record.trim_end_s is not None:
                record = self._materialize_trim(job_id, record)

            # Approval re-entry: the plan is already persisted and approved. Do not
            # call the director again; render exactly the approved plan.
            if record.approval_granted:
                return self._execute_approved_plan(job_id, record, transcript)

            # Post-consent resumption: the persisted plan is fresh (consent can
            # only be granted after the plan that triggered the deferral), so
            # never call transcription or the director again — the tail below
            # validates consent once more before any SAM upload.
            existing = record.result
            if (
                existing is not None
                and existing.director_plan is not None
                and existing.plan is not None
                and existing.segmentation is None
                and self._plan_requires_segmentation(existing.plan)
            ):
                if self.providers.segmentation_mode == "live" and not self._live_consent_is_valid(record):
                    resumed = self._persist_plan_result(
                        job_id,
                        transcript=transcript,
                        director_plan=existing.director_plan,
                        director_usage=existing.director_usage,
                        director_request_id=existing.director_request_id,
                        director_audit=existing.director_audit,
                        plan=existing.plan,
                        requires_approval=True,
                        render_status="awaiting_consent",
                    )
                    self.store.update(
                        job_id, status=JobStatus.AWAITING_CONSENT, stage="awaiting_consent", result=resumed
                    )
                    logger.info("job_awaiting_consent job_id=%s", job_id)
                    return JobStatus.AWAITING_CONSENT.value
                return self._await_approval_after_detection(
                    job_id,
                    record,
                    transcript,
                    existing.plan,
                    existing.director_plan,
                    existing.director_usage,
                    existing.director_request_id,
                    existing.director_audit,
                )

            self.store.update(job_id, stage="planning")
            director = self.providers.director
            if director is None:
                raise RuntimeError("No director provider is configured.")
            info = record.source_info
            video = DirectorVideoMetadata(
                width=info.width,
                height=info.height,
                fps=info.fps,
                duration_seconds=info.duration_seconds,
                frame_count=info.frame_count,
                has_audio=info.has_audio,
            )
            try:
                if self.providers.director_mode == "live":
                    authorization = LiveCallAuthorization(
                        LiveCallBudget(self.store.root), "director"
                    )
                    director_plan = director.create_plan(  # type: ignore[union-attr]
                        transcript,
                        video,
                        authorization=authorization,
                        clarification_answer=record.clarification_answer,
                    )
                else:
                    director_plan = director.create_plan(  # type: ignore[union-attr]
                        transcript,
                        video,
                        clarification_answer=record.clarification_answer,
                    )
            except Exception:
                director_usage, director_request_id, director_audit = self._director_metadata(
                    job_id, director
                )
                if director_usage is not None or director_audit is not None:
                    self.store.update(
                        job_id,
                        result=JobResult(
                            transcript=transcript,
                            director_usage=director_usage,
                            director_request_id=director_request_id,
                            director_audit=director_audit,
                        ),
                    )
                raise

            director_usage, director_request_id, director_audit = self._director_metadata(
                job_id, director
            )
            plan = director_plan.to_execution_plan()

            if director_plan.outcome is PlanOutcome.NEEDS_CLARIFICATION:
                if record.clarification_count >= MAX_CLARIFICATIONS:
                    result = self._persist_plan_result(
                        job_id,
                        transcript=transcript,
                        director_plan=director_plan,
                        director_usage=director_usage,
                        director_request_id=director_request_id,
                        director_audit=director_audit,
                        plan=plan,
                        requires_clarification=True,
                        render_status="failed",
                    )
                    self.store.update(
                        job_id,
                        status=JobStatus.FAILED,
                        stage="failed",
                        result=result,
                        error=JobError(
                            code="ClarificationLimitError",
                            message="Clarification limit reached; start a new session.",
                        ),
                    )
                    return JobStatus.FAILED.value
                result = self._persist_plan_result(
                    job_id,
                    transcript=transcript,
                    director_plan=director_plan,
                    director_usage=director_usage,
                    director_request_id=director_request_id,
                    director_audit=director_audit,
                    plan=plan,
                    requires_clarification=True,
                    render_status="awaiting_clarification",
                )
                self.store.update(
                    job_id,
                    status=JobStatus.AWAITING_CLARIFICATION,
                    stage="awaiting_clarification",
                    result=result,
                )
                logger.info("job_awaiting_clarification job_id=%s", job_id)
                return JobStatus.AWAITING_CLARIFICATION.value

            if director_plan.outcome is PlanOutcome.UNSUPPORTED:
                result = self._persist_plan_result(
                    job_id,
                    transcript=transcript,
                    director_plan=director_plan,
                    director_usage=director_usage,
                    director_request_id=director_request_id,
                    director_audit=director_audit,
                    plan=plan,
                    render_status="not_implemented",
                )
                self.store.update(
                    job_id, status=JobStatus.UNSUPPORTED, stage="unsupported", result=result
                )
                logger.info("job_unsupported job_id=%s", job_id)
                return JobStatus.UNSUPPORTED.value

            if director_plan.approval_status is ApprovalStatus.REJECTED:
                result = self._persist_plan_result(
                    job_id,
                    transcript=transcript,
                    director_plan=director_plan,
                    director_usage=director_usage,
                    director_request_id=director_request_id,
                    director_audit=director_audit,
                    plan=plan,
                    requires_approval=True,
                    render_status="rejected",
                )
                self.store.update(
                    job_id, status=JobStatus.REJECTED, stage="rejected", result=result
                )
                return JobStatus.REJECTED.value

            # Director planned first. SAM runs only for plans that isolate a
            # subject, and in live mode only after explicit user consent.
            if self._plan_requires_segmentation(plan):
                if not self._live_consent_is_valid(record):
                    deferred = self._persist_plan_result(
                        job_id,
                        transcript=transcript,
                        director_plan=director_plan,
                        director_usage=director_usage,
                        director_request_id=director_request_id,
                        director_audit=director_audit,
                        plan=plan,
                        requires_approval=True,
                        render_status="awaiting_consent",
                    )
                    self.store.update(
                        job_id, status=JobStatus.AWAITING_CONSENT, stage="awaiting_consent", result=deferred
                    )
                    logger.info("job_awaiting_consent job_id=%s", job_id)
                    return JobStatus.AWAITING_CONSENT.value
            return self._await_approval_after_detection(
                job_id,
                record,
                transcript,
                plan,
                director_plan,
                director_usage,
                director_request_id,
                director_audit,
            )

        except Exception as exc:  # recorded + logged, never swallowed; original preserved
            logger.exception("job_failed job_id=%s error=%s", job_id, exc)
            try:
                fresh = self.store.get(job_id)
                error_result = (
                    fresh.result.model_copy(update={"render_status": "failed"})
                    if fresh.result is not None
                    else None
                )
            except Exception:
                error_result = None
            if error_result is None and (
                transcript is not None or director_plan is not None or director_audit is not None
            ):
                error_result = JobResult(
                    transcript=transcript,
                    plan=plan,
                    director_plan=director_plan,
                    director_usage=director_usage,
                    director_request_id=director_request_id,
                    director_audit=director_audit,
                    render_status="failed",
                )
            self.store.update(
                job_id,
                status=JobStatus.FAILED,
                stage="failed",
                error=JobError(
                    code=getattr(exc, "code", type(exc).__name__),
                    message=str(exc),
                ),
                result=error_result,
            )
            return JobStatus.FAILED.value
