# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–5:** complete (foundation; providers/mocks/masks; benchmark prep; job system + API + worker; real renderer + benchmark; **frontend studio, browser-verified**).
- **Next milestone:** Milestone 6 — Live Integration Gate (blocked until Meta docs verified + explicit user approval). See TASKS.md.

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM (tokens finalized), API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 5 custom skills in `.opencode/skills/`. Note: external `frontend-design`/`web-design-guidelines`/`motion` skills are not installed in this environment; DESIGN_SYSTEM.md was followed directly.
- Backend: contracts, mock providers (+live placeholders), job store, FastAPI (upload/voice/status/result/download, CORS for localhost:3000), persistent worker, FFmpeg+OpenCV renderer with verified outputs.
- Frontend (`apps/web`): Next.js 15 + React 19 + TS + Tailwind 4 + Motion. Studio flow: drag/drop upload with real progress → MediaRecorder voice capture (real recording + playback; mock command confirmation, honestly labelled) → submit → live stage polling (stops at terminal) → backend transcript/plan/render facts → before/after/compare preview → blob download of verified MP4. Error banners with recovery, failed-job and clarification states rendered from real API data.
- Tests: **52 backend tests passing**; frontend `tsc` clean and `next build` succeeding.

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
