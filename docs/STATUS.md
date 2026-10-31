# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–5.1:** complete (foundation; providers/mocks/masks; benchmark prep; job system + API + worker; real renderer + benchmark; frontend studio; **professional editor redesign, browser-verified**).
- **Next milestone:** Milestone 6 — Live Integration Gate (blocked until Meta docs verified + explicit user approval). See TASKS.md.

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM (tokens finalized), API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 8 project skills (≤10 limit) — 5 custom in `.opencode/skills/`, plus `frontend-design` and `web-design-guidelines` in `.agents/skills/`, plus `motion` in `.opencode/skills/` (Motion AI Kit free tier installed via `npx motion-ai`; MCP configured; no Motion+ sign-in or purchase).
- Backend: contracts, mock providers (+live placeholders), job store, FastAPI (upload/voice/status/result/download, CORS for localhost:3000), persistent worker, FFmpeg+OpenCV renderer with verified outputs.
- Frontend (`apps/web`): Next.js 15 + React 19 + TS + Tailwind 4 + Motion. **Editor workspace (5.1):** TopBar (logo, project, job state, resolution/duration, Export MP4), Media panel (source thumbnail + real metadata, upload progress), central Viewer (custom play/seek transport, before/compare/after with synced edited overlay, fullscreen), AI Assistant (signal-orange mic with real voice-level ring, MediaRecorder capture, mock-labelled command confirmation, typed-instruction alternative with deterministic matching, live job step tracker, clarification/failure states), Timeline (time ruler, 10 real frame thumbnails captured from the file, real WebAudio audio peaks, click/keyboard seek, playhead synced to the video). `MotionConfig reducedMotion="user"` globally.
- Tests: **52 backend tests passing**; frontend `tsc` clean and `next build` succeeding; web-design-guidelines audit applied.

## Browser Verification (Milestone 5.1 redesign)

Full flow re-verified in the in-app Chromium on the redesigned UI: dropped a clip onto the Media panel (source selected, real 320×180/2.0s metadata), Timeline populated with 10 real frame thumbnails + audio peaks, timeline click-seek landed exactly (75% → 1.5/2.0s), typed instruction "blur the background please" matched the correct mock command, upload → confirm → job `completed` with backend transcript/plan and verified render facts, TopBar Export downloaded a real MP4 (`clipforge-1dba7953….mp4`, 36,817 bytes, video/mp4). Zero console errors; all five workspace areas present in the accessibility tree. Screenshot of the redesigned empty state captured at the available 781×582 browser window (stacked layout); the desktop app window size limits the in-app browser viewport, so 1440/1280/1024 screenshots could not be forced — desktop grid engages at the `lg` (1024px) breakpoint by CSS and remains to be eyeballed at full width.

## Browser Verification (Milestone 5)

Ran the full stack (uvicorn + worker process + `next start`) and drove the real UI in the in-app Chromium: dropped a local clip → uploaded (201, job created) → microphone correctly reported denied in headless browser → used the labelled no-microphone mock fallback → submitted → job reached `completed` with verified render facts → download button fetched a real MP4. Two separate UI sessions both ended `completed`/`verified` server-side (worker log: `rendered_and_verified frames=20`). The downloaded file was re-probed locally: video+audio streams, 320×180, 2.0 s — matches the source. Zero browser console errors. API log confirms real endpoint usage (uploads, voice, polling, result, download range requests).

## Measured Benchmark (ADR-006, from Milestone 4)

i5-4330M (2C/4T), 7.9 GB RAM: blur 199.29 s (1.51 FPS), replacement 25.16 s (11.92 FPS), peak RAM ~360 MB, 300 frames 720p, outputs verified + visually inspected. Raw: `benchmarks/results/benchmark_results.json`. Blur optimization (downscale-blur) remains the first post-profiling candidate; no user-facing timing promises.

## How To Run The Demo

1. `uvicorn clipforge_api.main:app --port 8000` (PYTHONPATH over `packages/*`, `apps/*`)
2. `python -m clipforge_worker.worker_process --storage storage`
3. `cd apps/web && npm run dev` → http://localhost:3000 (API base override: `NEXT_PUBLIC_API_URL`)

## Blockers / Uncertainties

- All Meta integration details unverified; live adapters are placeholders. Gate: Milestone 6 (docs verification, budget/idempotency design, explicit approval, one controlled test). The recorded voice audio is not yet sent anywhere — it becomes the transcription input at that gate.
- No licensed real-world footage with manual masks (ADR-007); quality on real people unproven.
- System FFmpeg is from 2018; upgrade recommended before production (not done silently).
- No frontend unit-test runner yet (backend suite + browser verification cover behaviour); shadcn primitives are local customised components, not Radix-based CLI output.

## Handoff

Read AGENTS.md, this file, TASKS.md. The MVP loop is fully demonstrable locally in mock mode with real rendering. Next step is only Milestone 6, and only with explicit approval. Keep mock mode; do not make external calls.
