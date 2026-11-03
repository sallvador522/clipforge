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
    AssetKind,
    AssetProvenance,
    AssetRecord,
    CapabilityStatus,
    ProjectMode,
    ProjectRecord,
    SubjectDetectionConsent,
    get_capability,
    sha256_file,
)
from clipforge_api.assets import (
    AUDIO_EXTENSIONS as ASSET_AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS as ASSET_IMAGE_EXTENSIONS,
    MAX_ASSET_BYTES as ASSET_MAX_BYTES,
    SVG_EXTENSIONS as ASSET_SVG_EXTENSIONS,
    TEXT_EXTENSIONS as ASSET_TEXT_EXTENSIONS,
    VIDEO_EXTENSIONS as ASSET_VIDEO_EXTENSIONS,
    classify_suffix,
    mime_for_suffix,
    probe_audio_file,
    probe_image,
    probe_text,
    sanitize_svg,
)
from clipforge_api.exports import EXPORT_FILENAMES, ExportError, export_video
from clipforge_api.ideas import create_ideas_router
from clipforge_api.media import UploadValidationError, probe_video
from clipforge_api.transcribe import (
    AudioValidationError,
    ensure_ffmpeg_available,
    transcribe_upload,
)
from clipforge_jobs import (
    MAX_CLARIFICATIONS,
    AssetNotFoundError,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JobStore,
    JobTransitionError,
    ProjectNotFoundError,
    ProjectStore,
    SourceInfo,
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


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_detection_consent: bool | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    project_id: str | None = None
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


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=80)
    mode: str | None = Field(default=None, max_length=10)


class ProjectRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)


