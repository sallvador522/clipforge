"""ADR-047 Muse tool execution — real operations on the real project.

The Studio chat proposes tool calls (deterministic local router today, Muse
Spark reasoning when live is explicitly enabled) and executes them here only
after the user presses Executar. Every tool is validated with strict
Pydantic schemas, operates on the persisted job record through the JobStore,
and returns a structured result — no mocks, no simulated success.

Selection itself stays a local UI state (the browser owns the preview), so
there is deliberately no `select` tool: Muse addresses elements by their
stable `overlay_id`, and the frontend applies `select_text_id` hints from
chat responses.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipforge_contracts import (
    CLIP_TEXT_MAX,
    ClipTextOverlay,
    ColourGrade,
)

_EDITABLE_STATUSES = ("queued", "completed")


class ToolError(Exception):
    """Validated tool failure. Carries the stable error code for the API."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class TextCreateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overlay_id: str | None = Field(default=None, pattern=r"^txt_[a-z0-9]{4,32}$")
    text: str = Field(min_length=1, max_length=140)
    style: str = "rise"
    start_s: float = Field(default=0.0, ge=0.0)
    duration_s: float = Field(default=2.5, ge=0.5, le=8.0)
    x: float = Field(default=0.5, ge=0.08, le=0.92)
    y: float = Field(default=0.78, ge=0.1, le=0.9)
    scale: float = Field(default=1.0, ge=0.7, le=1.6)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    weight: str = "bold"


class TextUpdateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overlay_id: str = Field(min_length=1, max_length=64)
    text: str | None = Field(default=None, min_length=1, max_length=140)
    style: str | None = None
    start_s: float | None = Field(default=None, ge=0.0)
    duration_s: float | None = Field(default=None, ge=0.5, le=8.0)
    x: float | None = Field(default=None, ge=0.08, le=0.92)
    y: float | None = Field(default=None, ge=0.1, le=0.9)
    scale: float | None = Field(default=None, ge=0.7, le=1.6)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    weight: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "TextUpdateParams":
        if all(
            v is None
            for k, v in self.model_dump().items()
            if k != "overlay_id"
        ):
            raise ValueError("Provide at least one field to update besides overlay_id.")
        if self.style is not None and self.style not in ("rise", "reveal", "pop", "kinetic", "tracking"):
            raise ValueError(f"Unknown style: {self.style}")
        if self.weight is not None and self.weight not in ("normal", "bold"):
            raise ValueError(f"Unknown weight: {self.weight}")
        return self


class TextRefParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overlay_id: str = Field(min_length=1, max_length=64)


class CaptionsCreateParams(BaseModel):
    """Create timed caption overlays from a transcript.

    Words come from the user (typed/pasted) or a confirmed Meta
    transcription; timing starts as an honest uniform distribution across
    the program and every line stays editable (timing, text, style) in
    Properties and the T1 lane before export.
    """

    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(min_length=1, max_length=1000)


class CaptionTurnParams(BaseModel):
    """One real speech turn (Meta ENDPOINTING): validated timings in ms."""

    model_config = ConfigDict(extra="forbid")
    turn_id: int | None = Field(default=None, ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)
    speaker: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _bounds(self) -> "CaptionTurnParams":
        if self.end_ms < self.start_ms:
            raise ValueError("Turn end_ms precedes start_ms.")
        return self


class CaptionsFromTurnsParams(BaseModel):
    """Create timed caption overlays from real speech turns.

    Timings are the model's detected boundaries (seconds = ms/1000),
    clamped to the overlay contract and the program; turns longer than
    8 s are split into sequential lines at word boundaries.
    """

    model_config = ConfigDict(extra="forbid")
    turns: list[CaptionTurnParams] = Field(min_length=1, max_length=60)


