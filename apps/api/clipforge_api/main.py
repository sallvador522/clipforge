"""ClipForge FastAPI application (Milestones 3-5).

Non-blocking by design: uploads create queued jobs, the persistent worker
(apps/worker) processes and renders them. No route performs provider or
rendering work. The download endpoint serves only verified rendered outputs.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Literal
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipforge_contracts import (
    SUBJECT_DETECTION_DISCLOSURE_VERSION,
    AUDIO_TRACKS,
    VIDEO_TRACKS,
    CLIP_TEXT_MAX,
    AssetKind,
    AssetProvenance,
    AssetRecord,
    CapabilityStatus,
    ClipTextOverlay,
    ColourGrade,
    ProjectMode,
    ProjectRecord,
    SubjectDetectionConsent,
    Timeline,
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
from clipforge_api.chat_context import (
    answer_project_question,
    build_chat_context,
    context_for_prompt,
    editorial_intent_verifiable,
    has_actionable_edit_signal,
    is_direct_question,
    norm_chat_text,
)
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
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # ADR-044: 15-min 720p programs; session upload streams in 1 MB chunks


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


class InterviewAnswers(BaseModel):
    """Slots the director interviews for before creating an idea.

    Stateless multi-turn: the Studio sends back everything answered so far
    on every turn; the server merges free-text parsing over it. All fields
    optional — only complete sets become proposals.
    """

    model_config = ConfigDict(extra="forbid")
    style: Literal["cinematic", "documentary", "product", "bold"] | None = None
    duration_s: int | None = Field(default=None, ge=5, le=60)
    aspect: Literal["9:16", "16:9"] | None = None
    # The original topic sentence: chip answers refine it but never replace
    # it, so Executar always creates the video the user first described.
    brief: str | None = Field(default=None, max_length=1000)


class ChatTurnMessage(BaseModel):
    """One prior chat turn, resent by the Studio so the director can keep
    track of the conversation. Server-side state stays stateless."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "muse"]
    text: str = Field(min_length=1, max_length=1000)


class ChatRequest(BaseModel):
    """Conversational Muse turn. Side-effect free: never creates jobs,
    ideas, ledger reservations or provider calls. Execution happens only
    through the existing voice/ideas endpoints or the explicit tools/execute
    endpoint after confirmation."""

    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=1000)
    job_id: str | None = Field(default=None, max_length=128)
    project_id: str | None = Field(default=None, max_length=128)
    idea_id: str | None = Field(default=None, max_length=128)
    selected_text_id: str | None = Field(default=None, max_length=64)
    interview: InterviewAnswers | None = None
    history: list[ChatTurnMessage] = Field(default_factory=list, max_length=24)


class TrimRequest(BaseModel):
    """ADR-041 upload trim (seconds into the original source). Both null clears."""

    model_config = ConfigDict(extra="forbid")
    start_s: float | None = Field(default=None, ge=0.0)
    end_s: float | None = Field(default=None, gt=0.0)


class UploadAudioRequest(BaseModel):
    """ADR-041 upload audio: gain + fades on the preserved original audio."""

    model_config = ConfigDict(extra="forbid")
    gain_db: float = Field(default=0.0, ge=-20.0, le=12.0)
    fade_in_s: float = Field(default=0.0, ge=0.0, le=60.0)
    fade_out_s: float = Field(default=0.0, ge=0.0, le=60.0)


