# ClipForge — Status

## Current State

- **AI mode:** `CLIPFORGE_AI_MODE=mock` (only mode; no external AI calls made or permitted).
- **Milestones 0–2:** complete (foundation; provider interfaces + mocks + mask contract/fixtures/validation; benchmark preparation only).
- **Next milestone:** Milestone 3 — Job system + FastAPI API + persistent worker (see TASKS.md).

## What Exists

- Docs: PRODUCT_SPEC, ARCHITECTURE, DESIGN_SYSTEM, API_CONTRACTS, DECISIONS (ADR-001…ADR-007), TASKS, STATUS.
- Skills: 5 custom skills in `.opencode/skills/`.
- Contracts (`packages/contracts`): EditingPlan, normalized provider responses, mask manifest.
- Providers (`packages/providers`): 4 typed interfaces, deterministic mocks, live placeholders, mode factory.
- Worker (`apps/worker`): mask writer/loader/validation, deterministic synthetic fixtures, explicit nearest-neighbour resize.
- Benchmarks (`benchmarks/`, `scripts/`): benchmark spec + source-preparation script + harness stub. **No rendering performance has been measured or claimed** — the renderer does not exist yet.
- Tests (`tests/`): mask validation, fixtures, provider mocks, EditingPlan, mock-mode zero-network safety.

## Environment (recorded at foundation)

- OS: Windows. Python 3.13.2 (`.venv` with pydantic, Pillow, numpy, pytest only).
- FFmpeg (2018 build) + ffprobe (2023) on PATH; Node 22; Git 2.48.
- OpenCV and FastAPI intentionally NOT installed yet (renderer/API milestones).

## Blockers / Uncertainties

- All Meta integration details (SAM 3.1, transcription, reasoning, image generation) are unverified; live adapters are placeholders. Gate: Milestone 6.
- No licensed real-world footage with manual masks yet (ADR-007 accepted limitation); synthetic fixtures only.
- CPU render performance unknown until Milestone 4 profiling (ADR-006).

## Handoff

Read AGENTS.md, this file, and TASKS.md Milestone 3. Keep mock mode. Do not install MediaBunny/PyTorch/CUDA. Do not make external calls.
