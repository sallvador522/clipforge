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
| API | `apps/api/` | REST endpoints, job state machine, Pydantic validation (later milestone) |
| Worker | `apps/worker/` | Mask writer/loader/validation, fixtures, renderer (later milestone) |
| Contracts | `packages/contracts/` | Single source of truth: `EditingPlan`, normalized provider responses, mask manifest |
| Providers | `packages/providers/` | Typed provider interfaces, deterministic mocks, live placeholders |

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

## Storage Layout (local, gitignored)

```
storage/
  uploads/<job_id>/source.<ext>
  jobs/<job_id>/masks/{manifest.json, frame_000000.png, ...}
  jobs/<job_id>/output.mp4
```

## Deferred / Placeholder

- Live Meta adapters: placeholders raising `LiveProviderNotImplementedError`. No endpoint, field, or schema is assumed (see `docs/API_CONTRACTS.md`).
- Frontend and FastAPI route implementation: later milestones.
