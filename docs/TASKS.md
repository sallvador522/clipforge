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
- [ ] SAM 3.1 segmentation — blocked on explicit approval; required for real subject tracking.
- [ ] Approval/rejection endpoint + UI to resume `awaiting_approval` jobs — future milestone.

## Milestone 6B-LIVE — LIVE-CALL 003 Lite Schema (EXECUTED: HTTP 200, truncated)

- Instruction: same as 001/002 + benchmark-unit video metadata. No audio bytes, no tools, no web search.
- Endpoint: `POST https://api.meta.ai/v1/chat/completions`, `muse-spark-1.3-contributor`, `reasoning_effort: medium`, `response_format` `ProfessionalEditingPlanLite` (1,948-byte hand-written schema, 0 `$ref`s), `max_completion_tokens: 800`.
- Wire: developer 1,987 chars + user 631 chars (2,618 total, ~654 est tokens); full payload 4,899 chars.
- Result: **HTTP 200, `finish_reason: "length"`** → truncated output rejected; no plan, no EDL, no render. Schema accepted → the full v2 schema (~8.4 KB) is confirmed as the likely 500 cause; the remaining blocker is output budget. No retry.
- Cost: billable; local usage lost pre-fix. Bounded ≤ ≈ $0.00026, realistic ≈ $0.0002 at Contributor rates.
- Next (blocked): same lite payload with `max_completion_tokens: 1500` (or 1200) — one approved retry. Plain-JSON control no longer necessary.

## Milestone 6 — Live Integration Gate (blocked)
- [ ] Verify official Meta documentation (schemas, media inputs, mask encoding, sync/async, polling, rate limits, pricing).
- [ ] Implement live adapters behind existing interfaces; request logging, idempotency, budget tracking; no automatic billable retries.
- [ ] Propose one controlled integration test and obtain explicit user approval before any live call.
