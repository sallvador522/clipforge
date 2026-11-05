# ClipForge — Tasks (dependency order)

Status key: `[x]` done, `[ ]` pending, `[~]` in progress.

## Milestone 0 — Foundation
- [x] Inspect environment (empty repo; Python 3.13.2, FFmpeg/ffprobe, Node 22, Git).
- [x] Project structure, AGENTS.md, 7 docs, 5 custom skills.
- [x] EditingPlan contract defined (packages/contracts).
- [x] Minimal Python deps only: pydantic, Pillow, numpy, pytest (venv). OpenCV/FastAPI deferred to their milestones.

## Milestone 1 — Provider Interfaces, Mock Fixtures, Mask Contract
- [x] Typed interfaces: Transcription, EditingPlanner, Segmentation, BackgroundGeneration + normalized contracts.
- [x] Deterministic mocks (PT voice fixtures, command→plan mappings, local backgrounds, synthetic segmentation returning real mask files).
- [x] Live provider placeholders (explicit, no network code, no credentials).
- [x] Mode factory: `CLIPFORGE_AI_MODE=mock` default; live raises explicitly; no silent fallback.
- [x] Mask writer/loader with full validation (ADR-005).
- [x] Synthetic mask fixtures: static, moving, crossing, occlusion, missing, holes, irregular edges, jitter, lighting (ADR-007).
- [x] Tests: mask validation failure modes, provider determinism, EditingPlan validation, zero-external-requests in mock mode.

## Milestone 2 — Benchmark Preparation (only)
- [x] Benchmark spec: 300 frames, 1280x720, 30 FPS, 10 s; blur and replacement measured separately (ADR-006).
- [x] Preparation script generating the deterministic benchmark source clip locally with FFmpeg.
- [x] Benchmark harness stub that refuses to report numbers until the renderer exists. No performance claims.

## Milestone 3 — Job System + API
- [x] FastAPI app: upload + ffprobe validation, job creation, local storage layout, state machine (queued/processing/completed/failed + stage), status/list/result endpoints per API_CONTRACTS.md. Download endpoint deferred to Milestone 4 (no fake downloads).
- [x] Persistent worker process (`clipforge_worker.worker_process`) consuming ready jobs without blocking API requests; atomic cross-process job claiming.
- [x] Error states with structured `{code, message}` errors, per-job isolation, logging; originals preserved on failure.
- [x] Lifecycle tests incl. real cross-process verification (API + separate worker process). Deps added: fastapi, uvicorn, python-multipart, httpx (tests).

## Milestone 4 — Real Renderer
- [x] OpenCV compositing: alpha from masks, edge smoothing, background blur, background replacement, subject kept sharp. Bounded memory (streaming mask iterator, one frame at a time).
- [x] FFmpeg encode preserving original audio; output verification (readable, duration, streams, exact frame count/resolution).
- [x] Download endpoint serving only verified outputs.
- [x] ADR-006 benchmark run (300f/720p/30fps, blur vs replacement separately); measurements + machine specs recorded in STATUS.md and benchmarks/results/benchmark_results.json.
- [x] Renderer tests: missing/corrupt masks, corrupt source, frame mismatch, invalid backgrounds, verification rejection, audio preservation, download gating. Deps added: opencv-python-headless, psutil (benchmark).

## Milestone 5 — Frontend
- [x] Next.js voice-first UI per DESIGN_SYSTEM.md (tokens finalized there); upload with real XHR progress, real MediaRecorder voice capture with honest mock-transcription fixture confirmation, live job/stage polling (stops at terminal states), transcript/plan/render facts from the API, before/after/compare preview, blob download of the verified MP4, explicit error/recovery states. Motion for React, reduced-motion respected.
- [x] Browser verification of the full mock-mode flow in a real browser (two UI jobs completed + verified; downloaded MP4 re-probed: video+audio, correct dimensions/duration). CORS added to the API for the local studio origin.

## Milestone 5.1 — Professional Editor Redesign
- [x] Installed + verified skills: frontend-design, web-design-guidelines (`.agents/skills/`), motion (`.opencode/skills/`, via `npx motion-ai` ConPTY-driven; free kit, no Motion+ sign-in/purchase). Total project skills: 8/10.
- [x] Five-area editor workspace: TopBar (project/state/export), Media panel (real source + metadata), central Viewer (custom transport, before/compare/after, fullscreen), AI Assistant panel (mic hero with real level, mock-labelled command confirmation, typed-instruction alternative, live job steps), Timeline (ruler, real filmstrip thumbnails, real WebAudio peaks, synced playhead/seek).
- [x] web-design-guidelines audit applied (focus-visible, dark color-scheme, skip link, h1, labels, img dimensions). Browser-verified full flow on the redesign; 52 backend tests, typecheck, build pass.

## Milestone 5.2 — Local QA & Editor Validation
- [x] Desktop/mobile QA at 1440×900, 1280×800, 1024×768, 390×844 via system Chrome (`scripts/qa-editor.mjs`): five areas present, timeline inside viewport, no horizontal overflow, desktop page height == viewport.
- [x] Real microphone validation on hardware (headed Chrome, actual default input): recording state, live analyser level (0–9% room level), 4 s recording, Blob playback advanced 0.63 s. Permission-denied path + fallback verified in headless.
- [x] Both editing modes validated end-to-end with verified downloads and ffprobe re-probe (video+audio, 2.0 s). Real user footage (Facebook_2.mp4) tested via a 10 s excerpt.
- [x] Interaction checks: export gating, play/pause, playhead sync, timeline seek, Before/After/Compare, compare split, polling stops after terminal.
- [x] Fixes: grid-row height (timeline visibility), transport wrapping, viewer flex, ruler label clipping, mobile timeline header, revoked-blob request error.
- Limitation confirmed: mock masks are synthetic ellipses and do not track the real person (ADR-007); real subject cutout requires live SAM at Milestone 6.

## Milestone 6A — Real Voice Transcription (live call executed in LIVE-E2E 005)
- [x] Official docs verified (speech-to-text, transcribe reference, pricing/rate limits). Confirmed model `muse-voice-transcribe-1.0`, endpoint `POST https://api.meta.ai/v1/asr/transcribe`, multipart `request` JSON + `audio` WAV, `languageBias: ["Portuguese"]`, JSON response `{sessionId, transcript, audioDurationMs, turns}`, $0.18/audio-hour (whole seconds), 32 MB/10 min caps.
- [x] `MetaVoiceTranscriptionProvider` with httpx, Bearer auth, exact multipart contract, normalization, timeout/429/API-error mapping, no retries, no key/audio logging.
- [x] `POST /api/transcribe`: upload validation, ffprobe, FFmpeg → mono 16-bit PCM WAV 24 kHz, temp cleanup, mock isolation (fixture required; audio never interpreted).
- [x] Scoped selection: `CLIPFORGE_TRANSCRIBE_MODE=live` + `MODEL_API_KEY`; other providers remain mock; missing key fails before any request.
- [x] Frontend: real MediaRecorder audio uploaded, upload/transcribe states, editable transcript review, explicit confirm, failure + explicit retry, typed alternative; mock commands hidden in live mode, MOCK badge retained in mock mode.
- [x] Tests (18 new): multipart construction, language bias, normalization, invalid audio, missing credentials, timeout, 429, API errors, mock isolation, provider selection, single-request/no-retry, confirmed-transcript planning.
- [x] First live transcription call — executed in LIVE-E2E 005 (3,680 ms, $0.000184, one request, ledger 1/2). See `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`.

## Milestone 6B-PREP — Professional Editing Director
- [x] Ninth skill `clipforge-editing-director` (9/10 project skills) with cinematography/editing/colour/audio/social guidance and hard capability-truth rules; 6B-PREP-R adds the video-use methodology section.
- [x] Runtime playbook + validating loader (no model call); v1.1 adds ClipForge Workflows, Hosted Model Tool Protocol, Edit Decision Lists, Output Self-Evaluation.
- [x] Capability registry with five statuses, typed params, handlers, dependencies, verification, approval flags; local vs mock vs live distinguished.
- [x] `ProfessionalEditingPlan` v2 + registry/approval/dependency validators + v1 adapter.
- [x] Deterministic offline mock director scenarios A–E (blur, replacement, simulated cinematic background, clarification, unsupported).
- [x] 10 director stages with validated transitions and job-stage mapper; operation status transitions validated.
- [x] EDL v2 with capability-typed params, registry-resolved handlers, timing forbidden while trim disabled, canonical provenance; immutable history in `job.json`; evaluation report with 3-pass ledger (6B-PREP-R).
- [x] 90 new tests (160 total); docs/ADR-009 and ADR-010 updated.

