---
name: clipforge-fastapi-jobs
description: Rules for ClipForge FastAPI endpoints and the asynchronous job system. Use when implementing or reviewing apps/api routes, job states, worker handoff, uploads, or downloads.
---

# ClipForge FastAPI Jobs

- FastAPI + Pydantic validation on every request/response. Strong typing, no unvalidated provider output, no arbitrary code execution from model outputs.
- API requests never block on rendering: uploads create jobs, a persistent worker renders asynchronously, clients poll job status.
- Job states: queued, transcribing, planning, segmenting, rendering, verifying, completed, failed, needs_clarification. Failures (timeouts, failed segmentation, corrupt media) produce explicit failed states with structured errors `{error: {code, message}}`.
- No swallowed exceptions. No invented routes: implement only endpoints defined in `docs/API_CONTRACTS.md`.
- Local storage layout under `storage/` (uploads, jobs/<id>/masks, output). Originals are preserved until output verification passes; downloads serve only verified files.
- Secrets server-side only; nothing provider-specific reaches the frontend.
