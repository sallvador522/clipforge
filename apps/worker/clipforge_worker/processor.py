"""Job processor: runs the mock AI pipeline for one claimed job.

Pipeline: transcribe (fixture) -> plan -> segment (real local masks) ->
optional mock background -> real render (renderer.py) -> verified output.
Clarification plans complete without segmentation or rendering, and their
result keeps render_status="not_implemented" honestly.

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
from clipforge_worker.renderer import RenderRequest, render_video

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

            # Real rendering (Milestone 4). Failure raises and fails the job below;
            # no simulated success is possible: render_status flips only after verification.
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

            result = JobResult(
                transcript=transcript, plan=plan, segmentation=segmentation, background=background,
                rendered=rendered, render_status="verified",
            )
            self.store.update(job_id, status=JobStatus.COMPLETED, stage="completed", result=result)
            logger.info("job_completed job_id=%s outcome=rendered_and_verified frames=%d", job_id, rendered.frame_count)
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
