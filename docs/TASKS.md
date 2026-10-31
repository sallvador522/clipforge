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

## Milestone 6 — Live Integration Gate (blocked)
- [ ] Verify official Meta documentation (schemas, media inputs, mask encoding, sync/async, polling, rate limits, pricing).
- [ ] Implement live adapters behind existing interfaces; request logging, idempotency, budget tracking; no automatic billable retries.
- [ ] Propose one controlled integration test and obtain explicit user approval before any live call.
