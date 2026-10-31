# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–6A:** complete (foundation; providers/mocks/masks; benchmark prep; job system + API + worker; real renderer + benchmark; frontend studio; editor redesign; local QA; **real transcription provider + audio pipeline, live call not yet made**).
- **Next milestone:** first controlled live transcription test — blocked on explicit user approval of the cost estimate.

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM (tokens finalized), API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 8 project skills (≤10 limit) — 5 custom in `.opencode/skills/`, plus `frontend-design` and `web-design-guidelines` in `.agents/skills/`, plus `motion` in `.opencode/skills/` (Motion AI Kit free tier installed via `npx motion-ai`; MCP configured; no Motion+ sign-in or purchase).
- Backend: contracts, mock providers (+live placeholders), job store, FastAPI (upload/voice/status/result/download, CORS for localhost:3000), persistent worker, FFmpeg+OpenCV renderer with verified outputs.
- Frontend (`apps/web`): Next.js 15 + React 19 + TS + Tailwind 4 + Motion. **Editor workspace (5.1):** TopBar (logo, project, job state, resolution/duration, Export MP4), Media panel (source thumbnail + real metadata, upload progress), central Viewer (custom play/seek transport, before/compare/after with synced edited overlay, fullscreen), AI Assistant (signal-orange mic with real voice-level ring, MediaRecorder capture, mock-labelled command confirmation, typed-instruction alternative with deterministic matching, live job step tracker, clarification/failure states), Timeline (time ruler, 10 real frame thumbnails captured from the file, real WebAudio audio peaks, click/keyboard seek, playhead synced to the video). `MotionConfig reducedMotion="user"` globally.
- Tests: **70 backend tests passing**; frontend `tsc` clean and `next build` succeeding; web-design-guidelines audit applied.

## Transcription (Milestone 6A)

- Provider: `MetaVoiceTranscriptionProvider` (`packages/providers/clipforge_providers/transcription_meta.py`), interface `transcription.transcribe_audio(path)`. Verified contract from official docs (model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe`, Bearer, multipart `request` JSON + `audio` WAV, `mode=PUSH_TO_TALK`, `languageBias=["Portuguese"]`, response `{sessionId, transcript, audioDurationMs, turns}`).
- Audio pipeline: browser MediaRecorder → `POST /api/transcribe` → extension/size/stream/duration validation → FFmpeg mono 16-bit PCM WAV 24 kHz → ffprobe verification → provider called **once** → normalized transcript → user reviews/edits → `POST /api/jobs/{id}/voice` with confirmed text → planner. Temp audio deleted after each request.
- Mode selection: `CLIPFORGE_TRANSCRIBE_MODE=mock` (default) / `live` + `MODEL_API_KEY`. Missing key fails before any request. Other providers stay mock. No silent fallback.
- Safety: no automatic retries, timeouts mapped to 504, 429 mapped to `transcription_rate_limited`, API errors to 502; `sessionId` logged (never key/audio); mock never interprets audio (requires explicit fixture, labelled MOCK).
- Tests: 18 new (multipart/language bias/normalization, invalid audio, missing key, timeout, 429, API error, mock network isolation, provider selection, exactly-one-request, confirmed-transcript planning).
- **No live call has been made.** Cost of the proposed first test (5 s recording): 5 whole seconds × $0.18 / 3600 s ≈ **$0.00025** (0.025 US cents).

### Live UI readiness (no calls)

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

1. `uvicorn clipforge_api.main:app --port 8000` (PYTHONPATH over `packages/*`, `apps/*`)
2. `python -m clipforge_worker.worker_process --storage storage`
3. `cd apps/web && npm run dev` → http://localhost:3000 (API base override: `NEXT_PUBLIC_API_URL`)

## Blockers / Uncertainties

- All Meta integration details unverified; live adapters are placeholders. Gate: Milestone 6 (docs verification, budget/idempotency design, explicit approval, one controlled test). The recorded voice audio is not yet sent anywhere — it becomes the transcription input at that gate.
- No licensed real-world footage with manual masks (ADR-007); the Facebook_2 test confirms mock masks do not track a real person.
- System FFmpeg is from 2018; upgrade recommended before production (not done silently).
- No frontend unit-test runner yet (backend suite + browser verification cover behaviour); shadcn primitives are local customised components, not Radix-based CLI output.

## Handoff

Read AGENTS.md, this file, TASKS.md. The MVP loop is fully demonstrable locally in mock mode with real rendering. Next step is only Milestone 6, and only with explicit approval. Keep mock mode; do not make external calls.