class CaptionsCoverParams(BaseModel):
    """Cover pre-existing burned-in subtitles with a blurred caption band.

    Fixed geometry (the same band our captions use); a validated bool,
    never model-drawn coordinates.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool


class CaptionsTranslateParams(BaseModel):
    """Translate a transcript to Portuguese with Muse Spark, then create
    timed caption overlays with uniform initial timing.

    Translation is a real text task for the model; timing stays uniform
    (declared) and every line remains editable. Billed per call
    (~$0.0001); fails closed without server credentials or budget.
    """

    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(min_length=1, max_length=1000)
    target_lang: str = Field(default="pt-PT", pattern=r"^pt-PT$")


TOOL_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "project.inspect": BaseModel,
    "job.status": BaseModel,
    "texts.list": BaseModel,
    "text.get": TextRefParams,
    "text.create": TextCreateParams,
    "text.update": TextUpdateParams,
    "text.delete": TextRefParams,
    "captions.create": CaptionsCreateParams,
    "captions.create_from_turns": CaptionsFromTurnsParams,
    "captions.cover": CaptionsCoverParams,
    "captions.translate": CaptionsTranslateParams,
    "colour.get": BaseModel,
    "colour.set": ColourGrade,
    "timeline.inspect": BaseModel,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "project.inspect": "Inspect the active project: title, assets by kind, linked job state.",
    "job.status": "Current job status, stage, readiness and render state.",
    "texts.list": "List every selectable text overlay with its real properties.",
    "text.get": "Read one text overlay by its stable overlay_id.",
    "text.create": "Create a text overlay with validated content, style, timing, position, size, colour and weight.",
    "text.update": "Update one or more validated fields of an existing text overlay.",
    "text.delete": "Delete a text overlay by id.",
    "captions.create": "Create timed caption lines from a transcript (uniform initial timing, every line stays editable).",
    "captions.create_from_turns": "Create timed caption lines from real speech turns (model-detected boundaries).",
    "captions.cover": "Blur the caption band to cover pre-existing burned-in subtitles (fixed geometry).",
    "captions.translate": "Translate a transcript to Portuguese with Muse Spark (~$0.0001, billed) then create uniform timed captions.",
    "colour.get": "Read the current local colour grade.",
    "colour.set": "Set the local contrast/brightness/saturation grade (real OpenCV processing on next render).",
    "timeline.inspect": "Clips, tracks and program duration of the explicit timeline.",
}


def tool_definitions() -> list[dict[str, Any]]:
    """Public tool catalogue. Capabilities text.overlay / colour.adjust."""
    definitions = []
    for name, model in TOOL_PARAM_MODELS.items():
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        if model is not BaseModel:
            schema = model.model_json_schema()
        definitions.append({
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": schema,
        })
    return definitions


def _require_editable(record) -> None:
    if record.status.value not in _EDITABLE_STATUSES or (
        record.status.value == "queued" and record.ready
    ):
        raise ToolError(409, "tool_not_allowed",
                        f"Job {record.job_id} is {record.status.value} (ready={record.ready}); "
                        "editing tools apply to queued jobs before voice input, or to completed jobs.")


def _program_duration(record) -> float:
    if record.timeline is not None and record.timeline.clips:
        return max(0.5, record.timeline.program_duration_s())
    return max(0.5, record.source_info.duration_seconds)


def _check_overlay_program_bounds(record, start_s: float, duration_s: float) -> None:
    ref = _program_duration(record)
    if start_s > ref + 1e-9:
        raise ToolError(422, "overlay_out_of_range",
                        f"Overlay starts at {start_s:.2f}s but the program is {ref:.2f}s.")
    if start_s + duration_s > ref + 0.5 + 1e-9:
        raise ToolError(422, "overlay_out_of_range",
                        f"Overlay [{start_s:.2f}, {start_s + duration_s:.2f}] exceeds the {ref:.2f}s program.")


def _find_overlay(record, overlay_id: str) -> ClipTextOverlay:
    for overlay in record.clip_texts or []:
        if overlay.overlay_id == overlay_id:
            return overlay
    raise ToolError(404, "overlay_not_found", f"Text overlay not found: {overlay_id}")


def _split_caption_lines(transcript: str, width: int = 42) -> list[str]:
    """Greedy word-boundary wrap; each line fits the overlay contract."""
    words = transcript.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        piece = word[:140]
        if current and len(" ".join(current + [piece])) > width:
            lines.append(" ".join(current))
            current = [piece]
        else:
            current.append(piece)
    if current:
        lines.append(" ".join(current))
    return [line[:140] for line in lines if line.strip()]


def _proportional_chunks(text: str, total_s: float, width: int = 42) -> list[tuple[float, float, str]]:
    """Split a turn's text into word-boundary lines with word-count-
    proportional timings inside the turn window.

    The outer [start, end] boundaries stay exactly the model's; only the
    inner splits are proportional (chars share), so no line is a stray
    fragment unless the turn itself is one word.
    """
    words = text.split()
    raw: list[str] = []
    current: list[str] = []
    for word in words:
        piece = word[:140]
        if current and len(" ".join(current + [piece])) > width:
            raw.append(" ".join(current))
            current = [piece]
        else:
            current.append(piece)
    if current:
        raw.append(" ".join(current))
    raw = [line[:140] for line in raw if line.strip()]
    # Merge stub lines (<15 chars) into the shorter neighbour.
    merged: list[str] = list(raw)
    i = 0
    while i < len(merged):
        if len(merged[i]) < 15 and len(merged) > 1:
            if i == 0:
                merged[1] = merged[0] + " " + merged[1]
            elif i == len(merged) - 1 or len(merged[i - 1]) <= len(merged[i + 1]):
                merged[i - 1] = merged[i - 1] + " " + merged[i]
            else:
                merged[i + 1] = merged[i] + " " + merged[i + 1]
            del merged[i]
            i = max(0, i - 1)
        else:
            i += 1
    chars = [max(1, len(line)) for line in merged]
    whole = sum(chars)
    out: list[tuple[float, float, str]] = []
    cursor = 0.0
    for index, line in enumerate(merged):
        share = total_s * chars[index] / whole if whole else total_s
        if index == len(merged) - 1:
            share = total_s - cursor
        out.append((round(cursor, 3), round(max(0.3, share), 3), line))
        cursor += share
    return out
    """Greedy word-boundary wrap; each line fits the overlay contract."""
    words = transcript.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        piece = word[:140]
        if current and len(" ".join(current + [piece])) > width:
            lines.append(" ".join(current))
            current = [piece]
        else:
            current.append(piece)
    if current:
        lines.append(" ".join(current))
    return [line[:140] for line in lines if line.strip()]


def execute_tool(store, projects, job_id: str, tool_name: str, params: dict[str, Any],
                  storage_root: Path | str | None = None) -> dict[str, Any]:
    """Validate params, execute against the persisted record, return JSONable result."""
    model = TOOL_PARAM_MODELS.get(tool_name)
    if model is None:
        raise ToolError(422, "unknown_tool", f"Unknown tool: {tool_name}")
    try:
        parsed = model.model_validate(params or {})
    except Exception as exc:
        raise ToolError(422, "invalid_tool_params", f"Invalid params for {tool_name}: {exc}") from exc
    record = store.get(job_id)

    if tool_name == "project.inspect":
        project = None
        assets: list[dict[str, Any]] = []
        if record.project_id:
            try:
                project = projects.get_project(record.project_id)
                assets_root = projects.assets_dir(record.project_id)
                if assets_root.is_dir():
                    from clipforge_contracts import AssetRecord as _AssetRecord

                    for path in sorted(assets_root.glob("*/asset.json")):
                        try:
                            meta = _AssetRecord.model_validate_json(path.read_text(encoding="utf-8"))
                            assets.append({"asset_id": meta.asset_id, "kind": meta.kind.value,
                                           "name": meta.original_filename})
                        except Exception:
                            continue
            except Exception:
                project = None
        return {"job_id": job_id, "status": record.status.value, "stage": record.stage,
                "project_id": record.project_id,
                "project_title": project.title if project else None,
                "assets": assets, "text_overlays": len(record.clip_texts or [])}

    if tool_name == "job.status":
        return {"job_id": job_id, "status": record.status.value, "stage": record.stage,
                "ready": record.ready,
                "render_status": record.result.render_status if record.result else None,
                "has_timeline": bool(record.timeline and record.timeline.clips),
                "text_overlays": len(record.clip_texts or [])}

    if tool_name == "texts.list":
        return {"texts": [t.model_dump(mode="json") for t in (record.clip_texts or [])]}

    if tool_name == "text.get":
        overlay = _find_overlay(record, parsed.overlay_id)  # type: ignore[attr-defined]
        return {"text": overlay.model_dump(mode="json")}

    if tool_name == "text.create":
        _require_editable(record)
        current = list(record.clip_texts or [])
        if len(current) >= CLIP_TEXT_MAX:
            raise ToolError(409, "too_many_overlays", f"At most {CLIP_TEXT_MAX} text overlays.")
        data = parsed.model_dump()  # type: ignore[union-attr]
        overlay_id = data.pop("overlay_id", None) or f"txt_{secrets.token_hex(6)}"
        if any(o.overlay_id == overlay_id for o in current):
            raise ToolError(422, "duplicate_overlay_id", f"Duplicate text overlay id: {overlay_id}")
        overlay = ClipTextOverlay.model_validate({"overlay_id": overlay_id, **data})
        _check_overlay_program_bounds(record, overlay.start_s, overlay.duration_s)
        record = store.update(job_id, clip_texts=current + [overlay])
        return {"created": overlay.model_dump(mode="json"), "count": len(record.clip_texts or [])}

    if tool_name == "text.update":
        _require_editable(record)
        overlay = _find_overlay(record, parsed.overlay_id)  # type: ignore[attr-defined]
        patch = {k: v for k, v in parsed.model_dump().items()  # type: ignore[union-attr]
                 if k != "overlay_id" and v is not None}
        updated = overlay.model_copy(update=patch)
        # Re-validate through the strict contract (style/weight literals enforced).
        updated = ClipTextOverlay.model_validate(updated.model_dump())
        _check_overlay_program_bounds(record, updated.start_s, updated.duration_s)
        current = [updated if o.overlay_id == updated.overlay_id else o for o in (record.clip_texts or [])]
        record = store.update(job_id, clip_texts=current)
        return {"updated": updated.model_dump(mode="json")}

    if tool_name == "text.delete":
        _require_editable(record)
        overlay = _find_overlay(record, parsed.overlay_id)  # type: ignore[attr-defined]
        current = [o for o in (record.clip_texts or []) if o.overlay_id != overlay.overlay_id]
        store.update(job_id, clip_texts=current)
        return {"deleted": overlay.overlay_id, "count": len(current)}

    if tool_name == "captions.create":
        _require_editable(record)
        assert isinstance(parsed, CaptionsCreateParams)
        lines = _split_caption_lines(parsed.transcript)
        if not lines:
            raise ToolError(422, "invalid_tool_params", "Transcript has no captionable words.")
        current = list(record.clip_texts or [])
        if len(current) + len(lines) > CLIP_TEXT_MAX:
            raise ToolError(409, "too_many_overlays",
                            f"Captions need {len(lines)} lines but only "
                            f"{CLIP_TEXT_MAX - len(current)} overlay slots remain.")
        program = _program_duration(record)
        per_line = min(8.0, max(0.5, program / max(1, len(lines))))
        created = []
        for index, line in enumerate(lines):
            overlay = ClipTextOverlay.model_validate({
                "overlay_id": f"txt_{secrets.token_hex(6)}",
                "text": line,
                "style": "rise",
                "start_s": round(index * per_line, 3),
                "duration_s": round(min(per_line, max(0.5, program - index * per_line)), 3),
                "x": 0.5,
                "y": 0.82,
                "scale": 0.9,
                "color": "#FFFFFF",
                "weight": "bold",
            })
            _check_overlay_program_bounds(record, overlay.start_s, overlay.duration_s)
            current.append(overlay)
            created.append(overlay.model_dump(mode="json"))
        record = store.update(job_id, clip_texts=current)
        return {"created": created, "count": len(record.clip_texts or []),
                "timing": "uniform — adjust each line in Properties"}

    if tool_name == "captions.cover":
        _require_editable(record)
        assert isinstance(parsed, CaptionsCoverParams)
        record = store.update(job_id, caption_cover=parsed.enabled)
        return {"caption_cover": record.caption_cover}

    if tool_name == "captions.translate":
        _require_editable(record)
        assert isinstance(parsed, CaptionsTranslateParams)
        if storage_root is None:
            raise ToolError(503, "translation_not_configured",
                            "Subtitle translation needs the server storage ledger.")
        api_key = os.environ.get("MODEL_API_KEY", "")
        if not api_key.strip():
            raise ToolError(503, "translation_not_configured",
                            "Subtitle translation needs a server-side MODEL_API_KEY.")
        from clipforge_director import LiveCallBudget
        from clipforge_director.ledger import (
            LiveBudgetExceeded,
            LiveCallAuthorization,
            LiveCallNotAuthorizedError,
        )
        from clipforge_providers import (
            SparkSubtitleTranslator,
            TranslationAPIError,
            TranslationError,
            TranslationRateLimitedError,
            TranslationTimeoutError,
        )
        lines = _split_caption_lines(parsed.transcript)
        current = list(record.clip_texts or [])
        if len(current) + len(lines) > CLIP_TEXT_MAX:
            raise ToolError(409, "too_many_overlays",
                            f"Translation needs {len(lines)} lines but only "
                            f"{CLIP_TEXT_MAX - len(current)} overlay slots remain.")
        budget = LiveCallBudget(Path(storage_root))
        authorization = LiveCallAuthorization(budget, "director")
        translator = SparkSubtitleTranslator(api_key)
        try:
            translated = translator.translate_lines(lines, authorization=authorization)
        except LiveCallNotAuthorizedError as exc:
            raise ToolError(503, "translation_not_authorized", str(exc)) from exc
        except LiveBudgetExceeded as exc:
            raise ToolError(429, "translation_budget_exhausted", str(exc)) from exc
        except TranslationTimeoutError as exc:
            raise ToolError(504, "translation_timeout", str(exc)) from exc
        except TranslationRateLimitedError as exc:
            raise ToolError(429, "translation_rate_limited", str(exc)) from exc
        except TranslationAPIError as exc:
            raise ToolError(502, "translation_failed", str(exc)) from exc
        except TranslationError as exc:
            raise ToolError(502, "translation_failed", str(exc)) from exc
        finally:
            translator.close()
        program = _program_duration(record)
        translated_lines = translated.translated_text.split("\n")
        per_line = min(8.0, max(0.5, program / max(1, len(translated_lines))))
        created = []
        for index, line in enumerate(translated_lines):
            start_s = round(index * per_line, 3)
            duration_s = round(min(per_line, max(0.5, program - start_s)), 3)
            overlay = ClipTextOverlay.model_validate({
                "overlay_id": f"txt_{secrets.token_hex(6)}",
                "text": line[:140],
                "style": "rise",
                "start_s": start_s,
                "duration_s": duration_s,
                "x": 0.5,
                "y": 0.82,
                "scale": 0.9,
                "color": "#FFFFFF",
                "weight": "bold",
            })
            _check_overlay_program_bounds(record, overlay.start_s, overlay.duration_s)
            current.append(overlay)
            created.append(overlay.model_dump(mode="json"))
        record = store.update(job_id, clip_texts=current)
        return {"created": created, "count": len(record.clip_texts or []),
                "translation": {"input_tokens": translated.input_tokens,
                                 "output_tokens": translated.output_tokens,
                                 "estimated_cost_usd": translated.estimated_cost_usd},
                "timing": "uniform — adjust each line in Properties"}

    if tool_name == "captions.create_from_turns":
        _require_editable(record)
        assert isinstance(parsed, CaptionsFromTurnsParams)
        program = _program_duration(record)
        planned: list[tuple[float, float, str]] = []
        for turn in parsed.turns:
            start = turn.start_ms / 1000.0
            total = (turn.end_ms - turn.start_ms) / 1000.0
            if start > program + 1e-9 or start + total > program + 0.5 + 1e-9:
                raise ToolError(422, "turn_out_of_range",
                                f"Turn [{start:.2f}, {start + total:.2f}] exceeds the {program:.2f}s program.")
            if total < 0.2:
                continue  # sub-frame blip: never invent a visible line for it
            for rel_start, rel_dur, line in _proportional_chunks(turn.text, total):
                planned.append((round(start + rel_start, 3),
                                round(min(8.0, max(0.5, rel_dur)), 3), line))
        if not planned:
            raise ToolError(422, "invalid_tool_params", "Turns produced no caption lines.")
        current = list(record.clip_texts or [])
        if len(current) + len(planned) > CLIP_TEXT_MAX:
            raise ToolError(409, "too_many_overlays",
                            f"Turns need {len(planned)} lines but only "
                            f"{CLIP_TEXT_MAX - len(current)} overlay slots remain.")
        created = []
        for start_s, duration_s, line in planned:
            overlay = ClipTextOverlay.model_validate({
                "overlay_id": f"txt_{secrets.token_hex(6)}",
                "text": line,
                "style": "rise",
                "start_s": start_s,
                "duration_s": duration_s,
                "x": 0.5,
                "y": 0.82,
                "scale": 0.9,
                "color": "#FFFFFF",
                "weight": "bold",
            })
            _check_overlay_program_bounds(record, overlay.start_s, overlay.duration_s)
            current.append(overlay)
            created.append(overlay.model_dump(mode="json"))
        record = store.update(job_id, clip_texts=current)
        return {"created": created, "count": len(record.clip_texts or []),
                "timing": "turn — model-detected speech boundaries"}

    if tool_name == "colour.get":
        grade = record.colour or ColourGrade()
        return {"colour": grade.model_dump(mode="json")}

    if tool_name == "colour.set":
        _require_editable(record)
        assert isinstance(parsed, ColourGrade)
        record = store.update(job_id, colour=parsed)
        return {"colour": record.colour.model_dump(mode="json")}

    if tool_name == "timeline.inspect":
        timeline = record.timeline
        return {"clips": timeline.model_dump(mode="json")["clips"] if timeline else [],
                "program_duration_s": timeline.program_duration_s() if timeline else 0.0}

    raise ToolError(422, "unknown_tool", f"Unknown tool: {tool_name}")
