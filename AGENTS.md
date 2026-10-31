# ClipForge — Development Rules

ClipForge is a voice-first AI video editing agent: upload a video, describe the edit by voice, receive a real edited MP4. MVP constraint: 10-second clips, 720p, up to 30 FPS.

## Non-Negotiable Rules

1. **Mock-first (ADR-004).** `CLIPFORGE_AI_MODE=mock` is the default. Transcription may run live only when explicitly enabled with `CLIPFORGE_TRANSCRIBE_MODE=live` and a server-side `MODEL_API_KEY` (ADR-008); planning, segmentation and image generation remain mocked. No live request may be made without explicit user approval of a cost estimate. No other external AI calls during development.
2. **Mocks simulate AI only, never rendering.** Video rendering is real FFmpeg + OpenCV (ADR-002). No fake output videos, no placeholder downloads.
3. **No invented integrations.** Use only verified official schemas (transcription is verified, see ADR-008). Any unverified provider stays an explicit placeholder until its official documentation is verified and the user approves a controlled test.
4. **Server-side secrets only.** Never expose API credentials to the frontend. No secrets in frontend bundles, no hardcoded credentials anywhere.
5. **Budget protection.** Remaining Meta API budget is ~$30. No automatic retries that could cause billable requests. Live execution requires explicit user approval.
6. **MediaBunny is excluded from the MVP (ADR-003).** Do not install MediaBunny or `@mediabunny/server`.
7. **No local SAM inference.** No PyTorch, CUDA, or SAM checkpoints (ADR-001). CPU rendering only (ADR-006).
8. **Preserve originals.** Never overwrite or delete the original video/audio until the rendered output is verified (readable file, valid duration, valid video + audio streams).
9. **No swallowed exceptions, no arbitrary code execution from model outputs.** Every provider output is validated against strict Pydantic schemas.
10. **Ambiguity rule.** When the intended subject is ambiguous, the agent must ask a spoken clarification instead of silently choosing a person.

## Stack

- Frontend (later milestone): Next.js, React, TypeScript, Tailwind CSS, customised shadcn/ui primitives, Motion for React.
- Backend: Python, FastAPI, Pydantic.
- Worker: persistent Python process, FFmpeg (decode/normalize/audio/encode) + OpenCV (masks/compositing, renderer milestone).
- Storage: local filesystem under `storage/` (gitignored).
- AI providers, behind typed adapters: Transcription, EditingPlanner, Segmentation (SAM 3.1 hosted, future), BackgroundGeneration.

## Workflow (every implementation task)

1. Read this file, `docs/STATUS.md`, and the relevant task in `docs/TASKS.md`.
2. Inspect only relevant code/dependencies. Never scan `node_modules`, `.venv`, build outputs, or generated files.
3. Explain proposed changes, implement the smallest coherent unit.
4. Verify: tests, type checks, and for media work inspect the actual generated file; for UI work inspect in a real browser.
5. Update `docs/STATUS.md`, `docs/TASKS.md`, and `docs/DECISIONS.md` (only via a new ADR; never silently change an established decision).
6. Load only the relevant skills from `.opencode/skills/` (max 10 project skills total). Do not duplicate skill instructions here.

## Acceptance Criteria

A feature is complete only with: functional behaviour, input validation, loading states, error handling, appropriate tests, type checking, build verification, and updated documentation. A passing API response is not proof: verify the actual media file.
