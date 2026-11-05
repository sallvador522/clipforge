# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock`; transcription, the director and SAM segmentation are live-capable in isolation. Background generation and the legacy planner remain mocked. SAM live is **live-validated** on one prepared clip (2026-11-01): 1 request, 2 subjects, real masks and verified renders.
- **Milestones 0-6D:** complete through 6D offline validation and the consent gate. 6D implements the real SAM 3.1 provider, official parser, per-object masks, subject selection, previews, SAM-compatible rendering and explicit external-processing consent. **300 backend tests**; full-resolution benchmark 300 frames/1280×720/30 FPS/10 s with audio. One live SAM request was made on 2026-11-01; see `docs/SAM_31_LIVE_TEST_REPORT.md`. Other docs: `docs/SAM_31_INTEGRATION.md`, `docs/SAM_31_LIVE_VALIDATION_PLAN.md`, `docs/PRODUCT_AUDIT.md`, ADR-019 and ADR-020.
- **SAM 3.1 live validation (2026-11-01):** one real inference on the prepared clip (177 frames, 360x640, 30 FPS); HTTP 200, request id `a6b54e67-61d4-4779-9fcc-80563b7166c9`, 2 subjects (IDs 0 and 1), 177/177 frames each, real masks/previews, and three verified renders with original audio. Ledger segmentation 1/2; no retry. Report: `docs/SAM_31_LIVE_TEST_REPORT.md`.
- **SAM stabilization (2026-11-01):** the original upload is the canonical render source; SAM still receives a temporary video-only copy. A new API→worker→render regression proves PCM-identical audio preservation. Capability badges now derive from actual provider/result metadata (`LIVE`/`MOCK`/`UNAVAILABLE`). Overlaid-label mask holes remain and were not filled or dilated; use clean footage for the demo if needed.
- **Muse Image 1.0 integration (2026-11-01):** real `POST /v1/images/generations` provider with `muse-image-1.0`, text-only prompts, PNG/Base64 validation, job-local persistence + provenance, one generation per approved job and a new `image` ledger slot. Default mock; live is opt-in (`CLIPFORGE_IMAGE_MODE=live`) and **not live-validated**. See `docs/API_CONTRACTS.md`.
- **Muse Image live test (2026-11-01):** one real generation (HTTP 200, request id `c515a42f-57e9-4662-ad6e-e55a378c6b8e`) produced a 1280×1920 PNG, composited with the persisted real SAM masks into a verified 177-frame MP4 with original audio. Ledger image 1/2; no retry, no SAM call. Report: `docs/MUSE_IMAGE_LIVE_TEST_REPORT.md`.
- **Real-user mode (2026-11-01):** `scripts/real-user.env` + `scripts/start_real_user.ps1` (`.sh` parity) start API + worker + Studio with all four providers live, no mock fallback, and a per-job MODELS USED panel driven by execution metadata. Judge kit (`judge.env`, setup/start/stop scripts, `docs/JUDGE_QUICKSTART.md`) covers fresh installs. See `docs/REAL_USER_TESTING.md`.
- **Live evidence remains 6B:** LIVE-E2E 005 — real Portuguese audio → Muse Spark plan → real blur render → verified download. Director usage 2,781 in / 1,856 out = **$0.000649**; ASR **$0.000184**; run total **$0.000833**. Full log: `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`. No live call was made in 6C or 6D.
- **Post-MVP scope (2026-11-03, user-approved):** "Create from an Idea" 20 s 9:16 reels mode with a $1 cap for the first real generation; the upload editor, SAM and background replacement are untouched. Idea-to-video vertical slice implemented and verified offline: storyboard/quality contracts, mock + live (untested-live) creative directors, Anime.js 4.5 scene engine with deterministic seek capture, Playwright/Chromium offline render pipeline (480/480 frames, 720×1280, 20.00 s verified MP4), mock critic + one-revision loop. **323 backend tests**. No paid call made. See `docs/IDEA_TO_VIDEO.md` and ADR-025.
- **TEST A (programmatic-only promo, 2026-11-03):** NEXUS 15 s 9:16 tech promo built end-to-end with zero image API calls ($0.00): mock storyboard validated by the contract, first render correctly REFUSED by the new asset gate (`asset_hero` referenced but never produced), correction dropped the raster dependency (gradient backdrop + kinetic type + orb + counter + bars + drawn divider), re-render 360/360 verified MP4 (`Videos\Video\NEXUS_promo_15s.mp4`). Full review→correct→revalidate loop demonstrated on a real defect.
- **Creative engine hardening (2026-11-03):** shared `SceneRenderer` component (single animation runtime for Studio preview and headless export), READY gate on fonts + decoded images, resume-from-N capture, typography-only layout/clipping QA, deterministic counters under muted seeks. Verified: 480/480 frames, 0 black, 720×1280, 20.00 s MP4 with kinetic titles and counter. Architecture: `docs/CREATIVE_PRODUCTION_ENGINE_PLAN.md`.
- **Director lite-schema fix (2026-11-02):** a live job failed with `IsolateSubjectParams.strategy: 'mock_segmentation'`. Root cause: the lite wire schema declared `params.strategy` as a free-form string and the playbook said "mock segmentation", so the model copied the phrase into the parameter after the paid call. The schema now pins `strategy`/`asset_source`/`composition` to the same enums as the strict models, the playbook/brief say "synthetic placeholder masks", and a regression test guards the enums. One live verification call returned `strategy: largest_subject` with a fully validated plan (2,607 out tokens, $0.000625). **301 backend tests**.
- **SAM stream observability (2026-11-02):** a live SAM call died mid-stream with `httpcore.ReadError` (188 s after HTTP 200) and surfaced only the parser's generic `source_error`. `SamStreamInterruptedError` (`code=sam_stream_interrupted`) now reports elapsed time and how many stream events arrived before the drop, logs `sam_stream_interrupted` with the request id and root cause, and keeps the no-retry rule. **302 backend tests**.
- **Advisory live ledger (2026-11-02):** the ledger is now a cost meter by default — it counts and reports usage but never refuses a live call. Enforcement is opt-in only via explicit `limits=`/`enforce=True`; environment limits remain advisory and `/health` reports `live_call_budget_enforced`. Ledger integrity, atomic reservations, lock handling, no refunds and one-shot authorization are unchanged. **304 backend tests**. See ADR-022.
- **Clarification intent fix (2026-11-02):** a live job failed after a paid call with "A clarification plan requires an ambiguous subject" — the model asked about the broad background-replacement intent while correctly marking the subject unambiguous. The v2 contract now accepts intent ambiguity (question required, subject flag stays truthful); the v1 adapter and the `awaiting_clarification` flow are unchanged. **306 backend tests**. See ADR-023.
- **SAM stream recovery (2026-11-03):** five straight drops at ~150–190 s all died after all frame data arrived, during finalization silence — while the server kept the completed result (store=true default). The provider now captures the response id + last frame marker (Fase 0) and, on a drop, recovers via non-billable `GET /v1/responses/{id}` with no second POST and no new ledger slot (Fase 2). LIVE-CALL 009 (approved, ~$0.0354) dropped at 153.3 s and its single GET returned HTTP 200 `completed` with the full 177-frame output; real masks written locally at zero extra billed cost. **310 backend tests**. See ADR-024.
- **Facebook delivery (2026-11-03):** end-to-end job `5ccd24d6` with the recovery active — director `plan_ready` ($0.000825), SAM stream dropped and **auto-recovered in production** (provenance diagnostic persisted), subject 0 (man in black blazer) approved, background replaced via one Muse Image generation, render verified (177 frames, 360×640, audio preserved). Output: `storage/uploads/5ccd24d6…/Facebook_senhor_de_preto.mp4` (156,316 bytes, h264+aac). Known limits: meme text burned into the source stays visible; minor edge roughness from overlaid-label mask holes.
- **Next milestone:** evaluate real SAM quality on a 720p two-person clip with movement/occlusion and address the overlaid-label mask holes; no further live calls without explicit approval. The first live validation is complete. The LIVE-CALL 006 plan-only retest remains optional. Live planning uses the lite schema, cap 16,000.
- **Frontend note (6A follow-up):** the mock command selector was removed from the studio. Mock transcription remains available only through the backend API/tests; the UI now either transcribes live (when enabled) or offers the typed instruction. Recorded audio in mock mode is not transcribed, and says so.
- **LIVE-CALL 006 proposal (prepared, NOT executed):** exact request artifacts in `storage/live_call_006_request_standard.json` / `..._contributor.json`; playbook 10,294 chars, developer 11,096, user 705, payload 14,369, input estimate 2,950 tokens, cap 16,000. Estimated cost: **$0.013888 Standard** / **$0.000775 Contributor**; worst case at cap **$0.071688** / **$0.003495**. No request was made; no new credits consumed. See `docs/LIVE_CALL_006_PROPOSAL.md`.
- **Mock verification (6D + consent):** explicit `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=mock`, `CLIPFORGE_DIRECTOR_MODE=mock`, `CLIPFORGE_SEGMENTATION_MODE=mock`; factory returned mock/mock/mock/mock (transcription/director/segmentation/image); **300 tests** and `scripts/check.ps1` exit 0; browser E2E of consent (live-like desktop/mobile), mock no-dialog, subject selection, approval/rejection/clarification/replacement/unsupported with zero console errors; ledger `3/2` transcription/director and segmentation 1 of 2 after the live validation.
- **Local user-testing phase (2026-11-01):** the fixed 2-call caps blocked a UI retry, so ADR-015 makes them configurable. `.env` sets **100 transcription + 25 director**. The phase-005 ledger was archived; the active ledger is now `3/2` after LIVE-E2E 006, leaving **97 transcription / 23 director**. Defaults for a fresh checkout remain 2/2/2 (including segmentation); live SAM has used 1 of 2.
- **6B-LIVE-HARDENING (2026-11-01):** model-generated operation ids are canonicalised (`op_1`…`op_n`) with dependency rewriting and cycle/forward/duplicate rejection; every director call now persists a `DirectorAudit` (request ids, tokens, estimated cost, validation/error/HTTP status) even when validation fails. **226 backend tests**; no live call was made in the hardening milestone itself. Meta budget available: **$31.78**. See `docs/LIVE_DIRECTOR_HARDENING_REPORT.md` and ADR-016.
- **6B-LIVE-BUDGET-SAFETY (2026-11-01):** ledger is fail-closed (corrupt/unreadable/invalid data refuses reservations; no automatic reset), lock contention is explicit, and live providers require a one-shot `LiveCallAuthorization` that reserves immediately before the POST. Direct provider calls without authorization are rejected; `transcribe_upload(budget=None)` in live mode is rejected. Dev launchers force mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1`. **226 backend tests; no live call or credits consumed.** See `docs/LIVE_BUDGET_SAFETY_HARDENING.md` and ADR-017.
- **LIVE-E2E 006 (same day, approved):** a user portrait clip (360×640, 30 FPS, 6.177 s, audio) was transcribed and edited live. Muse planned 5 operations; the render completed at 360×640/177 frames/6.177 s/166,088 bytes with audio. ASR $0.000272 + director $0.000738 = **$0.001010**. Audit verified: `accepted`, HTTP 200, server request id captured. Output saved to the user's `Videos\Video` folder. Known limitation confirmed: the mock ellipse keeps one side subject sharp at a time, not both. Full log: `docs/LIVE_E2E_006_USER_VIDEO_REPORT.md`.
- **P0 Project Workspace & Asset Library (2026-11-04):** persistent projects (`storage/projects/<id>/project.json`, assets with `asset.json` sidecars, `ProjectStore` with atomic writes), server-validated imports (video/audio/images/text/SVG with strict SVG sanitization + malicious fixtures), project CRUD + asset endpoints, `POST /api/uploads` links each job to its project, Studio left column is the Asset Library (filters/search/multi-import/preview/two-step remove, reload persistence). Full mock edit → verified download regression preserved. **340 backend tests** (incl. 12 new `test_project_workspace.py`); `tsc` + production `next build` clean. See `docs/PROJECT_WORKSPACE_PLAN.md`. No live calls; P1–P4 deferred.

## What Exists

- Docs: PRODUCT_SPEC, PRODUCT_AUDIT, ARCHITECTURE, DESIGN_SYSTEM (tokens finalized), API_CONTRACTS, DECISIONS (ADR-001…ADR-022), TASKS, STATUS, `SAM_31_INTEGRATION`, `SAM_31_LIVE_VALIDATION_PLAN`, `SAM_31_LIVE_TEST_REPORT`, live-call, hardening and budget-safety reports.
- Skills: 9 project skills (≤10 limit) — 6 custom in `.opencode/skills/` (including `clipforge-editing-director`), `frontend-design` and `web-design-guidelines` in `.agents/skills/`, plus `motion` in `.opencode/skills/` (Motion AI Kit free tier; no Motion+ purchase).
- Backend: contracts, mock providers with explicit live transcription/director/segmentation modes, auditable job store, FastAPI (upload/voice/plan/approve/reject/clarify/subject preview/status/result/download, CORS for localhost:3000), persistent worker, FFmpeg+OpenCV renderer with verified outputs. SAM provider uses the official Responses/Files contract, `meta-sam-parser==0.1.0`, temporary video-only uploads and per-object masks. Live voice submission requires a persisted, source-bound `SubjectDetectionConsent` record; the worker and provider validate it before any upload.
- Frontend (`apps/web`): Next.js 15 + React 19 + TS + Tailwind 4 + Motion. **Editor workspace (5.1 + social exports + P0 library):** TopBar (logo, project, job state, formato YouTube 16:9 / Reels 9:16 em pills com accent signal-orange + botão Baixar), Project Asset Library sidebar (persistent project title, session-clip card, multi-file import, All/Video/Audio/Images/Text/Graphics filters, search, inline previews, two-step remove; SVG served sanitized as images), central Viewer (frame no aspect do formato com o vídeo inteiro visível, sem corte nem distorção, custom play/seek transport, before/compare/after with synced edited overlay, fullscreen), AI Assistant (signal-orange mic with real voice-level ring, MediaRecorder capture, mock-labelled command confirmation, typed-instruction alternative with deterministic matching, plan-review entry points, truthful job step tracker, clarification/rejection/unsupported/failure states), plan review dialog (dynamic operations, mock/local/live status, parameters, approval, inline clarification, SAM/mock subject cards with previews and multi-select), pre-detection live-SAM consent dialog (unchecked by default, decline without request, explicit authorize), Timeline (time ruler, 10 real frame thumbnails captured from the file, real WebAudio audio peaks, click/keyboard seek, playhead synced to the video). No billing banner and no resolution/AI-mode metadata in the navbar. `MotionConfig reducedMotion="user"` globally.
- Social exports: `GET /api/jobs/{id}/download?format=reels|youtube|original` transcodes the verified render with real FFmpeg (Reels 1080x1920, YouTube 1920x1080, cover-fit + AAC, cached under `jobs/<id>/exports/`, verified width/height/audio/duration, originals untouched). Frontend downloads `clipforge-{id}-reels.mp4` / `-youtube.mp4` with per-format loading and error states.
- Tests: **304 backend tests passing** (including director/registry/playbook/EDL/evaluation/Spark/lite/live-wiring/hardening/budget-safety, 6C approval/clarification/idempotency/restart tests, 6D SAM parser/fixtures/mask/selection/renderer tests, 20 consent-gate tests and the plan-first consent-deferral suite); frontend `tsc` clean and `next build` succeeding; web-design-guidelines audit applied.
- Local verification: `scripts/check.ps1` runs the backend suite, frontend typecheck and production build (exit code 0). No GitHub Actions/paid CI is required.
- Full-resolution SAM-compatible benchmark: `scripts/benchmark_sam_render.py` → 300 frames, 1280×720, 30 FPS, 10 s, audio preserved, 1.74 FPS, 637.7 MB peak. Raw result in `benchmarks/results/sam_render_benchmark.json`.

### First live director test — LIVE-CALL 001/002 (500) and 003 (200 truncated)

- 001/002: two POSTs, both HTTP 500 with the full v2 schema (~8.4 KB). Billing under reconciliation (panel is source of truth); $0.00 claim withdrawn.
- 003: one POST with the lite schema (1,948 bytes) → **HTTP 200, `finish_reason: "length"`** at 800 tokens. No plan accepted; no retry. This confirms the full schema as the 500 cause and isolates the remaining blocker to output budget. Billable; local usage lost pre-fix (bounded ≤ ≈ $0.00026). Observability fixed: usage recorded before validation, `server_request_id` captured.
- 004: one POST, same lite schema, cap 1500 → **HTTP 200, still truncated**. Measured usage 951 in / 1500 out = **$0.000395** (Contributor rates), `x-request-id 134244ba-83c9-4721-95ae-a5677de9c34c`. No plan. Schema accepted twice; reasoning+plan output exceeds 1500.
- Full log: `docs/LIVE_CALL_001_002_REPORT.md`, `docs/LIVE_CALL_003_REPORT.md`, `docs/LIVE_CALL_004_REPORT.md`.

## Professional Editing Director (Milestone 6B-PREP)

- Ninth skill: `.opencode/skills/clipforge-editing-director` (9/10 total). It is development guidance only; it is never sent to the runtime model.
- Runtime playbook: `apps/api/clipforge_api/prompts/professional_editing_director.md`, loaded/validated by `clipforge_api/playbook.py` (12 required sections, versioned; no network/model call).
- Capability registry: 6 executable capabilities (1 mock segmentation, 5 local), 1 planned (Muse Image, implemented as the internal `background.replace` generation step), 9 disabled. Only available capabilities can be planned; disabled features are named in explanations but never executed.
- v2 plan + v1 adapter: validation covers registry membership, typed params, dependency order, clarification/unsupported rules, approval requirements and forbidden fields. v1 remains the worker's render contract; both mock and live paths now produce v2, persist it for review and adapt it to v1 (6C).
- Mock director: deterministic offline scenarios A–E; the worker now uses this v2 director in mock mode; cinematic background states that generation happens after approval via Muse Image when live or the local mock otherwise; vague/subject-ambiguous requests ask one clarification; unsupported requests name disabled capabilities. Every ready plan stops for review.
- Stages: 10 validated `DirectorStage` values + mapping from worker stages; no fabricated percentages.
- Approval/cancel/revision at 6B-PREP: contracts/docs only; the live approval gate and execution wiring arrived in ADR-014. The full user-facing review/approve/reject/clarify/resume workflow arrived in 6C (ADR-018).

**Safety (6B-PREP):** implementation and tests ran in `CLIPFORGE_AI_MODE=mock` with `CLIPFORGE_TRANSCRIBE_MODE=mock`; zero Meta/Muse Spark/SAM/Muse Image requests at that milestone; no credentials printed or committed. Later controlled live calls are documented below.

## Live End-to-End Execution (LIVE-E2E 005)

- **Flow:** recorded Portuguese audio → `POST /api/transcribe` (Muse Voice Transcribe) → confirmed transcript → worker → lite Muse Spark director → v1 adapter → mock segmentation → real FFmpeg/OpenCV blur → output verification → `GET /download`.
- **Transcript:** “Desfoca o fundo e mantém-me nítido.” (`pt-BR`, 3,680 ms, session `clipforge-9eeb63fa8d1f443ab7c6d42b4e18300e`); ASR cost $0.000184.
- **Plan:** 5 operations (`subject.isolate`, `background.blur`, `audio.preserve`, `video.render_mp4`, `output.verify`), approval `not_required`; 4,637 tokens, $0.000649, request `req_2c45fa340028`.
- **Output:** 320×180, 10 FPS, 20 frames, 2.000 s, 36,998 bytes, audio preserved, download HTTP 200; frame inspected (subject sharp, background blurred). Job `6b9e2dc1a95a4a60839b1312e34fc592`.
- **Wiring (6B/6C):** `CLIPFORGE_DIRECTOR_MODE=mock|live` (default `mock`). Both paths produce validated v2 plans, persist them for review and adapt them to v1 for execution. Since 6C every ready plan stops at `awaiting_approval` with no render; clarification/unsupported never render. `director_plan`, `director_usage`, `director_request_id` and `director_audit` are persisted in the job result.
- **Budget protection:** `storage/live-call-ledger.json` records per-function usage. It is a **cost meter by default** (ADR-022): defaults and `CLIPFORGE_LIVE_*_LIMIT` are advisory and never refuse a call. Hard enforcement exists only when code passes explicit `limits=`/`enforce=True` (tests and one-shot scripts). Reservation still occurs immediately before the network request, counters are never reset automatically and there are no automatic retries. `/health` reports the configured limits, usage and `live_call_budget_enforced`.
- **Defects fixed:** WAV temporary input/output shared the same filename (FFmpeg refused; no network call made) — input is now `upload{suffix}`; budget reservation moved after local conversion; dev launchers load `.env` and `packages/director`.
- **Verification:** 191 backend tests, frontend typecheck + production build, independent ffprobe + frame inspection, browser smoke at `:3000` (all five regions, LIVE TRANSCRIPTION badge, `/health` on `:8001`, zero console errors). Full report: `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`.
- **Limitations (at the time):** mock segmentation is a synthetic ellipse (not SAM); replacement backgrounds remain local/mock (not Muse Image); approval was backend-only. 6C later added the resume endpoint/UI; 6D implemented the SAM provider/parser and subject selection, but live inference still waits for explicit approval.

## Director Hardening (6B-LIVE-HARDENING)

- **Issue found in a live user test:** job `0563760dec3444fd86fb797880187e46` returned a lite plan with operation ids `op1_isolate`…`op5_verify`. The internal pattern `^op_[a-z0-9_]{1,40}$` rejected an otherwise valid plan; the failure path lost usage/request metadata.
- **Normalisation:** `normalize_lite_operation_ids()` assigns `op_1`…`op_n` in original order, returns the full original → canonical map, rewrites dependencies, and rejects duplicate/unknown/cyclic/forward dependencies before full v2 validation. Capability ids, params, order and execution semantics are unchanged; the strict full-plan contract remains in force. EDL provenance is recomputed from canonical ids.
- **Audit:** `DirectorAudit` (job id, client and server request ids, provider, model, live/standard/contributor mode, wire schema, tokens, estimated cost, actual cost only when available, validation status, error category/code, HTTP status, finish reason, timestamp). The provider updates it before/after the request; the worker persists it in `JobResult.director_audit` on success **and** failure. API result serialisation uses JSON mode.
- **Verification:** 226 backend tests (50 targeted director/lite/worker, 12 budget-safety), `scripts/check.ps1` exit 0. The rejected ID pattern is recreated in tests from a valid mock plan; the raw model response was not stored. Historical job records were not modified.
- **No live call was made in this milestone.** Meta budget available: **$31.78**. A plan-only retest is blocked on explicit approval; see `docs/LIVE_DIRECTOR_HARDENING_REPORT.md`.
- **Remaining:** actual billed cost remains external (Meta panel); failed-job audit is persisted in `job.json`, while `/result` remains completed-only (use `/plan` for review states). The approval/resume UI arrived in 6C.

## Transcription (Milestone 6A)

- Provider: `MetaVoiceTranscriptionProvider` (`packages/providers/clipforge_providers/transcription_meta.py`), interface `transcription.transcribe_audio(path)`. Verified contract from official docs (model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe`, Bearer, multipart `request` JSON + `audio` WAV, `mode=PUSH_TO_TALK`, `languageBias=["Portuguese"]`, response `{sessionId, transcript, audioDurationMs, turns}`).
- Audio pipeline: browser MediaRecorder → `POST /api/transcribe` → extension/size/stream/duration validation → FFmpeg mono 16-bit PCM WAV 24 kHz → ffprobe verification → provider called **once** → normalized transcript → user reviews/edits → `POST /api/jobs/{id}/voice` with confirmed text → planner. Temp audio deleted after each request.
- Mode selection: `CLIPFORGE_TRANSCRIBE_MODE=mock` (default) / `live` + `MODEL_API_KEY`. Missing key fails before any request. Other providers stay mock. No silent fallback.
- Safety: no automatic retries, timeouts mapped to 504, 429 mapped to `transcription_rate_limited`, API errors to 502; `sessionId` logged (never key/audio); mock never interprets audio (requires explicit fixture, labelled MOCK).
- Tests: 18 new (multipart/language bias/normalization, invalid audio, missing key, timeout, 429, API error, mock network isolation, provider selection, exactly-one-request, confirmed-transcript planning).
- **First live calls made in LIVE-E2E 005:** one transcription request, 3,680 ms, measured cost **$0.000184**. The earlier 5 s estimate (≈ $0.00025) was not used. The default cap remains 2 per phase; the current local test phase uses 100 transcription calls (ADR-015).
- **WAV bug fixed:** the temporary input is `upload{suffix}` and the converted output is `recording.wav`; a regression test covers `.wav` uploads.