class CaptionCoverBody(BaseModel):
    """ADR-049 burned-in subtitle cover toggle (validated bool only)."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool


class TimelineRenderBody(BaseModel):
    """ADR-051 output canvas. Default preserves the primary source;
    the user explicitly chooses landscape/portrait instead."""

    model_config = ConfigDict(extra="forbid")
    format: str = Field(default="source", pattern=r"^(source|landscape|portrait)$")


class TimelinePutRequest(BaseModel):
    """ADR-044 full timeline replacement. The server re-validates everything."""

    model_config = ConfigDict(extra="forbid")
    timeline: Timeline


class ClipTextsPutRequest(BaseModel):
    """ADR-047 full overlay replacement. The server re-validates everything."""

    model_config = ConfigDict(extra="forbid")
    texts: list[ClipTextOverlay] = Field(default_factory=list, max_length=CLIP_TEXT_MAX)


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
    trim_start_s: float | None = None
    trim_end_s: float | None = None
    audio_gain_db: float = 0.0
    audio_fade_in_s: float = 0.0
    audio_fade_out_s: float = 0.0
    caption_cover: bool = False
    original_duration_s: float | None = None
    timeline: dict | None = None
    timeline_render_requested: bool = False
    timeline_format: str = "source"


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
        trim_start_s=record.trim_start_s,
        trim_end_s=record.trim_end_s,
        audio_gain_db=record.audio_gain_db,
        audio_fade_in_s=record.audio_fade_in_s,
        audio_fade_out_s=record.audio_fade_out_s,
        caption_cover=bool(record.caption_cover),
        original_duration_s=record.original_duration_s,
        timeline=record.timeline.model_dump(mode="json") if record.timeline else None,
        timeline_render_requested=record.timeline_render_requested,
        timeline_format=record.timeline_format,
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


_CHAT_GREETINGS = ("ola", "olá", "oi", "boas", "hello", "hi", "hey", "bom dia", "boa tarde", "boa noite")
_CHAT_HELP = ("ajuda", "o que sabes fazer", "o que consegues", "como funciona", "help", "capacidades", "o que podes fazer")
_CHAT_STATUS = ("onde estamos", "estado", "o que falta", "status")
_CHAT_CANCEL = ("cancelar", "esquece", "deixa", "cancel")

_CHAT_CAN_DO = (
    "Posso desfocar o fundo mantendo-te nítido, substituir o fundo, "
    "ou criar um vídeo novo a partir de uma ideia."
)

# ADR-053: conversational chat live rewrite. Mock (local router only) is the
# default; live reuses the verified Chat Completions contract via
# SparkChatAssistant and only rewrites the reply text — intent and pending
# proposals stay deterministic so approval gates never move.
CHAT_ENV_VAR = "CLIPFORGE_CHAT_MODE"


def _chat_mode() -> str:
    selected = os.environ.get(CHAT_ENV_VAR, "mock").strip().lower()
    return "live" if selected == "live" else "mock"


def _strip_greeting_prefix(low: str) -> str:
    for g in _CHAT_GREETINGS:
        if low.startswith(g + ",") or low.startswith(g + " "):
            return low[len(g):].lstrip(" ,!.:;-").strip()
        if low == g:
            return ""
    return low


_CHAT_COLOURS = {
    "branco": "#FFFFFF", "branca": "#FFFFFF",
    "preto": "#000000", "preta": "#000000",
    "vermelho": "#FF2D2D", "vermelha": "#FF2D2D",
    "amarelo": "#FFD400", "amarela": "#FFD400",
    "azul": "#2D9BFF",
    "verde": "#35D05A",
    "laranja": "#FF8A00",
    "rosa": "#FF5FA2",
}


_INTERVIEW_STYLES = (
    ("cinematic", ("cinemat", "epic", "filme", "cinema", "dramat", "sombrio")),
    ("documentary", ("document", "jornal", "noticia", "reportagem", "entrevista")),
    ("product", ("produto", "marca", "anuncio", "publicidade", "loja", "promo")),
    ("bold", ("ousado", "vibrante", "festa", "jovem", "cores", "pop")),
)

_INTERVIEW_STYLE_LABELS = {
    "cinematic": "Cinematográfico",
    "documentary": "Documental",
    "product": "Produto",
    "bold": "Ousado",
}

_INTERVIEW_DURATIONS = (15, 20, 25, 30, 60)
_INTERVIEW_ASPECTS = ("9:16", "16:9")


def _parse_interview_slots(text: str) -> dict:
    """Free-text slot filling for the director interview. Never guesses:
    only explicit keywords/numbers fill a slot; the rest stays empty and the
    director asks again."""
    import re

    low = text.strip().lower()
    found: dict = {}
    for style, keywords in _INTERVIEW_STYLES:
        if any(k in low for k in keywords):
            found["style"] = style
            break
    duration = None
    minute = re.search(r"(\d+)\s*(minuto|min\b)", low)
    if minute:
        duration = min(60, max(5, int(minute.group(1)) * 60))
    else:
        secs = re.search(r"(\d+)\s*(segundo|s\b|s$)", low)
        if secs:
            duration = min(60, max(5, int(secs.group(1))))
    if duration is not None:
        found["duration_s"] = duration
    if "16:9" in low or "horizontal" in low or "youtube" in low or "paisagem" in low:
        found["aspect"] = "16:9"
    elif "9:16" in low or "vertical" in low or "reels" in low or "tiktok" in low or "retrato" in low:
        found["aspect"] = "9:16"
    return found


def _interview_turn(message: str, provided: dict | None) -> dict:
    """One director interview turn. Returns the response payload when the
    message is an idea request on an empty platform, else None.

    Complete slot sets become an idea_proposal with resolved options;
    anything missing becomes an idea_interview asking exactly one question
    with quick-reply chips. Side-effect free either way.
    """
    merged = dict(provided or {})
    brief = str(merged.pop("brief", "") or "").strip() or message.strip()
    merged.update(_parse_interview_slots(message))
    style = merged.get("style")
    duration_s = merged.get("duration_s")
    aspect = merged.get("aspect")
    answered = {k: v for k, v in (("style", style), ("duration_s", duration_s), ("aspect", aspect)) if v is not None}
    if style is None:
        need, question = "style", "Que estilo queres para o vídeo?"
        options = {"styles": [{"id": s, "label": _INTERVIEW_STYLE_LABELS[s]}
                              for s, _ in _INTERVIEW_STYLES]}
    elif duration_s is None:
        need, question = "duration_s", "Qual a duração? (5 a 60 segundos)"
        options = {"durations": list(_INTERVIEW_DURATIONS)}
    elif aspect is None:
        need, question = "aspect", "Formato vertical 9:16 ou horizontal 16:9?"
        options = {"aspects": list(_INTERVIEW_ASPECTS)}
    elif len(brief) < 10:
        return {
            "intent": "idea_interview",
            "reply": "Conta-me um pouco mais sobre o vídeo — qual é o tema?",
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
            "pending_idea_options": None,
            "interview": {"needed": ["brief"], "answered": answered, "brief": brief, "options": {}},
        }
    else:
        label = (
            f"{_INTERVIEW_STYLE_LABELS[style]}, {duration_s}s, "
            f"{'vertical 9:16' if aspect == '9:16' else 'horizontal 16:9'}"
        )
        return {
            "intent": "idea_proposal",
            "reply": (
                f"Perfeito: vídeo {label}. Posso criar este vídeo? "
                "Nada foi criado ainda — prime Executar para continuar."
            ),
            "needs_confirmation": True,
            "pending_text": brief,
            "pending_kind": "idea",
            "pending_idea_options": {
                "style": style, "duration_seconds": duration_s, "aspect_ratio": aspect,
            },
            "interview": {"needed": [], "answered": answered, "brief": brief, "options": {}},
        }
    return {
        "intent": "idea_interview",
        "reply": question,
        "needs_confirmation": False,
        "pending_text": None,
        "pending_kind": None,
        "pending_idea_options": None,
        "interview": {"needed": [need], "answered": answered, "brief": brief, "options": options},
    }


def _resolve_edit_target(record, selected_text_id: str | None) -> tuple[dict | None, str | None]:
    """Pick the overlay a voice/text instruction refers to.

    Returns (overlay_dict, clarification_question). Explicit selection wins;
    a single overlay is unambiguous; several overlays without a selection
    need a spoken clarification — never a silent guess.
    """
    overlays = [t.model_dump(mode="json") for t in (record.clip_texts or [])]
    if not overlays:
        return None, (
            "Ainda não há textos neste vídeo. Adiciona um texto na aba Texto "
            "e depois digo-te o que mudo."
        )
    if selected_text_id:
        for overlay in overlays:
            if overlay["overlay_id"] == selected_text_id:
                return overlay, None
    if len(overlays) == 1:
        return overlays[0], None
    titles = ", ".join(f"«{o['text'][:40]}»" for o in overlays)
    return None, (
        "Há vários textos — qual devo alterar? " + titles +
        " Seleciona-o na pré-visualização ou diz-me o título."
    )


def _propose_edit_tools(message: str, record, selected_text_id: str | None) -> dict | None:
    """ADR-047 deterministic edit router. Pure proposal: validated tool calls
    the frontend executes only after explicit confirmation. Returns None when
    the message is not an edit instruction."""
    import re

    low = message.strip().lower()
    overlays = [t.model_dump(mode="json") for t in (record.clip_texts or [])]
    grade = record.colour if record.colour is not None else None
    contrast = float(grade.contrast) if grade else 1.0
    brightness = float(grade.brightness) if grade else 0.0
    saturation = float(grade.saturation) if grade else 1.0

    def clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, round(value, 3)))

    # Background work (removal/blur/replacement) is a director job (Muse
    # Spark plan + SAM 3.1 + Muse Image), never a clip-text tool call: bail
    # out so the classifier routes it to the approval flow.
    if ("fundo" in low and "texto" not in low and "título" not in low
            and "titulo" not in low):
        return None

    # Burned-in subtitle cover: fixed-geometry local blur band.
    if re.search(r"(tapa|tapem|cobre|cobrir|esconde).*(legenda|texto queimado|texto gravado)", low) or \
       re.search(r"(legenda|texto).*(queimada|queimado|gravada|gravado|por baixo|por tr)", low):
        cover_params: dict[str, object]
        if re.search(r"(deslig|remove|tira|sem|off).*(cobertura|tapa|blur)", low):
            cover_params = {"enabled": False}
            cover_action = "Desligo a cobertura"
        else:
            cover_params = {"enabled": True}
            cover_action = "Tapo a faixa inferior com blur"
        return {"reply": (
            f"{cover_action} para esconder legendas já queimadas no vídeo e as nossas "
            "legendas saem nítidas por cima. Confirma para executar."),
            "tool_calls": [{"tool": "captions.cover", "params": cover_params}],
            "select_text_id": None}

    # --- Translation to Portuguese (live Muse Spark, ~$0.0001, billed) -----
    if re.search(r"traduz", low):
        quoted = re.search(r"para\s+['\"“”](.+?)['\"“”]|:\s*['\"“”](.+?)['\"“”]", message.strip(), flags=re.IGNORECASE)
        raw = (quoted.group(1) or quoted.group(2)) if quoted else None
        if not raw:
            bare = re.search(r"traduz(?:ir)?\s+(.*)$", message.strip(), flags=re.IGNORECASE)
            if bare:
                rest = re.sub(r"^(para\s+)?portugu[eê]s\s*[:\-–—]?\s*",
                              "", bare.group(1).strip(), flags=re.IGNORECASE)
                if len(rest.strip()) >= 3:
                    raw = rest.strip().strip("'\"“”")[:1000]
        if not raw:
            return {"reply": (
                "Que texto devo traduzir para português? Escreve-o entre aspas — "
                "por exemplo: traduz para português 'Hello world'. "
                "Custa cerca de $0.0001 (Muse Spark) e só executo se confirmares."),
                "tool_calls": [], "select_text_id": None}
        return {"reply": (
            "Traduzo para português com o Muse Spark (cerca de $0.0001, debitado "
            "do orçamento) e crio as legendas com tempo uniforme — ajusta o tempo "
            "de cada linha nas Propriedades. Confirma para executar."),
            "tool_calls": [{"tool": "captions.translate",
                            "params": {"transcript": raw, "target_lang": "pt-PT"}}],
            "select_text_id": None}

    # --- Captions (new overlays from a transcript; timing starts uniform) --
    if re.search(r"legend", low):
        quoted = re.search(r"para\s+['\"“”](.+?)['\"“”]|:\s*['\"“”](.+?)['\"“”]", message.strip(), flags=re.IGNORECASE)
        raw = (quoted.group(1) or quoted.group(2)) if quoted else None
        # Fallback: "adiciona legendas <texto>" without quotes.
        if not raw:
            bare = re.search(r"legendas?\s+(?:o\s+texto\s+)?(.+)$", message.strip(), flags=re.IGNORECASE)
            if bare and len(bare.group(1).strip()) >= 3:
                raw = bare.group(1).strip().strip("'\"“”")[:1000]
        if not raw:
            return {"reply": (
                "Que texto devo legendar? Escreve-o entre aspas — por exemplo: "
                "adiciona legendas 'A nossa história começa aqui'. "
                "Cada linha sai com tempo editável nas Propriedades. "
                "Em português ou no idioma do texto? Se for traduzir, diz "
                "«traduz para português» e digo o custo antes de executar."),
                "tool_calls": [], "select_text_id": None}
        from clipforge_contracts import CLIP_TEXT_MAX as _MAX
        if len(overlays) >= _MAX:
            return {"reply": (
                f"Já tens {len(overlays)} textos (máximo {_MAX}). "
                "Remove um texto para eu legendar este."),
                "tool_calls": [], "select_text_id": None}
        return {"reply": (
            "Preparo as legendas desse texto (distribuição inicial uniforme "
            "pelo vídeo — ajusta o tempo de cada linha nas Propriedades). "
            "Se o vídeo já tiver legendas queimadas, diz-me «tapa as legendas "
            "queimadas» e eu cubro a faixa inferior. Em português ou no idioma "
            "do texto? Para traduzir digo o custo antes de executar. "
            "Confirma para executar."),
            "tool_calls": [{"tool": "captions.create", "params": {"transcript": raw}}],
            "select_text_id": None}

    # --- Selection ---------------------------------------------------------
    if re.search(r"selecci?ona?.*(t[ií]tulo|texto|principal)", low):
        if not overlays:
            return {"reply": "Ainda não há textos para selecionar. Adiciona um na aba Texto.",
                    "tool_calls": [], "select_text_id": None}
        if len(overlays) == 1:
            only = overlays[0]
            return {"reply": f"Selecionei «{only['text'][:60]}» — podes ver as propriedades à direita.",
                    "tool_calls": [], "select_text_id": only["overlay_id"]}
        titles = ", ".join(f"«{o['text'][:40]}»" for o in overlays)
        return {"reply": f"Qual deles? {titles} Toca no texto na pré-visualização para o selecionar.",
                "tool_calls": [], "select_text_id": None}

    # --- Colour grade (no overlay needed) -----------------------------------
    step_word = 0.5 if "ligeiramente" in low or "um pouco" in low else 1.0
    if "contraste" in low and ("aumenta" in low or "reduz" in low or "reduzir" in low
                               or "aumentar" in low or "sobe" in low or "desce" in low
                               or "mais contraste" in low or "menos contraste" in low):
        up = any(w in low for w in ("aumenta", "aumentar", "sobe", "mais contraste"))
        new = clamp(contrast + (0.15 if up else -0.15) * step_word, 0.5, 1.5)
        direction = "Aumento" if up else "Reduzo"
        return {"reply": f"{direction} o contraste de {contrast:.2f} para {new:.2f}. Confirma para executar.",
                "tool_calls": [{"tool": "colour.set",
                                "params": {"contrast": new, "brightness": brightness, "saturation": saturation}}],
                "select_text_id": None}
    if ("brilho" in low or "luminosidade" in low) and any(
            w in low for w in ("aumenta", "aumentar", "reduz", "reduzir", "sobe", "desce", "mais", "menos")):
        up = any(w in low for w in ("aumenta", "aumentar", "sobe", "mais brilho", "mais luminosidade"))
        new = clamp(brightness + (0.05 if up else -0.05) * step_word, -0.3, 0.3)
        direction = "Aumento" if up else "Reduzo"
        return {"reply": f"{direction} o brilho de {brightness:.2f} para {new:.2f}. Confirma para executar.",
                "tool_calls": [{"tool": "colour.set",
                                "params": {"contrast": contrast, "brightness": new, "saturation": saturation}}],
                "select_text_id": None}
    if "satura" in low and any(
            w in low for w in ("aumenta", "aumentar", "reduz", "reduzir", "sobe", "desce", "mais", "menos")):
        up = any(w in low for w in ("aumenta", "aumentar", "sobe", "mais"))
        new = clamp(saturation + (0.2 if up else -0.2) * step_word, 0.0, 2.0)
        direction = "Aumento" if up else "Reduzo"
        return {"reply": f"{direction} a saturação de {saturation:.2f} para {new:.2f}. Confirma para executar.",
                "tool_calls": [{"tool": "colour.set",
                                "params": {"contrast": contrast, "brightness": brightness, "saturation": new}}],
                "select_text_id": None}

    # --- Overlay edits (need a target) --------------------------------------
    wants_text = bool(re.search(r"(muda|altera|troca).*(texto|t[ií]tulo)|texto.*para\s+['\"“”]|t[ií]tulo.*para\s+['\"“”]", low))
    wants_size = "tamanho" in low
    wants_colour = "cor" in low
    wants_move = any(w in low for w in ("move", "mover", "coloca", "posiciona", "arrasta",
                                        "direita", "esquerda", "acima", "abaixo", "centro", "meio"))
    wants_anim = any(w in low for w in ("anima", "entrada", "suavemente", "fundido", "pop", "cin[eé]tico"))
    if not (wants_text or wants_size or wants_colour or wants_move or wants_anim):
        return None

    target, question = _resolve_edit_target(record, selected_text_id)
    if target is None:
        return {"reply": question or "Não percebi qual o texto.",
                "tool_calls": [], "select_text_id": None}
    patch: dict[str, object] = {}
    bits: list[str] = []

    quoted = re.search(r"para\s+['\"“”](.+?)['\"“”]", message.strip(), flags=re.IGNORECASE)
    if wants_text and quoted:
        new_text = quoted.group(1).strip()[:140]
        if new_text:
            patch["text"] = new_text
            bits.append(f"texto «{new_text[:60]}»")
    elif wants_text:
        return {"reply": f"Que texto devo pôr em «{target['text'][:60]}»? Escreve entre aspas, por exemplo: muda o texto para 'A tua marca aqui'.",
                "tool_calls": [], "select_text_id": target["overlay_id"]}

    if wants_size and any(w in low for w in ("aumenta", "aumentar", "maior", "grande")):
        step = 0.1 if step_word < 1.0 else 0.2
        patch["scale"] = clamp(float(target["scale"]) + step, 0.7, 1.6)
        bits.append(f"tamanho {patch['scale']}")
    elif wants_size and any(w in low for w in ("diminui", "diminuir", "reduz", "menor", "pequeno")):
        step = 0.1 if step_word < 1.0 else 0.2
        patch["scale"] = clamp(float(target["scale"]) - step, 0.7, 1.6)
        bits.append(f"tamanho {patch['scale']}")

    if wants_colour:
        for name, hexcode in _CHAT_COLOURS.items():
            if name in low:
                patch["color"] = hexcode
                bits.append(f"cor {name}")
                break

    if wants_move:
        x, y = float(target["x"]), float(target["y"])
        if "direita" in low:
            x = clamp(x + 0.15, 0.08, 0.92)
        if "esquerda" in low:
            x = clamp(x - 0.15, 0.08, 0.92)
        if "acima" in low or "cima" in low:
            y = clamp(y - 0.1, 0.1, 0.9)
        if "abaixo" in low or "baixo" in low:
            y = clamp(y + 0.1, 0.1, 0.9)
        if "centro" in low or "meio" in low:
            x, y = 0.5, 0.5
        patch["x"], patch["y"] = x, y
        bits.append("posição")

    if wants_anim:
        if "pop" in low:
            patch["style"] = "pop"
        elif "cin" in low:
            patch["style"] = "kinetic"
        elif "revel" in low or "suavemente" in low or "suave" in low:
            patch["style"] = "reveal"
        elif "fundido" in low:
            patch["style"] = "rise"
        if "style" in patch:
            bits.append(f"animação {patch['style']}")

    if not patch:
        return {"reply": f"Percebi que queres editar «{target['text'][:60]}», mas não percebi a alteração. Diz-me o novo texto, tamanho, cor, posição ou animação.",
                "tool_calls": [], "select_text_id": target["overlay_id"]}
    summary = ", ".join(bits)
    return {"reply": f"Preparo a alteração em «{target['text'][:60]}» ({summary}). Confirma para executar.",
            "tool_calls": [{"tool": "text.update", "params": {"overlay_id": target["overlay_id"], **patch}}],
            "select_text_id": target["overlay_id"]}


def _classify_chat(message: str, has_clip: bool) -> dict:
    """Deterministic production router. No AI/provider calls, no side effects."""
    text = message.strip()
    low = text.lower()
    if len(text) < 2 or not any(ch.isalnum() for ch in text):
        return {
            "intent": "clarify",
            "reply": "Diz-me com as tuas palavras o que queres — por exemplo «desfoca o fundo» ou «cria um vídeo sobre…».",
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }
    for c in _CHAT_CANCEL:
        if low == c or low.startswith(c + " "):
            return {
                "intent": "cancel",
                "reply": "Sem problema. Nada foi executado e nada foi alterado.",
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }
    if any(h in low for h in _CHAT_HELP):
        return {
            "intent": "help",
            "reply": (
                f"Olá! {_CHAT_CAN_DO} "
                "Descreve a alteração com a tua voz ou por escrito. "
                "Nada acontece sem a tua confirmação: eu proponho e tu decides Executar."
            ),
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }
    if any(s in low for s in _CHAT_STATUS):
        where = (
            "Tens um clipe carregado. Descreve a alteração e eu proponho o plano."
            if has_clip
            else "Ainda não tens clipe. Descreve o vídeo que queres criar ou importa um clipe."
        )
        return {
            "intent": "status",
            "reply": where,
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }
    rest = _strip_greeting_prefix(low)
    if rest == "":
        return {
            "intent": "smalltalk",
            "reply": (
                f"Olá! {_CHAT_CAN_DO} "
                "Queres editar o teu clipe ou criar um vídeo novo a partir de uma ideia?"
                if has_clip
                else f"Olá! {_CHAT_CAN_DO} Descreve o vídeo que queres criar e eu trato do resto."
            ),
            "needs_confirmation": False,
            "pending_text": None,
            "pending_kind": None,
        }
    # Keep the user's original wording for execution; only the routing used `rest`.
    if has_clip:
        low_full = text.lower()
        bg_actions = ("remov", "tirar", "trocar", "mudar", "substitu", "desfoc",
                      "blur", "blurred", "focado", "bokeh")
        if ("fundo" in low_full and any(a in low_full for a in bg_actions)
                and "texto" not in low_full and "título" not in low_full
                and "titulo" not in low_full):
            programmatic = any(k in low_full for k in
                               ("gradient", "gradiente", "animad", "minimalista", "geometric"))
            bg_path = (
                "Para um fundo animado uso o gerador programático local "
                "(gradiente + formas em movimento, sem gerar imagens nem custos extra). "
                if programmatic else
                "Para o fundo uso o director (Muse Spark): ele planeia, tu aprovas, "
                "e a remoção ou substituição corre com SAM 3.1 + Muse Image com o teu "
                "consentimento explícito. "
            )
            return {
                "intent": "edit_proposal",
                "reply": (
                    f"Percebi: «{text}». {bg_path}"
                    "Nada foi executado ainda — prime Executar para continuar ou ajusta o texto."
                ),
                "needs_confirmation": True,
                "pending_text": text,
                "pending_kind": "edit",
            }
        if not has_actionable_edit_signal(text):
            # Gibberish or content-free text (e.g. "HSDJS") is never an
            # executable instruction: clarify with real options, no pending.
            return {
                "intent": "clarify",
                "reply": (
                    f"Não percebi «{text}». Queres desfocar o fundo, substituir o fundo, "
                    "adicionar legendas/texto ou criar outro vídeo?"
                ),
                "needs_confirmation": False,
                "pending_text": None,
                "pending_kind": None,
            }
        return {
            "intent": "edit_proposal",
            "reply": (
                f"Percebi: «{text}». Posso executar isto no teu clipe? "
                "Nada foi executado ainda — prime Executar para continuar ou ajusta o texto."
            ),
            "needs_confirmation": True,
            "pending_text": text,
            "pending_kind": "edit",
        }
    return {
        "intent": "idea_proposal",
        "reply": (
            f"Boa ideia: «{text}». Posso criar este vídeo? "
            "Nada foi criado ainda — prime Executar para continuar ou ajusta o texto."
        ),
        "needs_confirmation": True,
        "pending_text": text,
        "pending_kind": "idea",
    }


def create_app(
    storage_root: str | Path | None = None,
    providers: ProviderBundle | None = None,
    *,
    chat_provider_factory=None,
) -> FastAPI:
    root = Path(storage_root) if storage_root else Path(os.environ.get("CLIPFORGE_STORAGE_ROOT", "storage"))
    store = JobStore(root)
    projects = ProjectStore(root)
    bundle = providers if providers is not None else get_providers()  # mock by default; live raises explicitly

    app = FastAPI(title="ClipForge API", version="0.1.0")
    # Local studio frontend only (Milestone 5). No credentials are involved in mock mode.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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
        chat_mode = _chat_mode()
        return {
            "status": "ok",
            "ai_mode": bundle.mode,
            "transcribe_mode": bundle.transcription_mode,
            "director_mode": bundle.director_mode,
            "segmentation_mode": bundle.segmentation_mode,
            "image_mode": bundle.image_mode,
            "chat_mode": chat_mode,
            "subject_detection_disclosure_version": SUBJECT_DETECTION_DISCLOSURE_VERSION,
            "live_transcription_available": bundle.transcription_mode == "live",
            "live_image_available": bundle.image_mode == "live",
            "live_chat_available": chat_mode == "live",
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

    @app.post("/api/chat", response_model=None)
    async def chat(body: ChatRequest) -> JSONResponse:
        """Conversational Muse turn.

        Mock (default): deterministic local router with real project context,
        side-effect free. Live (`CLIPFORGE_CHAT_MODE=live`): the same router
        and real context stay authoritative; Muse Spark converses from the
        snapshot and short history but cannot invent facts or pending work.
        Approval gates are unchanged.
        """
        text = body.message.strip()
        if not text:
            return _error(422, "empty_message", "The chat message cannot be empty.")
        record = None
        if body.job_id:
            try:
                record = store.get(body.job_id)
            except (JobNotFoundError, ProjectNotFoundError):
                record = None
            except Exception:
                record = None
        has_clip = record is not None and bool(record.original_filename)

        idea_record = None
        if body.idea_id:
            try:
                from clipforge_jobs.idea_store import IdeaStore

                idea_record = IdeaStore(root).get(body.idea_id)
            except Exception:
                idea_record = None

        context = build_chat_context(
            projects=projects,
            store=store,
            job_id=body.job_id,
            project_id=body.project_id,
            idea_id=body.idea_id,
            idea_record=idea_record,
            interview=body.interview,
            history=body.history,
        )
        context_text = context_for_prompt(context)

        # Informational questions are answers, never edit proposals — even
        # with a clip loaded. This is the user-reported regression: counting
        # project videos used to become an edit_proposal.
        question = answer_project_question(
            text, context, has_clip=has_clip, has_texts=bool(context["job"]["texts"])
        )
        if question is not None:
            logger.info(
                "chat_turn intent=question has_clip=%s chars=%d",
                has_clip,
                len(text),
            )
            return _chat_response(question, text, has_clip, context=context)

        # ADR-047 edit router: real tool proposals on the persisted job.
        if record is not None and has_clip and editorial_intent_verifiable(text):
            try:
                proposal = _propose_edit_tools(text, record, body.selected_text_id)
            except Exception:
                proposal = None
            if proposal is not None:
                needs_confirmation = bool(proposal.get("tool_calls"))
                payload: dict = {
                    "intent": "edit_tools" if needs_confirmation else "edit_clarify",
                    "reply": proposal["reply"],
                    "needs_confirmation": needs_confirmation,
                    "pending_text": text if needs_confirmation else None,
                    "pending_kind": "tools" if needs_confirmation else None,
                    "pending_tool_calls": proposal.get("tool_calls") or [],
                    "select_text_id": proposal.get("select_text_id"),
                }
                logger.info("chat_turn intent=%s has_clip=%s chars=%d tools=%d",
                            payload["intent"], has_clip, len(text),
                            len(proposal.get("tool_calls") or []))
                return _chat_response(payload, text, has_clip, context=context)
        classified = _classify_chat(text, has_clip)
        result = _guard_pending(classified, text, context)
        # Director interview (empty platform): an idea request becomes 3
        # quick questions (style/duration/format) before the proposal.
        # Smalltalk/help/status/cancel pass through untouched.
        if not has_clip and result is not None and result.get("intent") == "idea_proposal":
            provided = body.interview.model_dump(exclude_none=True) if body.interview else {}
            turn = _interview_turn(text, provided)
            payload = {
                "intent": turn["intent"],
                "reply": turn["reply"],
                "needs_confirmation": turn["needs_confirmation"],
                "pending_text": turn["pending_text"],
                "pending_kind": turn["pending_kind"],
                "pending_tool_calls": [],
                "select_text_id": None,
                "pending_idea_options": turn.get("pending_idea_options"),
                "interview": turn.get("interview"),
            }
            payload = _guard_pending(payload, text, context) or payload
            logger.info("chat_turn intent=%s has_clip=%s chars=%d interview_needed=%s",
                        payload["intent"], has_clip, len(text),
                        (turn.get("interview") or {}).get("needed"))
            return _chat_response(payload, text, has_clip, context=context)
        logger.info(
            "chat_turn intent=%s has_clip=%s chars=%d",
            result.get("intent") if result is not None else classified.get("intent"),
            has_clip,
            len(text),
        )
        return _chat_response(result, text, has_clip, context=context, context_text=context_text)

    def _guard_pending(payload: dict, text: str, context: dict | None) -> dict | None:
        """Drop pending proposals for meta/informational questions."""
        if payload.get("pending_text") is None and not payload.get("needs_confirmation"):
            return payload
        if context is not None and answer_project_question(
            text, context, has_clip=bool(context["job"]["has_clip"]),
            has_texts=bool(context["job"]["texts"]),
        ) is not None:
            return None
        if is_direct_question(text) and not editorial_intent_verifiable(text):
            return None
        if payload.get("pending_text") is None and not payload.get("needs_confirmation"):
            return payload
        if context is not None and answer_project_question(
            text, context, has_clip=bool(context["job"]["has_clip"]),
            has_texts=bool(context["job"]["texts"]),
        ) is not None:
            return dict(payload, pending_text=None, pending_kind=None, pending_tool_calls=[])
        return payload

    def _chat_response(
        payload: dict,
        message: str,
        has_clip: bool,
        *,
        context: dict | None = None,
        context_text: str | None = None,
    ) -> JSONResponse:
        """Single exit for /api/chat.

        Mock returns the contextual router payload as-is. Live sends the
        contextual snapshot to Muse Spark for the human reply; pending work
        remains server-decided and is protected by _guard_pending upstream.
        """
        if context is not None:
            payload = _guard_pending(payload, message, context) or payload

        if _chat_mode() != "live":
            return JSONResponse(content={**payload, "chat_mode": "mock"})
        from clipforge_director.chat import (
            ChatAPIError,
            ChatError,
            ChatRateLimitedError,
            ChatTimeoutError,
            ChatValidationError,
            MissingCredentialsError as ChatMissingCredentialsError,
            SparkChatAssistant,
        )
        from clipforge_director.ledger import (
            LedgerIntegrityError,
            LedgerLockedError,
            LiveBudgetExceeded,
            LiveCallAuthorization,
            LiveCallBudget,
            LiveCallNotAuthorizedError,
        )

        api_key = os.environ.get("MODEL_API_KEY", "")
        if not api_key.strip():
            return _error(503, "chat_not_configured",
                            "O chat ao vivo precisa de MODEL_API_KEY no servidor.")
        try:
            if chat_provider_factory is not None:
                provider = chat_provider_factory()
            else:
                provider = SparkChatAssistant(
                    api_key,
                    max_output_tokens=int(os.environ.get("CLIPFORGE_CHAT_MAX_TOKENS", "900")),
                    timeout_seconds=float(os.environ.get("CLIPFORGE_CHAT_TIMEOUT_SECONDS", "45")),
                )
            authorization = LiveCallAuthorization(LiveCallBudget(root), "chat")
            interview = payload.get("interview") or {}
            history = []
            if context is not None:
                history = [
                    {"role": item.get("role"), "text": item.get("text", "")}
                    for item in context.get("history", [])[-6:]
                ]
            safe_context_text = (context_text or "").strip()
            if not safe_context_text and context is not None:
                safe_context_text = context_for_prompt(context)
            brief = str(interview.get("brief", "")).strip()
            if not safe_context_text and brief:
                safe_context_text = f"Idea brief: {brief}"
            reply, usage = provider.rewrite_reply(
                message=message,
                base_reply=str(payload.get("reply", "")),
                intent=str(payload.get("intent", "clarify")),
                has_clip=has_clip,
                interview_needed=list(interview.get("needed", [])),
                context=safe_context_text or None,
                history=history or None,
                authorization=authorization,
            )
        except ChatMissingCredentialsError:
            return _error(503, "chat_not_configured",
                            "O chat ao vivo precisa de MODEL_API_KEY no servidor.")
        except LiveCallNotAuthorizedError as exc:
            return _error(503, "live_budget_not_authorized", str(exc))
        except LedgerIntegrityError as exc:
            return _error(503, "live_budget_integrity_error", str(exc))
        except LedgerLockedError as exc:
            return _error(503, "live_budget_locked", str(exc))
        except LiveBudgetExceeded as exc:
            return _error(429, "live_budget_exhausted", str(exc))
        except ChatRateLimitedError as exc:
            return _error(429, "chat_rate_limited",
                            "O Muse está com muito tráfego. Tenta de novo.")
        except (ChatTimeoutError, ChatAPIError, ChatValidationError, ChatError,
                ValueError) as exc:
            logger.warning("chat_live_failed intent=%s has_clip=%s error=%s",
                           payload.get("intent"), has_clip, type(exc).__name__)
            return _error(502, "chat_live_failed",
                            f"O Muse ao vivo falhou ({type(exc).__name__}). Tenta de novo.")
        except Exception as exc:  # noqa: BLE001 - surfaced as a stable API error
            logger.warning("chat_live_failed intent=%s has_clip=%s error=%s",
                           payload.get("intent"), has_clip, type(exc).__name__)
            return _error(502, "chat_live_failed",
                            f"O Muse ao vivo falhou ({type(exc).__name__}). Tenta de novo.")
        out = dict(payload)
        out["reply"] = reply
        out["chat_mode"] = "live"
        out["chat_usage"] = usage.model_dump(mode="json")
        logger.info("chat_live_ok intent=%s has_clip=%s in=%d out=%d cost=%.6f",
                    payload.get("intent"), has_clip,
                    usage.prompt_tokens, usage.completion_tokens, usage.cost_usd)
        return JSONResponse(content=out)


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

    @app.post("/api/jobs/{job_id}/trim", response_model=None)
    async def set_trim(job_id: str, body: TrimRequest) -> JobResponse | JSONResponse:
        """ADR-041 upload trim. Allowed only before voice input (queued, not
        ready): the worker materializes a trimmed working copy and re-probes,
        so masks, render and verification all bind the trimmed clip while the
        original file stays untouched. Both null clears the trim."""
        record = store.get(job_id)
        if record.status.value != "queued" or record.ready:
            return _error(409, "trim_not_allowed",
                          f"Job {job_id} is {record.status.value} (ready={record.ready}); "
                          "trim applies only before voice input.")
        if bundle.segmentation_mode == "live":
            return _error(409, "trim_live_sam_unsupported",
                           "Trim is not supported with live SAM segmentation: consent binds "
                           "the original source hash. Clear the trim or use mock segmentation.")
        # Trims are always absolute in the ORIGINAL clip, so repeated edits
        # stay consistent after source_info switches to the trimmed copy.
        original_duration = record.original_duration_s or record.source_info.duration_seconds
        duration = original_duration
        if body.start_s is None and body.end_s is None:
            # Clearing restores the original probe immediately (the worker
            # would otherwise keep the trimmed source_info).
            try:
                original_info = probe_video(store.source_path(record))
            except UploadValidationError as exc:
                return _error(exc.status_code, exc.code, str(exc))
            record = store.update(
                job_id,
                trim_start_s=None,
                trim_end_s=None,
                trimmed_relative_path=None,
                trimmed_sha256=None,
                source_info=original_info,
            )
            return _to_response(record)
        start = 0.0 if body.start_s is None else body.start_s
        end = duration if body.end_s is None else body.end_s
        if not (0.0 <= start < end <= duration + 1e-6):
            return _error(422, "invalid_trim_range",
                           f"Trim [{start:.3f}, {end:.3f}] is outside the 0–{duration:.3f}s source.")
        if end - start < 0.5:
            return _error(422, "trim_too_short", "Trimmed clips must be at least 0.5s.")
        record = store.update(
            job_id,
            trim_start_s=start,
            trim_end_s=min(end, duration),
            original_duration_s=original_duration,
            trimmed_relative_path=None,
            trimmed_sha256=None,
        )
        logger.info("trim_set job_id=%s start=%.3f end=%.3f", job_id, start, end)
        return _to_response(record)

    @app.post("/api/jobs/{job_id}/audio", response_model=None)
    async def set_upload_audio(job_id: str, body: UploadAudioRequest) -> JobResponse | JSONResponse:
        """ADR-041 upload audio: gain + fades on the preserved original audio.
        Allowed only before voice input, like trim."""
        record = store.get(job_id)
        if record.status.value != "queued" or record.ready:
            return _error(409, "audio_not_allowed",
                          f"Job {job_id} is {record.status.value} (ready={record.ready}); "
                          "audio settings apply only before voice input.")
        duration = record.source_info.duration_seconds
        if body.fade_in_s + body.fade_out_s > duration:
            return _error(422, "invalid_fades",
                           "Combined fades exceed the source duration.")
        record = store.update(
            job_id,
            audio_gain_db=body.gain_db,
            audio_fade_in_s=body.fade_in_s,
            audio_fade_out_s=body.fade_out_s,
        )
        logger.info("upload_audio_set job_id=%s gain=%.1f in=%.2f out=%.2f",
                    job_id, body.gain_db, body.fade_in_s, body.fade_out_s)
        return _to_response(record)

    def _timeline_clip_error(project_id: str, clip) -> JSONResponse | None:
        """Asset-aware timeline validation. Returns an error response or None."""
        sidecar = projects.asset_dir(project_id, clip.asset_id) / "asset.json"
        if not sidecar.is_file():
            return _error(404, "timeline_asset_not_found", f"Asset not found: {clip.asset_id}")
        try:
            meta = AssetRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return _error(404, "timeline_asset_not_found", f"Asset not found: {clip.asset_id}")
        if meta.project_id != project_id:
            return _error(404, "timeline_asset_not_found", f"Asset not found: {clip.asset_id}")
        if clip.track in VIDEO_TRACKS and meta.kind != AssetKind.VIDEO:
            return _error(422, "timeline_track_mismatch",
                            f"Clip {clip.clip_id}: track {clip.track} needs video, asset is {meta.kind.value}.")
        if clip.track in AUDIO_TRACKS and meta.kind != AssetKind.AUDIO:
            return _error(422, "timeline_track_mismatch",
                            f"Clip {clip.clip_id}: track {clip.track} needs audio, asset is {meta.kind.value}.")
        asset_duration = meta.duration_seconds or 0.0
        if asset_duration <= 0:
            return _error(422, "timeline_asset_without_duration",
                            f"Clip {clip.clip_id}: asset {clip.asset_id} has no measurable duration.")
        if clip.source_out_s > asset_duration + 0.05:
            return _error(422, "timeline_source_out_of_range",
                            f"Clip {clip.clip_id}: source [{clip.source_in_s:.2f}, {clip.source_out_s:.2f}] "
                            f"exceeds asset duration {asset_duration:.2f}s.")
        return None

    def _timeline_payload(record) -> JSONResponse:
        tl = record.timeline
        return JSONResponse(content={
            "timeline": tl.model_dump(mode="json") if tl else {"clips": []},
            "program_duration_s": tl.program_duration_s() if tl else 0.0,
        })

    @app.get("/api/jobs/{job_id}/timeline", response_model=None)
    async def get_timeline(job_id: str) -> JSONResponse:
        """Return the explicit user arrangement (empty when never edited)."""
        record = store.get(job_id)
        return _timeline_payload(record)

    @app.put("/api/jobs/{job_id}/timeline", response_model=None)
    async def put_timeline(job_id: str, body: TimelinePutRequest) -> JSONResponse:
        """ADR-044 full timeline replacement. Allowed on queued or completed
        jobs only — never mid-flow (awaiting_*/processing/failed would fork
        the director pipeline). The server re-validates ownership, track
        kinds, source bounds and overlap; Pydantic already rejected shape
        errors."""
        record = store.get(job_id)
        if record.status.value not in ("queued", "completed") or (
            record.status.value == "queued" and record.ready
        ):
            return _error(409, "timeline_not_allowed",
                            f"Job {job_id} is {record.status.value} (ready={record.ready}); timeline edits apply "
                            "to queued jobs before voice input, or to completed jobs.")
        if not record.project_id:
            return _error(409, "timeline_no_project", "Job has no project workspace.")
        for clip in body.timeline.clips:
            err = _timeline_clip_error(record.project_id, clip)
            if err is not None:
                return err
        record = store.update(job_id, timeline=body.timeline)
        assert record.timeline is not None
        logger.info("timeline_saved job_id=%s clips=%d program=%.2f",
                    job_id, len(record.timeline.clips), record.timeline.program_duration_s())
        return _timeline_payload(record)

    @app.get("/api/jobs/{job_id}/texts", response_model=None)
    async def get_texts(job_id: str) -> JSONResponse:
        """Return the persisted selectable text overlays (empty when none)."""
        record = store.get(job_id)
        return JSONResponse(content={
            "texts": [t.model_dump(mode="json") for t in (record.clip_texts or [])],
        })

    @app.put("/api/jobs/{job_id}/texts", response_model=None)
    async def put_texts(job_id: str, body: ClipTextsPutRequest) -> JSONResponse:
        """ADR-047 full overlay replacement. Allowed on queued jobs before
        voice input, or on completed jobs (edit → Montar again). Pydantic
        already rejected shape errors; ids must be unique."""
        record = store.get(job_id)
        if record.status.value not in ("queued", "completed") or (
            record.status.value == "queued" and record.ready
        ):
            return _error(409, "texts_not_allowed",
                            f"Job {job_id} is {record.status.value} (ready={record.ready}); text edits apply "
                            "to queued jobs before voice input, or to completed jobs.")
        seen: set[str] = set()
        for overlay in body.texts:
            if overlay.overlay_id in seen:
                return _error(422, "duplicate_overlay_id",
                                f"Duplicate text overlay id: {overlay.overlay_id}")
            seen.add(overlay.overlay_id)
        record = store.update(job_id, clip_texts=list(body.texts))
        logger.info("texts_saved job_id=%s overlays=%d", job_id, len(body.texts))
        return JSONResponse(content={
            "texts": [t.model_dump(mode="json") for t in (record.clip_texts or [])],
        })

    @app.get("/api/jobs/{job_id}/colour", response_model=None)
    async def get_colour(job_id: str) -> JSONResponse:
        """Return the persisted local colour grade (identity when unset)."""
        record = store.get(job_id)
        grade = record.colour or ColourGrade()
        return JSONResponse(content={"colour": grade.model_dump(mode="json")})

    @app.put("/api/jobs/{job_id}/colour", response_model=None)
    async def put_colour(job_id: str, body: ColourGrade) -> JSONResponse:
        """ADR-047 local colour grade. Same edit window as text overlays;
        applied by the next timeline composition (Montar)."""
        record = store.get(job_id)
        if record.status.value not in ("queued", "completed") or (
            record.status.value == "queued" and record.ready
        ):
            return _error(409, "colour_not_allowed",
                            f"Job {job_id} is {record.status.value} (ready={record.ready}); colour edits apply "
                            "to queued jobs before voice input, or to completed jobs.")
        record = store.update(job_id, colour=body)
        logger.info("colour_saved job_id=%s contrast=%.2f brightness=%.2f saturation=%.2f",
                    job_id, body.contrast, body.brightness, body.saturation)
        return JSONResponse(content={"colour": record.colour.model_dump(mode="json")})

    @app.get("/api/jobs/{job_id}/caption-cover", response_model=None)
    async def get_caption_cover(job_id: str) -> JSONResponse:
        """Return whether the caption band cover is enabled."""
        record = store.get(job_id)
        return JSONResponse(content={"caption_cover": bool(record.caption_cover)})

    @app.put("/api/jobs/{job_id}/caption-cover", response_model=None)
    async def put_caption_cover(job_id: str, body: CaptionCoverBody) -> JSONResponse:
        """ADR-049 burned-in subtitle cover. Same edit window as text
        overlays; applied by the next timeline composition (Montar)."""
        record = store.get(job_id)
        if record.status.value not in ("queued", "completed") or (
            record.status.value == "queued" and record.ready
        ):
            return _error(409, "caption_cover_not_allowed",
                            f"Job {job_id} is {record.status.value} (ready={record.ready}); cover applies "
                            "to queued jobs before voice input, or to completed jobs.")
        record = store.update(job_id, caption_cover=bool(body.enabled))
        logger.info("caption_cover_saved job_id=%s enabled=%s", job_id, record.caption_cover)
        return JSONResponse(content={"caption_cover": bool(record.caption_cover)})

    @app.post("/api/jobs/{job_id}/timeline/render", response_model=None)
    async def render_timeline(job_id: str, body: TimelineRenderBody | None = None) -> JobResponse | JSONResponse:
        """Queue an explicit timeline composition. The worker composes the
        program with real FFmpeg/OpenCV (video z-order V2>V1, audio mix of
        all sounding clips) and verifies the output like any render."""
        record = store.get(job_id)
        if record.timeline is None or not record.timeline.clips:
            return _error(409, "timeline_empty", "Put at least one clip on the timeline first.")
        if record.status.value not in ("queued", "completed"):
            return _error(409, "timeline_render_not_allowed",
                            f"Job {job_id} is {record.status.value}; finish or reject the director flow first.")
        canvas_format = (body.format if body else "source")
        updated = store.transition(
            job_id,
            expected={JobStatus.QUEUED, JobStatus.COMPLETED},
            status=JobStatus.QUEUED,
            stage="timeline_queued",
            actor="user",
            note=f"timeline render requested (format={canvas_format})",
            timeline_render_requested=True,
            timeline_format=canvas_format,
            ready=True,
            error=None,
        )
        logger.info("timeline_render_requested job_id=%s clips=%d format=%s",
                    job_id, len(record.timeline.clips), canvas_format)
        return _to_response(updated)

    @app.get("/api/jobs/{job_id}/tools", response_model=None)
    async def list_tools(job_id: str) -> JSONResponse:
        """ADR-047 real tool catalogue: what Muse may operate on this job."""
        from clipforge_api.tools import tool_definitions
        store.get(job_id)
        return JSONResponse(content={"tools": tool_definitions()})

    @app.post("/api/jobs/{job_id}/tools/execute", response_model=None)
    async def execute_tool_call(job_id: str, body: dict) -> JSONResponse:
        """ADR-047 execute one validated tool against the persisted job.

        Called only after explicit user confirmation (the Studio Executar
        button). Never invoked by /api/chat itself.
        """
        from clipforge_api.tools import ToolError, execute_tool
        if not isinstance(body, dict) or not isinstance(body.get("tool"), str):
            return _error(422, "invalid_tool_request", "Body must be {tool: name, params: {...}}.")
        params = body.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(422, "invalid_tool_request", "params must be an object.")
        try:
            result = execute_tool(store, projects, job_id, body["tool"], params,
                                  storage_root=root)
        except ToolError as exc:
            return _error(exc.status_code, exc.code, str(exc))
        except (JobNotFoundError, ProjectNotFoundError) as exc:
            return _error(404, "job_not_found", str(exc))
        logger.info("tool_executed job_id=%s tool=%s", job_id, body["tool"])
        return JSONResponse(content={"tool": body["tool"], "result": result})

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
    async def transcribe(file: UploadFile = File(...), mock_fixture_id: str | None = Form(default=None),
                         asr_mode: str | None = Form(default=None, alias="mode")):
        """One recording in, one transcript out. No retries, no paid call in mock mode."""
        ensure_ffmpeg_available()
        upload_bytes = await file.read()
        result, mode = transcribe_upload(
            upload_bytes,
            file.filename or "",
            providers=bundle,
            mock_fixture_id=mock_fixture_id,
            budget=LiveCallBudget(root) if bundle.transcription_mode == "live" else None,
            asr_mode=(asr_mode or "PUSH_TO_TALK"),
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
