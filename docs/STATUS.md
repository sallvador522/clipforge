# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock`; transcription and the director are the only live-capable providers, enabled in isolation. Segmentation, background generation and the legacy planner remain mocked.
- **Milestones 0–6B-LIVE:** complete through LIVE-E2E 005 — real Portuguese audio → Muse Spark plan → real blur render → verified download. Director usage 2,781 in / 1,856 out = **$0.000649**; ASR **$0.000184**; run total **$0.000833**. Full log: `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`.
- **Frontend note (6A follow-up):** the mock command selector was removed from the studio. Mock transcription remains available only through the backend API/tests; the UI now either transcribes live (when enabled) or offers the typed instruction. Recorded audio in mock mode is not transcribed, and says so.
- **Next milestone:** SAM 3.1 segmentation — **blocked on explicit approval**. The director path is proven end-to-end; live planning uses the lite schema, cap 16,000. One live call per function remains in the current ledger.

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM (tokens finalized), API_CONTRACTS, DECISIONS (ADR-001…ADR-014), TASKS, STATUS, live-call reports.
- Skills: 9 project skills (≤10 limit) — 6 custom in `.opencode/skills/` (including `clipforge-editing-director`), `frontend-design` and `web-design-guidelines` in `.agents/skills/`, plus `motion` in `.opencode/skills/` (Motion AI Kit free tier; no Motion+ purchase).
- Backend: contracts, mock providers with explicit live transcription/director modes, job store, FastAPI (upload/voice/status/result/download, CORS for localhost:3000), persistent worker, FFmpeg+OpenCV renderer with verified outputs.
- Frontend (`apps/web`): Next.js 15 + React 19 + TS + Tailwind 4 + Motion. **Editor workspace (5.1):** TopBar (logo, project, job state, resolution/duration, Export MP4), Media panel (source thumbnail + real metadata, upload progress), central Viewer (custom play/seek transport, before/compare/after with synced edited overlay, fullscreen), AI Assistant (signal-orange mic with real voice-level ring, MediaRecorder capture, mock-labelled command confirmation, typed-instruction alternative with deterministic matching, live job step tracker, clarification/failure states), Timeline (time ruler, 10 real frame thumbnails captured from the file, real WebAudio audio peaks, click/keyboard seek, playhead synced to the video). `MotionConfig reducedMotion="user"` globally.
- Tests: **191 backend tests passing** (70 preserved pre-director + 121 director/registry/playbook/EDL/evaluation/Spark/lite/live-wiring); frontend `tsc` clean and `next build` succeeding; web-design-guidelines audit applied.

### First live director test — LIVE-CALL 001/002 (500) and 003 (200 truncated)

- 001/002: two POSTs, both HTTP 500 with the full v2 schema (~8.4 KB). Billing under reconciliation (panel is source of truth); $0.00 claim withdrawn.
- 003: one POST with the lite schema (1,948 bytes) → **HTTP 200, `finish_reason: "length"`** at 800 tokens. No plan accepted; no retry. This confirms the full schema as the 500 cause and isolates the remaining blocker to output budget. Billable; local usage lost pre-fix (bounded ≤ ≈ $0.00026). Observability fixed: usage recorded before validation, `server_request_id` captured.
- 004: one POST, same lite schema, cap 1500 → **HTTP 200, still truncated**. Measured usage 951 in / 1500 out = **$0.000395** (Contributor rates), `x-request-id 134244ba-83c9-4721-95ae-a5677de9c34c`. No plan. Schema accepted twice; reasoning+plan output exceeds 1500.
- Full log: `docs/LIVE_CALL_001_002_REPORT.md`, `docs/LIVE_CALL_003_REPORT.md`, `docs/LIVE_CALL_004_REPORT.md`.

## Professional Editing Director (Milestone 6B-PREP)

