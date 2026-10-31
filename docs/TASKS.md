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

## Milestone 3 — Job System + API (next recommended)
- [ ] FastAPI app: upload, job creation, local storage layout, job state machine, status/result/download endpoints per API_CONTRACTS.md.
- [ ] Persistent worker process consuming jobs without blocking API requests.
- [ ] Error states (provider timeout, failed segmentation) with originals preserved.

## Milestone 4 — Real Renderer
- [ ] OpenCV compositing: alpha from masks, edge smoothing, background blur, background replacement, subject kept sharp.
- [ ] FFmpeg encode preserving original audio; output verification (readable, duration, streams).
- [ ] Run ADR-006 benchmark; record measurements + machine specs in STATUS.md.

## Milestone 5 — Frontend
- [ ] Next.js voice-first UI per DESIGN_SYSTEM.md; before/after, real job states, download of verified MP4.
- [ ] Browser verification of the full mock-mode flow.

## Milestone 6 — Live Integration Gate (blocked)
- [ ] Verify official Meta documentation (schemas, media inputs, mask encoding, sync/async, polling, rate limits, pricing).
- [ ] Implement live adapters behind existing interfaces; request logging, idempotency, budget tracking; no automatic billable retries.
- [ ] Propose one controlled integration test and obtain explicit user approval before any live call.