## Milestone 6B-LIVE — Muse Spark Director (live-tested in LIVE-E2E 005)
- [x] Official docs verified (models, tool-calling, structured-output, Responses protocol, pricing/rate-limits). Confirmed `muse-spark-1.3`, base `https://api.meta.ai/v1`, Bearer auth, Chat Completions vs Responses distinction, `response_format` vs `text.format`, Standard pricing ($1.25/1M in, $4.25/1M out), 3000 RPM / 4M TPM.
- [x] Protocol selected: Chat Completions (single-turn plan generation; no reasoning replay, stateless, documented Pydantic structured-output flow).
- [x] `MetaEditingDirectorProvider` with mocked transport: playbook + registry loading, transcript + video metadata, one validated v2 plan, clarification/unsupported handling, concise explanations, no arbitrary tools/params.
- [x] Security: Pydantic + registry + echo enforcement, truncation/tool-call rejection, safe errors, single POST, no retries, no key/audio logging.
- [x] Cost control: Standard only, usage + per-request cost from actual usage, rough pre-request estimate, no web search, transcript text only, no background retries/duplicates.
- [x] 17 new tests (mocked transport: contract, validation, clarification, unsupported, malformed, timeout/429/API errors, isolation, selection, single-request, accounting, contributor-mode gating, reasoning_effort, contributor pricing, failure-context capture); 177 total preserved + new.
- [x] ADR-012: Contributor-Medium variant approved (`muse-spark-1.3-contributor`, `reasoning_effort: medium`, Contributor rates $0.10/1M in + $0.20/1M out); no `context` parameter exists in the verified contract; canonical env var is `MODEL_API_KEY`.
- [x] LIVE-CALL 001 — executed exactly 1 POST → HTTP 500 `internal server error`; mapped to `DirectorAPIError`, no retry, no result file. Billed cost under reconciliation (panel is source of truth).
- [x] LIVE-CALL 002 RETRY 1 (same payload) — executed exactly 1 POST → HTTP 500 again; repeat 500 on identical payload implicates the request (prime suspect: structured-output schema size/shape), not a transient fault. Stopped per approval. See `docs/LIVE_CALL_001_002_REPORT.md`.
- [x] Billing reconciliation: withdrew the $0.00 claim; `x-request-id` captured; reconciliation table pending user panel figures.
- [x] ADR-013 + lite contract (`director_lite.py`: 1,948-byte zero-$ref wire schema, abridged brief, essential registry summary, lite→full conversion with full v2 validation) + `LiteMetaEditingDirectorProvider` + guarded `scripts/live_call_003_spark_lite.py` + lite tests.
- [x] LIVE-CALL 003 — exactly 1 POST → **HTTP 200, `finish_reason: "length"`** at 800-token cap; no plan accepted (truncation rejected), no retry. Schema accepted → full-schema 500 suspect confirmed; remaining blocker is output budget. Billable; local usage lost pre-fix (bounded ≈ ≤ $0.00026). See `docs/LIVE_CALL_003_REPORT.md`.
- [x] Observability: usage recorded before validation; `DirectorValidationError.server_request_id` from `x-request-id`; script prints structured failure context; 183 tests.
- [x] LIVE-CALL 004 — exactly 1 POST, cap 1500 → **HTTP 200, still `finish_reason: length`**. Real usage 951 in / 1500 out = 2451, **$0.000395**, `x-request-id 134244ba-83c9-4721-95ae-a5677de9c34c`. No plan accepted, no retry. Schema proven accepted twice; budget still insufficient. See `docs/LIVE_CALL_004_REPORT.md`.
- [x] LIVE-CALL 005 — same lite payload with cap **16,000** and medium reasoning: **HTTP 200 with a complete plan**. Usage 2,781 in / 1,856 out, $0.000649, `req_2c45fa340028`. The larger cap superseded the 3000/low-effort proposal; no truncation. See `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`.

## Milestone 6B-LIVE-E2E — Director Wiring + Real Blur Execution

- [x] `CLIPFORGE_DIRECTOR_MODE=mock|live` factory wiring; live provider uses `LiteMetaEditingDirectorProvider`, `muse-spark-1.3-contributor`, medium effort, cap 16,000, timeout 180 s.
- [x] Worker live branch: reserve budget immediately before the call, validate v2, adapt to v1, execute real render; clarification/unsupported complete without rendering.
- [x] Approval gate: `approval_status` required/rejected completes as `awaiting_approval` with `render_status="awaiting_approval"` and no output file.
- [x] Persist `director_plan`, `director_usage`, `director_request_id`, `requires_approval` in the job result.
- [x] Per-function file ledger (`storage/live-call-ledger.json`) with 2-call caps, atomic writes, no retries; API returns `429 live_budget_exhausted` with zero provider calls when exhausted.
- [x] Fix WAV temp-name collision (`upload{suffix}` vs `recording.wav`) and add regression tests (WAV conversion + budget refusal).
- [x] Health reports `director_mode`; dev launchers load `.env` and `packages/director`.
- [x] End-to-end run: Portuguese audio → ASR → Muse plan (5 operations) → real blur render → verified download (320×180, 20 frames, 2.0 s, audio, 36,998 bytes).
- [x] Verification: 191 backend tests, frontend typecheck + production build, independent ffprobe and frame inspection.
- [x] Docs: LIVE_E2E report, STATUS, TASKS, DECISIONS ADR-014, ARCHITECTURE, API_CONTRACTS.
- [x] ADR-015: configurable live-call limits (`CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT`, `CLIPFORGE_LIVE_DIRECTOR_LIMIT`), default 2/2; local test phase 100/25; phase-005 ledger archived and active ledger reset to 0/0 with user approval.
- [x] `/health` exposes `live_call_limits` and `live_calls_used`; ledger tests cover env overrides, explicit overrides and invalid values.
- [ ] After user testing: review real usage/cost and either restore the 2/2 defaults or open a new approved phase.
- [x] SAM 3.1 provider + official parser + subject selection implemented and offline-validated in 6D; live detection quality still requires explicit approval and a controlled test.
- [x] Approval/rejection endpoint + UI to resume `awaiting_approval` jobs — delivered in Milestone 6C (ADR-018).

## Milestone 6B-LIVE-HARDENING — Director Reliability & Cost Audit
- [x] Canonicalise model-generated operation ids (`op1_isolate` → `op_1`) in original order; preserve capability ids, params and execution semantics.
- [x] Maintain the complete original → canonical map; rewrite dependency references.
- [x] Reject duplicate original ids, unknown dependencies, cycles and forward dependencies before full v2 validation.
- [x] Keep the strict full-plan `DirectorOperation` pattern; do not weaken Pydantic validation.
- [x] Recompute EDL provenance from canonical ids and verify every decision hash.
- [x] Add `DirectorAudit` (job/request/server ids, provider, model, execution/service mode, wire schema, tokens, estimated cost, actual cost only when available, validation status, error category/code, HTTP status, finish reason, timestamp).
- [x] Instrument the provider before/after the request; record usage before plan validation.
- [x] Persist `director_audit` in `JobResult` on success and failure; keep usage/request id on rejected plans.
- [x] Serialise job result responses with `model_dump(mode="json")` (audit datetime).
- [x] Regression fixture recreates the rejected `op1_…` pattern from a valid mock plan (raw model response unavailable); historical job records untouched.
- [x] 226 backend tests; targeted director/lite/worker plus 12 budget-safety tests; `scripts/check.ps1` exit 0.
- [x] Mock-only verification with explicit `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=mock`, `CLIPFORGE_DIRECTOR_MODE=mock`: factory modes confirmed; browser smoke showed `MOCK TRANSCRIPTION` with zero console errors; ledger `3/2`, no lock/tmp artifacts.
- [x] Docs: ADR-016, STATUS, TASKS, ARCHITECTURE, API_CONTRACTS, hardening report.
- [x] Live retest after hardening — executed as a full approved E2E rather than plan-only (LIVE-E2E 006). Muse generated a valid 5-operation plan; the worker rendered 360×640/177 frames/6.177 s with audio. Audit persisted and verified (`accepted`, HTTP 200, server request id).
- [x] Live audit fields verified on the real run: usage 2,792 in / 2,293 out, estimated **$0.000738**, request `req_03bff7ae260f`, server id `6096b398-7ce7-46ba-b4bf-c7a693cabbe7`.
- [x] Output saved outside the repository in the user's `Videos\Video` folder; source untouched; no frames or user video committed.
- [ ] Reconcile actual billed cost from the Meta panel (audit stores estimated cost only; run estimate $0.001010 including ASR).
- [ ] Improve real subject tracking (SAM 3.1 or a manual mask). The mock ellipse kept only one side subject sharp at a time; documented in `docs/LIVE_E2E_006_USER_VIDEO_REPORT.md`.
- [x] Prepare the exact LIVE-CALL 006 plan-only request without executing it: `scripts/prepare_live_call_006.py`, `storage/live_call_006_request_standard.json`, `..._contributor.json`, and `docs/LIVE_CALL_006_PROPOSAL.md`.
- [x] Cost proposal: input estimate 2,950 tokens, expected output 2,400, cap 16,000; Standard **$0.013888** expected / **$0.071688** cap; Contributor **$0.000775** expected / **$0.003495** cap.
- [ ] Execute LIVE-CALL 006 plan-only — **blocked on Salvador's explicit approval**; must use a ledger-authorized wrapper (not a raw provider script), with explicit dev live opt-in and a valid ledger; no tools, SAM, Muse Image, EDL or render.
- [ ] Then proceed to SAM 3.1 integration with a separate approved cost/scope.

