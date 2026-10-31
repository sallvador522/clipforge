# ClipForge — Architecture

## System Overview

```
Browser (Next.js) ──REST──> FastAPI (apps/api) ──job queue──> Worker (apps/worker)
                                │                                  │
                                │                                  ├─ Providers (packages/providers)
                                │                                  ├─ Mask storage (ADR-005)
                                └────────── Local storage ─────────┴─ FFmpeg + OpenCV renderer
```

FastAPI requests never block on rendering. Uploads create jobs; the persistent worker processes them asynchronously. The original video and audio are preserved until the rendered output is verified.

## Components

| Component | Path | Responsibility |
|---|---|---|
| Web frontend | `apps/web/` | Voice-first UI (later milestone; only scaffold definition exists now) |
| API | `apps/api/` | FastAPI REST endpoints, upload validation (ffprobe), non-blocking job submission |
| Worker | `apps/worker/` | Mask writer/loader/validation, fixtures, job processor, persistent worker process, FFmpeg+OpenCV renderer |
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
3. Renderer (`clipforge_worker/renderer.py`, implemented Milestone 4): OpenCV decodes frames sequentially and streams masks one at a time via `MaskLoader.iter_masks` (bounded memory — never the whole sequence in RAM), builds a feathered alpha (Gaussian edge smoothing in the renderer, not the loader), keeps the subject sharp, and either blurs the background (large-sigma Gaussian) or replaces it with a local background image (cover-fit resize; masks are never resized). Raw frames are piped to FFmpeg (libx264/yuv420p) which muxes the **original audio** from the source file (lossless `-c:a copy` for AAC/MP3, AAC re-encode otherwise).
4. Verification: `verify_render_output` re-probes the actual file with ffprobe frame counting — video stream, exact resolution, exact frame count, duration, and audio presence (when the source has audio) — before the job may complete or be downloaded.
5. CPU-only, sequential frame processing with bounded memory first (ADR-006). Optimizations (pipelining, parallelism, downscale-blur) only after profiling — blur is the known bottleneck (see STATUS.md measurements).

Environment findings recorded at Milestone 4 (no silent environment changes):
- System FFmpeg is a Dec 2018 build (`N-92722`) with libx264 + AAC; sufficient for this baseline. **Upgrade recommended before production** (security and encoder fixes); not performed automatically.
- Two 2018-build quirks are handled in code: FFmpeg stderr is redirected to a temp log file (an unread PIPE deadlocks at 720p), and `-shortest` is omitted (with copied audio it drops the video stream entirely — verified empirically).
- A latent Milestone 3 bug was found and fixed: upload probing used `-select_streams v:0`, so `has_audio` was always false.

Failure handling: provider timeouts and failed segmentation produce explicit failed job states. Job retries reuse an idempotency key per job so a retry never duplicates an inference request (enforced when live providers exist; mocks are deterministic and side-effect-free apart from local files).

## Job System (Milestone 3, implemented)

- State machine: `queued → processing → completed | failed`. A `stage` field carries progress detail (`awaiting_voice`, `transcribing`, `planning`, `segmenting`, `preparing_background`, `pipeline_completed`, `clarification_needed`, ...). A job becomes claimable only when a voice instruction is attached (`ready=true`).
- `JobStore` (`packages/jobs`) persists each record as `storage/jobs/<job_id>/job.json` with atomic temp-file + `os.replace` writes. Claiming uses an `O_CREAT|O_EXCL` lock file, so exactly one worker process can claim a job (job isolation, no duplicate processing).
- The API only validates, stores, and enqueues; it never runs provider or rendering work. The persistent worker (`python -m clipforge_worker.worker_process`) polls for ready jobs and processes them sequentially: transcribe → plan → segment (masks re-validated with the ADR-005 loader) → optional mock background → **render → verify**. Clarification and unsupported plans complete without segmentation or rendering (their `render_status` stays `"not_implemented"`, honestly).
- Since Milestone 4, an edit job's `completed` means: mock AI pipeline finished **and** a real MP4 was rendered and verified (`render_status="verified"`, `rendered` facts in the result). `GET /api/jobs/{id}/download` serves that file only when it is verified and present on disk; otherwise 409.
- Upload safety: filename path components stripped, extension allowlist (`.mp4/.mov/.webm/.mkv`), streaming size cap, empty/unreadable files rejected, ffprobe enforces MVP limits (video stream required, ≤720p, ≤10.5 s, ≤30 FPS). Invalid uploads leave no orphaned files or records. Per-job directories isolate all artefacts; originals are preserved on failure.
- Every worker exception is logged (with traceback) and stored as a structured `{code, message}` job error. Nothing is swallowed.

## Storage Layout (local, gitignored)

```
storage/
  uploads/<job_id>/source.<ext>
  jobs/<job_id>/job.json
  jobs/<job_id>/masks/{manifest.json, frame_000000.png, ...}
  jobs/<job_id>/output.mp4        (verified rendered output)
```

## Deferred / Placeholder

- Live Meta adapters: placeholders raising `LiveProviderNotImplementedError`. No endpoint, field, or schema is assumed (see `docs/API_CONTRACTS.md`).
- Frontend: Milestone 5.