- Ninth skill: `.opencode/skills/clipforge-editing-director` (9/10 total). It is development guidance only; it is never sent to the runtime model.
- Runtime playbook: `apps/api/clipforge_api/prompts/professional_editing_director.md`, loaded/validated by `clipforge_api/playbook.py` (12 required sections, versioned; no network/model call).
- Capability registry: 6 executable capabilities (1 mock segmentation, 5 local), 1 planned (Muse Image), 9 disabled. Only available capabilities can be planned; disabled features are named in explanations but never executed.
- v2 plan + v1 adapter: validation covers registry membership, typed params, dependency order, clarification/unsupported rules, approval requirements and forbidden fields. The worker still executes v1 only.
- Mock director: deterministic offline scenarios A–E; replacement requires approval; cinematic background is labelled simulated; vague/subject-ambiguous requests ask one clarification; unsupported requests name disabled capabilities.
- Stages: 10 validated `DirectorStage` values + mapping from worker stages; no fabricated percentages.
- Approval/cancel/revision at 6B-PREP: contracts/docs only; the live approval gate and execution wiring arrived in ADR-014.

**Safety (6B-PREP):** implementation and tests ran in `CLIPFORGE_AI_MODE=mock` with `CLIPFORGE_TRANSCRIBE_MODE=mock`; zero Meta/Muse Spark/SAM/Muse Image requests at that milestone; no credentials printed or committed. Later controlled live calls are documented below.

## Live End-to-End Execution (LIVE-E2E 005)

- **Flow:** recorded Portuguese audio → `POST /api/transcribe` (Muse Voice Transcribe) → confirmed transcript → worker → lite Muse Spark director → v1 adapter → mock segmentation → real FFmpeg/OpenCV blur → output verification → `GET /download`.
- **Transcript:** “Desfoca o fundo e mantém-me nítido.” (`pt-BR`, 3,680 ms, session `clipforge-9eeb63fa8d1f443ab7c6d42b4e18296e`); ASR cost $0.000184.
- **Plan:** 5 operations (`subject.isolate`, `background.blur`, `audio.preserve`, `video.render_mp4`, `output.verify`), approval `not_required`; 4,637 tokens, $0.000649, request `req_2c45fa340028`.
- **Output:** 320×180, 10 FPS, 20 frames, 2.000 s, 36,998 bytes, audio preserved, download HTTP 200; frame inspected (subject sharp, background blurred). Job `6b9e2dc1a95a4a60839b1312e34fc592`.
- **Wiring:** `CLIPFORGE_DIRECTOR_MODE=mock|live` (default `mock`). Live plans are validated as v2 then adapted to v1 for execution. Approval-required/rejected plans complete as `awaiting_approval` with no render. Clarification/unsupported complete without rendering. `director_plan`, `director_usage` and `director_request_id` are persisted in the job result.
- **Budget protection:** `storage/live-call-ledger.json` caps each function at 2 calls. Reservation occurs immediately before the network request; refusal returns an explicit error without a provider call. No automatic retries.
- **Defects fixed:** WAV temporary input/output shared the same filename (FFmpeg refused; no network call made) — input is now `upload{suffix}`; budget reservation moved after local conversion; dev launchers load `.env` and `packages/director`.
- **Verification:** 191 backend tests, frontend typecheck + production build, independent ffprobe + frame inspection, browser smoke at `:3000` (all five regions, LIVE TRANSCRIPTION badge, `/health` on `:8001`, zero console errors). Full report: `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`.
- **Limitations:** mock segmentation is a synthetic ellipse (not SAM); replacement backgrounds remain local/mock (not Muse Image); approval is backend-only (no resume endpoint/UI). SAM 3.1 waits for explicit approval.

## Transcription (Milestone 6A)