## Milestone 6B-LIVE-BUDGET-SAFETY — Fail-Closed Ledger & One-Shot Authorization
- [x] Ledger fail-closed: corrupt/unreadable/invalid data raises `LedgerIntegrityError`; counters never reset; valid data preserved.
- [x] Explicit `LedgerLockedError`; orphaned locks are not deleted automatically; manual recovery documented.
- [x] Atomic reservation retained; no release after uncertain network outcome; no automatic retries.
- [x] One-shot `LiveCallAuthorization`; providers reserve immediately before POST; a second reservation is rejected.
- [x] `MetaEditingDirectorProvider.create_plan` / lite variant require authorization; direct calls rejected before network.
- [x] `MetaVoiceTranscriptionProvider.transcribe_audio` requires authorization; direct calls rejected before network.
- [x] `transcribe_upload(budget=None)` in live mode raises `live_budget_not_configured` before conversion/network.
- [x] Worker creates a director authorization; API creates a transcription authorization; no double reservation.
- [x] Historical live-call scripts 001/003/004 now reserve through the ledger.
- [x] Dev launchers force mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1`; `.env.example` documents mock defaults, limits and opt-in.
- [x] 12 budget-safety regression tests; 226 backend tests; `scripts/check.ps1` exit 0.
- [x] Docs: ADR-017, `docs/LIVE_BUDGET_SAFETY_HARDENING.md`, STATUS, TASKS, ARCHITECTURE, API_CONTRACTS, README.
- [ ] Execute LIVE-CALL 006 plan-only — **blocked on explicit approval**; use a ledger-authorized wrapper, not a raw provider script.

## Milestone 6B-LIVE — LIVE-CALL 003 Lite Schema (EXECUTED: HTTP 200, truncated)

- Instruction: same as 001/002 + benchmark-unit video metadata. No audio bytes, no tools, no web search.
- Endpoint: `POST https://api.meta.ai/v1/chat/completions`, `muse-spark-1.3-contributor`, `reasoning_effort: medium`, `response_format` `ProfessionalEditingPlanLite` (1,948-byte hand-written schema, 0 `$ref`s), `max_completion_tokens: 800`.
- Wire: developer 1,987 chars + user 631 chars (2,618 total, ~654 est tokens); full payload 4,899 chars.
- Result: **HTTP 200, `finish_reason: "length"`** → truncated output rejected; no plan, no EDL, no render. Schema accepted → the full v2 schema (~8.4 KB) is confirmed as the likely 500 cause; the remaining blocker is output budget. No retry.
- Cost: billable; local usage lost pre-fix. Bounded ≤ ≈ $0.00026, realistic ≈ $0.0002 at Contributor rates.
- Next (blocked): same lite payload with `max_completion_tokens: 1500` (or 1200) — one approved retry. Plain-JSON control no longer necessary.

## Repository / Hackathon Delivery
- [x] Local Git repository clean; GitHub remote `sallvador522/clipforge`, branch `main`, public.
- [x] Hackathon README (architecture, real-vs-mock table, setup, live modes, limits, screenshot).
- [x] MIT `LICENSE` and third-party notices preserved.
- [x] Repository topics: `meta`, `ai`, `video-editing`, `ffmpeg`, `opencv`, `hackathon`, `nextjs`, `fastapi`.
- [x] Reproducible editor screenshot via `apps/web/scripts/capture-readme.mjs`.
- [x] Local verification script `scripts/check.ps1` (300 backend tests + frontend typecheck + production build; exit code 0).
- [ ] GitHub Actions CI — workflow removed because the GitHub account is billing-locked and jobs cannot start. CI is not required for the hackathon; revisit only if billing is resolved.

## Milestone 6C — Plan Review, Approval & Resume (complete, mock mode)

- [x] Audit product state and save `docs/PRODUCT_AUDIT.md` with verified/mock/unimplemented distinctions.
- [x] Wire `MockProfessionalEditingDirector` (v2) into the worker for `CLIPFORGE_DIRECTOR_MODE=mock`; keep live validation unchanged; no fallback to the legacy v1 planner.
- [x] Extend the state machine with `awaiting_approval`, `awaiting_clarification`, `rejected`, `unsupported`; approval resumes via `queued`/stage `approved`.
- [x] Persist every ready v2 plan (plus v1 adapter) before review; block rendering before approval. (6D later added subject detection before review.)
- [x] Add `GET /plan`, `POST /approve`, `POST /reject`, `POST /clarify` with state validation, stable error codes and no provider credentials.
- [x] Atomic cross-process transitions (`transition.lock`) and auditable `state_history`; claims released after every worker run.
- [x] Idempotency: duplicate/concurrent approvals cannot double-render; approved jobs resume from the persisted plan without a second director call.
- [x] Clarification: inline answer, original context preserved, 3-round limit, revised plan returned to review.
- [x] Rejection/unsupported: terminal, no render, original preserved.
- [x] Frontend plan review dialog with dynamic operations, subject strategy, parameters, mock/local/live/unavailable status, approval requirements and inline clarification.
- [x] Truthful step tracker and notices for awaiting approval/clarification, rejected, unsupported, failed and verified completion; no invented percentages.
- [x] Mock replacement labelled as local/mock asset; no Muse Image claim.
- [x] Backend tests for approval, rejection, clarification, unsupported, duplicate/concurrent approval, worker restart, clarification limit and render failure.
- [x] Browser E2E (`apps/web/scripts/qa-approval.mjs`): blur desktop/mobile, replacement, reject, clarification and unsupported; 4 real MP4 downloads; zero console errors.
- [x] Frontend typecheck and production build.
- [x] Docs: ADR-018, PRODUCT_AUDIT, ARCHITECTURE, API_CONTRACTS, STATUS, TASKS, README.
- [x] Real SAM 3.1 provider + official parser + subject selection implemented and offline-validated in 6D; live inference was validated later on 2026-11-01.
- [x] Muse Image 1.0 background provider implemented and offline-validated (ADR-021); live request pending.
- [ ] Authentication/ownership for multi-user deployment — not implemented.
- [ ] Automatic stale-claim recovery after a hard crash mid-render — not implemented.

## Milestone 6D - Real SAM 3.1 Segmentation & Subject Selection (offline-validated)