def _project_payload(record: ProjectRecord, asset_count: int = 0) -> dict:
    return {
        "project_id": record.project_id,
        "title": record.title,
        "mode": record.mode.value,
        "asset_count": asset_count,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _register_session_asset(
    store: ProjectStore,
    *,
    project_id: str,
    original_name: str,
    source_path: Path,
    size: int,
    info: SourceInfo,
    source_sha256: str,
) -> dict:
    """Register the uploaded editing source as a project asset (no AI triggered)."""
    import uuid as _uuid

    asset_id = "ast_" + _uuid.uuid4().hex[:12]
    suffix = Path(original_name).suffix.lower()
    stored_filename = f"original{suffix}"
    asset_dir = store.asset_dir(project_id, asset_id)
    asset_dir.mkdir(parents=True, exist_ok=False)
    # Copy (not move): the job source stays canonical; the asset is a stable copy.
    (asset_dir / stored_filename).write_bytes(source_path.read_bytes())
    record = AssetRecord(
        asset_id=asset_id,
        project_id=project_id,  # type: ignore[arg-type]
        kind=AssetKind.VIDEO,
        original_filename=Path(original_name).name[:255],
        stored_filename=stored_filename,
        mime=mime_for_suffix(suffix),
        size_bytes=size,
        sha256=source_sha256,
        provenance=AssetProvenance.SESSION_SOURCE,
        width=info.width,
        height=info.height,
        duration_seconds=info.duration_seconds,
        fps=info.fps,
        frame_count=info.frame_count,
        has_audio=info.has_audio,
    )
    store.write_asset_record(project_id, asset_id, record.model_dump_json(indent=2))
    return record.model_dump(mode="json")


def _store_uploaded_asset(
    store: ProjectStore,
    *,
    project_id: str,
    upload_bytes: bytes,
    original_name: str,
) -> dict:
    """Validate content, persist original (+ sanitized SVG) and sidecar atomically."""
    import uuid as _uuid

    clean_name = Path(original_name or "").name[:255] or "upload"
    suffix = Path(clean_name).suffix.lower()
    kind = classify_suffix(suffix)
    if kind is None:
        raise UploadValidationError(
            "unsupported_extension",
            f"Extension {suffix or '(none)'} is not a project asset; "
            "use video, audio, image, text or SVG files.",
        )
    if not upload_bytes:
        raise UploadValidationError("empty_file", "Uploaded file is empty.", 400)
    if len(upload_bytes) > ASSET_MAX_BYTES:
        raise UploadValidationError("file_too_large", "Upload exceeds the local size limit.", 413)

    asset_id = "ast_" + _uuid.uuid4().hex[:12]
    asset_dir = store.asset_dir(project_id, asset_id)
    asset_dir.mkdir(parents=True, exist_ok=False)
    stored_filename = f"original{suffix}"
    target = asset_dir / stored_filename
    metadata: dict = {}
    sanitized_bytes: bytes | None = None
    try:
        # Atomic content write first; validation reads the bytes just written.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(upload_bytes)
        os.replace(tmp, target)
        from clipforge_contracts.project import utc_now as _utc_now
        import hashlib as _hashlib

        digest = _hashlib.sha256(upload_bytes).hexdigest()
        if kind == "video":
            info = probe_video(target)
            metadata = {
                "width": info.width, "height": info.height,
                "duration_seconds": info.duration_seconds, "fps": info.fps,
                "frame_count": info.frame_count, "has_audio": info.has_audio,
            }
        elif kind == "audio":
            metadata = probe_audio_file(target)
        elif kind == "image":
            metadata = probe_image(upload_bytes)
        elif kind == "text":
            metadata = probe_text(upload_bytes, suffix)
        elif kind == "graphics":
            sanitized_bytes = sanitize_svg(upload_bytes)
            (asset_dir / "sanitized.svg").write_bytes(sanitized_bytes)
            metadata = {"sanitized": True}
        record = AssetRecord(
            asset_id=asset_id,
            project_id=project_id,  # type: ignore[arg-type]
            kind=AssetKind(kind),  # type: ignore[arg-type]
            original_filename=clean_name,
            stored_filename=stored_filename,
            mime=mime_for_suffix(suffix),
            size_bytes=len(upload_bytes),
            sha256=digest,
            provenance=AssetProvenance.UPLOAD,
            created_at=_utc_now(),
            **metadata,
        )
        store.write_asset_record(project_id, asset_id, record.model_dump_json(indent=2))
        return record.model_dump(mode="json")
    except Exception:
        # Failed uploads leave no orphaned asset directory behind.
        import shutil as _shutil

        _shutil.rmtree(asset_dir, ignore_errors=True)
        raise


def _to_response(record: JobRecord) -> JobResponse:
    return JobResponse(
        job_id=record.job_id,
        project_id=record.project_id,
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


class _ConsentBindingError(Exception):
    """Binding a consent record failed; carries the HTTP error to return."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _bind_consent_record(record: JobRecord, store: JobStore, bundle: ProviderBundle) -> SubjectDetectionConsent:
    """Build the source-bound consent record for a live job.

    Raises _ConsentBindingError (no state changed) when the source cannot be
    read, changed since upload, or the provider identity is missing. Only the
    explicit caller persists the returned record.
    """
    source_path = store.source_path(record)
    try:
        source_hash = sha256_file(source_path)
    except OSError:
        raise _ConsentBindingError(
            409,
            "source_video_unreadable",
            "The source video could not be read for consent binding.",
        )
    if record.source_sha256 and source_hash != record.source_sha256:
        raise _ConsentBindingError(
            409,
            "subject_detection_consent_source_mismatch",
            "The source video changed after upload; upload it again and provide consent.",
        )
    provider_name = getattr(bundle.segmentation, "provider_name", None)
    model = getattr(bundle.segmentation, "model", None)
    if not provider_name or not model:
        raise _ConsentBindingError(
            500,
            "segmentation_provider_misconfigured",
            "Live segmentation provider is missing provider/model identity.",
        )
    return SubjectDetectionConsent(
        job_id=record.job_id,
        source_video_hash=source_hash,
        consent_given=True,
        consent_timestamp=datetime.now(timezone.utc),
        disclosure_version=SUBJECT_DETECTION_DISCLOSURE_VERSION,
        provider=provider_name,
        model=model,
        segmentation_mode="live",
    )


def _capability_payload(
    capability,
    segmentation_provider,
    segmentation_result=None,
    *,
    background_provider=None,
    background_result=None,
) -> dict:
    """Report the capability status from the provider that actually runs it.

    The static registry marks subject isolation as a mock-capable executable and
    background replacement as a local composite. Runtime labels must follow the
    provider (or its persisted result): real SAM / Muse Image are LIVE, synthetic
    providers are MOCK, and a missing provider is UNAVAILABLE.
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
    elif capability.capability_id in {"background.replace", "background.generate"}:
        if background_result is not None:
            execution_mode = "mock" if background_result.is_mock else "live"
        else:
            execution_mode = getattr(background_provider, "execution_mode", None)
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
    projects = ProjectStore(root)
    bundle = providers if providers is not None else get_providers()  # mock by default; live raises explicitly

    app = FastAPI(title="ClipForge API", version="0.1.0")
    # Local studio frontend only (Milestone 5). No credentials are involved in mock mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.projects = projects
    app.state.providers = bundle
    app.state.storage_root = root
    app.include_router(
        create_ideas_router(root, transcription_mode=bundle.transcription_mode)
    )

    @app.exception_handler(JobNotFoundError)
    async def _not_found(_: Request, exc: JobNotFoundError) -> JSONResponse:
        return _error(404, "job_not_found", str(exc))

    @app.exception_handler(ProjectNotFoundError)
    async def _project_not_found(_: Request, exc: ProjectNotFoundError) -> JSONResponse:
        return _error(404, "project_not_found", str(exc))

    @app.exception_handler(AssetNotFoundError)
    async def _asset_not_found(_: Request, exc: AssetNotFoundError) -> JSONResponse:
        return _error(404, "asset_not_found", str(exc))

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
            "image_mode": bundle.image_mode,
            "subject_detection_disclosure_version": SUBJECT_DETECTION_DISCLOSURE_VERSION,
            "live_transcription_available": bundle.transcription_mode == "live",
            "live_image_available": bundle.image_mode == "live",
            "live_call_limits": budget.limits,
            "live_call_budget_enforced": budget.enforced,
            "live_calls_used": {function: budget.used(function) for function in budget.limits},
            "storage_root": str(root),
        }

    @app.post("/api/uploads", status_code=201, response_model=None)
    async def upload(
        file: UploadFile = File(...),
        project_id: str | None = Form(default=None),
    ) -> JobResponse | JSONResponse:
        original_name = Path(file.filename or "").name  # strip any client-side path components
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return _error(422, "unsupported_extension",
                          f"Extension {suffix or '(none)'} not allowed; use {sorted(ALLOWED_EXTENSIONS)}.")
        # Resolve the project: reuse the caller's workspace or create one so the
        # source clip is always a registered project asset (no AI triggered here).
        try:
            project: ProjectRecord | None = None
            if project_id:
                try:
                    project = projects.get_project(project_id)
                except ProjectNotFoundError:
                    return _error(404, "project_not_found", f"Project not found: {project_id}")
            else:
                base = Path(original_name).stem.strip() or "Untitled project"
                project = projects.create_project(base[:80])
        except ValueError as exc:
            return _error(422, "invalid_project", str(exc))
        assert project is not None
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
            try:
                upload_dir.rmdir()
            except OSError:
                pass
            raise
        except OSError as exc:
            source_path.unlink(missing_ok=True)
            try:
                upload_dir.rmdir()
            except OSError:
                pass
            raise UploadValidationError(
                "file_unreadable", "Uploaded file could not be read.", 422
            ) from exc
        record = JobRecord(
            job_id=job_id,
            project_id=project.project_id,
            original_filename=original_name,
            source_relative_path=f"uploads/{job_id}/source{suffix}",
            source_info=info,
            source_sha256=source_sha256,
        )
        store.create(record)
        try:
            _register_session_asset(
                projects,
                project_id=project.project_id,
                original_name=original_name,
                source_path=source_path,
                size=size,
                info=info,
                source_sha256=source_sha256,
            )
        except Exception:
            logger.warning("session_asset_registration_failed job_id=%s", job_id)
        logger.info("job_created job_id=%s project_id=%s file=%s size=%d", job_id, project.project_id, original_name, size)
        return _to_response(record)

    # -- Project workspace (P0) -------------------------------------------------
    @app.post("/api/projects", status_code=201, response_model=None)
    async def create_project(body: ProjectCreateRequest | None = None) -> JSONResponse:
        title = (body.title if body and body.title else "Untitled project").strip() or "Untitled project"
        mode_raw = (body.mode if body and body.mode else "edit").strip().lower()
        try:
            mode = ProjectMode(mode_raw)
        except ValueError:
            return _error(422, "invalid_project_mode", "Project mode must be 'edit' or 'idea'.")
        try:
            record = projects.create_project(title[:80], mode)
        except ValueError as exc:
            return _error(422, "invalid_project", str(exc))
        return JSONResponse(status_code=201, content=_project_payload(record, 0))

    @app.get("/api/projects", response_model=None)
    async def list_projects() -> JSONResponse:
        items = []
        for record in projects.list_projects():
            try:
                count = sum(1 for _ in projects.assets_dir(record.project_id).glob("*/asset.json"))
            except Exception:
                count = 0
            items.append(_project_payload(record, count))
        return JSONResponse(content={"projects": items})

    @app.get("/api/projects/{project_id}", response_model=None)
    async def get_project(project_id: str) -> JSONResponse:
        try:
            record = projects.get_project(project_id)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        try:
            count = sum(1 for _ in projects.assets_dir(record.project_id).glob("*/asset.json"))
        except Exception:
            count = 0
        return JSONResponse(content=_project_payload(record, count))

    @app.patch("/api/projects/{project_id}", response_model=None)
    async def rename_project(project_id: str, body: ProjectRenameRequest) -> JSONResponse:
        try:
            record = projects.rename_project(project_id, body.title)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        except ValueError as exc:
            return _error(422, "invalid_project", str(exc))
        try:
            count = sum(1 for _ in projects.assets_dir(record.project_id).glob("*/asset.json"))
        except Exception:
            count = 0
        return JSONResponse(content=_project_payload(record, count))

    @app.post("/api/projects/{project_id}/assets", status_code=201, response_model=None)
    async def upload_asset(project_id: str, file: UploadFile = File(...)) -> JSONResponse:
        try:
            projects.get_project(project_id)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        upload_bytes = await file.read()
        try:
            payload = _store_uploaded_asset(
                projects,
                project_id=project_id,
                upload_bytes=upload_bytes,
                original_name=file.filename or "upload",
            )
        except UploadValidationError as exc:
            return _error(exc.status_code, exc.code, str(exc))
        except OSError:
            return _error(422, "file_unreadable", "Uploaded file could not be read.")
        return JSONResponse(status_code=201, content=payload)

    @app.get("/api/projects/{project_id}/assets", response_model=None)
    async def list_assets(project_id: str) -> JSONResponse:
        try:
            projects.get_project(project_id)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        items = []
        assets_root = projects.assets_dir(project_id)
        if assets_root.is_dir():
            for path in sorted(assets_root.glob("*/asset.json")):
                try:
                    items.append(AssetRecord.model_validate_json(path.read_text(encoding="utf-8")).model_dump(mode="json"))
                except Exception:
                    continue
        return JSONResponse(content={"assets": items})

    @app.get("/api/projects/{project_id}/assets/{asset_id}", response_model=None)
    async def get_asset(project_id: str, asset_id: str) -> JSONResponse:
        try:
            projects.get_project(project_id)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        sidecar = projects.asset_dir(project_id, asset_id) / "asset.json"
        if not sidecar.is_file():
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        try:
            payload = AssetRecord.model_validate_json(sidecar.read_text(encoding="utf-8")).model_dump(mode="json")
        except Exception:
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        # Cross-project isolation: the sidecar must belong to this project.
        if payload.get("project_id") != project_id:
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        return JSONResponse(content=payload)

    @app.get("/api/projects/{project_id}/assets/{asset_id}/file", response_model=None)
    async def asset_file(project_id: str, asset_id: str) -> FileResponse | JSONResponse:
        try:
            projects.get_project(project_id)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        sidecar = projects.asset_dir(project_id, asset_id) / "asset.json"
        if not sidecar.is_file():
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        try:
            meta = AssetRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        if meta.project_id != project_id:
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        directory = projects.asset_dir(project_id, asset_id)
        # SVG: serve ONLY the sanitized copy as an image, never inline HTML/JS.
        if meta.kind == AssetKind.GRAPHICS:
            clean = directory / "sanitized.svg"
            if not clean.is_file():
                return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
            return FileResponse(
                clean, media_type="image/svg+xml", filename=meta.original_filename,
                headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"},
            )
        path = directory / meta.stored_filename
        # Contain the resolved file inside this asset directory (no traversal).
        try:
            path.resolve().relative_to(directory.resolve())
        except ValueError:
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        if not path.is_file():
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        return FileResponse(path, media_type=meta.mime, filename=meta.original_filename)

    @app.delete("/api/projects/{project_id}/assets/{asset_id}", response_model=None)
    async def delete_asset(project_id: str, asset_id: str) -> JSONResponse:
        try:
            projects.get_project(project_id)
        except ProjectNotFoundError:
            return _error(404, "project_not_found", f"Project not found: {project_id}")
        try:
            projects.delete_asset(project_id, asset_id)
        except AssetNotFoundError:
            return _error(404, "asset_not_found", f"Asset not found: {asset_id}")
        except OSError as exc:
            return _error(409, "asset_delete_failed", f"Asset could not be deleted: {exc}")
        return JSONResponse(content={"deleted": True})

    @app.post("/api/jobs/{job_id}/voice", response_model=None)
    async def submit_voice(job_id: str, body: VoiceRequest) -> JobResponse | JSONResponse:
        record = store.get(job_id)
        if record.status.value != "queued" or record.ready:
            return _error(409, "job_not_accepting_voice",
                          f"Job {job_id} is {record.status.value} (stage={record.stage}) and cannot accept voice input.")

        consent_record = None
        source_hash = None
        if bundle.segmentation_mode == "live" and body.subject_detection_consent is True:
            # Pre-granted consent is bound immediately; otherwise the worker
            # defers the job to awaiting_consent after the director plans, and
            # the dedicated /consent endpoint collects it then. Absent or false
            # consent never rejects the voice instruction itself.
            try:
                consent_record = _bind_consent_record(record, store, bundle)
            except _ConsentBindingError as exc:
                return _error(exc.status_code, exc.code, str(exc))
            source_hash = consent_record.source_video_hash

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

    @app.post("/api/jobs/{job_id}/consent", response_model=None)
    async def submit_consent(job_id: str, body: ConsentRequest) -> JobResponse | JSONResponse:
        """Grant explicit SAM consent for a job waiting in awaiting_consent.

        Binds the consent to this job and the current source-video hash, then
        re-queues the job so the worker resumes from the persisted plan —
        never re-running transcription or the director. No SAM upload happens
        here; the worker validates the record again before any upload.
        """
        record = store.get(job_id)
        if record.status is not JobStatus.AWAITING_CONSENT:
            return _error(
                409,
                "consent_not_applicable",
                f"Job {job_id} is {record.status.value}; consent is only collected while awaiting_consent.",
            )
        if body.subject_detection_consent is not True:
            return _error(
                422,
                "subject_detection_consent_required",
                "Live SAM subject detection requires explicit consent. Check the disclosure "
                "and authorize, or leave the job waiting.",
            )
        try:
            consent_record = _bind_consent_record(record, store, bundle)
        except _ConsentBindingError as exc:
            return _error(exc.status_code, exc.code, str(exc))
        updated = store.transition(
            job_id,
            expected=JobStatus.AWAITING_CONSENT,
            status=JobStatus.QUEUED,
            stage="queued",
            actor="user",
            note="subject detection consent granted",
            subject_detection_consent=consent_record,
        )
        logger.info("subject_detection_consent_granted job_id=%s", job_id)
        return _to_response(updated)

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
                        background_provider=bundle.background,
                        background_result=result.background,
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
    async def download(job_id: str, format: str = "original") -> FileResponse | JSONResponse:
        export_format = (format or "original").lower()
        if export_format not in EXPORT_FILENAMES:
            return _error(422, "invalid_export_format",
                          f"Unknown export format {format!r}; use original, reels or youtube.")
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
        if export_format != "original":
            try:
                output_path = export_video(store.job_dir(job_id), output_path, export_format)
            except ExportError as exc:
                code = exc.code if exc.code in ("invalid_export_format", "download_not_ready") else "export_failed"
                status = 422 if code == "invalid_export_format" else 409 if code == "download_not_ready" else 502
                return _error(status, code, str(exc))
        filename = EXPORT_FILENAMES[export_format].format(job_id=job_id)
        return FileResponse(
            output_path, media_type="video/mp4", filename=filename
        )

    return app


app = create_app()
