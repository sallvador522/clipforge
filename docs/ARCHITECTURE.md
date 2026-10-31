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
| Web frontend | `apps/web/` | Next.js studio: upload, voice recording, job monitoring, before/after preview, verified download (Milestone 5) |
| API | `apps/api/` | FastAPI REST endpoints, upload validation (ffprobe), non-blocking job submission |
| Worker | `apps/worker/` | Mask writer/loader/validation, fixtures, job processor, persistent worker process, FFmpeg+OpenCV renderer |
| Contracts | `packages/contracts/` | Single source of truth: `EditingPlan`, normalized provider responses, mask manifest |
| Providers | `packages/providers/` | Typed provider interfaces, deterministic mocks, live placeholders |
| Jobs | `packages/jobs/` | Shared `JobRecord` state machine + atomic file-based `JobStore` used by API and worker |

## Provider Architecture (ADR-004, ADR-008)

Four typed interfaces, each with a deterministic mock and shared normalized internal contracts from `packages/contracts`:

- `TranscriptionProvider` — voice audio → normalized transcript. **Live-capable** via `MetaVoiceTranscriptionProvider` (Muse Voice Transcribe). `transcribe(fixture_id)` remains the mock fixture path; `transcribe_audio(path)` is the real path.
- `EditingPlannerProvider` — transcript → validated `EditingPlan` (deterministic mapping; no LLM).
- `SegmentationProvider` — video reference → normalized segmentation result backed by real local mask data (ADR-005).
- `BackgroundGenerationProvider` — prompt → real local background image asset + simulated generation metadata.

Mode selection: `CLIPFORGE_AI_MODE=mock` is the default; `live` there is still rejected. Transcription can be enabled in isolation with `CLIPFORGE_TRANSCRIBE_MODE=live` + `MODEL_API_KEY`; every other provider remains the mock. There is no silent fallback and no automatic live activation. The frontend never talks to a provider directly and never sees credentials.

## Voice Pipeline (Milestone 6A)

1. Browser records with MediaRecorder and keeps the audio locally until the user clicks Transcribe.
2. `POST /api/transcribe` validates the upload, converts via FFmpeg to mono 16-bit PCM WAV at 24 kHz, verifies the WAV with ffprobe, and calls the provider **once** (temp files deleted afterwards).
3. Live: the Meta adapter posts the documented multipart request and normalizes `{sessionId, transcript, audioDurationMs, turns}`; no confidence is invented. Mock: the explicitly selected fixture is returned, labelled simulated.
4. The transcript is displayed and editable; only after explicit confirmation (`POST /api/jobs/{id}/voice` with `transcript`) does the planner run. Confirmed text is stored on the job; the worker never re-transcribes it.
5. Failures are explicit (timeout/429/API error); retry requires a user click, protecting the API budget.

## Professional Editing Director (Milestone 6B-PREP)

- **Capability registry** (`packages/contracts/clipforge_contracts/capabilities.py`) is the single authority: IDs, names, descriptions, typed input/output schemas, required providers, backend handlers, dependencies, status (`available_mock` / `available_local` / `available_live` / `planned` / `disabled`), verification and approval requirements.
- **v2 plan** (`director_plan.py`): `ProfessionalEditingPlan` with request id, raw instruction, interpretation, subject strategy, output target, typed operations (capability id, params, dependencies, status, expected output), providers, estimated stages, expected results, verification requirements, explanations, clarification and approval. Validators reject unknown/disabled capabilities, wrong parameter types, missing dependencies, dependency-order violations, arbitrary fields and invented approvals.
- **v1 adapter**: `to_execution_plan()` converts ready v2 plans into the existing `EditingPlan` (blur/replace + keep-subject-sharp); clarification/unsupported map to v1 intents. The worker still executes v1 only; v2 is not wired into execution yet.
- **Mock director** (`packages/director`): deterministic, offline scenarios A–E. Not part of the worker pipeline.
- **Playbook**: `apps/api/clipforge_api/prompts/professional_editing_director.md`, validated by `clipforge_api/playbook.py`; runtime asset for future Muse Spark, never loaded during tests' inference (there is none).
- **Stages**: ten validated `DirectorStage` values and a mapper from current worker stages; no percentages are fabricated.
- **Skills vs playbook**: `.opencode/skills/clipforge-editing-director` is development guidance for the coding agent; the playbook is runtime system content. They are intentionally separate.
- **Approval/cancel/revision**: contracts and docs only; no endpoints or UI exist yet. The v2 plan carries `approval_status`; replacement requires approval.
- **Video-use adaptation (6B-PREP-R)**: methodology adapted from browser-use/video-use at pinned commit `43cfc56` (see `docs/THIRD_PARTY_NOTICES.md` + `LICENSES/video-use-MIT.txt`); EDL v2 (`edl.py`) projects ready v2 plans with capability-typed params, registry-resolved handlers, timing forbidden while `timeline.trim` is disabled, canonical provenance hashes; immutable `EditHistoryEntry` persists in `job.json` via `JobRecord.edit_history`; `OutputEvaluationReport` separates objective checks from human review with a 3-pass correction ledger.
- **Muse Spark director (6B-LIVE, prepared not live-tested)**: `MetaEditingDirectorProvider` (`packages/director/.../spark.py`) implements plan generation only over Chat Completions (`POST /v1/chat/completions`, Standard `muse-spark-1.3` default, Bearer auth, `response_format` json_schema, `max_completion_tokens`, no tools, no web search, transcript text + video metadata only). Single POST, no retries; request_id/raw echo enforced; Pydantic + registry validation; token usage + Standard-rate cost accounting (Contributor rates via `require_contributor=True`, exact id `muse-spark-1.3-contributor`, optional `reasoning_effort`). `LiteMetaEditingDirectorProvider` (LIVE-CALL 003) reuses the same rails with a hand-written 1,948-byte zero-$ref `ProfessionalEditingPlanLite` wire schema parsed as `LitePlan` then converted and fully validated as v2. See ADR-011, ADR-012 and ADR-013.

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

## Frontend Integration (Milestone 5)

- The studio talks only to the contracted REST endpoints via a typed client (`apps/web/src/lib/api.ts`, types mirror `docs/API_CONTRACTS.md`). Upload uses XMLHttpRequest for real progress; job polling runs every 1.5 s and stops at terminal states; downloads fetch the verified endpoint as a Blob (cross-origin `download` attributes are ignored by browsers).
- Voice: the browser records real audio with MediaRecorder (with playback). Because transcription is a mock fixture provider (ADR-004), the user confirms which representative command they spoke; the UI labels this as simulated transcription everywhere, and the authoritative transcript is the one returned by the backend in the job result. When live transcription is integrated (Milestone 6), the recorded audio replaces the fixture selection.
- CORS: the API allows only `http://localhost:3000` / `http://127.0.0.1:3000` (GET/POST). No credentials exist in mock mode; nothing provider-specific reaches the frontend.

## Deferred / Placeholder

- Live Meta adapters: placeholders raising `LiveProviderNotImplementedError`. No endpoint, field, or schema is assumed (see `docs/API_CONTRACTS.md`).
