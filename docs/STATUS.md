# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–6B-PREP:** complete (foundation; providers/mocks/masks; benchmark prep; job system + API + worker; real renderer + benchmark; frontend studio; editor redesign; local QA; real transcription provider + audio pipeline; **professional editing director intelligence, offline**).
- **Frontend note (6A follow-up):** the mock command selector was removed from the studio. Mock transcription remains available only through the backend API/tests; the UI now either transcribes live (when enabled) or offers the typed instruction. Recorded audio in mock mode is not transcribed, and says so.
- **Next milestone:** LIVE-CALL 001 (one Contributor-Medium plan-generation POST) — user-approved, implementation + guard script ready, **blocked on a valid `MODEL_API_KEY` in gitignored `.env` (currently empty)**. The first live transcription test already succeeded (user-verified); transcription is currently configured as mock for development safety.

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM (tokens finalized), API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 9 project skills (≤10 limit) — 6 custom in `.opencode/skills/` (including `clipforge-editing-director`), `frontend-design` and `web-design-guidelines` in `.agents/skills/`, plus `motion` in `.opencode/skills/` (Motion AI Kit free tier; no Motion+ purchase).
- Backend: contracts, mock providers (+live placeholders), job store, FastAPI (upload/voice/status/result/download, CORS for localhost:3000), persistent worker, FFmpeg+OpenCV renderer with verified outputs.
- Frontend (`apps/web`): Next.js 15 + React 19 + TS + Tailwind 4 + Motion. **Editor workspace (5.1):** TopBar (logo, project, job state, resolution/duration, Export MP4), Media panel (source thumbnail + real metadata, upload progress), central Viewer (custom play/seek transport, before/compare/after with synced edited overlay, fullscreen), AI Assistant (signal-orange mic with real voice-level ring, MediaRecorder capture, mock-labelled command confirmation, typed-instruction alternative with deterministic matching, live job step tracker, clarification/failure states), Timeline (time ruler, 10 real frame thumbnails captured from the file, real WebAudio audio peaks, click/keyboard seek, playhead synced to the video). `MotionConfig reducedMotion="user"` globally.
- Tests: **175 backend tests passing** (70 preserved pre-director + 105 director/registry/playbook/EDL/evaluation/Spark incl. Contributor-mode gating); frontend `tsc` clean and `next build` succeeding; web-design-guidelines audit applied.

### Proposed first live director test — LIVE-CALL 001 Contributor Medium (APPROVED, NOT RUN — key missing)

- Instruction: "Keep me sharp, blur the people behind me and replace the background with a cinematic Luanda sunset."
- Data sent: confirmed transcript text + benchmark-unit video metadata (1280×720 @ 30fps, 10.0s, 300 frames, audio present) + playbook v1.1 + registry summary. No audio bytes, no tools, no web search.
- Endpoint: `POST https://api.meta.ai/v1/chat/completions`, model `muse-spark-1.3-contributor` (exact id enforced; Standard rejected), Bearer `MODEL_API_KEY`, `reasoning_effort: medium`, `response_format` json_schema `ProfessionalEditingPlan`, `max_completion_tokens: 1500`. (No `context` parameter exists in the verified contract.)
- Measured prompt: developer 12,234 chars (~3,058 est tokens) + user 631 chars (~157 est) = ~3,215 input tokens (chars/4 heuristic, not billing).
- Output cap 1500 tokens; reference valid plan ~3,659 chars (~914 est tokens).
- Cost at Contributor rates ($0.10/1M in, $0.20/1M out): at cap ≈ **$0.00062** (0.062 US cents); typical 600-token output ≈ **$0.00044** (0.044 cents). Consumes ~0.002% of the $30 budget at cap.
- Expected: ready v2 plan (isolate → replace → audio → render → verify, approval required) OR honest clarification; validated before any use; EDL/render **not** executed.
- Blocked on: a valid `MODEL_API_KEY` in gitignored `.env` (currently empty). Exactly one POST when unblocked; any second call needs fresh approval.

## Professional Editing Director (Milestone 6B-PREP)

- Ninth skill: `.opencode/skills/clipforge-editing-director` (9/10 total). It is development guidance only; it is never sent to the runtime model.
- Runtime playbook: `apps/api/clipforge_api/prompts/professional_editing_director.md`, loaded/validated by `clipforge_api/playbook.py` (12 required sections, versioned; no network/model call).
- Capability registry: 6 executable capabilities (1 mock segmentation, 5 local), 1 planned (Muse Image), 9 disabled. Only available capabilities can be planned; disabled features are named in explanations but never executed.
- v2 plan + v1 adapter: validation covers registry membership, typed params, dependency order, clarification/unsupported rules, approval requirements and forbidden fields. The worker still executes v1 only.
- Mock director: deterministic offline scenarios A–E; replacement requires approval; cinematic background is labelled simulated; vague/subject-ambiguous requests ask one clarification; unsupported requests name disabled capabilities.
- Stages: 10 validated `DirectorStage` values + mapping from worker stages; no fabricated percentages.
- Approval/cancel/revision: contracts/docs only; no endpoints/UI, no fake execution.

**Safety:** implementation and tests ran in `CLIPFORGE_AI_MODE=mock` with `CLIPFORGE_TRANSCRIBE_MODE=mock`; zero Meta/Muse Spark/SAM/Muse Image requests; no credentials printed or committed.

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

1. `python scripts/dev_api.py` (loads `.env`, starts uvicorn on :8000 with reload)
2. `python -m clipforge_worker.worker_process --storage storage`
3. `cd apps/web && npm run dev` → http://localhost:3000 (API base override: `NEXT_PUBLIC_API_URL`)

## Blockers / Uncertainties

- All Meta integration details unverified; live adapters are placeholders. Gate: Milestone 6 (docs verification, budget/idempotency design, explicit approval, one controlled test). The recorded voice audio is not yet sent anywhere — it becomes the transcription input at that gate.
- No licensed real-world footage with manual masks (ADR-007); the Facebook_2 test confirms mock masks do not track a real person.
- System FFmpeg is from 2018; upgrade recommended before production (not done silently).
- No frontend unit-test runner yet (backend suite + browser verification cover behaviour); shadcn primitives are local customised components, not Radix-based CLI output.

## Handoff

Read AGENTS.md, this file, TASKS.md. The MVP loop is fully demonstrable locally in mock mode with real rendering. Next step is only Milestone 6, and only with explicit approval. Keep mock mode; do not make external calls.
