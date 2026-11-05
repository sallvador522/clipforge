"""Muse Spark native video understanding (ADR-057).

Verified against current official Meta docs (video-understanding,
file-handling, responses, pricing-rate-limits, tool-calling):

- Model `muse-spark-1.3` (Contributor variant `muse-spark-1.3-contributor`),
  base `https://api.meta.ai/v1`, Bearer `MODEL_API_KEY`.
- Upload once: `POST /v1/files`, multipart `purpose=user_data` (+
  `expires_after` anchor/seconds), response `{id: "file-..."}`.
- Analyse: `POST /v1/responses` with
  `input=[{role: user, content: [{input_text}, {input_file: {file_id}}]}]`,
  non-streaming, plain-text answer (no response_format tricks, no tools).
- Pricing (Contributor): $0.10 / 1M input tokens, $0.20 / 1M output tokens.
  Video frames count as input tokens; the exact per-video count is reported
  back in `usage` and recorded — never estimated upfront as a promise.
- Audio in Spark 1.3 is documented as not fully supported, so the analysis
  copy is video-only; speech stays on the verified ASR path on demand.

Exactly one Files POST + one Responses POST per `analyze_video` call under a
single one-shot ledger authorization. No retries, no silent fallback.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from clipforge_director.ledger import LiveCallAuthorization, LiveCallNotAuthorizedError

logger = logging.getLogger("clipforge.providers.video_analysis")

DEFAULT_BASE_URL = "https://api.meta.ai"
RESPONSES_PATH = "/v1/responses"
FILES_PATH = "/v1/files"
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_TOKENS = 2000
DEFAULT_REASONING_EFFORT = "minimal"
FILE_EXPIRY_SECONDS = 3600
MAX_ANALYSIS_BYTES = 1_073_741_824  # Files API 1 GiB cap (docs).
_ACCEPTED_VIDEO_CODECS = {"h264", "hevc", "mpeg4"}

INPUT_USD_PER_M = 0.10
OUTPUT_USD_PER_M = 0.20


REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh"})


class VideoAnalysisError(RuntimeError):
    """Base class for safe video-analysis provider failures."""


class VideoAnalysisMissingCredentialsError(VideoAnalysisError):
    pass


class VideoAnalysisNotAuthorizedError(VideoAnalysisError):
    pass


class VideoAnalysisTimeoutError(VideoAnalysisError):
    pass


class VideoAnalysisRateLimitedError(VideoAnalysisError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class VideoAnalysisAPIError(VideoAnalysisError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        server_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.server_request_id = server_request_id


class VideoAnalysisValidationError(VideoAnalysisError):
    pass


class VideoAnalysisUsage(BaseModel):
    """Measured usage for one analysis (upload + inference under one slot)."""

    model_config = ConfigDict(extra="forbid")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    response_id: str | None = None
    file_id: str | None = None
    file_reused: bool = False


ANALYSIS_SYSTEM_PROMPT = (
    "És o Muse, o Director criativo do ClipForge. Vês o vídeo com atenção e "
    "respondes em português europeu, directo e concreto.\n"
    "REGRAS DURAS:\n"
    "- Descreve SÓ o que é visível no vídeo. Nunca inventes pessoas, objectos, "
    "acções ou texto que não se vejam.\n"
    "- Não infiras identidade: descreve pessoas em termos visuais neutros "
    "(ex.: «uma pessoa de casaco escuro»), nunca nomes ou dados pessoais.\n"
    "- Tempos (mm:ss) são SEMPRE aproximados — marca-os como tal, nunca como "
    "cortes exactos.\n"
    "- Se algo não for claro, diz que não tens a certeza em vez de adivinhar.\n"
    "- Responde EXACTAMENTE nestas secções, nesta ordem, mesmo que alguma "
    "fique vazia:\n"
    "RESUMO: (2-3 frases)\n"
    "ACONTECE: (o que se passa, por ordem)\n"
    "ELEMENTOS: (pessoas, objectos, ambiente — um por linha com '- ')\n"
    "MOMENTOS: (um por linha: 'mm:ss - descrição', aproximados)\n"
    "OBSERVACOES: (enquadramento, luz, composição — um por linha)\n"
    "MELHORIAS: (sugestões concretas com ferramentas do ClipForge: desfocar "
    "fundo, substituir fundo, texto/legendas, cor local — uma por linha)\n"
    "INCERTEZAS: (o que não conseguiste confirmar — uma por linha)"
)


def _ffprobe(path: Path, *, count_frames: bool = False) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    if count_frames:
        command.insert(3, "-count_frames")
    command.append(str(path))
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise VideoAnalysisValidationError(
            f"ffprobe failed on {path.name}: {result.stderr.strip()[-300:]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoAnalysisValidationError(
            f"ffprobe returned invalid JSON for {path.name}."
        ) from exc


def _video_stream(data: dict[str, Any]) -> dict[str, Any]:
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if stream is None:
        raise VideoAnalysisValidationError("The source has no video stream.")
    return stream


def _frame_count(stream: dict[str, Any]) -> int:
    raw = stream.get("nb_read_frames") or stream.get("nb_frames")
    if raw is None or not str(raw).isdigit():
        return -1
    return int(raw)


def prepare_analysis_copy(source: Path, output: Path) -> dict[str, Any]:
    """Build a video-only MP4 analysis copy without touching the original.

    MP4/H.264-family sources are stream-copied (no pixel changes); anything
    else is transcoded to H.264 yuv420p. Audio is always stripped: Spark 1.3
    audio understanding is documented as degraded, and speech stays on the
    verified ASR path. Dimensions, FPS and frame count must survive exactly.
    """
    if not source.is_file():
        raise VideoAnalysisValidationError("Source video not found for analysis.")
    if source.stat().st_size > MAX_ANALYSIS_BYTES:
        raise VideoAnalysisValidationError(
            f"Source video exceeds the 1 GiB Files API limit ({source.stat().st_size} bytes)."
        )
    probe = _ffprobe(source, count_frames=True)
    vstream = _video_stream(probe)
    width = int(vstream.get("width", 0))
    height = int(vstream.get("height", 0))
    if width <= 0 or height <= 0:
        raise VideoAnalysisValidationError("Source video has invalid dimensions.")
    container = str(probe.get("format", {}).get("format_name", ""))
    codec = str(vstream.get("codec_name", ""))
    copyable = codec in _ACCEPTED_VIDEO_CODECS and ("mp4" in container or "mov" in container)
    try:
        if copyable:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(source), "-map", "0:v:0",
                 "-c:v", "copy", "-an", "-movflags", "+faststart", str(output)],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                copyable = False
        if not copyable:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(source), "-map", "0:v:0",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                 "-movflags", "+faststart", str(output)],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                raise VideoAnalysisValidationError(
                    f"FFmpeg analysis-copy failed: {result.stderr.strip()[-400:]}"
                )
    except subprocess.TimeoutExpired as exc:
        raise VideoAnalysisTimeoutError("FFmpeg analysis copy timed out.") from exc
    check = _ffprobe(output, count_frames=True)
    if any(s.get("codec_type") == "audio" for s in check.get("streams", [])):
        raise VideoAnalysisValidationError("Temporary analysis copy still contains audio.")
    out_stream = _video_stream(check)
    if (int(out_stream.get("width", 0)), int(out_stream.get("height", 0))) != (width, height):
        raise VideoAnalysisValidationError("Temporary analysis copy changed dimensions.")
    if _frame_count(out_stream) != _frame_count(vstream):
        raise VideoAnalysisValidationError("Temporary analysis copy changed frame count.")
    return {
        "width": width,
        "height": height,
        "duration_seconds": float(check.get("format", {}).get("duration", 0.0) or 0.0),
        "size_bytes": output.stat().st_size,
    }


_SECTION_ALIASES = {
    "resumo": "overall_summary",
    "acontece": "happens",
    "elementos": "elements",
    "momentos": "moments",
    "observacoes": "observations",
    "observações": "observations",
    "melhorias": "opportunities",
    "incertezas": "uncertainties",
}

_TIMESTAMP_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _norm_header(line: str) -> str:
    head = line.strip().lower().rstrip(":").strip()
    return head


def parse_analysis_sections(raw_text: str) -> dict[str, Any]:
    """Lenient projection of the prompted sections. Missing stays missing.

    Never raises on odd model text: unparseable lines are dropped, never
    invented. Lists are truncated to the contract limits.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        head, colon, rest = line.partition(":")
        key = _SECTION_ALIASES.get(_norm_header(head)) if colon and len(head.strip()) <= 24 else None
        if key is not None:
            current = key
            sections.setdefault(current, [])
            rest = rest.strip()
            if rest:
                bullet = re.sub(r"^(\d+[.)\-:]|[-*•>])\s*", "", rest).strip()
                if bullet:
                    sections[current].append(bullet[:500])
            continue
        if current is None:
            continue
        bullet = re.sub(r"^(\d+[.)\-:]|[-*•>])\s*", "", line).strip()
        if bullet:
            sections[current].append(bullet[:500])

    def _first(key: str) -> str | None:
        lines = sections.get(key, [])
        text = " ".join(lines).strip()
        return text[:2000] if text else None

    def _bullets(key: str, limit: int) -> list[str]:
        return [b for b in sections.get(key, []) if b][:limit]

    moments = []
    for bullet in _bullets("moments", 12):
        match = _TIMESTAMP_RE.search(bullet)
        at_s: float | None = None
        if match:
            try:
                at_s = int(match.group(1)) * 60 + int(match.group(2))
            except ValueError:
                at_s = None
        label = _TIMESTAMP_RE.sub("", bullet, count=1).strip(" -–—:").strip() or bullet
        moments.append({"at_s": at_s, "approximate": True, "label": label[:200]})

    subjects: list[str] = []
    objects_seen: list[str] = []
    for bullet in _bullets("elements", 20):
        low = bullet.lower()
        if any(w in low for w in ("pessoa", "homem", "mulher", "criança", "sujeito", "apresentador")):
            subjects.append(bullet)
        else:
            objects_seen.append(bullet)

    return {
        "overall_summary": _first("overall_summary"),
        "sequence": _first("happens"),
        "subjects": subjects[:10],
        "objects_seen": objects_seen[:10],
        "moments": moments,
        "composition_observations": _bullets("observations", 12),
        "editing_opportunities": _bullets("opportunities", 12),
        "uncertainties": _bullets("uncertainties", 12),
    }


