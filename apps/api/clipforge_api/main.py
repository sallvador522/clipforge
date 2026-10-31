"""ClipForge FastAPI application (Milestone 3).

Non-blocking by design: uploads create queued jobs, the persistent worker
(apps/worker) processes them. No route performs provider or rendering work.
There is intentionally NO download endpoint yet: no rendered MP4 exists until
Milestone 4, and a fake download is prohibited.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from clipforge_api.media import UploadValidationError, probe_video
from clipforge_jobs import JobNotFoundError, JobRecord, JobStore
from clipforge_providers import ProviderBundle, get_providers

logger = logging.getLogger("clipforge.api")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # generous local cap; MVP media limits enforced by probe


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_fixture_id: str = Field(min_length=1)


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
        result=record.result.model_dump() if record.result else None,
        error=record.error.model_dump() if record.error else None,
        attempts=record.attempts,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def create_app(storage_root: str | Path | None = None, providers: ProviderBundle | None = None) -> FastAPI:
    root = Path(storage_root) if storage_root else Path(os.environ.get("CLIPFORGE_STORAGE_ROOT", "storage"))
    store = JobStore(root)
    bundle = providers if providers is not None else get_providers()  # mock by default; live raises explicitly

    app = FastAPI(title="ClipForge API", version="0.1.0")
    app.state.store = store
    app.state.providers = bundle
    app.state.storage_root = root

    @app.exception_handler(JobNotFoundError)
    async def _not_found(_: Request, exc: JobNotFoundError) -> JSONResponse:
        return _error(404, "job_not_found", str(exc))

    @app.exception_handler(UploadValidationError)
    async def _invalid_upload(_: Request, exc: UploadValidationError) -> JSONResponse:
        return _error(exc.status_code, exc.code, str(exc))

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "ai_mode": bundle.mode, "storage_root": str(root)}

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
        except UploadValidationError:
            # Invalid uploads leave no orphaned files or job records behind.
            source_path.unlink(missing_ok=True)
            upload_dir.rmdir()
            raise
        record = JobRecord(
            job_id=job_id,
            original_filename=original_name,
            source_relative_path=f"uploads/{job_id}/source{suffix}",
            source_info=info,
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
        record = store.update(job_id, audio_fixture_id=body.audio_fixture_id, ready=True, stage="queued")
        logger.info("voice_attached job_id=%s fixture=%s", job_id, body.audio_fixture_id)
        return _to_response(record)

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str) -> JobResponse:
        return _to_response(store.get(job_id))

    @app.get("/api/jobs/{job_id}/result")
    async def job_result(job_id: str) -> JSONResponse:
        record = store.get(job_id)
        if record.status.value != "completed" or record.result is None:
            return _error(409, "result_not_ready",
                          f"Job {job_id} is {record.status.value}; result available only when completed.")
        return JSONResponse(content=record.result.model_dump())

    @app.get("/api/jobs")
    async def list_jobs() -> list[JobResponse]:
        return [_to_response(r) for r in store.list_jobs()]

    return app


app = create_app()
