# LIVE-CALL 004 — Lite Schema, 1500-token cap (Contributor Medium)

Status: **EXECUTED — HTTP 200, `finish_reason: "length"` at 1500 tokens. No plan accepted. No retry.**

## What was sent (exactly 1 POST)

Same payload as LIVE-CALL 003, only the cap changed:

- `POST https://api.meta.ai/v1/chat/completions`
- `muse-spark-1.3-contributor`, `reasoning_effort: medium`, `max_completion_tokens: 1500`
- Wire schema `ProfessionalEditingPlanLite` (1,948 bytes, 0 `$ref`s)
- Developer 1,987 chars + user 631 chars (2,618 chars, ~654 est tokens); payload 4,899 chars
- No tools, no audio, no web search. Key never printed.

## What was received

- **HTTP 200**, `x-request-id: 134244ba-83c9-4721-95ae-a5677de9c34c`
- `finish_reason: "length"` → output still hit the cap; partial JSON rejected by design. No plan, no EDL, no render.
- **Real usage (first call with working accounting):**
  - `prompt_tokens: 951`
  - `completion_tokens: 1500` (cap reached)
  - `total_tokens: 2451`
  - **cost: $0.000395** at Contributor rates ($0.10/1M in + $0.20/1M out), i.e. **~0.0013% of $30**

## Interpretation

- The request is accepted (no 500) and the model is generating; **1500 tokens are still not enough**.
- Likely cause: Muse Spark is a reasoning model — reasoning tokens count inside the completion budget, and medium effort plus a 5-operation plan with explanations can exceed 1500. The lite schema itself is proven acceptable (two consecutive HTTP 200s).
- This gives a reliable local number for 003's lost usage: prompt ≈951, completion capped at 800 → ≈ $0.000255 (bounded ≤ $0.00026), consistent with the earlier estimate.

## Cost ledger so far (Contributor rates)

| Call | HTTP | Plan | Prompt tok | Completion tok | Cost |
|---|---|---|---|---|---|
| 001 | 500 | none | unknown | unknown | panel (unknown) |
| 002 | 500 | none | unknown | unknown | panel (unknown) |
| 003 | 200 truncated @800 | none | ~951 (inferred) | 800 (cap) | ~$0.000255 (inferred) |
| 004 | 200 truncated @1500 | none | 951 (measured) | 1500 (cap) | **$0.000395 (measured)** |

Panel remains source of truth for 001/002.

## Options for the next approval (not executed)

1. **Same call, cap 3000** — likely enough headroom; at Contributor rates ≤ ≈ $0.00075 if it hits the cap again.
2. **`reasoning_effort: "low"` + cap 2000** — reasoning consumes less budget, cheaper (~$0.0005 cap), but slightly less planning depth.
3. **Shorten the plan requirement** (fewer explanatory fields / 3 operations) — lowers output size without touching the schema, but changes the product output.

Recommendation: option 1 first (prove a complete plan exists), then tune effort downward for cost once a valid plan is seen. Plain-JSON control is unnecessary — the schema is already accepted.
