"""Job processor: plan review, approval, clarification and real rendering.

Pipeline: confirmed transcript -> v2 Director (mock or live) -> persisted plan ->
explicit user approval -> segmentation -> optional local/mock background -> real
FFmpeg/OpenCV render -> verified output. A plan never renders before approval.
Clarification and unsupported plans never render. Every exception is logged and
recorded as a structured job error; the original upload is preserved.
"""

from __future__ import annotations

import logging
from pathlib import Path

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
from clipforge_providers import ProviderBundle
from clipforge_worker.masks import MaskLoader, combine_subject_masks
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
        """The original upload is the only legal render source; never a SAM derivative."""
        path = self.store.source_path(record)
        if not path.is_file():
            raise ValueError("Canonical original upload is missing; refusing to render.")
        return path

    def _validate_render_provenance(self, record, segmentation):
        """Bind the persisted masks to the canonical original upload before rendering."""
        source_path = self._canonical_source_path(record)
        source_hash = sha256_file(source_path)
        if record.source_sha256 and record.source_sha256 != source_hash:
            raise ValueError(
                "The original upload changed after ingestion; refusing to render stale masks."
            )
        if segmentation.source_sha256 and segmentation.source_sha256 != source_hash:
            raise ValueError(
                "Segmentation masks do not belong to the original upload; refusing to render."
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

    def _run_segmentation(self, job_id: str, record):
        info = record.source_info
        source_path = self._canonical_source_path(record)
        authorization = None
        consent = None
        if self.providers.segmentation_mode == "live":
            source_hash = sha256_file(source_path)
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
        mode = "blur_background"
        blur_strength = next(
            (op.strength for op in plan.operations if op.type == "blur_background"), 0.8
        )
        if plan.intent is EditingIntent.REPLACE_BACKGROUND:
            mode = "replace_background"
            self.store.update(job_id, stage="preparing_background")
            prompt = next(
                (op.prompt for op in plan.operations if op.type == "replace_background"),
                "professional studio background",
            )
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
                background_path=background.image_path if background else None,
                blur_strength=blur_strength,
                expect_audio=info.has_audio,
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
        logger.info(
            "job_completed job_id=%s outcome=rendered_and_verified frames=%d",
            job_id,
            rendered.frame_count,
        )
        return JobStatus.COMPLETED.value

    def process(self, job_id: str) -> str:
        """Process one claimed job. Returns the resulting status value."""
        record = self.store.get(job_id)
        transcript: TranscriptResult | None = None
        plan = None
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

            # Approval re-entry: the plan is already persisted and approved. Do not
            # call the director again; render exactly the approved plan.
            if record.approval_granted:
                return self._execute_approved_plan(job_id, record, transcript)

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

            # Detection happens before review so the user can choose who stays
            # sharp. Rendering still cannot start before explicit approval.
            segmentation = None
            if any(operation.type == "keep_subject_sharp" for operation in plan.operations):
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
