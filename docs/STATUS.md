# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–3:** complete (foundation; providers/mocks/mask contract; benchmark preparation; job system + FastAPI + persistent worker).
- **Next milestone:** Milestone 4 — Real FFmpeg + OpenCV renderer, then run the ADR-006 benchmark (see TASKS.md).

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM, API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 5 custom skills in `.opencode/skills/`.
- Contracts (`packages/contracts`): EditingPlan, normalized provider responses, mask manifest.
- Providers (`packages/providers`): 4 typed interfaces, deterministic mocks, live placeholders, mode factory.
- Jobs (`packages/jobs`): `JobRecord` state machine (queued/processing/completed/failed + stage detail), atomic file-based `JobStore` with cross-process claim locks.
- API (`apps/api`): FastAPI — health, validated upload (ffprobe, MVP limits), voice submission, status/list/result. Non-blocking; no download endpoint yet.
- Worker (`apps/worker`): mask writer/loader/fixtures, job processor (transcribe→plan→segment→background; masks re-validated), persistent polling worker process.
- Benchmarks: spec + prepared 720p/10s source. **No rendering performance measured or claimed** — renderer does not exist yet.
- Tests: 41 passing (mask validation, fixtures, providers, mock-mode zero-network safety, full API job lifecycle incl. failure isolation and exclusive claiming).

## Verified Behaviour (Milestone 3)

- Cross-process end-to-end (real separate worker process + API): upload → queued/awaiting_voice → voice → worker claims → completed (`pipeline_completed`), 10 real mask PNGs written and loadable, original source preserved, `render_status="not_implemented"` reported honestly.
- A failed job (unknown fixture) ends `failed` with structured error, does not affect a parallel good job, and preserves its original upload.

## Environment

- Windows, Python 3.13.2 `.venv`: pydantic, Pillow, numpy, pytest + fastapi, uvicorn, python-multipart, httpx (Milestone 3). OpenCV intentionally not installed until Milestone 4.
- FFmpeg (2018 build) + ffprobe (2023) on PATH; Node 22; Git 2.48. Test-only warning: Starlette's TestClient deprecates `httpx` in favour of `httpx2` (upstream notice, no functional impact).

## Blockers / Uncertainties

- All Meta integration details unverified; live adapters are placeholders. Gate: Milestone 6.
- No licensed real-world footage with manual masks yet (ADR-007 accepted limitation).
- CPU render performance unknown until Milestone 4 profiling (ADR-006). Job `completed` currently means mock pipeline completed, **not** a rendered video.

## Handoff

Read AGENTS.md, this file, and TASKS.md Milestone 4. Keep mock mode. Do not install MediaBunny/PyTorch/CUDA. Do not make external calls. Do not claim rendering exists until the renderer is built and its output file is verified.
