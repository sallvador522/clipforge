"""Muse Spark subtitle translation adapter (ADR-050).

Live caption translation uses the ALREADY-VERIFIED Chat Completions contract
(same endpoint/auth/shape as the Spark director in
`clipforge_director/spark.py`): `POST https://api.meta.ai/v1/chat/completions`,
Bearer auth, single-turn, plain-text answer. No response_format tricks, no
tools, no retries, no web search. Translation is a text task the model can
really do — timings always come from real speech turns, never from the model.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from clipforge_director.ledger import LiveCallAuthorization, LiveCallNotAuthorizedError

logger = logging.getLogger("clipforge.providers.translation")

DEFAULT_BASE_URL = "https://api.meta.ai"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 1500

INPUT_USD_PER_M = 0.10
OUTPUT_USD_PER_M = 0.20


class TranslationError(Exception):
    """Base class for translation failures."""


class MissingCredentialsError(TranslationError):
    pass


class TranslationTimeoutError(TranslationError):
    pass


class TranslationRateLimitedError(TranslationError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TranslationAPIError(TranslationError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class TranslationResult(BaseModel):
    """Validated translation outcome with measured usage."""

    model_config = ConfigDict(extra="forbid")
    translated_text: str = Field(min_length=1)
    source_chars: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)


class SparkSubtitleTranslator:
    """One-shot EN->PT subtitle translation. Exactly one POST per call."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise MissingCredentialsError("MODEL_API_KEY is required (server-side only).")
        self._api_key = api_key.strip()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
            follow_redirects=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def translate_lines(
        self,
        lines: list[str],
        *,
        authorization: LiveCallAuthorization | None = None,
    ) -> TranslationResult:
        """Translate numbered subtitle lines EN->PT in one POST.

        Numbered in / numbered out preserves the line->timing mapping;
        the response is validated strictly and any deviation is rejected.
        """
        if not isinstance(authorization, LiveCallAuthorization):
            raise LiveCallNotAuthorizedError(
                "A valid LiveCallAuthorization is required before a live translation request. "
                "No request was attempted."
            )
        clean = [line.strip() for line in lines]
        if not clean or any(not line for line in clean):
            raise ValueError("Subtitle lines must be non-empty.")
        if sum(len(line) for line in clean) > 2000:
            raise ValueError("Subtitle batch too long (max 2000 chars).")
        numbered = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(clean))
        payload = {
            "model": self._model,
            "reasoning_effort": DEFAULT_REASONING_EFFORT,
            "messages": [
                {"role": "system", "content": (
                    "Translate the numbered English subtitle lines to European Portuguese. "
                    "Reply with exactly the same numbered lines, translated, one per line. "
                    "No explanations, no extra lines, keep numbering.")},
                {"role": "user", "content": numbered},
            ],
            "max_completion_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        }
        authorization.reserve()
        try:
            response = self._client.post(
                CHAT_COMPLETIONS_PATH,
                headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise TranslationTimeoutError(f"Translation timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TranslationError(f"Could not reach the translation service: {exc}") from exc
        if response.status_code == 429:
            raise TranslationRateLimitedError("Translation is rate limited.",
                                              retry_after=response.headers.get("Retry-After"))
        if response.status_code >= 400:
            raise TranslationAPIError(response.status_code,
                                       f"Translation failed with HTTP {response.status_code}.")
        try:
            body: dict[str, Any] = response.json()
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationAPIError(502, "Translation response was not usable.") from exc
        if not isinstance(content, str) or not content.strip():
            raise TranslationAPIError(502, "Translation response contained no text.")
        out_lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
        translated: list[str] = []
        for i in range(len(clean)):
            if i >= len(out_lines):
                raise TranslationAPIError(502, f"Translation missed line {i + 1}.")
            text = out_lines[i]
            prefix = f"{i + 1}."
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
            elif text[:2].rstrip(".").isdigit():
                raise TranslationAPIError(502, f"Translation line {i + 1} misnumbered.")
            if not text:
                raise TranslationAPIError(502, f"Translation line {i + 1} is empty.")
            translated.append(text)
        in_tokens = int(usage.get("prompt_tokens", 0) or 0)
        out_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost = round(in_tokens * INPUT_USD_PER_M / 1_000_000
                     + out_tokens * OUTPUT_USD_PER_M / 1_000_000, 6)
        logger.info("translation_ok lines=%d in=%d out=%d cost=%.6f",
                    len(clean), in_tokens, out_tokens, cost)
        return TranslationResult(
            translated_text="\n".join(translated),
            source_chars=sum(len(line) for line in clean),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            estimated_cost_usd=cost,
        )