- [x] Verify official SAM 3.1 docs: model `sam-3.1`, `POST /v1/responses`, `input_video` by URL/file_id, `stream=true`, output_text mask grammar, Files API `user_data` + expiration, 16 objects/frame.
- [x] Inspect and pin official Python parser `meta-sam-parser==0.1.0`; use `parse_responses_stream` and `decode_mask_to_raster`.
- [x] Implement `SamSegmentationProvider` with official request/stream, no retries, safe error mapping, one-shot `LiveCallAuthorization` and no mock fallback.
- [x] Temporary video-only MP4 preparation (copy or H.264 transcode), ffprobe validation of dimensions/FPS/frame count/no audio, original preserved + SHA-256.
- [x] Files API upload `purpose=user_data`, `expires_after=3600`, `file_id` reference, delete in `finally`; cleanup failures recorded.
- [x] Convert per-object box-local SAM rasters into ADR-005 full-frame PNG sequences; preserve object IDs, frame indices, source hash, provider/model and completion status; reject malformed/incomplete/wrong-size/duplicate/>16/out-of-range output.
- [x] Extend `SegmentationResult`, `MaskManifest`, `MaskLoader` and `MaskSequenceWriter`; loader rejects incomplete segmentation.
- [x] Detect subjects before plan review; persist per-object masks + previews; keep rendering blocked until approval.
- [x] Subject selection UI (preview cards, multi-select, stable IDs, single auto-select, multiple explicit, zero-subject state); approval sends `subject_ids`.
- [x] API: `GET /plan` subject metadata, `GET /subjects/{object_id}/preview`, `POST /approve` subject validation; `NoSubjectsDetected` terminal state.
- [x] Renderer integration: bounded-memory selected-mask union; audio/resolution/timing verification preserved. Selective person blur explicitly unsupported.
- [x] Mock provider emits two synthetic per-object tracks (enter/leave) and previews; no live SAM request.
- [x] Protocol-compatible offline fixtures and tests: one/multiple, stable IDs, enter/leave, occlusion, empty, incomplete, malformed, wrong dimensions, duplicates, out-of-order, >16, cleanup, expiry, source preservation.
- [x] Full-resolution benchmark: 300 frames/1280×720/30 FPS/10 s/audio; 1.74 FPS; 637.7 MB peak; verified 300 frames + AAC.
- [x] Browser E2E updated for subject selection and approval.
- [x] Docs: ADR-019, `docs/SAM_31_INTEGRATION.md`, ARCHITECTURE, API_CONTRACTS, STATUS, TASKS, README, PRODUCT_AUDIT.
- [x] ADR-020 + explicit live-SAM consent gate (plan-first order): director plans before any consent question; only subject-isolating plans pause live jobs at `awaiting_consent`; `POST /consent` binds job + source hash and re-queues, worker resumes the persisted plan with no second director call; "Not now" pauses without SAM. Portuguese dialog, unchecked consent, worker/provider revalidation before upload, mock mode unaffected.
- [x] UX revolution: auto-upload on select (one job, no Create-Job button), auto-transcribe on stop (no Transcribe button), single "Send to ClipForge" action, plan dialog auto-opens, shared preview-chip/card selection, consent dialog opens only when segmentation is actually required, human-language status. Browser E2E `qa-ux.mjs` + updated approval/editor/facebook/interactions/live-ui/mic scripts; no `api.meta.ai` requests.
- [x] Regression tests: pre-consent acceptance, deferral without SAM, consent grant + single-SAM resumption with one director call, double-consent idempotency, wrong-state rejection, clarification isolation, missing/false consent, changed source, another-job isolation, approval-without-consent, worker refusal, provider refusal before upload, mock no-consent.
- [x] Quick consent-gate verification (2026-11-01): targeted consent tests, typecheck/build and focused browser check; no live call.
- [x] **Live SAM 3.1 validation (2026-11-01) - SUCCESS on attempt 1.** One real inference (HTTP 200, request id `a6b54e67-61d4-4779-9fcc-80563b7166c9`) detected 2 subjects (IDs `0`, `1`), 177/177 frames each; real masks, manifests and previews; person A, person B and both rendered with original audio preserved. Ledger segmentation 1/2; no retry. See `docs/SAM_31_LIVE_TEST_REPORT.md`.
- [x] **SAM demo stabilization (2026-11-01):** original upload is the canonical render source; the SAM provider still uploads only a temporary video-only copy. Worker verifies source hash, mask provenance, dimensions, frame count and FPS before rendering. New API→worker→render regression compares decoded PCM with the original. Capability badges derive from actual provider/result metadata (LIVE/MOCK/UNAVAILABLE). Overlaid-label mask holes documented; no dilation or artificial fill added. **300 tests**, typecheck and build pass.
- [x] **Muse Image 1.0 integration (2026-11-01):** official `POST /v1/images/generations` with `muse-image-1.0`, `n=1`, PNG/Base64, text-only prompts, aspect-ratio `size`, tool disablement, one image per approved job, job-local image + provenance sidecar, idempotent worker marker, `image` ledger slot (`0/2` used), mock/live separation, full-workflow composition with SAM masks and audio preservation. **300 tests**, typecheck and build pass. No live image request made.
- [ ] Authentication/ownership and stale-claim recovery - not implemented.

## Milestone 6 - Live Integration Gate (SAM live-validated 2026-11-01)
- [x] Verify official Meta documentation for Muse Voice Transcribe and Muse Spark; implement live adapters with budget tracking and no automatic billable retries (ADR-008, ADR-014, ADR-017).
- [x] Verify official SAM 3.1 documentation and implement the adapter + parser + mask conversion (ADR-019); offline validation complete and one live inference validated on 2026-11-01.
- [x] Verify official Muse Image 1.0 documentation and implement the adapter, PNG/Base64 validation, provenance persistence, idempotent one-per-job generation and `image` budget slot (ADR-021); no live request made.
- [ ] Propose one controlled SAM integration test and obtain explicit user approval before any live call.
- [x] Fix live director rejection `strategy='mock_segmentation'`: pin capability param enums in the lite wire schema, reword the playbook away from "mock segmentation", add a regression test (301 tests) and validate with one live call (`largest_subject`, plan accepted).
- [x] Make SAM transport failures actionable: `SamStreamInterruptedError` (`sam_stream_interrupted`) reports elapsed time and received event count instead of the parser's generic `source_error`; no retry added (302 tests).
- [x] Make the live ledger advisory (ADR-022): it counts and reports usage but never blocks by default; hard enforcement is opt-in via explicit `limits=`/`enforce=True`; `/health` reports `live_call_budget_enforced`. Integrity checks, atomic reservations and one-shot authorization are unchanged (304 tests).
- [x] Accept clarification on ambiguous intent (ADR-023): a paid live plan was rejected because the model asked about the broad intent with a clear subject; v2 no longer forces `subject.is_ambiguous=true`, the v1 adapter and `awaiting_clarification` flow are unchanged (306 tests).
- [x] Recover dropped SAM streams via response retrieval (ADR-024): capture response id + last frame marker; on a drop, poll non-billable `GET /v1/responses/{id}` and re-parse the stored completed output with no second POST and no new slot. LIVE-CALL 009 (approved ~$0.0354) proved it: drop at 153.3 s, single GET returned completed 177-frame output, real masks written (310 tests).
- [x] Deliver the first real idea-to-video (ADR-027, approved ≈ $0.041 of the $1 cap): live storyboard `IMPACTO: Asteroide Gigante` ($0.000872, labelled assumptions, refs, narration), 4 Muse Image 9:16 plates (1280×1920, no text), shared SceneRenderer + deterministic capture (480/480, layout QA clean), verified MP4 720×1280 20.00 s 2.1 MB, copy in `Videos\Video`. Narration mux and Studio UI remain open.
- [x] TEST A programmatic-only promo (zero image calls, $0.00): NEXUS 15 s 9:16 validated, first render refused by the new asset gate (missing `asset_hero`), corrected to gradient backdrop, re-render 360/360 verified MP4 with kinetic type, counter, bars and drawn divider. Review→correct→revalidate loop demonstrated on a real defect.
- [x] Deliver the Facebook video end-to-end (job `5ccd24d6`): typed instruction (no audio needed), director `plan_ready`, SAM auto-recovered in production, subject 0 (man in black blazer) approved, Muse Image background, verified render with audio (`Facebook_senhor_de_preto.mp4`, 177 frames, 156,316 bytes).

## Milestone 7 - Idea-to-Video Vertical Slice (post-MVP, offline-verified)
- [x] Storyboard + quality-review contracts: allowlisted animation primitives, duration/asset validation, correction gate; `DirectorAudit.wire_schema` gains `storyboard` (ADR-025).
- [x] Creative directors: `MockCreativeDirector` fixture (asteroid, 20 s, 9:16, 4 scenes) + live `CreativeDirectorProvider` on the single-POST/no-retry Spark rails (mocked-transport tests only, never called live).
- [x] Anime.js 4.5 scene engine (`/idea`): data-driven composition, fixed builders per primitive, `autoplay: false`, `?t=ms` + `window.__idea.seek()` deterministic capture; unknown primitives/targets ignored.
- [x] Offline render pipeline: Playwright/Chromium frame-exact capture → FFmpeg → deterministic QA (480/480 frames, 0 black, 720×1280, 20.00 s verified MP4, silent). Procedural PIL fixtures, labelled as fixtures.
- [x] Mock critic + one-revision correction loop tested; real Spark video review stays an unverified placeholder; no TTS (user records narration).
- [x] Docs: `docs/IDEA_TO_VIDEO.md`, ADR-025. First real generation needs explicit approval within the $1 cap.
- [ ] Studio UI for the new mode (preview/demo page only in this slice).
- [ ] Real Muse Image scene assets + narration mux for the first approved generation.

