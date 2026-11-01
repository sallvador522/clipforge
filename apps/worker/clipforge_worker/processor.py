"""Job processor: plan review, approval, clarification and real rendering.

Pipeline: confirmed transcript -> v2 Director (mock or live) -> persisted plan ->
explicit user approval -> segmentation -> optional local/mock background -> real
FFmpeg/OpenCV render -> verified output. A plan never renders before approval.
Clarification and unsupported plans never render. Every exception is logged and
recorded as a structured job error; the original upload is preserved.
"""

from __future__ import annotations

import logging

from clipforge_contracts import ApprovalStatus, EditingIntent, PlanOutcome, TranscriptResult
from clipforge_director import DirectorVideoMetadata, LiveCallAuthorization, LiveCallBudget
from clipforge_jobs import MAX_CLARIFICATIONS, JobError, JobResult, JobStatus, JobStore
from clipforge_providers import ProviderBundle
from clipforge_worker.masks import MaskLoader
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

    def _execute_approved_plan(self, job_id: str, record, transcript: TranscriptResult) -> str:
        base = record.result
        if base is None or base.plan is None:
            raise ValueError("Approved job has no persisted plan; refusing to render.")
        plan = base.plan
        info = record.source_info
        masks_dir = self.store.job_dir(job_id) / "masks"

        self.store.update(job_id, stage="segmenting")
        segmentation = self.providers.segmentation.segment(
            job_id=job_id,
            source_video_id=record.job_id,
            output_dir=masks_dir,
            width=info.width,
            height=info.height,
            frame_count=info.frame_count,
            fps=info.fps,
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
            background = self.providers.background.generate(
                prompt=prompt,
                orientation="landscape" if info.width >= info.height else "portrait",
            )

        self.store.update(job_id, stage="rendering")
        rendered = render_video(
            RenderRequest(
                source_path=self.store.source_path(record),
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

            # Every ready plan, including blur-only plans, requires explicit user review.
            result = self._persist_plan_result(
                job_id,
                transcript=transcript,
                director_plan=director_plan,
                director_usage=director_usage,
                director_request_id=director_request_id,
                director_audit=director_audit,
                plan=plan,
                requires_approval=True,
                render_status="awaiting_approval",
            )
            self.store.update(
                job_id, status=JobStatus.AWAITING_APPROVAL, stage="awaiting_approval", result=result
            )
            logger.info("job_awaiting_approval job_id=%s ops=%d", job_id, len(plan.operations))
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
                error=JobError(code=type(exc).__name__, message=str(exc)),
                result=error_result,
            )
            return JobStatus.FAILED.value
