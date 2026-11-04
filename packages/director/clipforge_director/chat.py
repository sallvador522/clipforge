"""Muse Spark conversational director turn (ADR-054).

Reuses the ALREADY-VERIFIED Chat Completions contract (same endpoint/auth as
the Spark director in `clipforge_director/spark.py` and the subtitle
translator in `clipforge_providers/translation_spark.py`):
`POST https://api.meta.ai/v1/chat/completions`, Bearer auth, single-turn,
plain-text answer. No response_format tricks, no tools, no retries.

Design: the deterministic router keeps deciding intent and pending proposals
(side-effect free, approval gates unchanged), while this assistant phrases
the resolved turn from the real project snapshot (assets, job, texts,
timeline, idea) plus short chat history. The model never decides execution,
never emits tools/params/paths/commands, and its output is validated as
plain text before it replaces the local reply.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from clipforge_director.ledger import LiveCallAuthorization, LiveCallNotAuthorizedError

logger = logging.getLogger("clipforge.director.chat")

DEFAULT_BASE_URL = "https://api.meta.ai"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_OUTPUT_TOKENS = 900

INPUT_USD_PER_M = 0.10
OUTPUT_USD_PER_M = 0.20


class ChatError(Exception):
    """Base class for chat failures."""


class MissingCredentialsError(ChatError):
    pass


class ChatTimeoutError(ChatError):
    pass


class ChatRateLimitedError(ChatError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ChatAPIError(ChatError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ChatValidationError(ChatError):
    pass


class ChatUsage(BaseModel):
    """Measured token usage for one chat turn."""

    model_config = ConfigDict(extra="forbid")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)


CHAT_SYSTEM_PROMPT = (
    "És o Muse, o Director criativo do ClipForge. Falas português europeu "
    "informal (tratamento por tu), directo e natural.\n"
    "COMO PENSARES:\n"
    "- Le o ESTADO REAL do projeto antes de responder. Contas, nomes, duracoes, "
    "resolucoes, textos, estado do job, timeline e entrevista sao factos: usa-os, "
    "nao os renegocies.\n"
    "- Usa a conversa recente: segue o fio (referencias a 'a minha pergunta "
    "anterior', pronomes e follow-ups curtos ligam-se ao turno anterior).\n"
    "- Perguntas sao perguntas. Se o utilizador pergunta quantos videos ha, "
    "quantos textos, que clipe esta aberto ou o que ja foi feito, responde com "
    "a resposta real e nunca com 'Operacao concluida' nem 'prime Executar'.\n"
    "- Propostas de edicao sao propostas. Se a Resposta base ou o Pedido "
    "(intent=edit_tools, edit_proposal ou idea_proposal) aguarda Confirmar/"
    "Executar, mantem isso claro: nada foi executado ainda.\n"
    "CAPACIDADES REAIS (verificadas no codigo, nao promessas): desfocar o fundo "
    "mantendo a pessoa nitida, substituir o fundo (com confirmacao e "
    "consentimento SAM), criar um video novo a partir de uma ideia, textos/"
    "legendas editaveis sobre o clipe, cor local (contraste/brilho/saturacao), "
    "trim e audio do upload (manual), timeline multi-faixa V1/V2/A1/A2 quando "
    "ha blocos, e formato original/9:16/16:9 no Montar. Capacidades planeadas/"
    "desactivadas: nunca anuncies recortes de cena automaticos, transicoes "
    "como efeito livre, keyframes, speed ramp ou mistura de audio profissional "
    "como se existissem.\n"
    "REGRAS DURAS:\n"
    "- Nunca inventes ferramentas, parametros, caminhos, URLs, comandos, "
    "codigo, percentagens, cores, duracoes, resolucoes ou contagens que nao "
    "estejam no estado ou na resposta base.\n"
    "- Se nao tens o dado, diz o que falta em vez de adivinhar (selector de "
    "texto, tempo, idioma para traduzir, respostas da entrevista).\n"
    "- Responde SO com o texto da resposta, sem markdown, sem aspas extra."
)


def _interview_hint(needed: list[str] | None) -> str:
    if not needed:
        return "não falta nenhum dado"
    names = {"style": "estilo", "duration_s": "duração", "aspect": "formato", "brief": "tema"}
    return "falta: " + ", ".join(names.get(n, n) for n in needed)


class SparkChatAssistant:
    """One-shot PT-AO conversation from the real project snapshot.

    Exactly one POST per call, no retries. The endpoint owns intent/pending
    decisions; this assistant only phrases the resolved turn with the real
    application context and recent chat history.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise MissingCredentialsError("MODEL_API_KEY is required (server-side only).")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive.")
        self._api_key = api_key.strip()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
            follow_redirects=False,
        )
        self.last_usage: ChatUsage | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def rewrite_reply(
        self,
        *,
        message: str,
        base_reply: str,
        intent: str,
        has_clip: bool,
        interview_needed: list[str] | None = None,
        context: str | None = None,
        history: list[dict] | None = None,
        authorization: LiveCallAuthorization | None = None,
    ) -> tuple[str, ChatUsage]:
        """Answer one turn from the resolved payload + real snapshot."""
        if not isinstance(authorization, LiveCallAuthorization):
            raise LiveCallNotAuthorizedError(
                "A valid LiveCallAuthorization is required before a live chat request. "
                "No request was attempted."
            )
        clean_message = message.strip()
        clean_base = base_reply.strip()
        if not clean_message or not clean_base:
            raise ValueError("message and base_reply must be non-empty.")

        parts = [
            f"Contexto rápido: {'com clipe carregado' if has_clip else 'sem clipe (plataforma vazia)'}; "
            f"intenção decidida: {intent}; {_interview_hint(interview_needed)}."
        ]
        clean_context = (context or "").strip()
        if clean_context:
            parts.append("ESTADO REAL (factos verificados):\n" + clean_context[:5000])
        if history:
            lines = []
            for item in history[-6:]:
                text = " ".join(str(item.get("text", "")).strip().split())[:300]
                if not text:
                    continue
                role = "Tu" if item.get("role") == "user" else "Muse"
                lines.append(f"{role}: {text}")
            if lines:
                parts.append("Conversa recente:\n" + "\n".join(lines))
        parts.append(f"Mensagem do utilizador: {clean_message[:1000]}")
        parts.append(f"Resposta base (sentido obrigatório): {clean_base[:1000]}")
        parts.append(
            "Responde ao utilizador em PT-AO natural a partir do estado e da resposta "
            "base. Não alteres intenções, pendentes, ferramentas nem factos."
        )
        user_content = "\n\n".join(parts)
        payload = {
            "model": self._model,
            "reasoning_effort": DEFAULT_REASONING_EFFORT,
            "messages": [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "max_completion_tokens": self._max_output_tokens,
        }
        authorization.reserve()
        try:
            response = self._client.post(
                CHAT_COMPLETIONS_PATH,
                headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ChatTimeoutError(f"Chat timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ChatError(f"Could not reach the chat service: {exc}") from exc
        if response.status_code == 429:
            raise ChatRateLimitedError(
                "Chat is rate limited.", retry_after=response.headers.get("Retry-After")
            )
        if response.status_code >= 400:
            raise ChatAPIError(response.status_code, f"Chat failed with HTTP {response.status_code}.")
        try:
            body: dict[str, Any] = response.json()
            msg = body["choices"][0]["message"]
            if msg.get("tool_calls"):
                raise ChatValidationError("Chat returned tool calls; plain text only.")
            content = msg.get("content")
            usage = body.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ChatAPIError(502, "Chat response was not usable.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ChatAPIError(502, "Chat response contained no text.")
        reply = " ".join(content.strip().split())[:1000]
        if not reply:
            raise ChatAPIError(502, "Chat response contained no text.")
        in_tokens = int(usage.get("prompt_tokens", 0) or 0)
        out_tokens = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or (in_tokens + out_tokens))
        cost = round(in_tokens * INPUT_USD_PER_M / 1_000_000 + out_tokens * OUTPUT_USD_PER_M / 1_000_000, 6)
        self.last_usage = ChatUsage(
            prompt_tokens=in_tokens, completion_tokens=out_tokens, total_tokens=total, cost_usd=cost
        )
        logger.info("chat_ok intent=%s in=%d out=%d cost=%.6f", intent, in_tokens, out_tokens, cost)
        return reply, self.last_usage