class SparkVideoAnalysisProvider:
    """Hosted Muse Spark native video understanding. Analysis only.

    Uploads the prepared video-only MP4 once, then asks one visual question
    via Responses. Never executes tools, never retries, never falls back.
    """

    provider_name = "meta-muse-spark-video"
    execution_mode = "live"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise VideoAnalysisMissingCredentialsError(
                "Video analysis requires MODEL_API_KEY (server-side only). No request was attempted."
            )
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive.")
        if reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(
                f"Unknown reasoning effort {reasoning_effort!r}; verified values: "
                f"{sorted(REASONING_EFFORTS)}. No request was attempted."
            )
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
            follow_redirects=False,
        )
        self.last_usage: VideoAnalysisUsage | None = None
        self.last_response_id: str | None = None
        self.last_file_id: str | None = None

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def upload_file(self, path: Path) -> str:
        """POST /v1/files with purpose=user_data. Exactly one attempt."""
        if not path.is_file():
            raise VideoAnalysisValidationError("Analysis video file not found for upload.")
        if path.stat().st_size > MAX_ANALYSIS_BYTES:
            raise VideoAnalysisValidationError(
                f"Analysis video exceeds the 1 GiB Files API limit ({path.stat().st_size} bytes)."
            )
        try:
            with open(path, "rb") as handle:
                response = self._client.post(
                    FILES_PATH,
                    headers=self._headers(),
                    data={
                        "purpose": "user_data",
                        "expires_after[anchor]": "created_at",
                        "expires_after[seconds]": str(FILE_EXPIRY_SECONDS),
                    },
                    files={"file": (path.name, handle, "video/mp4")},
                )
        except httpx.TimeoutException as exc:
            raise VideoAnalysisTimeoutError("Video-analysis file upload timed out.") from exc
        except httpx.HTTPError as exc:
            raise VideoAnalysisError(f"Could not reach the file service: {exc}") from exc
        if response.status_code == 429:
            raise VideoAnalysisRateLimitedError(
                "Video-analysis upload is rate limited.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            raise VideoAnalysisAPIError(
                f"Video-analysis upload failed with HTTP {response.status_code}.",
                status_code=response.status_code,
                server_request_id=response.headers.get("x-request-id"),
            )
        try:
            file_id = response.json().get("id")
        except ValueError as exc:
            raise VideoAnalysisAPIError("Video-analysis upload returned invalid JSON.") from exc
        if not isinstance(file_id, str) or not file_id.startswith("file-"):
            raise VideoAnalysisAPIError("Video-analysis upload returned no file id.")
        self.last_file_id = file_id
        logger.info("video_analysis_uploaded file_id=%s bytes=%d", file_id, path.stat().st_size)
        return file_id

    def delete_file(self, file_id: str) -> None:
        """DELETE /v1/files/{file_id}. Best effort: callers log, never fail on it."""
        if not file_id or not file_id.startswith("file-"):
            raise VideoAnalysisValidationError(f"Invalid provider file id: {file_id!r}.")
        try:
            response = self._client.delete(
                f"{FILES_PATH}/{file_id}", headers=self._headers()
            )
        except httpx.TimeoutException as exc:
            raise VideoAnalysisTimeoutError("Video-analysis file delete timed out.") from exc
        except httpx.HTTPError as exc:
            raise VideoAnalysisError(f"Could not reach the file service: {exc}") from exc
        if response.status_code == 429:
            raise VideoAnalysisRateLimitedError(
                "Video-analysis file delete is rate limited.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            raise VideoAnalysisAPIError(
                f"Video-analysis file delete failed with HTTP {response.status_code}.",
                status_code=response.status_code,
            )

    def analyze_file(
        self,
        *,
        file_id: str,
        instruction: str,
        authorization: LiveCallAuthorization | None = None,
    ) -> tuple[str, VideoAnalysisUsage]:
        """One Responses call with input_text + input_file. No retries."""
        if not isinstance(authorization, LiveCallAuthorization):
            raise VideoAnalysisNotAuthorizedError(
                "A valid LiveCallAuthorization is required before a live analysis request. "
                "No request was attempted."
            )
        if not file_id or not file_id.startswith("file-"):
            raise VideoAnalysisValidationError(f"Invalid provider file id: {file_id!r}.")
        clean_instruction = " ".join(instruction.strip().split())
        if not clean_instruction:
            raise ValueError("instruction must be non-empty.")
        # The section rules live in the user text itself: this keeps the exact
        # verified Responses shape (message/user/content[input_text,
        # input_file]) with no extra unverified parameters.
        user_text = (
            ANALYSIS_SYSTEM_PROMPT
            + "\n\nPedido do utilizador: "
            + clean_instruction[:500]
        )
        payload = {
            "model": self._model,
            "reasoning": {"effort": self._reasoning_effort},
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {"type": "input_file", "file_id": file_id},
                    ],
                }
            ],
            "max_output_tokens": self._max_output_tokens,
        }
        authorization.reserve()
        try:
            response = self._client.post(
                RESPONSES_PATH,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise VideoAnalysisTimeoutError(
                "Video analysis timed out with no response."
            ) from exc
        except httpx.HTTPError as exc:
            raise VideoAnalysisError(f"Could not reach the analysis service: {exc}") from exc
        if response.status_code == 429:
            raise VideoAnalysisRateLimitedError(
                "Video analysis is rate limited.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            detail = ""
            try:
                error_body = response.json()
                message = (
                    error_body.get("error", {}).get("message")
                    if isinstance(error_body.get("error"), dict)
                    else error_body.get("message")
                )
                if isinstance(message, str) and message.strip():
                    detail = f": {message.strip()[:200]}"
            except Exception:
                detail = ""
            raise VideoAnalysisAPIError(
                f"Video analysis failed with HTTP {response.status_code}{detail}.",
                status_code=response.status_code,
                server_request_id=response.headers.get("x-request-id"),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise VideoAnalysisAPIError("Video analysis returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise VideoAnalysisAPIError("Video analysis returned an unexpected shape.")
        server_request_id = (
            body.get("id") if isinstance(body.get("id"), str) else None
        )
        self.last_response_id = server_request_id
        text = _output_text(body)
        if not text.strip():
            raise VideoAnalysisAPIError("Video analysis returned no text.")
        usage_body = body.get("usage") or {}
        try:
            prompt_tokens = int(usage_body.get("input_tokens", 0) or 0)
            completion_tokens = int(usage_body.get("output_tokens", 0) or 0)
            total_tokens = int(
                usage_body.get("total_tokens", 0) or (prompt_tokens + completion_tokens)
            )
        except (TypeError, ValueError):
            prompt_tokens, completion_tokens, total_tokens = 0, 0, 0
        cost = round(
            prompt_tokens * INPUT_USD_PER_M / 1_000_000
            + completion_tokens * OUTPUT_USD_PER_M / 1_000_000,
            6,
        )
        usage = VideoAnalysisUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            response_id=server_request_id,
            file_id=file_id,
            file_reused=False,
        )
        self.last_usage = usage
        logger.info(
            "video_analysis_ok response_id=%s in=%d out=%d cost=%.6f",
            server_request_id,
            prompt_tokens,
            completion_tokens,
            cost,
        )
        return text, usage

    def analyze_video(
        self,
        *,
        analysis_path: Path,
        instruction: str,
        authorization: LiveCallAuthorization | None = None,
    ) -> tuple[str, VideoAnalysisUsage]:
        """Upload (if needed by the caller) + one analysis call, one slot."""
        file_id = self.upload_file(analysis_path)
        text, usage = self.analyze_file(
            file_id=file_id, instruction=instruction, authorization=authorization
        )
        usage.file_reused = False
        return text, usage


def _output_text(body: dict[str, Any]) -> str:
    """Collect completed output_text from a Responses body (same shape as SAM)."""
    parts: list[str] = []
    output = body.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
    return "".join(parts)
