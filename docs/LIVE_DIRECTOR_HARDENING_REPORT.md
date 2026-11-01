# 6B-LIVE-HARDENING — Director Reliability, ID Normalisation & Cost Audit

**Date:** 2026-11-01
**Status:** Implementation complete; **no live call made in this milestone**.
**Meta budget available:** **$31.78**.
**Tests:** 212 backend tests passing; 50 targeted director/lite/worker tests; `scripts/check.ps1`
exits 0 (pytest + frontend typecheck + production build).

## 1. Why this milestone

A live user test exposed two reliability gaps:

1. **Operation-id rejection.** Job `0563760dec3444fd86fb797880187e46` received an otherwise
   valid lite plan with model-generated ids `op1_isolate`, `op2_blur`, `op3_audio`,
   `op4_render`, `op5_verify`. The internal `LiteOperation` pattern
   `^op_[a-z0-9_]{1,40}$` rejected the plan before conversion.
2. **Lost cost audit.** Because validation failed, `director_usage` and
   `director_request_id` were not persisted. The failure path kept only the `JobError`,
   creating a cost-reconciliation gap.

The raw model response was not stored. The regression fixture recreates the exact reported
operation-id pattern on an otherwise valid mock plan; no missing fields were invented. The
historical job record was not modified.

## 2. Operation-id normalisation

Implemented in `packages/contracts/clipforge_contracts/director_lite.py`.

- The lite wire accepts a non-empty model-generated id (max 80 chars).
- `normalize_lite_operation_ids()` assigns `op_1`…`op_n` in **original operation order**.
- It returns the complete **original → canonical map**; `lite_to_full_plan_with_mapping()`
  exposes it to callers/tests.
- All dependency references are rewritten through the same map.
- The conversion rejects:
  - duplicate original ids;
  - unknown dependency targets;
  - dependency cycles;
  - forward dependencies (a dependency must appear earlier).
- Capability ids, params, titles, explanations, expected outputs and operation order are
  unchanged.
- The strict `DirectorOperation` pattern remains in force; validation is not weakened.
- EDL decisions are projected only from the canonical plan, so every `provenance_hash` is
  recomputed over canonical ids. Tests verify every decision hash.

## 3. Director audit record

New contract: `packages/contracts/clipforge_contracts/director_audit.py`.

| Field | Meaning |
|---|---|
| `job_id` | Populated by the worker before persistence |
| `request_id` | Client-generated `req_…` used in the prompt |
| `server_request_id` | Meta `x-request-id`, when present |
| `provider`, `model` | Actual provider class and model id |
| `execution_mode` | `live` (mock never creates a live audit) |
| `service_mode` | `standard` or `contributor` |
| `wire_schema` | `lite` or `full` |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | Only when supplied by `usage` |
| `estimated_cost_usd` | Calculated from actual token usage and published rates |
| `actual_cost_usd` | Only when reliably available; currently `null` (Meta panel is source of truth) |
| `validation_status` | `accepted`, `rejected`, `error`, `not_attempted` |
| `error_category`, `error_code` | Stable category plus exception class |
| `http_status`, `finish_reason` | When available |
| `recorded_at` | UTC timestamp |

Provider lifecycle:

- The audit is created **before** the HTTP request.
- Transport/timeout/429/HTTP errors update the audit before raising.
- Usage is recorded **before** plan validation; truncated/rejected 200 responses still carry
  token and cost estimates.
- Successful validation marks the audit `accepted`; content/validation failures mark it
  `rejected` with a specific category (`truncated`, `invalid_json`, `validation`,
  `request_id_mismatch`, etc.).

Worker persistence:

- `_capture_director_metadata()` runs immediately after the call on success **and** failure.
- `JobResult.director_audit` is written to `job.json`, together with `director_usage` and
  `director_request_id`.
- A failed job therefore retains the audit; `/api/jobs/{id}/result` remains completed-only.
- Job result responses use `model_dump(mode="json")` so the audit timestamp/enums serialise.

## 4. Tests added

Normalisation (`tests/test_director_lite.py`):

- `op1_isolate`… → `op_1`… in order, with dependency rewriting.
- Already-canonical ids remain stable.
- Mixed naming formats normalise deterministically.
- Duplicate original ids rejected.
- Unknown dependency target rejected.
- Dependency cycle rejected.
- Forward dependency rejected.
- Invalid capability id rejected.
- Invalid operation parameters rejected.
- Full v2 contract still rejects non-canonical ids.
- Capability ids/params/execution intent preserved.
- Provenance hashes recomputed and verified.
- Provider roundtrip with the real rejected pattern (`op1_…`) accepted and audited.

Audit (`tests/test_director_spark.py`, `tests/test_director_lite.py`):

- Success audit records request/server ids, provider/model, modes, tokens, estimated cost,
  status, HTTP, finish reason; actual cost is null.
