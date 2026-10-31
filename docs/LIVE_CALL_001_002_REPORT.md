# LIVE-CALL 001 + 002 — Muse Spark Director (Contributor Medium)

Status: **EXECUTED, both failed server-side. BILLING CORRECTION PENDING — see "Billing reconciliation" below. No further calls without fresh approval + schema review.**

## Call log

| Call | Approval | Request | Response | Billed |
|---|---|---|---|---|
| LIVE-CALL 001 | 6B-LIVE approval | 1 POST, `muse-spark-1.3-contributor`, `reasoning_effort: medium`, `max_completion_tokens: 1500` | HTTP 500 `internal server error` | **UNKNOWN — see reconciliation. The $0.00 originally reported here was wrong.** |
| LIVE-CALL 002 (RETRY 1) | Retry approval, same payload | 1 POST, identical payload | HTTP 500 `internal server error` | **UNKNOWN — see reconciliation.** |

Total external POSTs across both approvals: **2** (1 per approval, never more).

## What was sent (identical both calls, no key)

- Endpoint: `POST https://api.meta.ai/v1/chat/completions`
- Model: `muse-spark-1.3-contributor` (exact id enforced; Standard rejected)
- `reasoning_effort: medium`, `max_completion_tokens: 1500`
- `response_format: {type: json_schema, name: ProfessionalEditingPlan, strict: false}` (~8.4 KB schema, 16 `$defs`)
- Developer message: playbook v1.1 (10,294 chars) + capability registry summary (1,568 chars) → 12,234 chars (~3,058 est tokens)
- User message (631 chars, ~157 est): confirmed transcript "Keep me sharp, blur the people behind me and replace the background with a cinematic Luanda sunset." + benchmark-unit video metadata (1280×720 @ 30fps, 10.0s, 300 frames, audio present) + verbatim `request_id` + `raw_instruction` + ambiguity/unsupported rules
- No `tools`, no web search, no audio bytes, no `text.format`, no `previous_response_id`

## What was received

- LIVE-CALL 001: `finish_reason` n/a (no `choices` parsed) — HTTP 500, client-safe message `internal server error`. No plan type. No `usage` in the response body.
- LIVE-CALL 002: identical HTTP 500.

## Billing reconciliation (correction of the earlier $0.00 claim)

The original version of this report stated **$0.00 real cost** for both calls on the theory that "failed requests are not billed". That was an error: the "failed requests are not billed" rule comes from the **Muse Voice Transcribe** documentation (transcription of audio that fails before producing a transcript, and 429s, are not billed). It was wrongly generalized to **Muse Spark Chat Completions**, for which no such guarantee was verified — the verified Spark docs say only that token usage counts input/output tokens, with no failed-request exemption.

What the Meta panel (source of truth) shows takes precedence over any local inference. Local facts constraining the reconciliation:

- The script never captured `usage`: on HTTP ≥ 400 the provider raises before parsing any body, and neither call wrote a result file. No local token counts exist for either call.
- The script never captured a server correlation id: the provider only read the `Retry-After` header (429 path). `x-request-id` is now captured into `DirectorAPIError.server_request_id` for future runs, but retroactively both calls have **no server request id on file**.
- What IS known locally and bounds the maximum: the request payload was byte-identical both times — developer message 12,234 chars + user message 631 chars = 12,865 chars (~3,215 heuristic tokens in). At Contributor rates ($0.10/1M in), the input side caps at ≈ $0.00032 per call even if the full prompt was metered. Output side is unknowable locally (no `usage`, no completion observed).
- Heuristic vs cap (unchanged): reference valid plan ~3,659 chars (~914 est out); cap 1500 out would have been ≈ $0.00062 at Contributor rates had it succeeded.

**Reconciliation table (panel figures to be filled by the user — Meta panel is source of truth):**

| Call | Panel cost (USD) | Panel input tokens | Panel output tokens |
|---|---|---|---|
| LIVE-CALL 001 | _pending user_ | _pending user_ | _pending user_ |
| LIVE-CALL 002 | _pending user_ | _pending user_ | _pending user_ |
| **Total billed** | **_pending user_** | — | — |
| **Budget remaining ($30 − total)** | **_pending user_** | — | — |

Until those figures arrive, the honest statement is: **billed cost is UNKNOWN, bounded above by ≈ $0.00064 total** (two input sides at ~3,215 tokens; output unknown but no completion was delivered to us).

## Validation performed

- Pydantic validation: n/a (no content returned; nothing to validate — correctly treated as failure, not success).
- Registry validation: n/a for the same reason.
- Heuristic vs cap: prompt ~3,215 est tokens in (chars/4), cap 1500 out, reference valid plan ~3,659 chars (~914 est out). Had the cap been hit at Contributor rates ($0.10/1M in, $0.20/1M out), cost would have been ≈ $0.00062 (0.062¢, ~0.002% of $30). Actual billed cost: **see Billing reconciliation above — $0.00 claim withdrawn**.

## Assessment

The repeat 500 on a byte-identical payload points away from a transient fault and toward the request itself. Prime suspect: the structured-output schema (16 `$defs`, ~8.4 KB, discriminated unions, pattern constraints) exceeding a server-side limit, or a Contributor-tier serving issue for structured output on this model. The provider behaved exactly as designed (single POST, safe error mapping, no retry, no key/audio logging, no result file).

Next step (requires fresh explicit approval): schema-reduction proposal — e.g. a minimal plan schema round-trip test, smaller `max_completion_tokens`, or plain-JSON (non-constrained) control call to isolate schema vs model vs tier. No call will be made until that approval exists.

## Billing reconciliation note (added post-run)

The $0.00 figure originally reported here was withdrawn: it wrongly generalized the Muse Voice Transcribe "failed requests are not billed" rule to Spark Chat Completions, where no such exemption is documented. The provider/script captured no `usage` and no `x-request-id` on the 500 path (fixed afterwards: `DirectorAPIError.server_request_id` + failure-context print). The Meta panel is the source of truth; reconciliation table above awaits the user's panel figures.