## Milestone 5.3 - Social exports & navbar cleanup (2026-11-04)
- [x] Remove LIVE AI ENABLED billing banner and resolution/AI-mode metadata from the navbar (`TopBar.tsx`, `Studio.tsx`).
- [x] Navbar Exportar dropdown with Reels 1080x1920 and YouTube 1920x1080 (`TopBar.tsx`, `Studio.tsx`, `lib/api.ts`) — superseded: formato virou seletor externo em pills (accent signal-orange, sem azul) e o preview muda de tamanho (frame 9:16 / 16:9, vídeo inteiro com contain, sem corte).
- [x] Backend `GET /api/jobs/{id}/download?format=reels|youtube|original`: real FFmpeg cover-fit transcode, AAC audio, atomic cache under `jobs/<id>/exports/`, verified output, originals untouched (`apps/api/clipforge_api/exports.py`, `main.py`). Invalid format 422, unverified 409.
- [x] Tests: `tests/test_exports.py` (invalid format, real Reels/YouTube resolutions with audio, cache hit, original untouched); `tests/test_renderer.py` still passing; frontend `tsc` + `next build` clean; browser check on production build (Exportar menu, no banner/metadata).
- [x] Docs: ADR-026, STATUS, TASKS, API_CONTRACTS download row.

## Milestone P0 - Project Workspace & Asset Library (persistent, mock-verified)

- [x] Contracts: `ProjectRecord`/`AssetRecord` (`project.py`); `JobRecord.project_id` links jobs to projects.
- [x] `ProjectStore`: atomic writes, server-generated `prj_/ast_` IDs, pattern-validated lookups, cross-project isolation.
- [x] Asset validation (`apps/api/clipforge_api/assets.py`): ffprobe video (MVP limits)/audio, Pillow images, UTF-8 text + SRT/VTT cues, strict SVG sanitization (original + sanitized copy, malicious fixtures).
- [x] API: project CRUD + asset import/list/get/file/delete; `POST /api/uploads` accepts optional `project_id`, otherwise creates one and registers the source as `session_source`; library imports never trigger AI.
- [x] Studio: left column is the Asset Library (filters, search, multi-import, preview, two-step remove, rename); session-clip flow preserved; project id in `localStorage`, reload restores title + assets.
- [x] Tests: `tests/test_project_workspace.py` (12 tests: CRUD, persistence, multi-video, audio/image/text/SVG, malicious rejection, ownership, cleanup, regression).
- [x] Docs: `docs/PROJECT_WORKSPACE_PLAN.md`, STATUS, TASKS. No P1 features (timeline/scenes/director tools/animation/export/versioning).

## Milestone 7.1 - Idea-to-Video Product Flow (2026-11-03, offline-verified)

- [x] Studio workspace `/?mode=idea` (brief / SceneRenderer preview / approvals+QA+result), PT-PT, MOCK/LIVE badges, `idea_id` in URL + localStorage.
- [x] Two cost approvals (storyboard, assets/programmatic), hash + mode re-checks in the worker, $0.10 cap, one attempt per plate, cancel/reject/rerender guards.
- [x] Manifest + `/render/[ideaId]` capture surface (READY, seek probe, layout/frame QA, FFmpeg + ffprobe verified MP4).
- [x] Tests: 26 idea tests; full suite 365 passed; typecheck + build clean; isolated browser smoke (manifest + READY + stage + seek, no agent render).
- [x] Docs: `docs/IDEA_PRODUCT_FLOW.md`, ADR-028. No paid calls; user tests manually.
- [ ] User manual test (restart API/Studio, create → approve → render → download); live modes only with explicit approval.

## Milestone 7.2 - Single-route Studio (2026-11-03)

- [x] Removed the `?mode=idea` split: `/` always renders `Studio`; assistant routes the empty platform into an idea job, clip present → edit unchanged.
- [x] Reused `IdeaPreview` (centre) + `IdeaStatusPanel` (right column); removed `IdeaStudio`/`IdeaBriefPanel`; typecheck + build clean.
- [x] Docs: `docs/IDEA_PRODUCT_FLOW.md` updated, ADR-029.

## Milestone 7.3 - Static-board fail-fast + high storyboard effort (2026-11-03)

- [x] Root-caused live `qa_failed` (122 frozen): descriptive targets animated nothing; boundary samples flashed; HEAD asset check 405d every plated job.
- [x] `validate_board_targets` (engine vocabulary + per-scene motion) at plan/PATCH/render pre-check (`storyboard_static`); mid-frame sampling + per-seek advancement check; streaming-GET asset check.
- [x] `CLIPFORGE_CREATIVE_DIRECTOR_EFFORT` for the storyboard call only (verified values, recorded in approvals, UI badge); xhigh 504d at the gateway → profile pins **high** with 300 s timeout ($0.01 uncalibrated ceiling); edit flow untouched.
- [x] Recovered stranded `idea_30d803703d0a` (orphaned claim) via store transition; re-rendered verified (480/480, 0 frozen).
- [x] Tests: 38 idea + full suite (377) pass; typecheck + build clean. Docs: ADR-030.

## Milestone 7.4 - Motion-first director + fuller Anime.js (2026-11-03)

- [x] STAGE MODEL no prompt (palco, elementos, dicionário de movimento, gramática de timing, easings); motion budget validado (≥2 passos/cena, abre ≤1s, fecha nos últimos 500ms, ≥3 primitivas).
- [x] Easing passthrough (9 nomes verificados); 5 primitivas novas (mask_reveal, elastic_pop, shake, gradient_shift, tracking); tipografia auto-fit.
- [x] Mock exercita mask_reveal + elastic_pop. Tests: 41 ideia + suite 380; typecheck + build limpos. Docs: ADR-031.
- [ ] Fase C (parallax multi-plate) após validação do utilizador.

## Milestone 7.9 - Prompt exige soma exacta da duração (2026-11-04)

- [x] Causa-raiz dos dois `storyboard_failed` live (25 s→20 s, 75 s→60 s, ambos 1.25×): o prompt dizia "about X seconds (durations define the final length)", contradizendo o contrato.
- [x] Instrução endurecida: soma tem de ser exactamente `{ms}` (±500 ms), sem arredondar cenas a valores redondos. (A premissa de rejeição foi depois superada pelo ADR-036, duração director-authoritative; o wording fica como guia. Docs: ADR-046.)
- [x] Test de regressão em `test_idea_contracts.py`; 46 passed (contracts + API). Docs: ADR-046.

## Milestone 7.8 - Duração à escolha + automática (trava dos 20 s removida, 2026-11-04)

- [x] Pills de duração (15/20/25/30/60 s) no composer quando vai criar ideia; valor aplicado a `POST /api/ideas` sobre os defaults; sem mudança de contrato/preços.
- [x] Automático: `detectDurationSeconds` lê o texto ("25 segundos", "30s", "1 minuto"; 5–60 s, local e grátis); vence o default, pill tocada vence a deteção; legenda honesta no chat.
- [x] Tests: ideia 25 s planeia com soma exacta 25000 ms; deteção 10/10 contra o código compilado; suite ideia 17; `tsc` + `build` limpos. Sem renders do agente.
- [x] Motivação: board live de 25000 ms chumbou contra projeto de 20 s (`storyboard_failed`, 1 chamada paga perdida); duração passa a ser decisão do utilizador. Docs: ADR-035.

## Milestone 7.7 - Edição de cenas 1-2: texto + eliminação (2026-11-04)

- [x] `PATCH /storyboard` pós-conclusão (`completed`/`failed`): mesma validação + `expected_hash`; prompts novos rejeitados (`storyboard_new_images`); gerados idênticos preservados (ficheiro/estado/custo) — edição $0.00.
- [x] Eliminação redistribui duração proporcionalmente e escala os passos de animação (sem cauda estática); última cena protegida; re-render continua explícito via botão existente.
- [x] UI PT-AO: editor de texto por cena + botão eliminar na revisão (pré-aprovação) e bloco "Cenas" no vídeo concluído; timeline mantém-se como navegador (seek).
- [x] Tests: 4 novos em `test_idea_api.py` (guarda mid-flow, texto preserva gerados, imagens novas rejeitadas, delete 4→3 com soma exacta); suite 392; `tsc` limpo. Sem renders do agente — teste manual pelo utilizador.