### Live UI readiness (historical, dummy key)

Verified with a dummy key and `TRANSCRIBE_MODE=live`: the studio shows the LIVE badge, hides mock commands, and does not call Meta on load. The transcription button is only enabled after a recording exists.

## Browser Verification (Milestone 5.1 redesign)

Full flow re-verified in the in-app Chromium on the redesigned UI: dropped a clip onto the Media panel (source selected, real 320×180/2.0s metadata), Timeline populated with 10 real frame thumbnails + audio peaks, timeline click-seek landed exactly (75% → 1.5/2.0s), typed instruction "blur the background please" matched the correct mock command, upload → confirm → job `completed` with backend transcript/plan and verified render facts, TopBar Export downloaded a real MP4 (`clipforge-1dba7953….mp4`, 36,817 bytes, video/mp4). Zero console errors; all five workspace areas present in the accessibility tree.

Follow-up layout bug (reported by the user: "the timeline doesn't appear"): the grid row had no height constraint, so the assistant's content made the row taller than the clipped viewport and the timeline fell below the fold. Fixed with an explicit `minmax(0,1fr)` row, min-h-0/overflow-hidden columns, `h-full` panels, viewer `flex-1` (the empty-state viewer had also collapsed to 132px) and a wrapping transport bar (playhead/tabs no longer clipped at 1024px). Re-verified with headless system Chrome via `apps/web/scripts/responsive-check.mjs` at 1440×900, 1280×800, 1024×768 and 390×844: timeline fully inside the viewport at every size, no horizontal overflow, desktop document height exactly equals the viewport (no page scroll), 10 filmstrip thumbnails after upload, `Export MP4` enabled only after `completed`, viewer heights 452–452/326/309 px depending on size. Screenshots captured at all four sizes for visual review.

