"""Meta Muse Spark professional editing director provider (Milestone 6B-LIVE).

Prepared but NOT live-tested: every test uses an injected httpx MockTransport.
No request may reach api.meta.ai without explicit user approval.

Official configuration verified against current Meta docs:
- Models: `muse-spark-1.3` (Standard) and `muse-spark-1.3-contributor`
  (Contributor). Default is Standard; Contributor only when explicitly required
  with `require_contributor=True` (approved LIVE-CALL 001).
- Protocol: Chat Completions, `POST https://api.meta.ai/v1/chat/completions`.
- Auth: `Authorization: Bearer MODEL_API_KEY` (canonical env var name; there is
  no `META_API_KEY` in the verified docs or this repo).
- `reasoning_effort`: documented values `minimal`/`low`/`medium`/`high`/`xhigh`
  (`none` is rejected for Spark). There is no `context`-size parameter in the
  verified Chat Completions contract.
- Single-turn plan generation with structured output via `response_format`
  (`type: "json_schema"`, Pydantic-derived schema, `strict: false` default).
- Response shape: `choices[0].message.content` (JSON string), `finish_reason`,
  `usage: {prompt_tokens, completion_tokens, total_tokens}`.
- Pricing Standard: $1.25 / 1M input, $4.25 / 1M output. Contributor:
  $0.10 / 1M input, $0.20 / 1M output (cached input $0.002; not modeled — usage
  breakdown is reported raw and cached tokens are not assumed).
- No `tools` are sent in the first test (plan generation only, no tool execution).
- No web search grounding, no audio input (confirmed transcript text only).

Protocol choice: Chat Completions, not Responses API. Reasons:
- The first test is single-turn plan generation; no multi-turn reasoning replay or
  server-managed history is needed (Responses strengths we do not use yet).
- Structured output via `response_format` has a documented Pydantic flow and a
  guaranteed-conformance contract.
- Stateless: no `store` / `previous_response_id` / encrypted-reasoning handling.
- The Responses `text.format` parameter must not be sent here; the Chat
  `response_format` parameter must not be sent to Responses. This provider sends
  only the Chat Completions shape.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from clipforge_contracts import ProfessionalEditingPlan, TranscriptResult

logger = logging.getLogger("clipforge.director.spark")

DEFAULT_BASE_URL = "https://api.meta.ai"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
DEFAULT_MODEL = "muse-spark-1.3"
CONTRIBUTOR_MODEL = "muse-spark-1.3-contributor"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 1500

REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh"})

INPUT_USD_PER_M = 1.25
OUTPUT_USD_PER_M = 4.25
CONTRIBUTOR_INPUT_USD_PER_M = 0.10
CONTRIBUTOR_OUTPUT_USD_PER_M = 0.20


class SparkDirectorError(Exception):
    """Base class for director provider failures."""


class MissingCredentialsError(SparkDirectorError):
    pass


class InvalidModelError(SparkDirectorError):
    pass


class DirectorTimeoutError(SparkDirectorError):
    pass


class DirectorRateLimitedError(SparkDirectorError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class DirectorAPIError(SparkDirectorError):
    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str | None = None,
        server_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        # Server-side correlation handle for panel reconciliation. Non-secret:
        # safe to log, print and store. Never the API key.
        self.server_request_id = server_request_id


class DirectorValidationError(SparkDirectorError):
    def __init__(self, message: str, server_request_id: str | None = None) -> None:
        super().__init__(message)
        self.server_request_id = server_request_id


class DirectorVideoMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    frame_count: int = Field(gt=0)
    has_audio: bool = False


class DirectorUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)


def estimate_tokens(text: str) -> int:
    """Rough pre-request size estimate (chars / 4). Not a billing figure."""
    return max(1, len(text) // 4)


def calculate_cost_usd(prompt_tokens: int, completion_tokens: int, mode: str = "standard") -> float:
    if mode == "contributor":
        per_in, per_out = CONTRIBUTOR_INPUT_USD_PER_M, CONTRIBUTOR_OUTPUT_USD_PER_M
    elif mode == "standard":
        per_in, per_out = INPUT_USD_PER_M, OUTPUT_USD_PER_M
    else:
        raise ValueError(f"Unknown pricing mode {mode!r}; expected 'standard' or 'contributor'.")
    return round(prompt_tokens * per_in / 1_000_000 + completion_tokens * per_out / 1_000_000, 6)


def build_developer_prompt(*, playbook_text: str, capability_summary: str) -> str:
    return (
        playbook_text.strip()
        + "\n\n## Approved capabilities (registry authority)\n"
        + capability_summary.strip()
        + "\n\n## Output rules for this request\n"
        + "- Emit exactly one ProfessionalEditingPlan v2 JSON object and nothing else.\n"
        + "- Use only capabilities marked available in the summary above.\n"
        + "- Copy request_id and raw_instruction from the user message verbatim.\n"
        + "- Never invent tools, paths, URLs, shell commands, FFmpeg flags or credentials.\n"
    )


def build_user_prompt(
    *,
    transcript: TranscriptResult,
    video: DirectorVideoMetadata | None,
    request_id: str,
) -> str:
    lines = [
        f"Confirmed transcript: {transcript.text}",
        f"Transcript language: {transcript.language}",
        f"Required request_id (copy verbatim): {request_id}",
        "Required raw_instruction (copy the confirmed transcript verbatim): " + transcript.text,
    ]
    if video is not None:
        lines.append(
            "Source video metadata: "
            f"{video.width}x{video.height} @ {video.fps:.2f}fps, "
            f"{video.duration_seconds:.2f}s, {video.frame_count} frames, "
            f"audio={'present' if video.has_audio else 'absent'}."
        )
    lines.append(
        "Produce the editing plan for this instruction. If the subject or intent is "
        "ambiguous, return a needs_clarification plan with one focused question and no "
        "operations. If it needs an unavailable capability, return an unsupported plan "
        "naming it, with no operations."
    )
    return "\n".join(lines)


class MetaEditingDirectorProvider:
    """Hosted Muse Spark director. Plan generation only; never executes tools."""

    provider_name = "meta-muse-spark-director"

    def __init__(
        self,
        api_key: str,
        playbook_text: str,
        capability_summary: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        reasoning_effort: str | None = None,
        require_contributor: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise MissingCredentialsError(
                "MODEL_API_KEY is required for the live director. It is server-side only."
            )
        if require_contributor:
            if model != CONTRIBUTOR_MODEL:
                raise InvalidModelError(
                    f"Contributor call requires exactly {CONTRIBUTOR_MODEL!r}; "
                    f"refusing {model!r} (Standard strings rejected in this mode)."
                )
        elif "contributor" in model:
            raise InvalidModelError(
                f"Refusing Contributor mode model {model!r}: Standard mode only ({DEFAULT_MODEL})."
            )
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(
                f"Unknown reasoning_effort {reasoning_effort!r}; verified values: "
                f"{sorted(REASONING_EFFORTS)}."
            )
        if not playbook_text or not playbook_text.strip():
            raise ValueError("playbook_text is required.")
        if not capability_summary or not capability_summary.strip():
            raise ValueError("capability_summary is required.")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive.")
        self._api_key = api_key.strip()
        self._playbook_text = playbook_text
        self._capability_summary = capability_summary
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._pricing_mode = "contributor" if require_contributor else "standard"
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
            follow_redirects=False,
        )
        self.last_usage: DirectorUsage | None = None
        self.last_request_id: str | None = None

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _wire_schema(self) -> dict:
        return ProfessionalEditingPlan.model_json_schema()

    def _schema_name(self) -> str:
        return "ProfessionalEditingPlan"

    def request_payload(
        self,
        transcript: TranscriptResult,
        video: DirectorVideoMetadata | None = None,
        *,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        expected_request_id = request_id or ("req_" + hashlib.sha256(transcript.text.encode()).hexdigest()[:12])
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "developer",
                    "content": build_developer_prompt(
                        playbook_text=self._playbook_text,
                        capability_summary=self._capability_summary,
                    ),
                },
                {
                    "role": "user",
                    "content": build_user_prompt(
                        transcript=transcript, video=video, request_id=expected_request_id
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": self._schema_name(),
                    "schema": self._wire_schema(),
                    "strict": False,
                },
            },
            "max_completion_tokens": self._max_output_tokens,
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        return payload, expected_request_id

    def create_plan(
        self,
        transcript: TranscriptResult,
        video: DirectorVideoMetadata | None = None,
        *,
        request_id: str | None = None,
    ) -> ProfessionalEditingPlan:
        """Generate exactly one v2 plan via a single Chat Completions call. No retries."""
        payload, expected_request_id = self.request_payload(transcript, video, request_id=request_id)
        self.last_request_id = expected_request_id
        logger.info(
            "director_request model=%s max_tokens=%d transcript_chars=%d",
            self._model,
            self._max_output_tokens,
            len(transcript.text),
        )
        try:
            response = self._client.post(
                CHAT_COMPLETIONS_PATH,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise DirectorTimeoutError(
                f"Director request timed out after {self._timeout_seconds:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise SparkDirectorError("Could not reach the director service.") from exc

        if response.status_code == 429:
            raise DirectorRateLimitedError(
                "Director is rate limited. No automatic retry was attempted.",
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code >= 400:
            message, error_type = self._safe_error(response)
            server_request_id = response.headers.get("x-request-id")
            logger.warning(
                "director_api_error status=%d type=%s server_request_id=%s",
                response.status_code,
                error_type,
                server_request_id or "absent",
            )
            raise DirectorAPIError(
                response.status_code,
                f"Director failed with HTTP {response.status_code}: {message}",
                error_type=error_type,
                server_request_id=server_request_id,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DirectorAPIError(502, "Director returned invalid JSON.") from exc

        server_request_id = response.headers.get("x-request-id")
        # Record usage BEFORE validation: a truncated but successful (billed) call
        # must still feed token accounting even though no plan is accepted.
        self.last_usage = self._record_usage(body)
        content = self._extract_content(body, server_request_id)
        plan = self._validate_content(content, expected_request_id, transcript, server_request_id)

        logger.info(
            "director_ok outcome=%s ops=%d prompt=%d completion=%d cost_usd=%.6f",
            plan.outcome.value,
            len(plan.operations),
            self.last_usage.prompt_tokens,
            self.last_usage.completion_tokens,
            self.last_usage.cost_usd,
        )
        return plan

    def _record_usage(self, body: dict[str, Any]) -> DirectorUsage:
        usage = body.get("usage") or {}
        try:
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        except (TypeError, ValueError):
            prompt_tokens, completion_tokens, total_tokens = 0, 0, 0
        return DirectorUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=calculate_cost_usd(prompt_tokens, completion_tokens, self._pricing_mode),
        )

    @staticmethod
    def _extract_content(body: dict[str, Any], server_request_id: str | None = None) -> str:
        try:
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DirectorValidationError(
                "Director response has no choices[0].message.", server_request_id
            ) from exc

        if message.get("tool_calls"):
            raise DirectorValidationError(
                "Director returned tool calls; this provider never executes tools.",
                server_request_id,
            )
        if choice.get("finish_reason") == "length":
            raise DirectorValidationError(
                "Director output was truncated (finish_reason=length); no partial plan accepted.",
                server_request_id,
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise DirectorValidationError("Director returned empty content.", server_request_id)
        return content

    def _validate_content(
        self,
        content: str,
        expected_request_id: str,
        transcript: TranscriptResult,
        server_request_id: str | None = None,
    ) -> ProfessionalEditingPlan:
        try:
            raw_plan = json.loads(content)
        except ValueError as exc:
            raise DirectorValidationError(
                "Director content is not valid JSON.", server_request_id
            ) from exc

        try:
            plan = ProfessionalEditingPlan.model_validate(raw_plan)
        except Exception as exc:
            raise DirectorValidationError(
                f"Director plan failed validation: {exc}", server_request_id
            ) from exc

        if plan.request_id != expected_request_id:
            raise DirectorValidationError(
                f"Director request_id {plan.request_id!r} does not match {expected_request_id!r}.",
                server_request_id,
            )
        if plan.raw_instruction != transcript.text:
            raise DirectorValidationError(
                "Director raw_instruction must equal the confirmed transcript.",
                server_request_id,
            )
        return plan

    @staticmethod
    def _safe_error(response: httpx.Response) -> tuple[str, str | None]:
        try:
            body = response.json()
        except ValueError:
            return "unexpected error response", None
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            message = error.get("message")
            code = error.get("type") or error.get("code")
            return (
                message if isinstance(message, str) and message.strip() else "unexpected error response",
                code if isinstance(code, str) else None,
            )
        if isinstance(body, dict):
            message = body.get("message")
            error_type = body.get("type")
            return (
                message if isinstance(message, str) and message.strip() else "unexpected error response",
                error_type if isinstance(error_type, str) else None,
            )
        return "unexpected error response", None


class LiteMetaEditingDirectorProvider(MetaEditingDirectorProvider):
    """Contributor-Medium lite-schema variant (LIVE-CALL 003).

    Same safety rails as the base provider (single POST, no retries, echo
    enforcement, no key/audio logging). Differences: the wire carries the
    hand-written minimal `LITE_WIRE_SCHEMA` (zero $refs) instead of the full
    v2 JSON Schema, and the response is parsed as `LitePlan` then converted
    and fully validated as a v2 `ProfessionalEditingPlan`.
    """

    provider_name = "meta-muse-spark-director-lite"

    def _wire_schema(self) -> dict[str, Any]:
        from clipforge_contracts.director_lite import LITE_WIRE_SCHEMA

        return LITE_WIRE_SCHEMA

    def _schema_name(self) -> str:
        return "ProfessionalEditingPlanLite"

    def _validate_content(
        self,
        content: str,
        expected_request_id: str,
        transcript: TranscriptResult,
        server_request_id: str | None = None,
    ) -> ProfessionalEditingPlan:
        from clipforge_contracts.director_lite import LitePlan, lite_to_full_plan

        try:
            raw_lite = json.loads(content)
        except ValueError as exc:
            raise DirectorValidationError(
                "Director content is not valid JSON.", server_request_id
            ) from exc

        try:
            lite = LitePlan.model_validate(raw_lite)
            plan = lite_to_full_plan(lite)
        except Exception as exc:
            raise DirectorValidationError(
                f"Lite plan failed validation: {exc}", server_request_id
            ) from exc

        if plan.request_id != expected_request_id:
            raise DirectorValidationError(
                f"Director request_id {plan.request_id!r} does not match {expected_request_id!r}.",
                server_request_id,
            )
        if plan.raw_instruction != transcript.text:
            raise DirectorValidationError(
                "Director raw_instruction must equal the confirmed transcript.",
                server_request_id,
            )
        return plan
