"""Job processor: runs the mock AI pipeline for one claimed job.

Pipeline: transcribe (fixture) -> plan -> segment (real local masks) ->
optional mock background. Clarification plans complete without segmentation.
Rendering is Milestone 4 and is NEVER faked here: the result carries
render_status="not_implemented".

Every exception is logged and recorded as a structured job error; the job is
marked failed and its original upload is preserved. Nothing is swallowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from clipforge_contracts import EditingIntent
from clipforge_jobs import JobError, JobResult, JobStatus, JobStore
from clipforge_providers import ProviderBundle
from clipforge_worker.masks import MaskLoader

logger = logging.getLogger("clipforge.worker")


class JobProcessor:
    def __init__(self, store: JobStore, providers: ProviderBundle) -> None:
        self.store = store
        self.providers = providers

    def process(self, job_id: str) -> str:
        """Process one job to completion or failure. Returns the final status value."""
        record = self.store.get(job_id)
        try:
            if not record.audio_fixture_id:
                raise ValueError("Job has no voice instruction attached.")
            self.store.update(job_id, stage="transcribing")
            transcript = self.providers.transcription.transcribe(record.audio_fixture_id)

            self.store.update(job_id, stage="planning")
            plan = self.providers.planner.create_plan(transcript)

            if plan.intent is EditingIntent.CLARIFICATION_NEEDED:
                result = JobResult(transcript=transcript, plan=plan, requires_clarification=True)
                self.store.update(job_id, status=JobStatus.COMPLETED, stage="clarification_needed", result=result)
                logger.info("job_completed job_id=%s outcome=clarification_needed", job_id)
                return JobStatus.COMPLETED.value

            if plan.intent is EditingIntent.UNSUPPORTED:
                result = JobResult(transcript=transcript, plan=plan)
                self.store.update(job_id, status=JobStatus.COMPLETED, stage="unsupported_intent", result=result)
                logger.info("job_completed job_id=%s outcome=unsupported_intent", job_id)
                return JobStatus.COMPLETED.value

            self.store.update(job_id, stage="segmenting")
            info = record.source_info
            masks_dir = self.store.job_dir(job_id) / "masks"
            segmentation = self.providers.segmentation.segment(
                job_id=job_id,
                source_video_id=record.job_id,
                output_dir=masks_dir,
                width=info.width,
                height=info.height,
                frame_count=info.frame_count,
                fps=info.fps,
            )
            # Verify the masks we just produced are actually loadable and valid (ADR-005).
            loaded = MaskLoader().load(masks_dir)
            if len(loaded) != segmentation.frame_count:
                raise ValueError("Segmentation mask count does not match the segmentation result.")

            background = None
            if plan.intent is EditingIntent.REPLACE_BACKGROUND:
                self.store.update(job_id, stage="preparing_background")
                prompt = next(
                    (op.prompt for op in plan.operations if op.type == "replace_background"),
                    "professional studio background",
                )
                background = self.providers.background.generate(
                    prompt=prompt,
                    orientation="landscape" if info.width >= info.height else "portrait",
                )

            result = JobResult(
                transcript=transcript, plan=plan, segmentation=segmentation, background=background
            )
            self.store.update(job_id, status=JobStatus.COMPLETED, stage="pipeline_completed", result=result)
            logger.info("job_completed job_id=%s outcome=pipeline_completed render_status=not_implemented", job_id)
            return JobStatus.COMPLETED.value

        except Exception as exc:  # recorded + logged, never swallowed; original upload preserved
            logger.exception("job_failed job_id=%s error=%s", job_id, exc)
            self.store.update(
                job_id,
                status=JobStatus.FAILED,
                stage="failed",
                error=JobError(code=type(exc).__name__, message=str(exc)),
            )
            return JobStatus.FAILED.value