## Browser Verification (Milestone 5)

Ran the full stack (uvicorn + worker process + `next start`) and drove the real UI in the in-app Chromium: dropped a local clip → uploaded (201, job created) → microphone correctly reported denied in headless browser → used the labelled no-microphone mock fallback → submitted → job reached `completed` with verified render facts → download button fetched a real MP4. Two separate UI sessions both ended `completed`/`verified` server-side (worker log: `rendered_and_verified frames=20`). The downloaded file was re-probed locally: video+audio streams, 320×180, 2.0 s — matches the source. Zero browser console errors. API log confirms real endpoint usage (uploads, voice, polling, result, download range requests).

## Milestone 5.2 QA (local, mock mode)

**Viewports** (system Chrome, `apps/web/scripts/qa-editor.mjs`, genuinely configured 1440×900 / 1280×800 / 1024×768 / 390×844): all five areas present at every size; timeline fully inside the viewport; no horizontal overflow; desktop document height equals the viewport; transport buttons not clipped; 10 real filmstrip thumbnails after import; `Export MP4` disabled before verification and enabled after; zero browser console errors. Screenshots: `qa52/*.png` (blur at each size, replacement at 1440, empty states).

**Microphone (real hardware)**: Windows exposes “Microphone (High Definition Audio Device)”. Headed Chrome with only the permission prompt auto-accepted (no fake audio device, `--use-fake-ui-for-media-stream`) reached the recording state, sampled the real analyser ring at 0–9% room level, recorded 4 s (UI timer 00:04), produced a Blob of 4.80 s, and playback advanced to 0.63 s. No console errors. Headless permission-denied path shows the explicit message plus the labelled fallback. Transcription remains mock-only; recording is validated, transcription is not.

