# LIVE-CALL 001 + 002 — Muse Spark Director (Contributor Medium)

Status: **EXECUTED, both failed server-side. No further calls without fresh approval + schema review.**

## Call log

| Call | Approval | Request | Response | Billed |
|---|---|---|---|---|
| LIVE-CALL 001 | 6B-LIVE approval | 1 POST, `muse-spark-1.3-contributor`, `reasoning_effort: medium`, `max_completion_tokens: 1500` | HTTP 500 `internal server error` | No (no `usage` returned; failed requests are not billed) |
| LIVE-CALL 002 (RETRY 1) | Retry approval, same payload | 1 POST, identical payload | HTTP 500 `internal server error` | No (same reason) |

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

- LIVE-CALL 001: `finish_reason` n/a (no `choices` parsed) — HTTP 500, client-safe message `internal server error`. No plan type. No `usage`, so no cost to compute: **$0.00 real cost**.
- LIVE-CALL 002: identical HTTP 500. **$0.00 real cost.**

## Validation performed

- Pydantic validation: n/a (no content returned; nothing to validate — correctly treated as failure, not success).
- Registry validation: n/a for the same reason.
- Heuristic vs cap: prompt ~3,215 est tokens in (chars/4), cap 1500 out, reference valid plan ~3,659 chars (~914 est out). Had the cap been hit at Contributor rates ($0.10/1M in, $0.20/1M out), cost would have been ≈ $0.00062 (0.062¢, ~0.002% of $30). Actual billed cost: **$0.00**.

## Assessment

The repeat 500 on a byte-identical payload points away from a transient fault and toward the request itself. Prime suspect: the structured-output schema (16 `$defs`, ~8.4 KB, discriminated unions, pattern constraints) exceeding a server-side limit, or a Contributor-tier serving issue for structured output on this model. The provider behaved exactly as designed (single POST, safe error mapping, no retry, no key/audio logging, no result file).

Next step (requires fresh explicit approval): schema-reduction proposal — e.g. a minimal plan schema round-trip test, smaller `max_completion_tokens`, or plain-JSON (non-constrained) control call to isolate schema vs model vs tier. No call will be made until that approval exists.