- Provider: `MetaVoiceTranscriptionProvider` (`packages/providers/clipforge_providers/transcription_meta.py`), interface `transcription.transcribe_audio(path)`. Verified contract from official docs (model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe`, Bearer, multipart `request` JSON + `audio` WAV, `mode=PUSH_TO_TALK`, `languageBias=["Portuguese"]`, response `{sessionId, transcript, audioDurationMs, turns}`).
- Audio pipeline: browser MediaRecorder → `POST /api/transcribe` → extension/size/stream/duration validation → FFmpeg mono 16-bit PCM WAV 24 kHz → ffprobe verification → provider called **once** → normalized transcript → user reviews/edits → `POST /api/jobs/{id}/voice` with confirmed text → planner. Temp audio deleted after each request.
- Mode selection: `CLIPFORGE_TRANSCRIBE_MODE=mock` (default) / `live` + `MODEL_API_KEY`. Missing key fails before any request. Other providers stay mock. No silent fallback.
- Safety: no automatic retries, timeouts mapped to 504, 429 mapped to `transcription_rate_limited`, API errors to 502; `sessionId` logged (never key/audio); mock never interprets audio (requires explicit fixture, labelled MOCK).
- Tests: 18 new (multipart/language bias/normalization, invalid audio, missing key, timeout, 429, API error, mock network isolation, provider selection, exactly-one-request, confirmed-transcript planning).
- **First live calls made in LIVE-E2E 005:** one transcription request, 3,680 ms, measured cost **$0.000184**. The earlier 5 s estimate (≈ $0.00025) was not used. The ledger caps transcription at 2 calls per phase; one remains.
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

**Real user footage**: `Facebook_2.mp4` (360×640, 25 fps, 19.6 s) exceeds the 10 s MVP input limit, so a 10.0 s excerpt was made locally (original untouched; no external calls). Both blur and replacement rendered and verified (360×640, 250 frames, 10.00 s, audio preserved). **Honest limitation:** mock segmentation is a synthetic ellipse, so the sharp region does not follow the person — the result proves the pipeline, not subject tracking. Real person cutout requires live SAM at Milestone 6 (ADR-007).

**Bugs fixed in 5.2**: ruler tick labels clipped at the right edge; mobile timeline header overflow; revoked filmstrip/probe blobs triggering `net::ERR_FILE_NOT_FOUND`; view-mode switches unmounting the playing video (now the verified render stays mounted as a synced overlay, so switching never aborts a blob fetch). Zero browser console errors after the fixes.

## Measured Benchmark (ADR-006, from Milestone 4)

## How To Run The Demo

1. `python scripts/dev_api.py` (loads `.env`; default port 8000, override with `CLIPFORGE_API_PORT=8001`)
2. `python scripts/dev_worker.py` (loads `.env`; persistent worker over `storage/`)
3. `cd apps/web && npm run dev` → http://localhost:3000 (API base override: `NEXT_PUBLIC_API_URL`)

For live runs, set `CLIPFORGE_TRANSCRIBE_MODE=live` and/or `CLIPFORGE_DIRECTOR_MODE=live` plus a server-side `MODEL_API_KEY`. Both default to `mock`; there is no silent fallback. The budget ledger must be reviewed before a new phase.

## Blockers / Uncertainties

- **SAM 3.1 integration is blocked on explicit approval.** Live transcription and director are proven; segmentation is still a synthetic mock ellipse and does not track a real person.
- **Approval gate is backend-only.** Approval-required plans stop at `awaiting_approval`, but there is no endpoint or UI to approve/reject and resume execution.
- **Live budget:** one transcription and one director call remain in `storage/live-call-ledger.json`. A new phase needs fresh approval and a ledger reset. LIVE-CALL 001/002 billing remains unknown (Meta panel is source of truth).
- No licensed real-world footage with manual masks (ADR-007); the Facebook_2 test confirms mock masks do not track a real person.
- System FFmpeg is from 2018; upgrade recommended before production (not done silently).
- No frontend unit-test runner yet (backend suite + browser verification cover behaviour); shadcn primitives are local customised components, not Radix-based CLI output.

## Handoff

Read AGENTS.md, this file, TASKS.md and `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`. The MVP loop is demonstrable with real rendering; the voice → Muse Spark → render path has been executed once end-to-end in live mode. Defaults remain mock. Next step is SAM 3.1, and only with explicit approval; do not reset the ledger or make further live calls without approval. The local `.env` used for the demonstrated run had transcription and director live; one spare call per function remains.