**Full editing workflows**: blur and background replacement both completed through the UI with the worker’s real FFmpeg render; downloads re-probed (video + audio, 2.000 s). Interaction QA: export gating, play/pause, playhead movement (37% at 0.88 s), seek to 1.5 s, Before/After/Compare (After source = verified download endpoint), compare split `inset(0 0 0 30%)`, polling stops exactly at terminal (4 requests, still 4 after 5 s).

**Real user footage**: `Facebook_2.mp4` (360×640, 25 fps, 19.6 s) exceeds the 10 s MVP input limit, so a 10.0 s excerpt was made locally (original untouched; no external calls). Both blur and replacement rendered and verified (360×640, 250 frames, 10.00 s, audio preserved). **Honest limitation:** mock segmentation is a synthetic ellipse, so the sharp region does not follow the person - the result proves the pipeline, not subject tracking. 6D implements the real SAM provider and subject selection, but live SAM inference still requires explicit approval (ADR-019).

**Bugs fixed in 5.2**: ruler tick labels clipped at the right edge; mobile timeline header overflow; revoked filmstrip/probe blobs triggering `net::ERR_FILE_NOT_FOUND`; view-mode switches unmounting the playing video (now the verified render stays mounted as a synced overlay, so switching never aborts a blob fetch). Zero browser console errors after the fixes.

## Measured Benchmark (ADR-006, from Milestone 4)

## How To Run The Demo

1. `python scripts/dev_api.py` (loads `.env`; default port 8000, override with `CLIPFORGE_API_PORT=8001`)
2. `python scripts/dev_worker.py` (loads `.env`; persistent worker over `storage/`)
3. `cd apps/web && npm run dev` → http://localhost:3000 (API base override: `NEXT_PUBLIC_API_URL`)
4. Verify everything locally: `.\scripts\check.ps1` (pytest + typecheck + production build)

For live runs, set `CLIPFORGE_TRANSCRIBE_MODE=live`, `CLIPFORGE_DIRECTOR_MODE=live` and/or `CLIPFORGE_SEGMENTATION_MODE=live` plus a server-side `MODEL_API_KEY`. All default to `mock`; there is no silent fallback. The budget ledger and cost estimate must be reviewed before a new phase. SAM live has not been validated and must not be activated without explicit approval.

## Plan Review, Approval and Resume (6C)

- **Mandatory review:** every ready plan (blur or replacement) is persisted as v2 + v1 adapter and stops at `awaiting_approval`; 6D adds subject detection before review, but no render happens. Approval atomically returns the job to `queued`/stage `approved`; the worker reads the persisted plan and renders once without calling the director again.
- **Rejection/unsupported:** terminal states with no output. The original upload is untouched.
- **Clarification:** inline answer, original instruction/context preserved, maximum 3 rounds; a revised plan returns to review.
- **State/audit:** new statuses `awaiting_approval`, `awaiting_clarification`, `rejected`, `unsupported`; `state_history` records every user/worker status/stage change. User transitions use a cross-process `transition.lock`; claims are released after each worker run so approved jobs can resume.
- **Mock Director v2:** `CLIPFORGE_DIRECTOR_MODE=mock` uses `MockProfessionalEditingDirector`; the legacy keyword planner is no longer the worker's mock path. Live validation is unchanged.
- **Verification at 6C:** 234 backend tests; duplicate/concurrent approval and restart tests; browser E2E with blur desktop/mobile, replacement, reject, clarification and unsupported, 4 real MP4 downloads (video + audio) and zero console errors. 6D extends the suite to 272 tests and adds subject selection plus the external-processing consent gate.
- **Remaining:** the mock provider is still a synthetic two-ellipse track; real SAM is live-validated on one prepared clip; broader quality is still unknown. No authentication/ownership; no automatic stale-claim recovery after a hard crash mid-render.

## SAM 3.1 and Subject Selection (6D)

