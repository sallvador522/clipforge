# ClipForge — Architecture Decision Records

Decisions are never silently changed. Superseding a decision requires a new ADR referencing the old one.

## ADR-001: Hosted SAM 3.1 via Meta Model API
- **Status:** Approved (integration deferred, see ADR-004).
- **Decision:** Subject segmentation/tracking will use SAM 3.1 through Meta hosted inference, accessed only from server-side code with a Bearer API key held server-side. A dedicated SAM provider adapter isolates the integration so it can change without rewriting the video pipeline.
- **Consequences:** The Python worker must NOT download, install, or host SAM checkpoints. No PyTorch, CUDA, or local SAM inference dependencies. The worker prepares input video, submits segmentation requests, decodes results into the internal mask contract (ADR-005), and passes masks to rendering.
- **Uncertainty:** User-supplied integration details (model name, base URL, endpoint) are recorded as unverified. Request/response schema, mask encoding, sync vs async execution, and polling must be confirmed against current official Meta documentation before any live code is written. Until then the live adapter is an explicit placeholder.

## ADR-002: FFmpeg + OpenCV Python Video Stack
- **Status:** Approved.
- **Decision:** Python worker uses FFmpeg for video decoding, normalization, audio preservation, encoding and final export; OpenCV for frame processing, mask operations, compositing, and visual transformations.
- **Consequences:** Rendering is CPU-based; no GPU/CUDA infrastructure unless profiling demonstrates necessity (ADR-006). Original video/audio preserved until output is verified.

## ADR-003: MediaBunny Excluded from MVP
- **Status:** Approved.
- **Decision:** MediaBunny (including `@mediabunny/server`) is removed from the MVP architecture and must not be installed.
- **Consequences:** All media processing is Python FFmpeg + OpenCV. MediaBunny may only be reconsidered when a clearly justified browser-side media processing requirement appears, via a new ADR.

## ADR-004: Mock-First Development
- **Status:** Approved. Mandatory.
- **Context:** Remaining external AI API budget is ~$30. The entire application must be completed and validated without consuming external AI credits.
- **Decision:** All AI functionality is implemented with deterministic local mocks and fixtures behind typed provider interfaces (`TranscriptionProvider`, `EditingPlannerProvider`, `SegmentationProvider`, `BackgroundGenerationProvider`), each with a deterministic mock, an unimplemented live placeholder, and a shared normalized internal contract. Default configuration is `CLIPFORGE_AI_MODE=mock`. Rendering is never mocked.
- **Consequences:** Mock mode makes zero external requests (verified by tests), needs no credentials, never silently falls back to live, and uses deterministic fixtures for repeatable tests. Live mode requires an explicit configuration change plus explicit user approval.
- **Live integration gate:** Real providers are activated only after frontend, backend, mocks end-to-end, FFmpeg/OpenCV rendering, error handling, automated tests, and documentation are complete; then official docs (schemas, media inputs, mask encoding, sync/async, polling, rate limits, pricing) are verified, and a single controlled integration test is proposed. No automatic retries that could cause billable requests; request logging, idempotency where supported, and application-level budget tracking are required for live mode.

## ADR-005: PNG Mask Sequence + manifest.json
- **Status:** Approved.
- **Decision:** Canonical internal mask representation is one lossless 8-bit grayscale PNG per frame (`frame_%06d.png`, 0=background, 255=subject, intermediate=soft alpha/confidence) plus `manifest.json` recording video dimensions, frame count, FPS, frame timestamps or the derivation rule `timestamp_ms = round(index * 1000 / fps)`, subject identifier, mask encoding, filenames/frame indices, and source video identifier or hash. Never lossy JPEG for masks.
- **Consequences:** A mask writer and validating loader are implemented in the worker. The loader rejects missing frames, invalid files, wrong dimensions (never silently resized), unexpected indices, and corrupt masks; both binary and grayscale masks are accepted. Explicit resize, when necessary, uses nearest-neighbour only. Edge smoothing is applied separately during rendering, never in the loader. No alternative format (FFV1, packed arrays) until profiling demonstrates a concrete need.

