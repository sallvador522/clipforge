# LIVE-CALL 003 — Lite Schema (Contributor Medium)

Status: **EXECUTED — HTTP 200, output truncated at the 800-token cap. No plan accepted, no retry.**

## What was sent (exactly 1 POST)

- `POST https://api.meta.ai/v1/chat/completions`
- Model `muse-spark-1.3-contributor` (exact id), `reasoning_effort: medium`, `max_completion_tokens: 800`
- `response_format`: hand-written `ProfessionalEditingPlanLite` (1,948 bytes, 0 `$ref`s, depth < 6, <100 props), `strict: false`
- Developer message 1,987 chars (~496 est tokens) = abridged brief + essential registry summary
- User message 631 chars (~157 est tokens) = approved transcript + benchmark-unit metadata + request_id/raw_instruction
- Total message chars 2,618 (~654 est tokens); full payload JSON 4,899 chars
- No tools, no audio, no web search, no `text.format`, no `previous_response_id`. Key never printed/logged.

## What was received

- **HTTP 200** (the request was accepted — the 500s are gone) with `finish_reason: "length"`.
- Content was therefore a partial JSON document; the provider rejected it as a truncation validation failure. No plan, no EDL, no render.
- **No `x-request-id` on file** and **no local `usage`**: this call ran before the observability fix that now records usage before validation. The panel remains the source of truth for its billed tokens/cost.

## What this proves

- The full v2 schema (~8.4 KB, 16 `$defs`) was the likely cause of the two 500s: the lite schema was accepted immediately by the same model/tier/endpoint.
- The remaining issue is **output budget**, not schema validity or tier access: the compound instruction (blur + replace + cinematic background, 5 operations with explanations) needs more than 800 completion tokens.
- This call is billable (HTTP 200 with generation), unlike an HTTP 500. Local cost is unknown but bounded: prompt ~650–1,000 tokens, completion capped at 800 → at Contributor rates ($0.10/1M in, $0.20/1M out) **≤ ≈ $0.00026**; a realistic estimate is **≈ $0.0002**.

## Observability fix applied after the call (no new call)

- `usage` is now recorded **before** validation, so truncated/200-invalid responses still feed token accounting (`last_usage`).
- `DirectorValidationError` now carries `server_request_id` from `x-request-id`, including truncation, tool-call, empty-content and schema-mismatch failures.
- `scripts/live_call_003_spark_lite.py` prints structured failure context (status/error/server_request_id/usage) without writing a result file, preserving the exactly-once guard.
- New test: truncated 200 with usage + `x-request-id` is captured; cost computed at the correct pricing mode.

## Validation performed

- Pydantic: `LitePlan` parse never ran to success (finish_reason=length rejected first, by design). No partial plan accepted.
- Registry: not reached (nothing executable).
- Test suite: **183 passed** (5 lite tests + new truncation-accounting test).

## Cost ledger (panel is source of truth)

| Call | HTTP | Plan | Billed locally known? |
|---|---|---|---|
| 001 | 500 | none | unknown (panel) |
| 002 | 500 | none | unknown (panel) |
| 003 | 200, truncated | none | unknown locally (pre-fix); bounded ≤ ≈ $0.00026, realistic ≈ $0.0002 |

## Recommendation

Next step should be **one approved retry of the same lite payload with `max_completion_tokens: 1500`** (schema now proven acceptable; only the output budget failed). Alternative smaller-blast-radius options: 1200-token cap, or explicitly instruct fewer/shorter operation explanations. A plain-JSON control is no longer the priority — the 200 already exonerated the schema.