- **Explicit consent gate (ADR-020, plan-first order):** the worker runs the Director first and, only for plans that isolate a subject, pauses live jobs at `awaiting_consent` for explicit SAM consent via `POST /api/jobs/{id}/consent` — no SAM call before that. Consent binds job, source SHA-256, timestamp, disclosure version, provider and model; granting re-queues the job and the worker resumes the persisted plan without re-running transcription or the director. Worker and provider revalidate before upload; plan approval is not consent. Browser dialog is Portuguese, unchecked by default, "Not now" pauses without triggering anything, and mock mode never asks.
- **Real provider live-validated (2026-11-01):** `SamSegmentationProvider` follows the official `sam-3.1` Responses contract (`POST /v1/responses`, `input_video.file_id`, `stream=true`), uses the official `meta-sam-parser==0.1.0`, and requires a one-shot `LiveCallAuthorization`. One live request returned HTTP 200 (request id `a6b54e67-61d4-4779-9fcc-80563b7166c9`) with 2 subjects and 177/177 frames; no retry was made.
- **Privacy:** temporary video-only MP4 (no audio; exact dimensions/FPS/frame count verified), Files API upload with `purpose=user_data` + 1-hour expiration, `file_id` reference, delete in `finally`. The original is untouched; source SHA-256 is recorded. Cleanup failures are stored without credentials.
- **Masks:** per-object PNG sequences + union, stable SAM object IDs preserved exactly, explicit frame markers, absent frames zero-filled only after a completed clean stream, no silent resizing, no incomplete-manifest rendering. Up to 16 objects/frame.
- **Selection:** detection runs before review; the dialog shows source-frame previews and stable IDs; `POST /approve` takes `subject_ids`; one subject is preselected, multiple require an explicit choice. Zero detections is a terminal `NoSubjectsDetected` result with no render.
- **Renderer:** selected object masks are unioned with bounded memory and consumed by the existing FFmpeg/OpenCV renderer; audio/resolution/timing stay verified. Selective person blur is **not** supported.
- **Benchmark:** 300 frames, 1280×720, 30 FPS, 10 s, audio preserved; 1.74 FPS, 637.7 MB peak, output 1,103,667 bytes. Raw: `benchmarks/results/sam_render_benchmark.json`.
- **Validated on one clip:** real detection, streaming completion, Files API upload/expiry fields (HTTP 200), DELETE (HTTP 200, `deleted`), 2-subject masks, previews and selection renders. Still unvalidated: 720p/occlusion quality, a follow-up cleanup existence check and overlaid-label mask holes. See `docs/SAM_31_INTEGRATION.md` and ADR-019.

## Blockers / Uncertainties

- **Live SAM 3.1 validation is complete on one prepared clip.** Detection quality beyond 360x640/5.9s, occlusion behavior, 720p quality and the overlaid-label holes remain unknown. Further live calls need explicit approval; the ledger slot is advisory (ADR-022) and no longer blocks.
- **Muse Image live generation is validated once on 2026-11-01.** The provider, PNG/Base64 validation, persistence, one-per-job marker and mock/live separation are implemented and offline-tested (300 tests); one real request produced a 1280×1920 plate composited with real SAM masks. No further live calls without approval. Default remains mock.
- **Multi-user authorization is not implemented.** The API is a local single-user service scoped by job id; this is acceptable for the demo but must be added before deployment.
- **Live budget:** the active ledger is `11/15/8/7` for transcription/director/segmentation/image. Two director calls were the user's Studio retries (one failed on the `strategy` schema bug, one succeeded); two more were the 2026-11-02 fix verification (one returned a valid plan but crashed in the harness before recording, one recorded the artefact). The second segmentation slot was consumed by a stream drop: the slot is reserved immediately before the billable Responses POST, so a mid-stream transport failure still bills it. Since ADR-022 these numbers are a **cost meter, not a cap**: segmentation is no longer blocked and no limit change or reset is required to keep testing. LIVE-CALL 001/002 billing remains unknown (Meta panel is source of truth). LIVE-CALL 009/010/011 added 1 director ($0.000872), 1 segmentation (~$0.0354) and 4 image (~$0.01 each); the idea-to-video delivery spent ≈ $0.041 of its $1 cap. (Other ledger growth comes from the parallel session's live testing.)
- No licensed real-world footage with manual masks (ADR-007); the Facebook_2 test confirms mock masks do not track a real person.
- System FFmpeg is from 2018; upgrade recommended before production (not done silently).
- No frontend unit-test runner yet (backend suite + browser verification cover behaviour); shadcn primitives are local customised components, not Radix-based CLI output.

## Handoff

Read AGENTS.md, this file, `docs/PRODUCT_AUDIT.md`, `docs/SAM_31_INTEGRATION.md`, `docs/SAM_31_LIVE_VALIDATION_PLAN.md`, TASKS.md, `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`, `docs/LIVE_E2E_006_USER_VIDEO_REPORT.md`, `docs/LIVE_DIRECTOR_HARDENING_REPORT.md`, `docs/LIVE_BUDGET_SAFETY_HARDENING.md` and `docs/LIVE_CALL_006_PROPOSAL.md`. The full mock loop is demonstrable: upload → instruction → v2 plan → detect subjects → review/select → approve/reject/clarify → real render → verification → before/after → download. The voice → Muse Spark → render path has been executed live twice; 6C/6D made no live calls. Defaults remain mock. Real SAM 3.1 is implemented, offline-validated, protected by an explicit consent gate and live-validated once on 2026-11-01 (1 request, 2 subjects, 177/177 frames, verified renders); the image provider was live-validated once. No further live call is authorized without explicit approval. The prepared LIVE-CALL 006 plan-only retest remains optional. The local `.env` has transcription and director live with advisory limits 100/25; the real-user launcher runs all four providers live. Meta budget available before E2E 006: **$31.78**; run cost **$0.001010**; no new credits were consumed by 6C/6D. The ledger is advisory (ADR-022) and no longer blocks; watch `/health` and the Meta panel for cost.