## ADR-006: CPU Rendering Performance
- **Status:** Approved.
- **Decision:** CPU rendering is mandatory. No processing times are promised before benchmarks. The benchmark unit is 300 frames, 1280x720, 30 FPS, 10-second source, measured independently for background blur and background replacement, capturing: total processing time, FPS, peak RAM, CPU usage, output file size, audio synchronization, frame integrity. Test machine specifications are recorded with measurements.
- **Consequences:** Implementation starts with sequential frame processing and bounded memory. Bounded frame pipelining, parallel processing, downscale-blur, and other optimizations are introduced only after profiling, and never by sacrificing mask correctness or visual quality without measuring the trade-off.

## ADR-007: Synthetic Testing Limitations
- **Status:** Approved. Limitation accepted for MVP.
- **Decision:** Mock segmentation uses deterministic synthetic fixtures covering: static subject, moving subject, multiple subjects crossing, partial occlusion, missing masks, mask holes, irregular edges, temporal mask jitter, and different foreground/background lighting conditions.
- **Consequences:** These fixtures validate the rendering pipeline and mask-handling behaviour, **not** real SAM tracking quality. This limitation is accepted. Where suitable licensed footage is available, at least one real-world video with manually prepared masks should be added; this must not trigger any AI API request.

## ADR-008: Transcription Is the First Live-Capable Provider
- **Status:** Approved (Milestone 6A). No live calls performed yet.
- **Context:** Muse Voice Transcribe is available through Meta Model API with a verified file endpoint, schema and pricing. The remaining budget is ~$30, so live inference must be tightly scoped and explicitly approved.
- **Decision:** Transcription gains a real provider (`MetaVoiceTranscriptionProvider`, model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe`, Bearer `MODEL_API_KEY`, multipart `request` JSON + `audio` WAV). It is enabled only by `CLIPFORGE_TRANSCRIBE_MODE=live` plus `MODEL_API_KEY`; `CLIPFORGE_AI_MODE=mock` remains the default and all other providers (planning, segmentation, image generation) remain mocks. The frontend receives real audio from MediaRecorder, the API converts it with FFmpeg to mono 16-bit PCM WAV at 24 kHz, and calls the provider exactly once. The user reviews and edits the transcript before it reaches the planner.
- **Consequences:** No automatic retries of transcription requests (a failed call is reported; retry requires an explicit user action). Timeouts, 429 and API errors have distinct, safe messages. `sessionId` is generated per request and logged; raw audio and the API key are never logged, and temporary audio is deleted after each request. Mock mode never interprets audio: it requires an explicitly selected mock command and labels the transcript simulated. The first live request requires a reviewed cost estimate and explicit user approval.

## ADR-009: Professional Editing Director Architecture
- **Status:** Approved (Milestone 6B-PREP). No live model integration.
- **Context:** ClipForge needs professional editing intelligence that understands intent, plans with real tools, explains decisions and verifies results. The previous mock planner mapped phrases into a minimal v1 `EditingPlan`; there was no capability registry, approval concept or truthful director stage model.
- **Decision:**
  - **Capability registry** in `packages/contracts` is the single authority. Statuses are `available_mock`, `available_local`, `available_live`, `planned`, `disabled`. Local FFmpeg/OpenCV work is `available_local` (never described as live AI); mock segmentation is `available_mock` and explicitly not SAM; local/mock background assets are not Muse Image.
  - **Dual contracts:** v1 `EditingPlan` remains the worker execution contract, untouched. v2 `ProfessionalEditingPlan` adds request id, interpretation, subject strategy, typed capability operations, dependencies, providers, stages, expected results, verification, explanations, clarification and approval. A validated `to_execution_plan()` adapter bridges v2 to v1. Model output can never contain paths, shell commands or arbitrary parameters.
  - **Mock director** is implemented independently from the worker (`packages/director`), deterministic and offline. It is not wired into execution in this milestone.
  - **Runtime playbook** (`apps/api/clipforge_api/prompts/professional_editing_director.md`) is versioned system-instruction content for the future Muse Spark integration, loaded by a validating loader. The **development skill** (`.opencode/skills/clipforge-editing-director`) guides the coding agent only and is never sent to the runtime model.
  - **Transparency:** ten validated director stages prepare truthful progress; approval, rejection, cancellation and revisions are contracts/documentation only until a plan actually gates execution.
- **Consequences:** Muse Spark can be integrated later by loading the playbook and registry, emitting v2 plans, validating and adapting to v1 for execution. Unsupported capabilities cannot be invented. No live model, SAM or image generation call is made in this milestone; the worker and renderer are unchanged.

## ADR-010: Video-Use Methodology Adaptation (6B-PREP-R)
- **Status:** Approved. Read-only audit of browser-use/video-use at pinned commit `43cfc56`.
- **Context:** The upstream skill is a coding-agent editing workstation with shell access, segment pipelines and hosted ElevenLabs transcription. ClipForge is a hosted web app with a capability registry, typed contracts and local rendering.
- **Decision:**
  - Adapt methodology only: audio-first reasoning, bounded on-demand visuals, Ask → Confirm → Execute → Iterate (max 3) → Persist, declarative EDL, objective self-evaluation with explicit human review.
  - Reject execution model: no segment extract/concat, no subtitle/fade/cut-boundary rules, no invented tools or raw FFmpeg strings, no ElevenLabs, no animation engines, no new dependencies.
  - EDL v2 is a projection of ready v2 plans with capability-typed params, registry-resolved handlers, timing forbidden while `timeline.trim` is disabled, and canonical provenance hashes.
  - Evaluation separates objective media checks from subjective quality; visual corrections require a new render plus re-inspection.
  - History reuses `job.json` via immutable `EditHistoryEntry`; no new database, memory service, read API or endpoint.
  - Licensing: MIT text preserved in `LICENSES/video-use-MIT.txt` and attributed in `docs/THIRD_PARTY_NOTICES.md`; no upstream code copied.
- **Consequences:** Spark can later reason with the adapted playbook while staying registry-gated. Timing/segment features remain disabled until their capabilities, handlers and verification exist.

## ADR-011: Muse Spark Director Integration Prep (6B-LIVE, no live call)
- **Status:** Prepared, NOT live-tested. No request sent; no approval granted yet.
- **Context:** Muse Spark 1.3 is verified on Model API (`muse-spark-1.3`, base `https://api.meta.ai/v1`, Bearer `MODEL_API_KEY`, Standard mode $1.25/1M in + $4.25/1M out). ClipForge needs plan generation only for the first test — no tool execution, rendering, SAM, image or audio input.
- **Decision:**
  - **Protocol: Chat Completions** (`POST /v1/chat/completions`), not Responses API. Single-turn plan generation needs no reasoning replay or server-managed history; structured output via `response_format` (`json_schema`, Pydantic-derived, `strict: false`) has a documented guaranteed-conformance contract; stateless with no `store`/`previous_response_id`. Responses `text.format` must never be sent here.
  - **Provider:** `MetaEditingDirectorProvider` (`packages/director/.../spark.py`) loads the v1.1 playbook + registry summary, takes the confirmed transcript text plus registered video metadata, emits one validated v2 plan. No `tools` are sent (plan generation only), no web search, no audio bytes, Standard model only (Contributor variants rejected).
  - **Security:** Pydantic + registry validation, capability/param match, dependency order, approval rules, echo enforcement (`request_id`, `raw_instruction`), truncation/tool-call rejection, safe error mapping, single POST, no retries, key never logged.
  - **Accounting:** `usage.{prompt,completion,total}_tokens` → cost at Standard rates; rough pre-request size estimate (`estimate_tokens`, chars/4, not a billing figure).
- **Consequences:** The first live call remains blocked on explicit approval of the measured proposal. All other providers stay mock; the worker, renderer and UI are unchanged.

## ADR-012: First Live Director Call — Contributor Medium (6B-LIVE LIVE-CALL 001)
- **Status:** EXECUTED twice (LIVE-CALL 001 + 002 RETRY 1, same payload) — both returned HTTP 500 `internal server error`. NO further calls without fresh approval + schema review. Full log: `docs/LIVE_CALL_001_002_REPORT.md`.
- **Context:** ADR-011 prepared a Standard-mode provider. The approved live call uses the Contributor variant with medium reasoning effort: model id `muse-spark-1.3-contributor` (verified in the Models and Pricing docs fetched the same day), Contributor rates $0.10/1M input + $0.20/1M output (150 RPM / 4M TPM for the Contributor variant row), `reasoning_effort: "medium"` (verified accepted value; `none` is rejected for Spark). There is NO `context`-size parameter in the verified Chat Completions contract — “medium context” is interpreted as the default 1,048,576-token window carrying a ~3.2k-token prompt, and only `reasoning_effort` is sent.
- **Decision:**
  - Model must be exactly `muse-spark-1.3-contributor` (`require_contributor=True`); every other model string, including Standard, is rejected in this mode.
  - Endpoint `POST https://api.meta.ai/v1/chat/completions`, Bearer `MODEL_API_KEY` (canonical env var name per official docs and repo-wide use; no `META_API_KEY` exists anywhere).
  - `response_format` json_schema `ProfessionalEditingPlan` (`strict: false`), `max_completion_tokens: 1500`, no tools, no web search, transcript text + benchmark-unit video metadata only.
  - Accounting at Contributor rates from actual `usage`; cached-token breakdown not modeled.
  - Exactly one POST, no retries; a second call needs fresh approval. Key never printed, logged or committed.
- **Consequences:** Provider gains `require_contributor` and `reasoning_effort` options (defaults preserve Standard-only safety). All other providers stay mock; worker, renderer and UI unchanged.
- **Correction (billing reconciliation):** the "no billed cost on 500" assumption in the 6B-LIVE reports was wrong — it generalized the Muse Voice Transcribe failed-request rule to Spark Chat Completions without documentation. Both calls may have been metered server-side; the Meta panel is source of truth. Provider now captures `x-request-id` into `DirectorAPIError.server_request_id` (non-secret) and the live-call script prints structured failure context without writing result files.

## ADR-013: Lite Plan Schema + LIVE-CALL 003 (Contributor Medium)
- **Status:** EXECUTED — one POST returned **HTTP 200 with `finish_reason: "length"`** at the 800-token cap. No plan accepted; no retry. Full log: `docs/LIVE_CALL_003_REPORT.md`.
- **Context:** LIVE-CALL 001 + 002 returned identical HTTP 500s on the full v2 schema (~8.4 KB, 16 `$defs`). Prime suspect: schema size/shape on the Contributor tier.
- **Decision:**
  - Wire format is hand-written `ProfessionalEditingPlanLite` (zero `$refs`, 1,948 bytes, depth < 6, <100 properties): request id, raw/inferred text, outcome enum, flat subject fields, operations with capability enum (6 executable only) + fixed scalar params, no timing fields at all, approval enum.
  - Abridged developer brief (playbook-derived, ~1.2k chars) + essential-only registry summary (~430 chars); developer message < 8k chars, total payload < 9k chars.
  - Strictness preserved off-wire: response parsed as `LitePlan`, converted to full v2, all registry/dependency/approval validators run, then `to_execution_plan()` adapter available (not executed).
  - Same endpoint/model/reasoning-effort/cap (`muse-spark-1.3-contributor`, `medium`, 1500 → **800** max tokens), no tools/audio/search; single POST, no retries; key never logged.
- **Consequences:** If the lite call succeeds, the schema was the likely 500 cause and the full v2 schema stays server-side-unproven. If it 500s identically, the schema is exonerated and investigation moves to tier/model/payload factors. Either way no further calls without fresh approval.
- **Result (LIVE-CALL 003):** HTTP **200**, `finish_reason: "length"` at 800 tokens → no plan accepted. This exonerates the full schema as the 500 cause (same model/tier/endpoint accepted the lite schema) and isolates the remaining issue to the output budget. Call is billable; local usage was lost pre-fix (bounded ≈ ≤ $0.00026). Observability fixed afterwards: usage recorded before validation; `DirectorValidationError.server_request_id` captured.
- **Result (LIVE-CALL 004, cap 1500):** HTTP **200**, still `finish_reason: "length"`. Real usage captured: 951 prompt + 1500 completion = 2451 tokens, **$0.000395** (Contributor), `x-request-id 134244ba-83c9-4721-95ae-a5677de9c34c`. No plan accepted. Conclusion: schema accepted twice; the cap is still too small (reasoning tokens count inside completion). Next option: cap 3000, or `reasoning_effort: low` + cap 2000. Full log: `docs/LIVE_CALL_004_REPORT.md`.

## ADR-014: Live Director Execution Wiring, Budget Ledger and Approval Gate
- **Status:** Approved and EXECUTED (LIVE-E2E 005). Extends ADR-009/011/012/013; supersedes only the earlier statements that v2 is not wired to execution and that every ready plan auto-executes.
- **Context:** LIVE-CALL 005 produced the first complete v2 plan. ClipForge needed the plan to drive a real edit — not stop at validation — while preserving the v1 execution contract, budget limits and approval rules.
- **Decision:**
  - **Mode selection:** `CLIPFORGE_DIRECTOR_MODE=mock|live` (default `mock`), independent of `CLIPFORGE_AI_MODE=mock`. Live uses `LiteMetaEditingDirectorProvider` with `muse-spark-1.3-contributor`, `reasoning_effort=medium`, cap 16,000, timeout 180 s. Missing `MODEL_API_KEY` fails before any request.
  - **Execution path:** after the confirmed transcript, the live worker calls the director once, validates/converts the lite response to a full v2 plan, applies the v1 adapter and executes the existing real renderer. The v1 `EditingPlan` remains the worker's execution contract; no model-provided paths, commands or arbitrary parameters are accepted. When the director is mocked, the legacy mock planner path is unchanged.
  - **Approval gate:** a plan with `approval_status` `required` or `rejected` completes the job as `awaiting_approval` with `render_status="awaiting_approval"` and **no render**. Clarification/unsupported outcomes complete without segmentation or rendering. There is no approval/resume endpoint or UI yet. **(Superseded in 6C by ADR-018: the review/approval/resume workflow is now implemented.)**
  - **Observability:** `director_plan`, `director_usage` and `director_request_id` are persisted in `JobResult`; the health endpoint reports `director_mode`.
  - **Budget protection:** `storage/live-call-ledger.json` caps live transcription and director calls at 2 each per phase. A reservation is written atomically immediately before the provider network call; an exhausted cap raises `LiveBudgetExceeded` / HTTP 429 `live_budget_exhausted` with zero provider calls. No automatic retries.
  - **Scope:** fixed a real WAV temp-name collision (input `upload{suffix}`, converted output `recording.wav`) that failed before any network call; added regression tests. No SAM, Muse Image, ElevenLabs, new AI provider or renderer change.
- **Evidence (LIVE-E2E 005):** Portuguese audio 3.680 s → transcript → 5-operation plan → real blur render → verified download. ASR $0.000184; director 2,781 in / 1,856 out = $0.000649; total $0.000833. Output 320×180, 10 FPS, 20 frames, 2.000 s, 36,998 bytes, audio preserved. Ledger 1/1. 191 backend tests, frontend typecheck and production build pass; output re-probed and a frame inspected. Full log: `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`.
- **Consequences:** The voice → director → render path is proven for blur. Real subject tracking still requires SAM 3.1 (mock segmentation remains an ellipse), replacement backgrounds remain local/mock, and approval is backend-only. One live call per function remained at the end of the phase; a new phase needs fresh approval and a deliberate ledger reset (see ADR-015 for the user-testing phase).

## ADR-015: Configurable Live-Call Limits for Local Testing
- **Status:** Approved and applied at the user's explicit request (2026-11-01), after the phase-005 cap blocked a UI retry.
- **Context:** ADR-014 fixed each live function at 2 calls. The user used the spare transcription call while testing the UI and hit `429 live_budget_exhausted`. They asked to remove the block so they can test repeatedly.
- **Decision:**
  - **Default safety unchanged:** `DEFAULT_LIMITS` remains 2 transcription + 2 director per phase. A fresh checkout with no overrides keeps the original protection.
  - **Per-function overrides:** `CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT` and `CLIPFORGE_LIVE_DIRECTOR_LIMIT` accept positive integers. Explicit `LiveCallBudget(..., limits={...})` overrides the environment (used by tests). Invalid values fail with a clear `ValueError`.
  - **Ledger unchanged:** the file ledger still reserves atomically immediately before the network call and never resets automatically. Raising a limit does not erase usage history.
  - **Current local test phase:** `.env` sets 100 transcription + 25 director. The phase-005 ledger (`2` transcription, `1` director) was archived to `storage/live-call-ledger.phase-005.json` and the active ledger reset to `0/0` with the user's approval.
  - **Observability:** `GET /health` now reports `live_call_limits` and `live_calls_used`.
- **Rationale for a high-but-finite cap:** at measured rates, 100 four-second ASR calls cost ≈ $0.02 and 25 director calls ≈ $0.016, so the worst case of this test phase is **under $0.04** — while a runaway loop still stops. This is a testing override, not a removal of budget protection.
- **Consequences:** The UI retry now works. If the user reaches 100/25, raise the variables and reset the ledger only with fresh approval. The SAM 3.1 gate and all other ADR-014 rules are unchanged.

## ADR-016: Director Operation-ID Normalisation and Per-Call Audit
- **Status:** Implemented and tested (Milestone 6B-LIVE-HARDENING). **No live call was made in this milestone.** Meta budget available at the time: **$31.78**.
- **Context:** A live user test (`0563760dec3444fd86fb797880187e46`) returned an otherwise valid lite plan whose operation ids were `op1_isolate`, `op2_blur`, `op3_audio`, `op4_render`, `op5_verify`. The internal `LiteOperation` pattern `^op_[a-z0-9_]{1,40}$` rejected the plan before conversion, and the failure path persisted only the `JobError` — no usage, request id or audit metadata. The underlying editing operations were valid; only the model-chosen internal ids were not.
- **Decision:**
  - **Canonical ids:** the lite wire accepts model-generated operation ids (non-empty string, max 80 chars). `normalize_lite_operation_ids()` assigns `op_1`…`op_n` in original operation order and returns the complete original → canonical map. It preserves capability ids, params, titles, explanations and order.
  - **Dependency integrity:** dependencies are rewritten through the map. Duplicate original ids, unknown targets, cycles and forward dependencies are rejected before the full v2 validators run. Self-dependencies are rejected as cycles. The strict `DirectorOperation` pattern remains unchanged.
  - **Provenance:** EDL decisions are projected only from the canonical plan, so every `provenance_hash` is computed over canonical operation ids. A regression test verifies each decision hash.
  - **Audit contract:** `DirectorAudit` captures job id, client request id, server `x-request-id`, provider, model, execution mode (`live`), service mode (`standard`/`contributor`), wire schema (`lite`/`full`), prompt/completion/total tokens when supplied, estimated cost from actual usage, actual cost only when reliably available (currently `None`), validation status, error category/code, HTTP status when available, finish reason and timestamp.
  - **Provider timing:** the audit record is created before the HTTP request and updated on transport/HTTP/validation outcomes. Usage is recorded before plan validation, so truncated/rejected 200 responses still carry token and cost estimates.
  - **Worker persistence:** the worker persists `director_audit` (plus usage/request id) in `JobResult` immediately after the call, on success **and** failure. Failed jobs now retain the audit in `job.json`; the original historical job record was not modified.
  - **API serialisation:** job result responses use `model_dump(mode="json")`, so the audit timestamp and enums are valid JSON.
- **Evidence:** 212 backend tests pass; targeted director/lite/worker tests 50 pass; `scripts/check.ps1` exits 0. The rejected pattern is recreated in tests from a valid mock plan because the raw model response was never stored. No live request was made.
- **Consequences:** A model-generated id no longer blocks an otherwise valid plan. Failed calls are auditable without claiming billed cost. A plan-only live retest remains **blocked on explicit approval**; expected cost is ~$0.00066 (Contributor, ~2.8k in / ~1.9k out) or ~$0.0116 (Standard), with the current 16k cap bounding the worst case.

## ADR-017: Fail-Closed Live Budget and One-Shot Provider Authorization
- **Status:** Implemented and tested (Milestone 6B-LIVE-BUDGET-SAFETY). **No live API call was made in this milestone.**
- **Context:** PRE-LIVE AUDIT 006 found that `LiveCallBudget._read()` returned `{}` for a corrupt/unreadable ledger (fail-open), direct calls to live providers could bypass reservations, `transcribe_upload(budget=None)` could run live without protection, and dev launchers loaded a live `.env` implicitly.
- **Decision:**
  - **Ledger fail-closed:** a missing ledger is a valid empty phase; invalid JSON, unreadable files, non-object data, unknown function keys, non-integer or negative counts raise `LedgerIntegrityError`. Counters are never reset automatically and corrupted bytes are never overwritten by a reservation.
  - **Atomic reservation:** `tmp` + `os.replace` retained. Lock acquisition failure raises `LedgerLockedError`; an existing lock is never deleted automatically. Stale-lock recovery is manual and must be preceded by verification that no call is in flight.
  - **No release:** a reservation is consumed once and is not refunded after a timeout/HTTP/validation failure. No automatic retry.
  - **One-shot authorization:** `LiveCallAuthorization` wraps `LiveCallBudget` + function. Providers require it on every live call and call `reserve()` immediately before the HTTP POST. The same authorization cannot reserve twice. Missing/invalid authorization raises `LiveCallNotAuthorizedError` before any network request.
  - **Entry points:** `MetaEditingDirectorProvider.create_plan`/`LiteMetaEditingDirectorProvider` and `MetaVoiceTranscriptionProvider.transcribe_audio` require authorization. The worker creates a director authorization; `transcribe_upload` creates a transcription authorization from its budget and refuses live mode with `budget=None`. Historical live-call scripts now reserve through the ledger.
  - **Development safety:** `scripts/dev_api.py` and `scripts/dev_worker.py` force transcription/director to mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is explicitly set. `.env` live flags alone no longer activate live through these launchers. Billing/privacy settings and the user's key are untouched.
- **Evidence:** 226 backend tests pass, including 12 budget-safety tests (corrupt/unreadable ledger, invalid counts, valid counters, lock contention, concurrent reservations, one-shot authorization, direct-provider rejection, `transcribe_upload(budget=None)`, mock mode, dev launcher opt-in). `scripts/check.ps1` exits 0. No external request was made.
- **Consequences:** direct live provider calls now fail closed; ad-hoc scripts must own an explicit authorization. The local `.env` may remain live for deliberate testing, but dev launchers default to mock and require the opt-in. The current ledger (`3/2`, limits 100/25) is preserved. LIVE-CALL 006 remains unexecuted and requires explicit approval.

## ADR-018: User-Controlled Plan Review, Approval and Resume

- **Status:** Implemented and tested (Milestone 6C, mock mode). **No live API call was made in this milestone.**
- **Context:** The product audit found the largest functional gap: ClipForge could upload, transcribe, plan and render, but the user could not inspect or control the AI Director's decisions before execution. The 6B approval gate stopped approval-required plans at `awaiting_approval` but had no endpoint or UI to continue them; mock mode still used the legacy keyword planner and auto-executed blur plans. Approval-required and blur-only plans needed the same explicit review contract.
- **Decision:**
  - **Review is mandatory for every ready plan.** Both blur and background replacement stop at `awaiting_approval` with a persisted v2 plan, a v1 execution adapter and `render_status="awaiting_approval"`. The worker never segments or renders before approval.
  - **State machine:** `JobStatus` adds `awaiting_approval`, `awaiting_clarification`, `rejected` and `unsupported`. Approval returns the job to `queued` with stage `approved`; no separate `approved` status is added because the existing stage field carries it without duplicating state. `rejected`, `unsupported`, `completed` and `failed` are terminal for user actions.
  - **Atomic user transitions:** `JobStore.transition(expected=..., status=..., stage=...)` validates the current and target states under a cross-process `transition.lock`, applies changes atomically and appends a `JobStateEntry` (`from_status`, `to_status`, `from_stage`, `to_stage`, actor, note, timestamp). Worker status/stage changes are also recorded in `state_history`.
  - **API:** `GET /api/jobs/{job_id}/plan` returns the v2 plan, v1 adapter, capability metadata (mock/local/live/planned/unavailable), approval/clarification flags, the pending question, clarification count, render status and error. `POST /approve`, `POST /reject` and `POST /clarify` validate the current state and return the updated job; invalid transitions return 409 with a stable code.
  - **One approved plan renders once:** the API transitions `awaiting_approval → queued` exactly once; duplicate approvals receive 409. The worker claims the approved job with the existing exclusive claim lock, reads the persisted plan and renders without calling the Director again. Duplicate/concurrent approvals, repeated polling and a clean worker restart cannot create a second render.
  - **Clarification:** answers are persisted on the job, the original transcript and context are preserved, and the answer is passed to the Director (mock and live). The revised plan is validated and returned to review. `MAX_CLARIFICATIONS=3`; once exceeded the job fails with an explicit error instead of looping.
  - **Rejection and unsupported:** rejection is a terminal user decision; the original is untouched and no output exists. Unsupported plans are terminal and expose the named unavailable capability.
  - **Mock Director v2:** `CLIPFORGE_DIRECTOR_MODE=mock` now uses `MockProfessionalEditingDirector` (v2) in the worker; the legacy keyword planner is no longer the worker's mock path. Live mode retains `LiteMetaEditingDirectorProvider` and full validation. There is no silent fallback to v1.
  - **Truthful UI:** the review dialog renders the dynamic operation list (never a fixed five), subject strategy/description, parameters, expected outputs, dependencies, capability status and approval requirements. The step tracker is derived from real status/stage/render/result fields; `completed` and `Done — verified MP4` are shown only when a verified result exists. Pending, rejected, unsupported and failed states have explicit notices. No invented percentages.
  - **Mock assets:** background replacement keeps using local/mock assets, labelled as such; the UI never claims Muse Image generated them.
  - **Scope:** no SAM, Muse Image, real subject recognition, new effects, trim, captions, timeline editing or frontend redesign.
- **Evidence:** **234 backend tests pass** in mock mode; `npm run typecheck` and the production build pass. Browser E2E (`apps/web/scripts/qa-approval.mjs`) covers blur desktop/mobile, replacement, reject, clarification and unsupported with 4 real MP4 downloads (video + audio) and zero console errors. Tests cover duplicate approval, concurrent transition locking, worker restart, clarification limit, render failure, post-render persistence failure and original preservation.
- **Consequences:** the product now has a genuine human-in-the-loop editing workflow in mock mode. The remaining limitation is subject quality: segmentation is still a synthetic moving ellipse and does not track a real person. Multi-user authorization/ownership is not implemented; the API is a local single-user service scoped by job id. A hard worker crash after claiming a job can leave it in `processing` with a claim lock; there is no automatic stale-lock recovery. Real SAM 3.1 and Muse Image remain blocked on explicit approval.