## Milestone 7.6 - Generated assets in Recursos + timeline scenes (2026-11-04)

- [x] Worker publica plates/SRT/MP4 verificado como assets `generated` no projecto (idempotente, sem falhar o job); validação MVP mantida para uploads.
- [x] Ideia ligada ao projecto na criação; Recursos mostra tudo com etiqueta "Gerado"; timeline com faixa de cenas clicável (só leitura, seek real).
- [x] Smoke ponta-a-ponta em mock: 5 assets publicados, MP4 120/120 verificado, seek nas cenas OK, zero erros de consola. Tests: 6 novos; suite 388; typecheck+build limpos. Docs: ADR-033.

## Milestone 7.5 - Multiplane foreground (Fase C, 2026-11-03)

- [x] `role` no contrato (AssetSpec/IdeaAsset, default background); build_assets 1 fundo + 1 frente/cena (máx 6); validação (≤2/cena, papéis únicos, cenas conhecidas).
- [x] Motor monta `data-layer="fg"` (banda 62% inferior) com parallax diferencial; prompts fg server-side; UI lista plates com tag FUNDO/FRENTE; estimativa conta plates reais.
- [x] Smoke mock ponta-a-ponta: bg+fg geradas e servidas, MP4 120/120 verificado, prova diferencial (topo 6,47 vs banda 0,01). Docs: ADR-032.

## Milestone 8 - Studio premium em PT-AO, chat com o Muse (2026-11-04)

- [x] Auditoria hallmark; layout em 3 regiões (Projecto | Pré-visualização + Linha de tempo | Muse).
- [x] Painel esquerdo com tabs Projeto/Recursos; TopBar mínima (nome + estado + Exportar); formatos 9:16/16:9 junto à pré-visualização.
- [x] Chat com histórico da sessão (bolhas tu/Muse), cartões de aprovação/consentimento/progresso/resultado inline, composer com microfone integrado.
- [x] Copy PT-AO em todo o Studio; removida linguagem técnica da interface (mantida honestidade mock vs directo).
- [x] Funcionalidade preservada: typecheck + build limpos; zero erros de consola; fluxo ideia ponta-a-ponta verificado em mock (criar → aprovar plano → rever cenas). Sem commits.

## Milestone 9 - Director-authoritative duration + voice refinement (2026-11-04, ADR-036)
- [x] Dura��o derivada das cenas (sem teto de 60 s, sem rejei��o por mismatch); progresso e manifesto l�em o board.
- [x] `text_style` + `backdrop_hue_deg` no contrato e no SceneRenderer (preview = export).
- [x] `StoryboardPatch` (9 opera��es tipadas ou clarifica��o) + `apply_storyboard_patch` validado.
- [x] `RefinementDirectorProvider` live (single POST, autoriza��o one-shot, board como contexto) + `POST /direct|apply|reject` com aprova��o expl�cita e guarda de imagens.
- [x] Studio: composer (voz inclu�da) refina a ideia activa; cart�o de proposta com Aplicar/Rejeitar; comandos sequenciais sobre o board actualizado.
- [x] Testes: 8 novos + suite 401; `tsc` + build limpos. Sem chamadas pagas.
- [ ] Primeira validaçao live do refinamento (requer aprovaçao de custo explicita).
- [x] LIVE-CALL refine 001: HTTP 500 (schema 11.5 KB, mesmo sintoma 001/002) — sem retry; causa confirmada offline.
- [x] Wire lite (`refinement_lite.py`, flat ops, `scene_json`) + LIVE-CALL refine 002: HTTP 200, $0.000410, patch serif/1.3 aplicado e validado (ADR-038).

## Milestone 9.2 - Edição de timeline no trilho idea (2026-11-04, ADR-039)
- [x] Trim (1–15 s, passos escalados), split (playhead/meio, animação repetida comprimida, texto+plates duplicados) e reorder (botões + arrasto V1); via PATCH existente + re-render explícito, sem custo.
- [x] Multitrack, transições editáveis e trim do upload ficam fora (declarado no ADR).
- [x] Verificação: `tsc` + `next build` limpos; helpers TS em execução (node); 3 testes API novos; suite 407. Sem chamadas pagas, sem renders do agente.

## Milestone 9.3 - Transições editáveis + multitrack de sobreposição (2026-11-04, ADR-040)
- [x] Transições por cena (corte/fundido/dissolver/cortina/zoom, 400 ms) honradas pelo motor; seletor no painel.
- [x] Camada OV: overlays de texto globais (máx 3) + faixa na timeline + CRUD no painel.
- [x] Voz: 4 operações de patch + wire lite + brief.
- [x] Verificação: `tsc` + build limpos; 4 testes novos; suite 411. Sem chamadas pagas, sem renders do agente.

## Milestone 9.4 - Trim + áudio do upload, overlay de imagem, duração de transição (2026-11-04, ADR-041)
- [x] Overlay de imagem (reuse de plates geradas, falha fechada, preview=export).
- [x] transition_ms 200–1000 por cena (motor+UI+voz).
- [x] Trim do upload (endpoints, worker, re-probe, validação) + áudio (gain+fades).
- [x] Verificação: trim+áudio e2e real + validation tests; suite completa a correr. Sem chamadas pagas.

## Milestone 9.5 - Voz para a timeline, upload manual permanente (2026-11-04, ADR-042)
- [x] `set_scene_duration`, `split_scene`, `move_scene` (contrato + lite + aplicador + brief).
- [x] Upload trim/áudio declarados manuais; registo inalterado.
- [x] Verificação: conversão + aplicador e2e + rejeições; suite 416; `tsc` + build limpos. Sem chamadas pagas.

## Milestone 9.1 - Timeline honesta estilo profissional (2026-11-04, ADR-037)
- [x] Idea mode: faixas V1/T1/FX/A1 so-leitura do storyboard (cenas, texto, animacoes posicionadas, transicoes marcadas, audio honesto); trilho de upload oculto nesse modo.
- [x] Clip mode: V1/A1 inalterados + badge "Editado · verificado" quando o render existe.
- [x] Sem drag/trim/keyframes — proibicoes do registo mantidas; edicao continua no painel Cenas + /direct.
- [x] Verificacao: `tsc` + `next build` limpos; suite 401. Sem chamadas pagas, sem renders do agente.

## Milestone 9.6 - Reorganização do editor em layout profissional (2026-11-04, ADR-043)
- [x] Shell `[rail 44px + Recursos] | palco | [Propriedades / Muse]`; Timeline full-width com toolbar + pill + zoom + headers de faixa.
- [x] `EditorRail.tsx` + `PropertiesPanel.tsx` novos; `MediaPanel`/`Viewer`/`Timeline`/`AssistantPanel`/`TopBar` restyle; marca e tokens intactos, sem capacidades novas.
- [x] Verificação: `tsc` + `next build` limpos; upload real → 10 thumbnails, 0 erros consola; 1440/1280/1024 sem overflow, 390 empilhado. Sem chamadas pagas (upload sem `ready`, worker não reclama).

## Milestone 9.7 - Montagem multitrack real (2026-11-04, ADR-044, pós-MVP)
- [x] Teto 15 min (baixado de 30 a pedido; probe/uploads/assets/áudio; 720p/30fps mantidos).
- [x] Contrato `timeline.py` + `timeline`/`timeline_render_requested` no `JobRecord` + transições `queued/completed→queued`.
- [x] API `GET/PUT /timeline` (validação total) + `POST /timeline/render` (fila auditada).
- [x] Worker `timeline_render.py` (z-order V2>V1, letterbox 1280x720@30, leitura sequencial, mix áudio, verify `timeline_assemble`).
- [x] Frontend DnD (assets→faixas, mover/aparar/remover, régua adaptativa, botão Montar, erros honestos).
- [x] Verificação: 16 testes novos + e2e browser em stack mock (drop→bloco→mover→Montar→verificado→Exportar, 0 erros). Sem chamadas pagas (compose é FFmpeg local).

