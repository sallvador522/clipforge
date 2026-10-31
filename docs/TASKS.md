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

## Milestone 6A — Real Voice Transcription (no live calls yet)
- [x] Official docs verified (speech-to-text, transcribe reference, pricing/rate limits). Confirmed model `muse-voice-transcribe-1.0`, endpoint `POST https://api.meta.ai/v1/asr/transcribe`, multipart `request` JSON + `audio` WAV, `languageBias: ["Portuguese"]`, JSON response `{sessionId, transcript, audioDurationMs, turns}`, $0.18/audio-hour (whole seconds), 32 MB/10 min caps.
- [x] `MetaVoiceTranscriptionProvider` with httpx, Bearer auth, exact multipart contract, normalization, timeout/429/API-error mapping, no retries, no key/audio logging.
- [x] `POST /api/transcribe`: upload validation, ffprobe, FFmpeg → mono 16-bit PCM WAV 24 kHz, temp cleanup, mock isolation (fixture required; audio never interpreted).
- [x] Scoped selection: `CLIPFORGE_TRANSCRIBE_MODE=live` + `MODEL_API_KEY`; other providers remain mock; missing key fails before any request.
- [x] Frontend: real MediaRecorder audio uploaded, upload/transcribe states, editable transcript review, explicit confirm, failure + explicit retry, typed alternative; mock commands hidden in live mode, MOCK badge retained in mock mode.
- [x] Tests (18 new): multipart construction, language bias, normalization, invalid audio, missing credentials, timeout, 429, API errors, mock isolation, provider selection, single-request/no-retry, confirmed-transcript planning.
- [ ] First live transcription call — **blocked on explicit user approval** after reviewing the cost estimate.

## Milestone 6B-PREP — Professional Editing Director
- [x] Ninth skill `clipforge-editing-director` (9/10 project skills) with cinematography/editing/colour/audio/social guidance and hard capability-truth rules; 6B-PREP-R adds the video-use methodology section.
- [x] Runtime playbook + validating loader (no model call); v1.1 adds ClipForge Workflows, Hosted Model Tool Protocol, Edit Decision Lists, Output Self-Evaluation.
- [x] Capability registry with five statuses, typed params, handlers, dependencies, verification, approval flags; local vs mock vs live distinguished.
- [x] `ProfessionalEditingPlan` v2 + registry/approval/dependency validators + v1 adapter.
- [x] Deterministic offline mock director scenarios A–E (blur, replacement, simulated cinematic background, clarification, unsupported).
- [x] 10 director stages with validated transitions and job-stage mapper; operation status transitions validated.
- [x] EDL v2 with capability-typed params, registry-resolved handlers, timing forbidden while trim disabled, canonical provenance; immutable history in `job.json`; evaluation report with 3-pass ledger (6B-PREP-R).
- [x] 90 new tests (160 total); docs/ADR-009 and ADR-010 updated.

## Milestone 6B-LIVE — Muse Spark Director (prepared, no live call)
- [x] Official docs verified (models, tool-calling, structured-output, Responses protocol, pricing/rate-limits). Confirmed `muse-spark-1.3`, base `https://api.meta.ai/v1`, Bearer auth, Chat Completions vs Responses distinction, `response_format` vs `text.format`, Standard pricing ($1.25/1M in, $4.25/1M out), 3000 RPM / 4M TPM.
- [x] Protocol selected: Chat Completions (single-turn plan generation; no reasoning replay, stateless, documented Pydantic structured-output flow).
- [x] `MetaEditingDirectorProvider` with mocked transport: playbook + registry loading, transcript + video metadata, one validated v2 plan, clarification/unsupported handling, concise explanations, no arbitrary tools/params.
- [x] Security: Pydantic + registry + echo enforcement, truncation/tool-call rejection, safe errors, single POST, no retries, no key/audio logging.
- [x] Cost control: Standard only, usage + per-request cost from actual usage, rough pre-request estimate, no web search, transcript text only, no background retries/duplicates.
- [x] 15 new tests (mocked transport: contract, validation, clarification, unsupported, malformed, timeout/429/API errors, isolation, selection, single-request, accounting, contributor-mode gating, reasoning_effort, contributor pricing); 175 total preserved + new.
- [x] ADR-012: Contributor-Medium variant approved (`muse-spark-1.3-contributor`, `reasoning_effort: medium`, Contributor rates $0.10/1M in + $0.20/1M out); no `context` parameter exists in the verified contract; canonical env var is `MODEL_API_KEY`.
- [ ] LIVE-CALL 001 (exactly one POST) — blocked on a valid `MODEL_API_KEY` in gitignored `.env` (currently empty). No tools execute; no SAM/image/FFmpeg; no render; no EDL execution.

## Milestone 6 — Live Integration Gate (blocked)
- [ ] Verify official Meta documentation (schemas, media inputs, mask encoding, sync/async, polling, rate limits, pricing).
- [ ] Implement live adapters behind existing interfaces; request logging, idempotency, budget tracking; no automatic billable retries.
- [ ] Propose one controlled integration test and obtain explicit user approval before any live call.
