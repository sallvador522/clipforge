# ClipForge — Architecture

## System Overview

```
Browser (Next.js) ──REST──> FastAPI (apps/api) ──job queue──> Worker (apps/worker)
                                │                                  │
                                │                                  ├─ Providers (packages/providers)
                                │                                  ├─ Mask storage (ADR-005)
                                └────────── Local storage ─────────┴─ FFmpeg + OpenCV renderer (later milestone)
```

FastAPI requests never block on rendering. Uploads create jobs; the persistent worker processes them asynchronously. The original video and audio are preserved until the rendered output is verified.

## Components

| Component | Path | Responsibility |
|---|---|---|
| Web frontend | `apps/web/` | Voice-first UI (later milestone; only scaffold definition exists now) |
| API | `apps/api/` | FastAPI REST endpoints, upload validation (ffprobe), non-blocking job submission |
| Worker | `apps/worker/` | Mask writer/loader/validation, fixtures, job processor, persistent worker process, renderer (later milestone) |
| Contracts | `packages/contracts/` | Single source of truth: `EditingPlan`, normalized provider responses, mask manifest |
| Providers | `packages/providers/` | Typed provider interfaces, deterministic mocks, live placeholders |
| Jobs | `packages/jobs/` | Shared `JobRecord` state machine + atomic file-based `JobStore` used by API and worker |

## Provider Architecture (ADR-004)

Four typed interfaces, each with a deterministic mock and an unimplemented live placeholder, all sharing normalized internal contracts from `packages/contracts`:

- `TranscriptionProvider` — voice audio fixture → normalized transcript.
- `EditingPlannerProvider` — transcript → validated `EditingPlan` (deterministic mapping, no LLM in mock mode).
- `SegmentationProvider` — video reference → normalized segmentation result backed by real local mask data (ADR-005).
- `BackgroundGenerationProvider` — prompt → real local background image asset + simulated generation metadata.

Mode selection: `CLIPFORGE_AI_MODE=mock` (default). The factory in `packages/providers/clipforge_providers/factory.py` returns mocks in mock mode, raises an explicit error for `live` (live adapters are placeholders until documentation is verified), and never silently falls back. The frontend never talks to a provider directly and never sees credentials.

## Video Pipeline (ADR-001, ADR-002, ADR-005, ADR-006)

1. Worker prepares the source video (FFmpeg decode/normalize).
2. Segmentation provider returns masks in the canonical internal format: PNG sequence + `manifest.json` (ADR-005). In mock mode these are synthetic fixtures; in the future the SAM adapter maps the hosted Meta response into this same format. The pipeline never consumes a provider-native format.
3. Renderer (later milestone): OpenCV builds alpha masks, applies edge smoothing separately from mask loading, blurs or replaces the background, keeps the subject sharp; FFmpeg encodes the final MP4 preserving original audio.
4. Verification: output must be readable with valid duration and video + audio streams before the job is marked complete.
5. CPU-only, sequential frame processing with bounded memory first (ADR-006). Optimizations (pipelining, parallelism, downscale-blur) only after profiling.

Failure handling: provider timeouts and failed segmentation produce explicit failed job states. Job retries reuse an idempotency key per job so a retry never duplicates an inference request (enforced when live providers exist; mocks are deterministic and side-effect-free apart from local files).

## Job System (Milestone 3, implemented)

- State machine: `queued → processing → completed | failed`. A `stage` field carries progress detail (`awaiting_voice`, `transcribing`, `planning`, `segmenting`, `preparing_background`, `pipeline_completed`, `clarification_needed`, ...). A job becomes claimable only when a voice instruction is attached (`ready=true`).
- `JobStore` (`packages/jobs`) persists each record as `storage/jobs/<job_id>/job.json` with atomic temp-file + `os.replace` writes. Claiming uses an `O_CREAT|O_EXCL` lock file, so exactly one worker process can claim a job (job isolation, no duplicate processing).
- The API only validates, stores, and enqueues; it never runs provider or rendering work. The persistent worker (`python -m clipforge_worker.worker_process`) polls for ready jobs and processes them sequentially: transcribe → plan → segment (masks re-validated with the ADR-005 loader) → optional mock background. Clarification and unsupported plans complete without segmentation.
- `completed` means the mock AI pipeline finished. It does **not** mean a video was rendered: results carry `render_status="not_implemented"` (Milestone 4) and there is no download endpoint yet.
- Upload safety: filename path components stripped, extension allowlist (`.mp4/.mov/.webm/.mkv`), streaming size cap, empty/unreadable files rejected, ffprobe enforces MVP limits (video stream required, ≤720p, ≤10.5 s, ≤30 FPS). Invalid uploads leave no orphaned files or records. Per-job directories isolate all artefacts; originals are preserved on failure.
- Every worker exception is logged (with traceback) and stored as a structured `{code, message}` job error. Nothing is swallowed.

## Storage Layout (local, gitignored)

```
storage/
  uploads/<job_id>/source.<ext>
  jobs/<job_id>/job.json
  jobs/<job_id>/masks/{manifest.json, frame_000000.png, ...}
  jobs/<job_id>/output.mp4        (Milestone 4)
```

## Deferred / Placeholder

- Live Meta adapters: placeholders raising `LiveProviderNotImplementedError`. No endpoint, field, or schema is assumed (see `docs/API_CONTRACTS.md`).
- Renderer and download endpoint: Milestone 4. Frontend: Milestone 5.
