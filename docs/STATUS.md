# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–4:** complete (foundation; providers/mocks/masks; benchmark prep; job system + API + worker; **real FFmpeg+OpenCV renderer + benchmark run**).
- **Next milestone:** Milestone 5 — Frontend (voice-first UI). See TASKS.md.

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM, API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 5 custom skills in `.opencode/skills/`.
- Contracts: EditingPlan, normalized provider responses (now incl. verified `RenderResult`), mask manifest.
- Providers: 4 typed interfaces, deterministic mocks, live placeholders, mode factory.
- Jobs: `JobRecord` state machine (queued/processing/completed/failed + stage), atomic file-based `JobStore`.
- API: FastAPI — health, validated upload, voice, status/list/result, **download (verified outputs only)**.
- Worker: masks/fixtures, job processor, persistent worker, **renderer** (`renderer.py`: sequential OpenCV decode, streaming mask iterator, feathered alpha compositing, background blur/replacement, FFmpeg libx264 encode with original audio, ffprobe output verification).
- Tests: **51 passing** (previous 41 preserved — one assertion updated to the new verified-render reality, and a latent `has_audio` probing bug found and fixed — plus 10 renderer tests).

## Measured Benchmark (ADR-006, Milestone 4)

Machine: Intel Core i5-4330M @ 2.80GHz (2C/4T), 7.9 GB RAM, Windows 10, Python 3.13.2. Source: 300 frames, 1280x720, 30 FPS, 10 s, mock masks.

| Case | Time | FPS | Peak RAM | CPU avg/peak | Output |
|---|---|---|---|---|---|
| Blur | 199.29 s | 1.51 | 358.7 MB | 267.5%/474.9% | 1,246,300 B |
| Replacement | 25.16 s | 11.92 | 363.3 MB | 104.2%/193.4% | 949,510 B |

Both outputs verified (300 frames, 720p, 10.000 s video+audio in sync) and visually inspected (frame 150): subject sharp with clean feathered edges; blur output background smoothly blurred; replacement output subject over the warm studio background. Raw data: `benchmarks/results/benchmark_results.json`.

Quality/performance limitations (honest): masks are synthetic ellipses on test-pattern footage, not people (ADR-007); edge quality on real hair/skin is unvalidated. Blur at 1.51 FPS on this machine is slow — full-res large-sigma Gaussian per frame is the bottleneck; downscale-blur is the first post-profiling optimization candidate (ADR-006), not yet implemented. Numbers are machine-specific, not promises.

## Environment Notes

- `.venv`: pydantic, Pillow, numpy, pytest, fastapi, uvicorn, python-multipart, httpx, opencv-python-headless 4.14, psutil (benchmark only).
- System FFmpeg is a Dec 2018 build (libx264+AAC present; adequate for baseline). **Upgrade recommended before production; not done silently.** Workarounds in code for its `-shortest` video-drop bug and stderr-pipe deadlock (see ARCHITECTURE.md).
- Test-only warning: Starlette TestClient prefers `httpx2` over `httpx` (upstream, no impact).

## Blockers / Uncertainties

- All Meta integration details unverified; live adapters are placeholders. Gate: Milestone 6.
- No licensed real-world footage with manual masks yet (ADR-007 accepted limitation); visual quality on real people unproven.
- No frontend yet (Milestone 5). No processing-time promises for end users until optimization + profiling on target hardware.

## Handoff

Read AGENTS.md, this file, and TASKS.md Milestone 5. Keep mock mode. Load `frontend-design`, `web-design-guidelines`, and `motion` skills before UI work; verify in a real browser. Do not make external calls.