**Budget safety (ADR-017 + ADR-022):** the ledger is fail-closed on integrity (corrupt/unreadable data refuses reservations) but advisory on limits: by default it counts usage and never blocks. Live providers require a one-shot `LiveCallAuthorization` that reserves before the POST; direct calls without it are rejected. `transcribe_upload(budget=None)` is rejected in live mode. Dev launchers force mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1`. Hard caps exist only when code passes explicit `limits=`/`enforce=True`. `/health` reports `live_call_budget_enforced`. The current `.env` may remain live for deliberate testing, but the dev launchers do not activate it implicitly.

## Idea-to-Video product flow (2026-11-03)

Product slice delivered and offline-verified: `/?mode=idea` workspace, two cost approvals, manifest + `/render/[ideaId]` capture of the shared scene engine, verified MP4 only. 26 idea tests pass (full suite 365), typecheck + build clean, isolated browser smoke done with no agent render and no paid calls (ledger `12/15/8/7`). Docs: `docs/IDEA_PRODUCT_FLOW.md`, ADR-028, TASKS 7.1. Live idea modes stay mock by default; the user runs the manual checklist before any live approval. The parallel P0 workspace work is untouched.

## Single-route Studio (2026-11-03)

The `?mode=idea` split is gone: `/` is the only route and the assistant routes the empty platform into an idea job (clip present → edit unchanged). `IdeaPreview`/`IdeaStatusPanel` reused inline; `IdeaStudio`/`IdeaBriefPanel` removed. Typecheck + build clean. Docs: ADR-029, TASKS 7.2, `IDEA_PRODUCT_FLOW.md` updated.

## Static-board fail-fast + high effort (2026-11-03)

Live `qa_failed` root-caused: descriptive targets left scene 1 fully static; boundary samples flashed; HEAD asset check 405d all plated renders. Fixed with target validation, mid-frame sampling clamped to the engine timeline, advancement checks, streaming-GET assets, and storyboard effort **high** (xhigh 504s; 300 s timeout). Live board delivered verified (480/480, 37 holds). Tests: 38 idea + full suite (377) pass. Docs: ADR-030, TASKS 7.3.

## Motion-first director + fuller Anime.js (2026-11-03)

Stage model no prompt, motion budget validado, 9 easings + 5 primitivas novas, tipografia auto-fit. Mock exercita o novo. Tests: 41 + 380. Docs: ADR-031, TASKS 7.4. Fase C (multi-plate) pendente de validação.

## Multiplane foreground — Fase C pronta e provada (2026-11-03)

Fundo + frente por cena (banda 62% inferior, parallax diferencial), validado e com prompt próprio. Smoke mock ponta-a-ponta: MP4 120/120 verificado, prova diferencial de camadas. Tests: 45 ideia + suite 384. Docs: ADR-032, TASKS 7.5. Agressão zero ao mock/edição existente.

## Studio premium em PT-AO, chat com o Muse (2026-11-04)

Redesign hallmark só-frontend: 3 regiões, tabs Projeto/Recursos, chat com histórico da sessão e cartões inline, TopBar mínima, copy PT-AO sem jargão. Typecheck + build limpos, zero erros de consola, fluxo ideia verificado em mock. Sem commits.

## Reorganização do editor em layout profissional (2026-11-04, ADR-043)

Shell `[rail 44px + Recursos 256px] | palco | [Propriedades / Muse 360px]`; Timeline full-width com toolbar (ferramentas honestas, pill `Cena principal`, zoom 0.75–3x), ruler `00:00/15f`, headers V1/T1/FX/OV/A1 ou V1/A1, playhead accent. Novos `EditorRail.tsx` + `PropertiesPanel.tsx`; `MediaPanel`/`Viewer`/`Timeline`/`AssistantPanel`/`TopBar` restyle; marca, tokens e copy intactos, sem azul da referência, sem capacidades novas. `tsc` + `next build` limpos; upload real `studio-clip.mp4` → 10 thumbnails + picos, 0 erros consola; 1440/1280/1024 sem overflow (docH == viewport), 390 empilhado. Sem chamadas pagas (upload sem `ready`, worker não reclama). Screenshots em `editor-redesign/`.

## Montagem multitrack real (2026-11-04, ADR-044, pós-MVP)

Saída deliberada do MVP aprovada pelo utilizador: arrastar assets dos Recursos para V1/V2/A1/A2, blocos com mover/aparar/remover, botão `Montar` com render FFmpeg/OpenCV real (z-order V2>V1, 1280x720@30, mix áudio) e MP4 verificado para download. Teto 15 min (baixado de 30 a pedido; probe/uploads/assets/áudio; 720p/30fps mantidos). Contrato `timeline.py`, `PUT` total validado, `POST /timeline/render` auditado, trim handles incluídos. 16 testes novos (incl. regressão do preflight CORS — o `PUT` faltava nos métodos permitidos e o browser reportava API inalcançável no drop) + e2e browser em stack mock isolada (drop→bloco→mover→Montar→`Concluído`/`editado · verificado`→Exportar, 0 erros consola). Diretoria se mantém cega à timeline nesta etapa — snapshot só de leitura e operações do diretor ficam para as próximas etapas (ADR-044).

## Recursos com gerados + faixa de cenas na timeline (2026-11-04)

Publicação automática de plates/SRT/MP4 como assets "Gerado" no projecto da ideia (idempotente, sem falhar o render); ideia ligada ao projecto na criação; timeline com faixa de cenas clicável (só leitura, seek real no player). Smoke mock: 5 assets, MP4 120/120 verificado, seek 2.51s/0.01s, zero erros de consola. Tests: 4 novos; suite 388. Docs: ADR-033, TASKS 7.6.

## Edição de cenas 1-2: texto + eliminação (2026-11-04)

`PATCH /storyboard` aceite após conclusão/falha com a mesma validação e guarda `expected_hash`; edições que pedissem imagens novas são rejeitadas (`storyboard_new_images`), gerados idênticos preservados — custo $0.00. Eliminar redistribui a duração e escala os passos (sem cauda estática); última cena protegida. UI PT-AO no painel (revisão + bloco "Cenas" no concluído); timeline continua a navegar. Tests: 4 novos em `test_idea_api.py`; suite 392; `tsc` limpo. Sem renders do agente; teste manual pelo utilizador. Docs: ADR-034, TASKS 7.7. Adicionar cenas/elementos (chamada paga) continua pendente de desenho aprovado.

## Duração à escolha, trava dos 20 s removida (2026-11-04)

Pills 15/20/25/30/60 s no composer quando vai criar ideia; automático lê o texto ("25 segundos", "30s", "1 minuto") e vence o default, pill tocada vence a deteção; valor aplicado ao `POST /api/ideas`. Motivação: board live de 25000 ms chumbou contra projeto de 20 s (`storyboard_failed`, 1 chamada paga perdida). Sem mudança de contrato/preços. Test: 25 s soma 25000 ms; deteção 10/10 no código compilado; `tsc` + `build` limpos. Docs: ADR-035, TASKS 7.8.

## Dura��o do Director + refinamento por voz (2026-11-04, ADR-036)

Boards j� n�o s�o rejeitados por dura��o: `duration_seconds` deriva da soma das cenas (regress�o 75000 ms coberta), tetos de 60 s removidos, e o refinamento por voz/texto existe no trilho idea: instru��o -> patch tipado do Director real (tipografia, anima��o, texto, cenas, tom) -> aprova��o -> board actualizado -> preview imediata, re-render expl�cito. Live apenas, sem caminho mock novo; **validado ao vivo em 2026-11-04 (ADR-038)** - reteste HTTP 200 ($0.000410, dentro do teto $1). Suite 407 testes, `tsc` + build limpos.

## Edição de timeline no trilho idea (2026-11-04, ADR-039)

Trim (1–15 s), split (playhead ou meio) e reorder (botões + arrasto na V1) sobre o storyboard, via PATCH + re-render explícito, sem custo. Multitrack, transições editáveis e trim do upload ficam fora de âmbito (declarado). `tsc` + build limpos, helpers verificados em execução, 3 testes API novos, suite 407, zero chamadas pagas.

## Transições editáveis + multitrack de sobreposição (2026-11-04, ADR-040)

Transição de saída por cena (corte/fundido/dissolver/cortina/zoom, 400 ms) executada pelo motor; camada OV com overlays de texto globais (máx 3), faixa própria na timeline e CRUD no painel; 4 operações de voz no patch. Ligações de vídeo sobrepostas, durações de transição editáveis e trim do upload continuam fora. `tsc` + build limpos, 4 testes novos, suite 411, zero chamadas pagas.

## Trim + áudio do upload, overlay de imagem, duração de transição (2026-11-04, ADR-041)

Overlay de imagem reutilizando plates geradas (falha fechada `overlay_asset_missing`, preview=export); `transition_ms` 200–1000 por cena (motor+UI+voz); trim do clipe (e2e real: 1s → corte 0.2–0.8 +6 dB + fades, MP4 0.6s verificado com áudio, original intacto); trim/split/reorder manuais e2e via PATCH. Suite 414, `tsc` + build limpos, zero chamadas pagas.

## Voz para a timeline, upload manual permanente (2026-11-04, ADR-042)

Trim, split e reorder por voz no trilho idea (`set_scene_duration`, `split_scene`, `move_scene`; wire lite 2.871 bytes; aplicador com as mesmas regras do editor manual). Upload trim/áudio ficam manuais — registo inalterado. Suite 416, `tsc` + build limpos, zero chamadas pagas.

## Timeline honesta estilo profissional (2026-11-04, ADR-037)

Trilho de clipe resolvido: em idea mode a timeline ja nao mostra "importa um clipe"/"sem clipe" — rende V1 cenas + T1 texto + FX animacoes (posicionadas por start/duration reais) + A1 honesto, tudo so-leitura com click-to-seek; em clip mode V1/A1 mantem thumbnails e picos reais com badge de verificado. Sem trim/drag/multitrack: edicao continua no painel Cenas e no refinamento por voz. `tsc` + build limpos, suite 401, zero chamadas pagas.

## Muse conversacional com execução por aprovação (2026-11-04, ADR-045)

`POST /api/chat` side-effect free (router determinístico: smalltalk/help/status/cancel/clarify/edit_proposal/idea_proposal; nunca cria jobs/ideas, nunca toca no ledger, nunca chama providers). Studio chat-first: texto/voz → `/api/chat` → resposta do Muse; intenções acionáveis guardam `pendingChat` com cartão `Posso executar?` (Executar/Ajustar/Cancelar) — execução só via `voice`/`ideas` existentes (consentimento/aprovação intactos). `olá` responde sem criar nada. Suite 437 (5 novos `test_chat_api.py`), `tsc` + `next build` limpos, e2e browser em stack isolada (`qa-chat.mjs`: olá→resposta sem Executar, proposta→cartão, Executar→ideia com aprovação de custo, 0 erros consola). Ledger inalterado (`22/24/8/16`), zero chamadas pagas. Implementado sobre o working tree partilhado com outra sessão ativa (41 ficheiros dirty pré-existentes); verificação isolada em `storage/_chat_qa` + cópia web em `$TEMP/clipforge-web-qa` (portas 8001/3001).

## Texto selecionável, cor local e ferramentas reais do Muse (2026-11-04, ADR-047, hackathon final-rescue)

Rescue P0/P1 do editor: textos passam a dados reais do projeto (contrato + JobRecord + PUT/GET /texts + /colour), queimados no Montar/Export pelo worker (PIL fade+rise só na janela; grade contraste/brilho/saturação por frame), capacidades text.overlay + colour.adjust available_local. Muse com 10 ferramentas reais validadas (POST /tools/execute após confirmação) + propostas PT no chat com select_text_id e regra de ambiguidade. Studio: guarda de seleção no clique (o clique simples estava quebrado), edição inline, Propriedades com cor/peso, cor com Aplicar, persistência backend. Testes: test_clip_texts.py (11) + test_texts_render_e2e.py (compose 90f 1280x720 com áudio + tool-edit + re-render); suite 455; tsc + build limpos; qa-rescue.mjs em stack isolada (8001/3001, mock): adicionar→persistir→selecionar→Propriedades→inline→cor→Muse Executar→Montar→verificado, 0 erros consola. Entregáveis reais em Videos/Video: ClipForge_Final_PropertiesTest.mp4 + ClipForge_Final_Editing.mp4 (6 s, 1280x720, h264+aac, contact sheets). Zero chamadas pagas na missão; live Muse reasoning = NOT VERIFIED. Re-verificado em 2026-11-04: suite 449 passed, tsc + build limpos, qa-rescue.mjs OK (0 erros), entregaveis regenerados e validados (ffprobe 1280x720 h264+aac 6.0 s), ledger 22/24/8/16 ($0.00/$5.00). Veredicto: READY WITH LIMITATIONS, ver relatorio §K.

## Entrevista do director + anexo + legendas (2026-11-04, ADR-048)

Chat pergunta estilo/duracao/formato com chips antes de propor a ideia (stateless, brief preservado); anexo de video no composer com retorno honesto; fundo anunciado via director (SAM 3.1 + Muse Image, sem bypass); tool captions.create (timing uniforme declarado, tudo editavel). Testes: test_chat_interview_captions.py (15); suite 464; tsc + build limpos; qa-chat2.mjs em stack isolada (8003/3003, mock): entrevista→ideia com opcoes, anexo real, legendas 1 execucao, fundo SAM, 0 erros consola. Zero chamadas pagas; ledger 22/24/8/16.

## Legendas reais com turnos ENDPOINTING + cover de queimadas (2026-11-04, ADR-049)

SAM nao ouve (visao apenas); Spark adivinhar tempos seria fabricacao. Docs oficiais confirmam turns {turnId,startMs,endMs} em ENDPOINTING. Provider estendido + TranscriptTurn validado; 2 chamadas pagas aprovadas ($0.00190): 1a falhou na nossa validacao (turnId 0, corrigido sem retry automatico), 2a devolveu 1 turno real 0-19.02s do Facebook_2 (EN). Tools captions.create_from_turns (9 linhas temporizadas) + captions.cover (blur fixo); E2E real: upload 19.61s → Montar worker → MP4 19.6s 1280x720 h264+aac verificado em Videos/Video/ClipForge_Facebook2_Legendas_Timed.mp4 (588 frames, texto centrado na faixa). Suite 479; tsc + build limpos; qa-chat2.mjs com cover (1 execucao, 0 erros). Ledger transcricao 24/25.

## Traducao PT com Spark + pergunta de idioma (2026-11-04, ADR-050)

Muse pergunta o idioma nas propostas (nao assume); tool captions.translate ledger-autorizada (~$0.0001, fail-closed). Traducao live: 2 tentativas diagnosticadas (truncacao por reasoning, corrigido com effort minimal + cap 1500), 9 linhas PT com tempos reais → Videos/Video/ClipForge_Facebook2_Legendas_PT.mp4 (19.6s 360x640 verificado, contact sheet). Custo total missao legendas ~$0.002. Suite 484; ledger director 25/25 (fase cheia).

## Magic Background — fundo programático animado, full-stack mock (2026-11-04, ADR-052)

Isola sujeito (mock SAM) + fundo gradiente azul animado gerado localmente por frame (sem Muse Image, sem custo); publica o MP4 como asset; formato preservado por omissão; legendas com auto-fit + verify/redo. Testes programáticos (6) + canvas (4); suite 497; tsc + build limpos; qa-magicbg.mjs PASS (chat→review→select→approve→download real, 0 erros); deliverable Videos/Video/ClipForge_MagicBackground_Programmatic.mp4 (5 s 640x360 h264+aac verificado). Live SAM validado 2x sem retries (recorte 5 s: sujeito 0 125/125, \.025; Facebook_2 completo 19.6 s/490 frames: sujeito 0 490/490, \.098) -> Videos/Video/ClipForge_MagicBackground_Facebook2_Live.mp4 (360x640@25fps h264+aac, fundo animado 73.6% + sujeito real). **Live SAM executado e validado ($0.025, sem retries): Videos/Video/ClipForge_MagicBackground_LiveSAM.mp4 (máscaras reais, sujeito 0 125/125, fundo animado 73.6%).** Zero chamadas pagas além da SAM aprovada.

## Formato original por omissao + legendas que cabem sempre (2026-11-04, ADR-051)

Montar ja nao converte tudo para 1280x720: canvas/fps derivam do primeiro V2 (senao V1), fallback 1280x720@30 so sem video; `POST /timeline/render {format}` (source default) + seletor Original/16:9/9:16 no Studio. Burn-in com auto-fit (wrap + shrink ate 12px, bloco dentro do frame) e `verify_caption_legibility` com redo (reduz escala, re-renderiza 1x) no fluxo de entrega. Facebook_2 recomposto: Videos/Video/ClipForge_Facebook2_Legendas_PT.mp4 360x640@25fps, 490 frames, verificado por pixels. Suite 490 (1 flaky de lock Windows, passa isolado); qa-rescue + qa-chat2 PASS, 0 erros. Gotcha FastAPI 0.162: modelos Pydantic aninhados como body opcional viram query params — body models ao nivel do modulo. Zero chamadas pagas.

## Chat ao vivo com Muse Spark (2026-11-04, ADR-053)

`CLIPFORGE_CHAT_MODE=mock|live` (default mock); live = Muse Spark reescreve só o `reply` (contrato Chat Completions verificado, contributor/minimal/cap 600), router determinístico continua a decidir intent + proposta (aprovação/consentimento intactos). 1 POST + 1 slot `chat` no ledger por mensagem, sem retries, fail-closed sem chave; `/health` com `chat_mode`, Studio mostra `Ao vivo · Muse Spark`. Estimativa ~$0.0001/turno (teto ~$0.00032). Suite 503 passed; `tsc` limpo; zero chamadas pagas feitas — o utilizador testa na stack ligada com a própria conta.

## Final hackathon E2E rescue (2026-11-04)

Auditoria completa utilizador→download: 509 testes backend, `tsc`+build limpos, 5 suites browser reais PASS com 0 erros de consola (`qa-final-e2e` novo: upload UI com nome acentuado→download original SHA-256 idêntico→422 em `.exe`→reload→zoom→Montar→Exportar ffprobe; rescue/chat/chat2/magicbg). Corrigido P1: assets sem acção de download (cartão de sessão + linhas da biblioteca, endpoint real com Content-Disposition). `qa-chat.mjs` actualizado para a entrevista ADR-048. Entregáveis novos em Videos/Video: `ClipForge_E2E_PropertiesEditing.mp4`, `ClipForge_E2E_ExistingVideoEdit.mp4`, `ClipForge_E2E_Timeline.mp4` (h264+aac verificados). Zero chamadas pagas; ledger intacto 24/27/8/16/17. Live Meta e voz = NOT EXECUTED nesta missão. Relatório: `docs/HACKATHON_FINAL_E2E_REPORT.md`. Veredicto: READY WITH LIMITATIONS.

## Transcrição do áudio-fonte em blocos (2026-11-04, ADR-060)

Teto 10 min/bloco respeitado: estimativa antes, async com poll, junção com offsets, falha sem parcial, chat propõe com blocos + USD. Testes: `test_source_transcript.py` (8) + suite 559; zero chamadas pagas.

## Retomar upload + ETA adaptativo (2026-11-04, ADR-059)

`PendingUpload` no localStorage retoma o mesmo ficheiro após reload (sem re-PUT, status honesto); EMA local calibra o Montar e mostra ETA por máquina; sem mudanças backend. Testes: browser PHASEB (5/5, 0 erros) + suite 559; zero chamadas pagas.

## Upload 30 min retomável (2026-11-04, ADR-058, produção)

Protocolo fatiado (init → PUT raw idempotente → status → complete → abort) com retry ×3 e progresso real; teto 30 min na validação, programa e régua; single-shot preservado via finalize partilhado. Testes: `test_chunked_upload.py` (5) + browser CHUNKED-UI (0 erros); suite 558; zero chamadas pagas.

## Consentimento SAM vinculado ao recorte (2026-11-04, ADR-056)

Trim + SAM live deixa de ser recusado: o consentimento vincula (job, hash original, janela) e o worker/provider verificam ambos antes de qualquer upload; diálogo mostra o trecho. Testes: `test_consent_trim_rebind.py` (5) + browser até ao diálogo (recusado, ledger intacto); suite 525; zero chamadas pagas.

## Trecho da timeline para o Director (2026-11-04, ADR-055)

Marcar Início/Fim na timeline → chip + faixa; o Muse cita o trecho com estimativa honesta (frames + $ SAM) e o Executar aplica o recorte antes do fluxo normal. Testes: `test_chat_segment.py` (6) + browser SEGMENT-E2E (trim aplicado, director em curso, 0 erros); suite 520 passed; tsc+build limpos; ledger intacto, zero chamadas pagas.

## Hackathon README + presentation docs (2026-11-04)

README升級 sem ficção: atribuição (António Salvador, Angola; Muse Wonder só desenvolvimento — ausente do runtime, verificado por grep), tabela Meta com I/O real por modelo, diagrama Mermaid do ecossistema, matriz Capability status (13 linhas, classificações honestas), números verificados (513 testes, next 15.5.28, motion 12.43.0), links internos 22/22 OK, sem segredos. Novos: `README.pt-AO.md`, `docs/HACKATHON_PROJECT_OVERVIEW.md`, `docs/HACKATHON_DEMO_GUIDE.md`. `.env.example` já completo, sem alterações. Comandos de instalação verificados contra configuração (não executados); tsc+build+pytest herdados da missão UI/UX (sem mudanças de código desde então).

## UI/UX quality rescue (2026-11-04, `/ui-ux-rescue`, frontend-only)

Auditoria de interacções no browser real (stacks mock isoladas, zero chamadas pagas): `friendlyApiError()` em `lib/api.ts` (20+ call sites PT-AO, sem inglês técnico nem URLs); upload falhado já não deixa sessão falsa (limpa file/blob/duração, volta ao empty state, status "Precisa de atenção"); rename desactivado e honesto antes do import; transporte 00:00.0/00:00.0 consistente no vazio. Suites: `qa-ux-rescue` (shots 4 viewports + interacções), audits DOM 13/13 + 9/9 (overflow 1920/1440/1366/390 vazio e populado, pills radiogroup, rename, no-dupe send, focus-visible), `qa-final-e2e`/`rescue`/`chat`/`chat2`/`magicbg` PASS 0 erros; `tsc`+build limpos; backend 513 passed sem alterações backend. Ledger intacto. Relatório: `docs/UI_UX_QUALITY_REPORT.md`. Veredicto: pronto para apresentação com as limitações registadas.

## Director conversacional com contexto real (2026-11-04, ADR-054)

O chat ja nao trata perguntas como ordens de edicao: `chat_context` junta ProjectStore/JobStore/IdeaStore em snapshot pequeno + historia resentida (ate 12 turnos) e responde a "quantos videos tenho?", "o que eu tenho?", "o que foi feito?" e follow-ups meta sem pending. Instrucoes de edicao reais continuam a passar por Executar (sem side effects ate confirmacao). Suite de chat: 37/37 (inclui barreira anti-gibberish e regressão do crash 500 em pergunta direta); suite completa 514 passed; `tsc` + `next build` limpos; sem chamadas pagas novas.

## Muse Spark native video understanding (2026-11-04, ADR-057)

Muse passa a receber o vídeo de verdade: `POST .../assets/{id}/analyze` normaliza para MP4 só-vídeo, faz upload uma vez por versão (`POST /v1/files`, reutilizado por SHA-256) e corre uma análise Responses (`input_text` + `input_file`), sem retries, sob um slot `video_analysis` do ledger. Modo mock por omissão (fixture simulada, zero custo). Chat responde de cache; sem cache aponta o botão «Analisar vídeo» do painel Propriedades. Contrato `VideoAnalysis` nunca inventa campos; timestamps sempre aproximados. Suite: `tests/test_video_analysis.py` (21 testes); suite completa 574 passed; `tsc` + `next build` limpos. TEST 1+2 live executado com aprovação: Facebook_2 analisado de verdade ($0.000709), file_id reutilizável, servido via GET + chat.

## Chat segue a seleção dos Recursos + anexo vira asset (2026-11-04, ADR-061)

Correção de dois falhanços encadeados reportados com o MP4 real: (1) o chat ignorava o asset selecionado na biblioteca — `POST /api/chat` agora aceita `selected_asset_id`, validado contra o projeto efetivo no backend, e o router responde da análise desse asset (fallback: clipe do job por sha256; vários analisados sem desempate → pergunta qual, sem escolha silenciosa; seleção sem análise → aponta «Analisar vídeo» nomeando o asset); fallback sha256 no mesmo projeto cobre re-imports. (2) anexar vídeo com clipe carregado morria em silêncio no `uploadFileObject` (que recusa com job ativo) com mensagem enganadora de formato — agora importa como asset da biblioteca, seleciona-o e sugere analisar. `tests/test_chat_selected_asset.py` (8 testes); 574 passed no total; `tsc` + build limpos. E2E no browser adiado a pedido — fica como follow-up.

## Fix 2026-11-05 — conjugação "analise/analises" caía na entrevista de ideia (ADR-061)

Reportado com o MP4 real: "analise o video para mim" / "estou a (a)pedir para analisar" / "quero que analises ele" respondiam "…ainda não tenho análise… Que estilo queres para o vídeo?" — o trigger exato não cobria a conjugação, o `answer_project_question` devolvia `None` e o `_classify_chat` sem clipe caía em `idea_proposal` → `_interview_turn` (estilo). Em live o Spark reescrevia esse base e juntava o nome/duração reais do asset + a pergunta de estilo. Correção backend-only: `_requests_visual_analysis` aceita a raiz "analis"/"anális" (qualquer conjugação; não há outra análise no produto), resposta de seleção determinística ("qual video tenho selecionado" nomeia o selecionado e o estado da análise, sem estilo), e guarda-redes no `/api/chat` que nunca deixa um pedido de análise/seleção ir ao interview. Verificação: chat suites 26 passed (10 seleção + 16 contexto); suite completa pós-fix **576 passed**; API destacada reiniciada e depois parada a pedido (sem listeners). Zero chamadas pagas na verificação (mock). Smoke live sem Executar pendente de aprovação com estimativa.

## Chat permanece aberto após Montar/verificado (2026-11-04, fix)

Causa: `voiceSubmitted` bloqueava textarea/mic/anexo/enviar após a primeira instrução e `canConfirm` era `false` com `job.status=completed`; o cartão `Vídeo pronto e verificado` ficava visível mas sem forma de falar com o Muse — `Recomeçar` era a única saída e perdia o contexto. Correção frontend-only: `AssistantPanel` ignora o legado `submitted` (removido da interface e de todos os gates), `Studio` usa `canConfirm={!pendingChat}` (chat-first ADR-045: `/api/chat` é side-effect free, execução só via `Executar`). Verificação: `tsc` limpo, `next build` limpo, chat suites 29 passed, e2e isolado (8001/3001, mock) drop→Montar→`completed/verificado`→`ola`→resposta→2º turno, 0 erros consola. Zero chamadas pagas.

## Drop no vazio cria job a partir do asset (2026-11-05, ADR-062)

Sem job não havia `assembly` e a V1 recusava o drop em silêncio. Agora a V1 vazia aceita o drop (`onEmptyDrop`), o Studio valida (só vídeo com duração; texto/áudio com mensagem honesta) e cria o job via `fetch(assetFileUrl)->File->uploadVideoChunked` (sem IA), com auto-place na V1. Original da biblioteca intacto (job usa cópia `session_source`). Verificação: `tsc` + `build` limpos, timeline suites 18 passed, browser isolado (API :8001 + web :3000, mock) com asset 4 s sem job — hint "Arrasta um vídeo para aqui para começar", drop → job + clipe V1 0–4 s → Montar `completed/verified` (320x180 h264+aac 4.0 s, `source.mp4` preservado), 0 erros consola. Zero chamadas pagas.

## Rail sem botões fantasma (2026-11-05, fix)

A barra esquerda mostrava Áudio/Efeitos/Transições/Legendas/Ajustes desativados + seta decorativa — sem função, percebidos como fakes. Removidos (product-guard: o que não existe não se mostra); ficam só `Recursos` + `Texto`, os únicos destinos reais. Verificação: `tsc` + `next build` limpos, browser (prod :3000) com rail de 2 botões, 0 erros consola.