- Validation failure audit records tokens/cost/category/HTTP/finish reason.
- HTTP 500 audit records status/category/server request id and no invented tokens.
- Timeout audit records category without HTTP status.
- Missing usage yields null token/cost fields, not fabricated zeros.
- Lite provider audit records `wire_schema="lite"` and `service_mode="contributor"`.

Worker/API (`tests/test_live_director.py`, `tests/test_api_jobs.py`):

- Successful live-director job persists `director_audit` with the job id.
- Rejected plan fails the job, writes no output, and persists the audit + usage + request id.
- `/api/jobs/{id}/result` serialises the audit datetime/enums as JSON.

## 5. Cost status and proposed retest

No live call was made; this milestone cost **$0.00**. Meta budget available: **$31.78**.

A single plan-only retest is still blocked on explicit approval. Using the production
Contributor path (full playbook, lite schema, medium effort, cap 16,000):

| Item | Estimate |
|---|---|
| Input tokens | ~2,800–3,000 (playbook + lite registry summary + transcript/metadata) |
| Expected output tokens | ~1,900–2,200 |
| Expected cost (Contributor) | **~$0.00066–$0.00074** |
| Worst case at 16,000 completion cap | **~$0.0035** |
| Expected cost (Standard) | ~$0.0116–$0.0129 |
| Worst case at 16,000 completion cap (Standard) | ~$0.0715 |

Data transmitted would be the confirmed transcript text, video metadata (dimensions, fps,
duration, frame count, audio presence), request id/raw instruction and the playbook/registry
summary. No audio bytes, video bytes, tools, web search or credentials are sent. The model
would only return a plan; it would not execute tools or render.

## 6. Remaining limitations

- Actual billed cost is still external; the audit stores an estimate from usage.
- Failed-job audit is in `job.json`; the public `/result` endpoint remains completed-only.
- Approval/resume UI/endpoint is still missing.
- SAM 3.1 and Muse Image are not integrated.
- No live retest has been performed after the normalisation fix; that requires fresh approval.

## 7. Files changed

- `packages/contracts/clipforge_contracts/director_audit.py` (new)
- `packages/contracts/clipforge_contracts/director_lite.py`
- `packages/contracts/clipforge_contracts/__init__.py`
- `packages/director/clipforge_director/spark.py`
- `packages/jobs/clipforge_jobs/models.py`
- `apps/worker/clipforge_worker/processor.py`
- `apps/api/clipforge_api/main.py`
- `tests/test_director_lite.py`
- `tests/test_director_spark.py`
- `tests/test_live_director.py`
- `tests/test_api_jobs.py`
- `docs/API_CONTRACTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` (ADR-016),
  `docs/STATUS.md`, `docs/TASKS.md`, `README.md`

## 8. Zero external calls during implementation

All tests use `httpx.MockTransport` or in-process fakes. No request reached Meta during the
implementation/test phase. No SAM, Muse Image, FFmpeg or renderer call was made by the director.

## 9. Follow-up — approved live retest (same day)

The user approved one real execution. It was run as a full E2E rather than plan-only:

- User portrait clip 360×640, 30 FPS, 6.177 s, audio; source untouched.
- Live ASR: 5.440 s, **$0.000272**.
- Muse Spark: 5-operation plan, 2,792 in / 2,293 out, **$0.000738**, request
  `req_03bff7ae260f`, server id `6096b398-7ce7-46ba-b4bf-c7a693cabbe7`.
- Audit persisted and verified: `accepted`, HTTP 200, `finish_reason=stop`,
  `actual_cost_usd=null`.
- Render: 360×640, 30 FPS, 177 frames, 6.177007 s, 166,088 bytes, audio preserved.
- Output saved in the user's `Videos\Video` folder. Run total: **$0.001010**.
- Limitation confirmed: the mock segmentation ellipse kept one side subject sharp at a
  time, not both. Real subject tracking still requires SAM 3.1 or a manual mask.

Full log: `docs/LIVE_E2E_006_USER_VIDEO_REPORT.md`.

## 10. Mock verification for the hardening spec

- Explicit mock env confirmed: `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=mock`,
  `CLIPFORGE_DIRECTOR_MODE=mock`; `get_providers()` returned mock/mock/mock with
  `MockProfessionalEditingDirector`.
- Full suite: **212 passed**; `scripts/check.ps1` exit 0 (backend + typecheck + production build).
- Browser smoke: page loaded with all five areas and **MOCK TRANSCRIPTION**; zero console errors.
- Ledger: `transcription=3`, `director=2`; no `.lock` or `.tmp` artifacts.
- LIVE-CALL 006 plan-only request prepared, **not executed**:
  `scripts/prepare_live_call_006.py`, `docs/LIVE_CALL_006_PROPOSAL.md`, and exact payloads in
  `storage/live_call_006_request_standard.json` / `..._contributor.json`.
- No external API request was made by the preparation or mock verification.
