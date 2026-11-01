"""ClipForge FastAPI application (Milestones 3-5).

Non-blocking by design: uploads create queued jobs, the persistent worker
(apps/worker) processes and renders them. No route performs provider or
rendering work. The download endpoint serves only verified rendered outputs.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipforge_contracts import (
    SUBJECT_DETECTION_DISCLOSURE_VERSION,
    CapabilityStatus,
    SubjectDetectionConsent,
    get_capability,
    sha256_file,
)
from clipforge_api.media import UploadValidationError, probe_video
from clipforge_api.transcribe import (
    AudioValidationError,
    ensure_ffmpeg_available,
    transcribe_upload,
)
from clipforge_jobs import (
    MAX_CLARIFICATIONS,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JobStore,
    JobTransitionError,
)
from clipforge_director import LiveCallBudget
from clipforge_providers import ProviderBundle, get_providers

logger = logging.getLogger("clipforge.api")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # generous local cap; MVP media limits enforced by probe


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_fixture_id: str | None = Field(default=None, min_length=1)
    transcript: str | None = Field(default=None, min_length=1, max_length=500)
    transcription_session_id: str | None = Field(default=None, max_length=128)
    subject_detection_consent: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "VoiceRequest":
        if bool(self.audio_fixture_id) == bool(self.transcript):
            raise ValueError("Provide exactly one of audio_fixture_id (mock) or transcript (reviewed text).")
        return self


class PlanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=300)
    subject_ids: list[str] | None = Field(default=None, max_length=16)


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=300)


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: str
    stage: str
    ready: bool
    original_filename: str
    audio_fixture_id: str | None
    source_info: dict
    result: dict | None
    error: dict | None
    attempts: int
    created_at: str
    updated_at: str


def _to_response(record: JobRecord) -> JobResponse:
    return JobResponse(
        job_id=record.job_id,
        status=record.status.value,
        stage=record.stage,
        ready=record.ready,
        original_filename=record.original_filename,
        audio_fixture_id=record.audio_fixture_id,
        source_info=record.source_info.model_dump(),
        result=record.result.model_dump(mode="json") if record.result else None,
        error=record.error.model_dump() if record.error else None,
        attempts=record.attempts,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _capability_payload(
    capability,
    segmentation_provider,
    segmentation_result=None,
) -> dict:
    """Report the capability status from the provider that actually runs it.

    The static registry marks subject isolation as a mock-capable executable; the
    runtime label must follow the segmentation provider (or its persisted result)
    so a real SAM run is never shown as MOCK/SIMULATED.
    """
    status = capability.status
    simulated = capability.simulated
    if capability.capability_id == "subject.isolate":
        if segmentation_result is not None:
            execution_mode = "mock" if segmentation_result.is_mock else "live"
        else:
            execution_mode = getattr(segmentation_provider, "execution_mode", None)
        if execution_mode == "live":
            status = CapabilityStatus.AVAILABLE_LIVE
            simulated = False
        elif execution_mode == "mock":
            status = CapabilityStatus.AVAILABLE_MOCK
            simulated = True
        else:
            status = CapabilityStatus.DISABLED
            simulated = True
    return {
        "capability_id": capability.capability_id,
        "name": capability.name,
        "status": status.value,
        "simulated": simulated,
        "requires_approval": capability.requires_approval,
        "provider": capability.required_provider,
    }


def _subject_review(record: JobRecord) -> dict:
    result = record.result
    segmentation = result.segmentation if result is not None else None
    if segmentation is None:
        return {
            "subjects": [],
            "segmentation": None,
            "selected_subject_ids": record.selected_subject_ids,
            "selection_required": False,
            "no_subjects": False,
        }
    subjects = [
        {
            "object_id": subject.object_id,
            "label": subject.label,
            "preview_url": (
                f"/api/jobs/{record.job_id}/subjects/{subject.object_id}/preview"
                if subject.preview_path
                else None
            ),
            "first_frame": subject.first_frame,
            "last_frame": subject.last_frame,
            "frames_detected": subject.frames_detected,
            "confidence": subject.confidence,
        }
        for subject in segmentation.subjects
    ]
    return {
        "subjects": subjects,
        "segmentation": {
            "provider": segmentation.provider_name,
            "model": segmentation.model,
            "is_mock": segmentation.is_mock,
            "status": segmentation.status,
            "frame_count": segmentation.frame_count,
            "width": segmentation.width,
            "height": segmentation.height,
            "fps": segmentation.fps,
            "diagnostics": segmentation.diagnostics,
            "file_cleanup": segmentation.file_cleanup,
        },
        "selected_subject_ids": record.selected_subject_ids,
        "selection_required": len(subjects) > 1,
        "no_subjects": not subjects,
    }


def create_app(storage_root: str | Path | None = None, providers: ProviderBundle | None = None) -> FastAPI:
    root = Path(storage_root) if storage_root else Path(os.environ.get("CLIPFORGE_STORAGE_ROOT", "storage"))
    store = JobStore(root)
    bundle = providers if providers is not None else get_providers()  # mock by default; live raises explicitly

    app = FastAPI(title="ClipForge API", version="0.1.0")
    # Local studio frontend only (Milestone 5). No credentials are involved in mock mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.providers = bundle
    app.state.storage_root = root

    @app.exception_handler(JobNotFoundError)
    async def _not_found(_: Request, exc: JobNotFoundError) -> JSONResponse:
        return _error(404, "job_not_found", str(exc))

    @app.exception_handler(JobTransitionError)
    async def _invalid_transition(_: Request, exc: JobTransitionError) -> JSONResponse:
        return _error(409, exc.code, str(exc))

    @app.exception_handler(UploadValidationError)
    async def _invalid_upload(_: Request, exc: UploadValidationError) -> JSONResponse:
        return _error(exc.status_code, exc.code, str(exc))

    @app.exception_handler(AudioValidationError)
    async def _invalid_audio(_: Request, exc: AudioValidationError) -> JSONResponse:
        return _error(exc.status_code, exc.code, str(exc))

    @app.get("/health")
    async def health() -> dict:
        budget = LiveCallBudget(root)
        return {
            "status": "ok",
            "ai_mode": bundle.mode,
            "transcribe_mode": bundle.transcription_mode,
            "director_mode": bundle.director_mode,
            "segmentation_mode": bundle.segmentation_mode,
            "subject_detection_disclosure_version": SUBJECT_DETECTION_DISCLOSURE_VERSION,
            "live_transcription_available": bundle.transcription_mode == "live",
            "live_call_limits": budget.limits,
            "live_calls_used": {function: budget.used(function) for function in budget.limits},
            "storage_root": str(root),
        }

    @app.post("/api/uploads", status_code=201, response_model=None)
    async def upload(file: UploadFile = File(...)) -> JobResponse | JSONResponse:
        original_name = Path(file.filename or "").name  # strip any client-side path components
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return _error(422, "unsupported_extension",
                          f"Extension {suffix or '(none)'} not allowed; use {sorted(ALLOWED_EXTENSIONS)}.")
        job_id = uuid.uuid4().hex
        upload_dir = store.uploads_dir / job_id
        upload_dir.mkdir(parents=True, exist_ok=False)
        source_path = upload_dir / f"source{suffix}"
        size = 0
        try:
            with source_path.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise UploadValidationError("file_too_large", "Upload exceeds the local size limit.", 413)
                    out.write(chunk)
            if size == 0:
                raise UploadValidationError("empty_file", "Uploaded file is empty.", 400)
            info = probe_video(source_path)
            source_sha256 = sha256_file(source_path)
        except UploadValidationError:
            # Invalid uploads leave no orphaned files or job records behind.
            source_path.unlink(missing_ok=True)
            upload_dir.rmdir()
            raise
        except OSError as exc:
            source_path.unlink(missing_ok=True)
            upload_dir.rmdir()
            raise UploadValidationError(
                "file_unreadable", "Uploaded file could not be read.", 422
            ) from exc
        record = JobRecord(
            job_id=job_id,
            original_filename=original_name,
            source_relative_path=f"uploads/{job_id}/source{suffix}",
            source_info=info,
            source_sha256=source_sha256,
        )
        store.create(record)
        logger.info("job_created job_id=%s file=%s size=%d", job_id, original_name, size)
        return _to_response(record)

    @app.post("/api/jobs/{job_id}/voice", response_model=None)
    async def submit_voice(job_id: str, body: VoiceRequest) -> JobResponse | JSONResponse:
        record = store.get(job_id)
        if record.status.value != "queued" or record.ready:
            return _error(409, "job_not_accepting_voice",
                          f"Job {job_id} is {record.status.value} (stage={record.stage}) and cannot accept voice input.")

        consent_record = None
        source_hash = None
        if bundle.segmentation_mode == "live":
            if body.subject_detection_consent is not True:
                return _error(
                    422,
                    "subject_detection_consent_required",
                    "Live SAM subject detection requires explicit consent before a "
                    "video-only copy is sent to Meta. Set subject_detection_consent=true "
                    "only after showing the disclosure.",
                )
            source_path = store.source_path(record)
            try:
                source_hash = sha256_file(source_path)
            except OSError:
                return _error(
                    409,
                    "source_video_unreadable",
                    "The source video could not be read for consent binding.",
                )
            if record.source_sha256 and source_hash != record.source_sha256:
                return _error(
                    409,
                    "subject_detection_consent_source_mismatch",
                    "The source video changed after upload; upload it again and provide consent.",
                )
            provider_name = getattr(bundle.segmentation, "provider_name", None)
            model = getattr(bundle.segmentation, "model", None)
            if not provider_name or not model:
                return _error(
                    500,
                    "segmentation_provider_misconfigured",
                    "Live segmentation provider is missing provider/model identity.",
                )
            consent_record = SubjectDetectionConsent(
                job_id=job_id,
                source_video_hash=source_hash,
                consent_given=True,
                consent_timestamp=datetime.now(timezone.utc),
                disclosure_version=SUBJECT_DETECTION_DISCLOSURE_VERSION,
                provider=provider_name,
                model=model,
                segmentation_mode="live",
            )

        changes: dict[str, object] = {"ready": True, "stage": "queued"}
        if consent_record is not None:
            changes["subject_detection_consent"] = consent_record
            changes["source_sha256"] = source_hash
        if body.transcript:
            changes.update(
                confirmed_transcript=body.transcript.strip(),
                transcript_is_mock=bundle.transcription_mode == "mock",
                transcription_session_id=body.transcription_session_id,
            )
            logger.info("transcript_confirmed job_id=%s chars=%d", job_id, len(body.transcript.strip()))
        else:
            changes["audio_fixture_id"] = body.audio_fixture_id
            logger.info("voice_attached job_id=%s fixture=%s", job_id, body.audio_fixture_id)
        record = store.update(job_id, **changes)
        return _to_response(record)

    @app.post("/api/transcribe", response_model=None)
    async def transcribe(file: UploadFile = File(...), mock_fixture_id: str | None = Form(default=None)):
        """One recording in, one transcript out. No retries, no paid call in mock mode."""
        ensure_ffmpeg_available()
        upload_bytes = await file.read()
        result, mode = transcribe_upload(
            upload_bytes,
            file.filename or "",
            providers=bundle,
            mock_fixture_id=mock_fixture_id,
            budget=LiveCallBudget(root) if bundle.transcription_mode == "live" else None,
        )
        logger.info(
            "transcribe_completed mode=%s provider=%s session=%s",
            mode, result.provider_name, result.session_id or "n/a",
        )
        return {**result.model_dump(), "transcribe_mode": mode}

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str) -> JobResponse:
        return _to_response(store.get(job_id))

    @app.get("/api/jobs/{job_id}/result")
    async def job_result(job_id: str) -> JSONResponse:
        record = store.get(job_id)
        if record.status.value != "completed" or record.result is None:
            return _error(409, "result_not_ready",
                          f"Job {job_id} is {record.status.value}; result available only when completed.")
        return JSONResponse(content=record.result.model_dump(mode="json"))

    @app.get("/api/jobs/{job_id}/plan")
    async def job_plan(job_id: str) -> JSONResponse:
        record = store.get(job_id)
        result = record.result
        plan = result.director_plan if result is not None else None
        if result is None or plan is None:
            return _error(409, "plan_not_ready", f"Job {job_id} has no persisted editing plan.")
        question = plan.clarification_questions[0] if plan.clarification_questions else None
        capabilities = []
        for operation in plan.operations:
            capability = get_capability(operation.capability_id)
            if capability is not None:
                capabilities.append(
                    _capability_payload(
                        capability,
                        bundle.segmentation,
                        result.segmentation,
                    )
                )
        return JSONResponse(
            content={
                "job_id": record.job_id,
                "status": record.status.value,
                "stage": record.stage,
                "ready": record.ready,
                "plan": plan.model_dump(mode="json"),
                "legacy_plan": result.plan.model_dump(mode="json") if result.plan else None,
                "capabilities": capabilities,
                "requires_approval": result.requires_approval,
                "requires_clarification": result.requires_clarification,
                "clarification_question": question,
                "clarification_count": record.clarification_count,
                "render_status": result.render_status,
                "error": record.error.model_dump() if record.error else None,
                **_subject_review(record),
            }
        )

    @app.get("/api/jobs/{job_id}/subjects/{object_id}/preview", response_model=None)
    async def subject_preview(job_id: str, object_id: str) -> FileResponse | JSONResponse:
        record = store.get(job_id)
        result = record.result
        segmentation = result.segmentation if result is not None else None
        subject = next(
            (item for item in (segmentation.subjects if segmentation else []) if item.object_id == object_id),
            None,
        )
        if subject is None or not subject.preview_path:
            return _error(404, "subject_preview_not_found", "No preview exists for this subject.")
        path = Path(subject.preview_path)
        try:
            path.resolve().relative_to(store.job_dir(job_id).resolve())
        except ValueError:
            return _error(404, "subject_preview_not_found", "No preview exists for this subject.")
        if not path.is_file():
            return _error(404, "subject_preview_not_found", "No preview exists for this subject.")
        return FileResponse(path, media_type="image/png", filename=f"subject_{object_id}.png")

    @app.post("/api/jobs/{job_id}/approve", response_model=None)
    async def approve_plan(job_id: str, body: PlanDecisionRequest | None = None) -> JobResponse | JSONResponse:
        record = store.get(job_id)
        if record.status is not JobStatus.AWAITING_APPROVAL:
            return _error(
                409,
                "approval_not_allowed",
                f"Job {job_id} is {record.status.value}; only awaiting_approval plans can be approved.",
            )
        if record.result is None or record.result.director_plan is None:
            return _error(409, "plan_not_ready", f"Job {job_id} has no persisted plan to approve.")
        segmentation = record.result.segmentation
        selected_subject_ids: list[str] = []
        if segmentation is not None:
            if not segmentation.subjects:
                return _error(
                    409,
                    "no_subjects_detected",
                    "No people were detected in this clip; there is no subject to keep sharp.",
                )
            allowed = {subject.object_id for subject in segmentation.subjects}
            requested = list(body.subject_ids) if body and body.subject_ids else []
            if not requested:
                if record.selected_subject_ids:
                    requested = list(record.selected_subject_ids)
                elif len(allowed) == 1:
                    requested = [next(iter(allowed))]
                else:
                    return _error(
                        422,
                        "subject_selection_required",
                        "Select at least one detected person before approving the plan.",
                    )
            selected_subject_ids = list(dict.fromkeys(requested))
            if not selected_subject_ids:
                return _error(
                    422,
                    "subject_selection_required",
                    "Select at least one detected person before approving the plan.",
                )
            unknown = [subject_id for subject_id in selected_subject_ids if subject_id not in allowed]
            if unknown:
                return _error(
                    422,
                    "invalid_subject_selection",
                    f"Unknown subject id(s): {unknown}. Only detected SAM object ids can be selected.",
                )
            if len(selected_subject_ids) > 16:
                return _error(422, "invalid_subject_selection", "At most 16 subjects can be selected.")
        result = record.result.model_copy(update={"render_status": "approved"})
        updated = store.transition(
            job_id,
            expected=JobStatus.AWAITING_APPROVAL,
            status=JobStatus.QUEUED,
            stage="approved",
            actor="user",
            note=(body.note if body and body.note else "plan approved"),
            approval_granted=True,
            selected_subject_ids=selected_subject_ids,
            result=result,
        )
        logger.info("plan_approved job_id=%s", job_id)
        return _to_response(updated)

    @app.post("/api/jobs/{job_id}/reject", response_model=None)
    async def reject_plan(job_id: str, body: PlanDecisionRequest | None = None) -> JobResponse | JSONResponse:
        record = store.get(job_id)
        if record.status not in {JobStatus.AWAITING_APPROVAL, JobStatus.AWAITING_CLARIFICATION}:
            return _error(
                409,
                "rejection_not_allowed",
                f"Job {job_id} is {record.status.value}; only reviewable plans can be rejected.",
            )
        result = (
            record.result.model_copy(update={"render_status": "rejected"})
            if record.result is not None
            else None
        )
        updated = store.transition(
            job_id,
            expected={JobStatus.AWAITING_APPROVAL, JobStatus.AWAITING_CLARIFICATION},
            status=JobStatus.REJECTED,
            stage="rejected",
            actor="user",
            note=(body.note if body and body.note else "plan rejected"),
            approval_granted=False,
            result=result,
        )
        logger.info("plan_rejected job_id=%s", job_id)
        return _to_response(updated)

    @app.post("/api/jobs/{job_id}/clarify", response_model=None)
    async def clarify_plan(job_id: str, body: ClarificationRequest) -> JobResponse | JSONResponse:
        record = store.get(job_id)
        if record.status is not JobStatus.AWAITING_CLARIFICATION:
            return _error(
                409,
                "clarification_not_allowed",
                f"Job {job_id} is {record.status.value}; it is not awaiting clarification.",
            )
        if record.clarification_count >= MAX_CLARIFICATIONS:
            return _error(
                409,
                "clarification_limit_reached",
                "Clarification limit reached; start a new session with a more specific instruction.",
            )
        answer = body.answer.strip()
        if not answer:
            return _error(422, "empty_clarification", "The clarification answer cannot be empty.")
        result = (
            record.result.model_copy(update={"render_status": "replanning"})
            if record.result is not None
            else None
        )
        updated = store.transition(
            job_id,
            expected=JobStatus.AWAITING_CLARIFICATION,
            status=JobStatus.QUEUED,
            stage="replanning",
            actor="user",
            note="clarification answered",
            approval_granted=False,
            clarification_answer=answer,
            clarification_count=record.clarification_count + 1,
            result=result,
        )
        logger.info("clarification_answered job_id=%s round=%d", job_id, updated.clarification_count)
        return _to_response(updated)

    @app.get("/api/jobs")
    async def list_jobs() -> list[JobResponse]:
        return [_to_response(r) for r in store.list_jobs()]

    @app.get("/api/jobs/{job_id}/download", response_model=None)
    async def download(job_id: str) -> FileResponse | JSONResponse:
        record = store.get(job_id)
        # Only a verified, on-disk rendered output may ever be downloaded.
        if (
            record.status.value != "completed"
            or record.result is None
            or record.result.render_status != "verified"
            or record.result.rendered is None
        ):
            return _error(409, "download_not_ready",
                          f"Job {job_id} has no verified rendered output (status={record.status.value}).")
        output_path = root / record.result.rendered.output_relative_path
        if not output_path.is_file() or output_path.stat().st_size == 0:
            return _error(409, "download_not_ready", f"Rendered output for job {job_id} is missing on disk.")
        return FileResponse(
            output_path, media_type="video/mp4", filename=f"clipforge-{job_id}.mp4"
        )

    return app


app = create_app()