## Milestone 9.8 - Muse conversacional com execução por aprovação (2026-11-04, ADR-045)
- [x] Backend `POST /api/chat` side-effect free (`ChatRequest` 1..1000 chars; router determinístico; 422 vazio; nunca cria jobs/ideas nem toca no ledger/providers).
- [x] Frontend chat-first (`sendChat`, `pendingChat`, cartão Executar/Ajustar/Cancelar; `submitInstructionWith`/`handleDirectIdeaWith`/`handleCreateIdeaWith`; voz via transcribe → chat).
- [x] Testes `tests/test_chat_api.py` (saudação sem side effects, ajuda, entrevista→proposta idea com opções, vazio 422).
- [x] Verificação: suite 437, `tsc` + `next build` limpos, e2e browser isolado `qa-chat.mjs` (0 erros consola). Ledger inalterado, zero chamadas pagas.

## Milestone 9.9 - Director interview + anexo no chat + legendas (2026-11-04, ADR-048)
- [x] Entrevista stateless (`InterviewAnswers` + parsing PT estilo/duração/formato + brief preservado; pergunta 1 de cada vez com chips; proposta com `pending_idea_options`).
- [x] Anexo de vídeo no composer (mesmo upload, retorno honesto; `uploadFileObject` devolve o job).
- [x] Fundo via Meta anunciado no chat (bail das clip-tools → fluxo director SAM 3.1 + Muse Image, sem bypass).
- [x] `captions.create` (11ª tool: split ≤42 chars, teto 20, timing uniforme declarado, janela de edição) + router PT (proposta com aspas, clarificação sem texto).
- [x] Studio: chips, `interviewBrief`, `handleCreateIdeaWith(text, opts)`, ramo captions no Executar.
- [x] Testes `tests/test_chat_interview_captions.py` (15); suite 464; `tsc` + `next build` limpos; browser `qa-chat2.mjs` (entrevista→ideia, anexo real, legendas 1 execução, fundo SAM, 0 erros consola). Zero chamadas pagas.

## Milestone 9.10 - Legendas reais com turnos + cover de queimadas (2026-11-04, ADR-049)
- [x] `TranscriptTurn` + `mode` ENDPOINTING no provider/`transcribe_upload`/`POST /api/transcribe` (validação estrita; PTT-com-turns rejeitado).
- [x] 2 chamadas live aprovadas ($0.00190): 1ª expôs validação nossa demasiado estrita (turnId 0; corrigida sem retry automático); 2ª devolveu 1 turno real 0–19.02 s do Facebook_2 (EN).
- [x] Tools `captions.create_from_turns` (split >8 s, skip blips, teto 20) + `captions.cover` (blur fixo) + endpoints + render no `compose_timeline` via worker.
- [x] Chat: intenção cover + dica de cobertura na proposta de legendas; sem deteção fingida (pergunta ao utilizador).
- [x] Testes `tests/test_captions_turns.py` (12) + 4 endpointing em `test_transcription_meta.py`; suite 479; `tsc` + `next build` limpos; `qa-chat2.mjs` com cover (1 execução, 0 erros).
- [x] E2E real: Facebook_2 19.61 s → 9 linhas temporizadas → Montar → MP4 19.6 s verificado em `Videos/Video/ClipForge_Facebook2_Legendas_Timed.mp4` (588 frames h264+aac, contact sheet).

## Milestone 9.11 - Tradução PT com Spark + pergunta de idioma (2026-11-04, ADR-050)
- [x] Adapter `translation_spark.py` (mesmo contrato Chat Completions verificado, contributor, effort minimal, cap 1500; validação linha-a-linha).
- [x] 2 tentativas live diagnosticadas (~$0.0001): truncagem por reasoning → corrigido; 9 linhas PT com tempos reais.
- [x] Tool `captions.translate` (ledger-autorizada slot director, fail-closed 503/429/502/504) + intenção "traduz..." com preço + pergunta de idioma nas propostas.
- [x] Testes tradução mocked + chat; `qa-chat2.mjs` (proposta mostra preço, NÃO executa em mock); suite 484; `tsc` + `next build` limpos.
- [x] Entrega real: `Videos/Video/ClipForge_Facebook2_Legendas_PT.mp4` (19.6 s 360x640 h264+aac verificado, contact sheet). Ledger director 25/25.

## Milestone 9.12 - Magic Background programático (2026-11-04, ADR-052)
- [x] Contrato `ProgrammaticBackdrop`/`asset_source=programmatic` + v1/lite wire actualizados (enums iguais).
- [x] `programmatic_bg.render_frame` determinístico (gradiente + formas sinusoidais); renderer usa-o por frame; poster PNG como `BackgroundResult`.
- [x] Worker: ramo programático sem `generate` (zero custo); publica o MP4 como asset `LOCAL_RENDER` idempotente.
- [x] Mock director com cenário programático; subject selection/approval inalterados; boxes/pontos avaliados (fora do contrato SAM).
- [x] Testes programáticos (6) + canvas; suite 497; `tsc` + `next build` limpos; `qa-magicbg.mjs` PASS (0 erros).
- [x] Deliverable `Videos/Video/ClipForge_MagicBackground_Programmatic.mp4` (5 s 640x360 h264+aac verificado). **Live SAM validado 2x sem retries: recorte 5 s sujeito 0 125/125 ($0.025) + Facebook_2 completo 19.6 s sujeito 0 490/490 (490 frames, $0.098) → `Videos/Video/ClipForge_MagicBackground_Facebook2_Live.mp4` (360x640@25fps h264+aac).**

## Milestone 9.11 - Formato original + legendas com fit + verify/redo (2026-11-04, ADR-051)
- [x] `compose_timeline` com canvas/fps da origem (primeiro V2 senão V1; fallback 1280x720@30); `POST /timeline/render {format}` default source + seletor Original/16:9/9:16 no Studio.
- [x] Auto-fit no burn-in (wrap + shrink até 12 px, bloco dentro do frame) + `verify_caption_legibility` com redo (reduz escala, 1 re-render) no fluxo de entrega.
- [x] Testes `tests/test_timeline_canvas_fit.py` (fit, verify pass/fail, portrait preservado); e2e source default + override landscape + 422; suite 490 (1 flaky Windows lock, passa isolado); `qa-rescue.mjs` + `qa-chat2.mjs` PASS, 0 erros.
- [x] Facebook_2 recomposto: `Videos/Video/ClipForge_Facebook2_Legendas_PT.mp4` 360x640@25fps, 490 frames h264+aac, verificado por pixels. Zero chamadas pagas.

- [x] Contrato `ClipTextOverlay` + `ColourGrade`, `JobRecord.clip_texts/colour`, `PUT/GET /texts` + `/colour` (validados, janela queued-sem-voice/completed).
- [x] `text.overlay` + `colour.adjust` como `available_local` (compose real; director não planeia; EDL transform).
- [x] Burn-in real no `compose_timeline` (PIL + fade/rise, só na janela) + grade por frame; pixel-diff + ffprobe.
- [x] `tools.py` (10 ferramentas validadas, execução real) + `GET /tools` + `POST /tools/execute`; chat propõe `pending_tool_calls` PT + `select_text_id`, ambiguidade pede clarificação.
- [x] Studio: guarda de seleção no clique, edição inline, Propriedades (cor/peso/timing), cor com Aplicar, persistência backend, badge honesto.
- [x] Correção: clique-seleção estava quebrada (pointerdown selecionava, click alternava) — guarda pointerdown/click.
- [x] Testes `test_clip_texts.py` (11) + `test_texts_render_e2e.py` (compose 90f + tool-edit + re-render); `qa-rescue.mjs` browser (0 erros).
- [x] Entregáveis reais em `Videos/Video`: `ClipForge_Final_PropertiesTest.mp4` + `ClipForge_Final_Editing.mp4` (1280x720, 6 s, áudio, texto queimado, contact sheets).
- [x] Zero chamadas pagas nesta missão ($0.00 de $5.00); live Muse reasoning = NOT VERIFIED (sem aprovação para gasto).

## Milestone 9.13 - Chat ao vivo com Muse Spark (2026-11-04, ADR-053)
- [x] `SparkChatAssistant` (contrato Chat Completions verificado reutilizado: contributor, minimal, cap 600, timeout 30 s; texto puro validado, sem tools).
- [x] `CLIPFORGE_CHAT_MODE=mock|live` (default mock); live reescreve só o `reply`, router decide intent/pending (gates intactos); 1 POST + 1 slot `chat` no ledger (default 2, consultivo), sem retries, fail-closed sem chave.
- [x] `/health` com `chat_mode`/`live_chat_available`; resposta com `chat_mode` (+ `chat_usage` em live); Studio mostra `Ao vivo · Muse Spark` vs `Disponível`.
- [x] Testes `tests/test_chat_live.py` (6, transporte simulado, zero custo) + limites atualizados; suite 503; `tsc` limpo; sem browser run (utilizador testa na stack ligada).
- [x] Estimativa: ~$0.0001/turno típico, teto ~$0.00032; cada mensagem = 1 slot `chat`. Zero chamadas pagas feitas nesta missão.

