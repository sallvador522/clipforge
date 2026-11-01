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
- [x] Local verification script `scripts/check.ps1` (296 backend tests + frontend typecheck + production build; exit code 0).
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
- [x] ADR-020 + explicit live-SAM consent gate: Portuguese pre-send dialog, unchecked consent, decline without request; API 422 before ready/worker; source-bound consent record (job, SHA-256, timestamp, disclosure version, provider, model, live mode); worker/provider revalidation before upload; mock mode unaffected.
- [x] Regression tests: missing/false consent, no ready/worker, valid persistence, changed source, another-job reuse, approval-without-consent, worker refusal, provider refusal before upload, mock no-consent. Browser E2E desktop/mobile + mock no-dialog + zero `api.meta.ai` requests.
- [x] Quick consent-gate verification (2026-11-01): targeted consent tests, typecheck/build and focused browser check; no live call.
- [x] **Live SAM 3.1 validation (2026-11-01) - SUCCESS on attempt 1.** One real inference (HTTP 200, request id `a6b54e67-61d4-4779-9fcc-80563b7166c9`) detected 2 subjects (IDs `0`, `1`), 177/177 frames each; real masks, manifests and previews; person A, person B and both rendered with original audio preserved. Ledger segmentation 1/2; no retry. See `docs/SAM_31_LIVE_TEST_REPORT.md`.
- [x] **SAM demo stabilization (2026-11-01):** original upload is the canonical render source; the SAM provider still uploads only a temporary video-only copy. Worker verifies source hash, mask provenance, dimensions, frame count and FPS before rendering. New API→worker→render regression compares decoded PCM with the original. Capability badges derive from actual provider/result metadata (LIVE/MOCK/UNAVAILABLE). Overlaid-label mask holes documented; no dilation or artificial fill added. **296 tests**, typecheck and build pass.
- [x] **Muse Image 1.0 integration (2026-11-01):** official `POST /v1/images/generations` with `muse-image-1.0`, `n=1`, PNG/Base64, text-only prompts, aspect-ratio `size`, tool disablement, one image per approved job, job-local image + provenance sidecar, idempotent worker marker, `image` ledger slot (`0/2` used), mock/live separation, full-workflow composition with SAM masks and audio preservation. **296 tests**, typecheck and build pass. No live image request made.
- [ ] Authentication/ownership and stale-claim recovery - not implemented.

## Milestone 6 - Live Integration Gate (SAM live-validated 2026-11-01)
- [x] Verify official Meta documentation for Muse Voice Transcribe and Muse Spark; implement live adapters with budget tracking and no automatic billable retries (ADR-008, ADR-014, ADR-017).
- [x] Verify official SAM 3.1 documentation and implement the adapter + parser + mask conversion (ADR-019); offline validation complete and one live inference validated on 2026-11-01.
- [x] Verify official Muse Image 1.0 documentation and implement the adapter, PNG/Base64 validation, provenance persistence, idempotent one-per-job generation and `image` budget slot (ADR-021); no live request made.
- [ ] Propose one controlled SAM integration test and obtain explicit user approval before any live call.