## Milestone 9.15 - Final hackathon E2E rescue (2026-11-04)
- [x] Auditoria completa: 509 testes, tsc/build limpos, 5 suites browser (0 erros consola).
- [x] P1 corrigido: download do ficheiro original (sessão + biblioteca) com SHA-256 idêntico; upload inválido 422 sem asset.
- [x] `qa-final-e2e.mjs` novo (A1–A8) + `qa-chat.mjs` alinhado com a entrevista ADR-048.
- [x] Entregáveis `ClipForge_E2E_*.mp4` verificados em Videos/Video; relatório `docs/HACKATHON_FINAL_E2E_REPORT.md`; zero chamadas pagas (ledger intacto).
- [ ] Live Meta + voz: NOT EXECUTED nesta missão (sem aprovação de custo por chamada / sem microfone headless).

## Milestone 9.21 - Retomar upload + ETA adaptativo (2026-11-04, ADR-059)
- [x] Cross-reload resume + host-calibrated Montar ETA; browser PHASEB 5/5 PASS; suite 559; zero chamadas pagas.

## Milestone 9.22 - Transcricao do audio-fonte em blocos (2026-11-04, ADR-060)
- [x] Chunking <=10 min + estimativa + juncao + falha fechada + chat; `test_source_transcript.py` (8) + suite 559; zero chamadas pagas.

## Milestone 9.20 - Upload retomável 30 min (2026-11-04, ADR-058, produção)
- [x] Protocolo chunked + teto 1800 s + retry/progresso reais; `test_chunked_upload.py` (5) + CHUNKED-UI browser PASS; suite 558; zero chamadas pagas.

## Milestone 9.19 - Consentimento SAM vinculado ao recorte (2026-11-04, ADR-056)
- [x] Consentimento vincula janela + hash; trim permitido em live; worker/provider verificam antes do upload; diálogo mostra o trecho; `test_consent_trim_rebind.py` (5) + browser até recusar sem chamada; suite 525; zero chamadas pagas.

## Milestone 9.18 - Trecho da timeline como âmbito do Director (2026-11-04, ADR-055)
- [x] Seleção Início/Fim + chip/faixa; `ChatSegment` validado; router com estimativa e teto SAM; Executar aplica trim primeiro; `test_chat_segment.py` (6) + SEGMENT-E2E browser PASS; suite 520; zero chamadas pagas.

## Milestone 9.17 - Hackathon README + presentation docs (2026-11-04, docs-only)
- [x] README: ownership, per-model I/O, Mermaid, capability matrix, verified numbers/links; `README.pt-AO.md`, `HACKATHON_PROJECT_OVERVIEW.md`, `HACKATHON_DEMO_GUIDE.md`; zero paid calls, no app changes.

## Milestone 9.16 - UI/UX quality rescue (2026-11-04, frontend-only)
- [x] `friendlyApiError` (PT-AO) em todos os erros visíveis; upload falhado sem sessão falsa; status honesto; rename guardado.
- [x] `qa-ux-rescue.mjs` + audits DOM; todas as suites browser PASS (0 erros consola); tsc+build limpos; backend 513 passed.
- [x] Relatório `docs/UI_UX_QUALITY_REPORT.md`; zero chamadas pagas (ledger intacto).

## Milestone 9.14 - Director conversacional com contexto real (2026-11-04, ADR-054)
- [x] `apps/api/clipforge_api/chat_context.py` com snapshot real (ProjectStore/JobStore/IdeaStore), prompt-safe e Q&A direta com contagens/estado/ficheiro/follow-ups meta.
- [x] `/api/chat` aceita `idea_id` + `history`; perguntas informacionais cortam antes de qualquer pending; `_guard_pending` remove pendentes em conversa/meta.
- [x] Spark live recebe estado real + historia; continua sem decidir pendentes, ferramentas ou factos novos; capacidades/desactivadas enunciadas com honestidade.
- [x] Studio propaga `idea_id` e ultimas 12 mensagens; regressao coberta em `tests/test_chat_context.py` (11 testes, inclui barreira anti-gibberish e crash 500); chat suites 37/37; suite completa 514 passed; `tsc` + `next build` limpos; zero novas chamadas pagas.

## Milestone 9.17 - Muse Spark native video understanding (2026-11-04, ADR-057)
- [x] Contratos `VideoAnalysis` + `ProviderFileRef` (tudo descritivo opcional; sem fabricar campos).
- [x] Provider `SparkVideoAnalysisProvider` (Responses `input_text`+`input_file`, Files upload reutilizado por sha256, sem retries).
- [x] Endpoints `POST .../assets/{id}/analyze` + `GET .../analysis`; aprovação explícita ($0.10 teto); modo mock zero-custo; ledger slot `video_analysis`.
- [x] Chat responde de cache; Studio com botão «Analisar vídeo» + confirmação + estados honestos.
- [x] `tests/test_video_analysis.py` (21 testes) + resposta a análise e fallback a excerto verbatim; suite completa 553 passed; `tsc` + `next build` limpos; zero chamadas pagas.
- [x] TEST 1+2 live EXECUTADO (aprovado $0.10): upload Facebook_2 + 1 análise Responses — resposta descreve conteúdo visível real (split-screen adcopy.ai, apresentador, legendas, CTA webinar); custo real **$0.000709** (4993 in / 1049 out); file_id reutilizável; análise persistida e servida via GET + chat.

## Milestone 9.23 - Chat segue a seleção dos Recursos + anexo vira asset (2026-11-04, ADR-061)
- [x] `ChatRequest.selected_asset_id` (max 32); backend só aceita asset do projeto efetivo (sidecar + project_id), resto é ignorado sem partir o chat.
- [x] Router responde do selecionado com análise; seleção sem análise aponta «Analisar vídeo» nomeando-o; vários analisados sem desempate pedem qual (sem escolha silenciosa); fallback sha256 no mesmo projeto.
- [x] `handleAttachVideo` com job carregado importa para a biblioteca, seleciona e sugere análise (fim do falso "verifica o formato").
- [x] `tests/test_chat_selected_asset.py` (8 testes novos); suite completa **574 passed**; `tsc` + `next build` limpos; e2e browser adiado a pedido (follow-up).
- [x] Fix 2026-11-05 (reporte "analise o video para mim"): raiz "analis"/"anális" + resposta de seleção determinística + guarda-redes anti-interview; 2 regressões novas (10 testes); chat suites 26 passed; suite completa pós-fix **576 passed**; API destacada reiniciada (depois parada a pedido).

## Fix - Chat permanece aberto após Montar/verificado (2026-11-04)
- [x] Removido gate legado `submitted`/`voiceSubmitted` no `AssistantPanel` (anexo, mic, textarea, enviar, Descartar, Executar, pills, contador); `Studio` com `canConfirm={!pendingChat}`.
- [x] Verificação: `tsc` + `next build` limpos; chat suites 29 passed; e2e isolado (8001/3001, mock) Montar→completed→2 turnos follow-up, 0 erros consola; zero chamadas pagas.

## Fix - Drop no vazio cria job a partir do asset (2026-11-05, ADR-062)
- [x] `Timeline` V1 vazia droppable (`onEmptyDrop/emptyDropping/emptyError`); `Studio.handleEmptyDrop` valida e cria job via `fetch->uploadVideoChunked` + auto-place (sem IA, original intacto).
- [x] Verificação: `tsc` + `next build` limpos; timeline suites 18 passed; browser isolado (API :8001 + web :3000, mock): hint visível → drop → job + clipe V1 4 s → Montar `completed/verified` (320x180 h264+aac 4.0 s, `source.mp4` preservado), 0 erros consola; zero chamadas pagas.

## Fix - Rail sem botões fantasma (2026-11-05)
- [x] `EditorRail` passa a mostrar só `Recursos` + `Texto` (destinos reais); removidos Áudio/Efeitos/Transições/Legendas/Ajustes desativados e a seta decorativa.
- [x] Verificação: `tsc` + `next build` limpos; browser (prod :3000): rail com 2 botões, 0 erros consola.
