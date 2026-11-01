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
| Web frontend | `apps/web/` | Next.js studio: upload, voice recording, plan review, job monitoring, before/after preview, verified download |
| API | `apps/api/` | FastAPI REST endpoints, upload validation (ffprobe), plan decisions, non-blocking job submission |
| Worker | `apps/worker/` | Mask writer/loader/validation, fixtures, job processor, persistent worker process, FFmpeg+OpenCV renderer |
| Contracts | `packages/contracts/` | Single source of truth: `EditingPlan`, v2 director plan, capability registry, normalized provider responses, mask manifest |
| Providers | `packages/providers/` | Typed provider interfaces, deterministic mocks, live transcription |
| Director | `packages/director/` | Mock v2/live editing director, lite wire schema, v2 validation + v1 adapter, live-call ledger |
| Jobs | `packages/jobs/` | Shared `JobRecord` state machine, auditable transitions + atomic file-based `JobStore` used by API and worker |

## Provider Architecture (ADR-004, ADR-008, ADR-014, ADR-019)

Four typed provider interfaces plus the director, each with a deterministic mock and shared normalized internal contracts from `packages/contracts`:

- `TranscriptionProvider` - voice audio → normalized transcript. **Live-capable** via `MetaVoiceTranscriptionProvider` (Muse Voice Transcribe). `transcribe(fixture_id)` remains the mock fixture path; `transcribe_audio(path, authorization=...)` is the real path and requires a one-shot `LiveCallAuthorization` before its POST.
- `EditingPlannerProvider` — transcript → validated `EditingPlan` (deterministic mapping; no LLM). Kept for backward compatibility and tests; the worker no longer uses it when the director is mocked. Mock mode now consumes the v2 Director plan and adapts it to the same v1 execution contract.
- `SegmentationProvider` - video reference → normalized segmentation result backed by real local mask data (ADR-005). `MockSegmentationProvider` writes two deterministic synthetic per-object tracks. `SamSegmentationProvider` (6D) implements the official SAM 3.1 Responses/Files contract, `meta-sam-parser` decoding, per-object masks, selected-union masks and source-frame previews. Live mode requires `CLIPFORGE_SEGMENTATION_MODE=live` and a one-shot `LiveCallAuthorization`; it has **not** been live-validated.
- `BackgroundGenerationProvider` — prompt → real local background image asset + simulated generation metadata.
- `ProfessionalEditingDirector` (`packages/director`) - transcript + video metadata → validated v2 plan. Mock is deterministic/offline; live uses `LiteMetaEditingDirectorProvider` (Muse Spark) and `create_plan(..., authorization=...)` requires a one-shot `LiveCallAuthorization` before its POST. The worker adapts ready plans to v1 for execution.

Mode selection: `CLIPFORGE_AI_MODE=mock` is the default; `live` there is still rejected. Three providers can be enabled live, independently and explicitly: `CLIPFORGE_TRANSCRIBE_MODE=live`, `CLIPFORGE_DIRECTOR_MODE=live` and `CLIPFORGE_SEGMENTATION_MODE=live`, all requiring server-side `MODEL_API_KEY`. Background generation and the legacy planner remain mocked. There is no silent fallback and no automatic live activation. The dev launchers (`scripts/dev_api.py`, `scripts/dev_worker.py`) force all three live functions to mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is explicitly set. Live providers themselves reject direct calls without a `LiveCallAuthorization`. The frontend never talks to a provider directly and never sees credentials.

## Voice Pipeline (Milestone 6A)

1. Browser records with MediaRecorder and keeps the audio locally until the user clicks Transcribe.
2. `POST /api/transcribe` validates the upload, converts via FFmpeg to mono 16-bit PCM WAV at 24 kHz, verifies the WAV with ffprobe, and calls the provider **once** (temp files deleted afterwards).
3. Live: the Meta adapter posts the documented multipart request and normalizes `{sessionId, transcript, audioDurationMs, turns}`; no confidence is invented. Mock: the explicitly selected fixture is returned, labelled simulated.
4. The transcript is displayed and editable; only after explicit confirmation (`POST /api/jobs/{id}/voice` with `transcript`) does the planner run. Confirmed text is stored on the job; the worker never re-transcribes it.
5. Failures are explicit (timeout/429/API error); retry requires a user click, protecting the API budget.

## Professional Editing Director (Milestone 6B-PREP)

- **Capability registry** (`packages/contracts/clipforge_contracts/capabilities.py`) is the single authority: IDs, names, descriptions, typed input/output schemas, required providers, backend handlers, dependencies, status (`available_mock` / `available_local` / `available_live` / `planned` / `disabled`), verification and approval requirements.
- **v2 plan** (`director_plan.py`): `ProfessionalEditingPlan` with request id, raw instruction, interpretation, subject strategy, output target, typed operations (capability id, params, dependencies, status, expected output), providers, estimated stages, expected results, verification requirements, explanations, clarification and approval. Validators reject unknown/disabled capabilities, wrong parameter types, missing dependencies, dependency-order violations, arbitrary fields and invented approvals.
- **v1 adapter**: `to_execution_plan()` converts ready v2 plans into the existing `EditingPlan` (blur/replace + keep-subject-sharp); clarification/unsupported map to v1 intents. Since 6C, both mock and live paths validate the v2 plan, persist it for review, adapt it to v1 and execute it only after approval; v1 remains the render contract.
- **Mock director** (`packages/director`): deterministic, offline scenarios A–E. When `CLIPFORGE_DIRECTOR_MODE=mock`, the worker uses `MockProfessionalEditingDirector` (v2), persists the validated plan and adapts it to v1; when `live`, the live director runs instead. There is no silent fallback to the legacy planner.
- **Playbook**: `apps/api/clipforge_api/prompts/professional_editing_director.md`, validated by `clipforge_api/playbook.py`; runtime system content for the Muse Spark director. It is read from disk when the live director provider is constructed (no model call at load) and is never sent to the coding agent as development instructions.
- **Stages**: ten validated `DirectorStage` values and a mapper from current worker stages; no percentages are fabricated.
- **Skills vs playbook**: `.opencode/skills/clipforge-editing-director` is development guidance for the coding agent; the playbook is runtime system content. They are intentionally separate.
- **Review and approval (6C)**: every ready plan, including blur-only plans, stops at `awaiting_approval` with a persisted v2 plan and `render_status="awaiting_approval"`. `GET /plan` exposes the plan and capability metadata; `POST /approve` atomically moves the job to `queued`/stage `approved`; `POST /reject` makes it terminal; `POST /clarify` submits an inline answer and rebuilds the plan. The worker re-enters from the persisted plan and never calls the director again after approval. Clarification is limited to 3 rounds. See ADR-018.
- **Video-use adaptation (6B-PREP-R)**: methodology adapted from browser-use/video-use at pinned commit `43cfc56` (see `docs/THIRD_PARTY_NOTICES.md` + `LICENSES/video-use-MIT.txt`); EDL v2 (`edl.py`) projects ready v2 plans with capability-typed params, registry-resolved handlers, timing forbidden while `timeline.trim` is disabled, canonical provenance hashes; immutable `EditHistoryEntry` persists in `job.json` via `JobRecord.edit_history`; `OutputEvaluationReport` separates objective checks from human review with a 3-pass correction ledger.
- **Muse Spark director (live-tested in LIVE-E2E 005)**: `MetaEditingDirectorProvider` (`packages/director/.../spark.py`) implements plan generation only over Chat Completions (`POST /v1/chat/completions`, Standard `muse-spark-1.3` default, Bearer auth, `response_format` json_schema, `max_completion_tokens`, no tools, no web search, transcript text + video metadata only). Single POST, no retries; request_id/raw echo enforced; Pydantic + registry validation; token usage + Standard-rate cost accounting (Contributor rates via `require_contributor=True`, exact id `muse-spark-1.3-contributor`, optional `reasoning_effort`). `LiteMetaEditingDirectorProvider` (LIVE-CALL 003) reuses the same rails with a hand-written 1,948-byte zero-$ref `ProfessionalEditingPlanLite` wire schema parsed as `LitePlan` then converted and fully validated as v2. Live wiring uses the lite provider with `reasoning_effort=medium` and a 16,000-token cap (LIVE-CALL 005). See ADR-011, ADR-012, ADR-013 and ADR-014.
- **Live-call ledger**: `LiveCallBudget` (`packages/director/.../ledger.py`) enforces per-function caps in `storage/live-call-ledger.json` (defaults 2 transcription + 2 director + 2 segmentation; `CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT` / `CLIPFORGE_LIVE_DIRECTOR_LIMIT` / `CLIPFORGE_LIVE_SEGMENTATION_LIMIT` raise them for explicit local testing, ADR-015/ADR-019). It is fail-closed (ADR-017): corrupt/unreadable/invalid data raises `LedgerIntegrityError`; counters are never reset; an existing lock raises `LedgerLockedError` and is not deleted automatically. `LiveCallAuthorization` is a one-shot token that reserves immediately before the provider POST and cannot reserve twice. Reservations are atomic and are not released after an uncertain network outcome. There are no automatic retries. `/health` reports configured limits and current usage.
- **Job result**: live execution persists `director_plan`, `director_usage`, `director_request_id` and `director_audit` alongside the existing transcript/plan/segmentation/render fields.
- **Operation-id normalisation (ADR-016)**: the lite wire may carry model-generated ids (`op1_isolate`). `normalize_lite_operation_ids()` assigns `op_1`…`op_n` in original order, returns the original → canonical map, rewrites dependencies and rejects duplicate/unknown/cyclic/forward dependencies before full v2 validation. Capability ids, params, order and execution semantics are unchanged; the strict `DirectorOperation` pattern remains in force. EDL provenance is computed from canonical ids.
- **Per-call audit (ADR-016)**: `DirectorAudit` records client/server request ids, provider/model, live/standard/contributor mode, wire schema, token counts when supplied, estimated cost from usage, actual cost only when reliably available, validation status, error category/code, HTTP status, finish reason and timestamp. The provider updates it around the single POST; the worker persists it in `JobResult` on success and failure, so rejected plans still have an audit trail. Failed jobs keep this audit in `job.json`; `/result` remains completed-only.

## SAM Segmentation and Subject Selection (ADR-019)

- **Detection before review:** after the Director produces a ready plan, the worker runs the segmentation provider and persists per-object masks and previews before setting `awaiting_approval`. This is required so the user can choose who stays sharp. Rendering still cannot start before approval.
- **Official contract:** `SamSegmentationProvider` uses `sam-3.1` over `POST /v1/responses`, `input_text` noun phrase `"person"`, `input_video.file_id`, `stream=true`, `metadata.mask_encoding="one_bit"`, and `meta-sam-parser==0.1.0` (`parse_responses_stream` + `decode_mask_to_raster`).
- **Private input:** a temporary video-only MP4 is created (stream copy when compatible, otherwise H.264 transcode) and verified for dimensions/FPS/frame count/no audio. The original is untouched. The temporary file is uploaded with `purpose=user_data` and `expires_after=3600`, referenced by `file_id`, and deleted in `finally`. No public URL is used. Cleanup failures are recorded.
- **Per-object masks:** each SAM object gets its own ADR-005 PNG sequence (all frames, zeros where absent); the job root holds the union. Stable SAM object IDs are preserved as strings, not list positions. Duplicate/non-increasing revisions, >16 objects per frame, out-of-range frames/bounds, mask/bounds dimension mismatch, incomplete streams and malformed output are rejected. The loader refuses `segmentation_status="incomplete"`.
- **Selection:** `GET /plan` exposes subject IDs, preview URLs and detection metadata. `POST /approve` takes `subject_ids`; the backend validates them and stores the selection. One subject is preselected; multiple require an explicit choice. Zero detections is a terminal `NoSubjectsDetected` outcome with no render.
- **Renderer:** `combine_subject_masks()` streams selected per-object masks into `masks/selected/` with bounded memory. The existing renderer keeps the selected people sharp and blurs/replaces the background outside them. **Selective person blur is not supported.**
- **Live status:** implemented but **not live-validated**. No request was made in 6D; detection quality and live cleanup/stream behaviour are unknown. See `docs/SAM_31_INTEGRATION.md`.

## Video Pipeline (ADR-001, ADR-002, ADR-005, ADR-006, ADR-019)

1. Worker prepares the source video (FFmpeg decode/normalize).
2. Segmentation provider returns masks in the canonical internal format: PNG sequence + `manifest.json` (ADR-005). Mock mode writes two synthetic per-object tracks. Live SAM maps the official Responses records into per-object masks and a union; the pipeline never consumes a provider-native format. Detection happens before plan review; selected subject masks are unioned at render time.
3. Renderer (`clipforge_worker/renderer.py`, implemented Milestone 4): OpenCV decodes frames sequentially and streams masks one at a time via `MaskLoader.iter_masks` (bounded memory — never the whole sequence in RAM), builds a feathered alpha (Gaussian edge smoothing in the renderer, not the loader), keeps the subject sharp, and either blurs the background (large-sigma Gaussian) or replaces it with a local background image (cover-fit resize; masks are never resized). Raw frames are piped to FFmpeg (libx264/yuv420p) which muxes the **original audio** from the source file (lossless `-c:a copy` for AAC/MP3, AAC re-encode otherwise).
4. Verification: `verify_render_output` re-probes the actual file with ffprobe frame counting — video stream, exact resolution, exact frame count, duration, and audio presence (when the source has audio) — before the job may complete or be downloaded.
5. CPU-only, sequential frame processing with bounded memory first (ADR-006). Optimizations (pipelining, parallelism, downscale-blur) only after profiling — blur is the known bottleneck (see STATUS.md measurements).

Environment findings recorded at Milestone 4 (no silent environment changes):
- System FFmpeg is a Dec 2018 build (`N-92722`) with libx264 + AAC; sufficient for this baseline. **Upgrade recommended before production** (security and encoder fixes); not performed automatically.
- Two 2018-build quirks are handled in code: FFmpeg stderr is redirected to a temp log file (an unread PIPE deadlocks at 720p), and `-shortest` is omitted (with copied audio it drops the video stream entirely — verified empirically).
- A latent Milestone 3 bug was found and fixed: upload probing used `-select_streams v:0`, so `has_audio` was always false.

Failure handling: provider timeouts, incomplete SAM streams, malformed masks and failed segmentation produce explicit failed job states. SAM uploads are deleted in `finally`; cleanup failures are recorded. Live calls are single-shot with no automatic retries; the ledger refuses a call once the per-function cap is reached. Mocks are deterministic and side-effect-free apart from local files.

## Job System (Milestone 3, implemented)

- State machine: `queued → processing → awaiting_approval | awaiting_clarification | completed | failed`, plus terminal `rejected` and `unsupported`. Ready plans first run `segmenting` (detection) and then stop at `awaiting_approval`; approval moves `awaiting_approval → queued` with stage `approved`; clarification moves `awaiting_clarification → queued` with stage `replanning`. A `stage` field carries progress detail (`awaiting_voice`, `planning`, `segmenting`, `awaiting_approval`, `approved`, `preparing_masks`, `rendering`, `completed`, ...). A job becomes claimable only when a voice instruction is attached (`ready=true`).
- `JobStore` (`packages/jobs`) persists each record as `storage/jobs/<job_id>/job.json` with atomic temp-file + `os.replace` writes. Claiming uses an `O_CREAT|O_EXCL` lock file, so exactly one worker process can claim a job (job isolation, no duplicate processing); the claim lock is released after every worker run, including a review wait, so an approved job can be claimed again. User transitions use a separate `transition.lock` and validate the expected source state. Every status/stage change appends an auditable `JobStateEntry` (`state_history`).
- The API only validates, stores, and enqueues; it never runs provider or rendering work. The persistent worker (`python -m clipforge_worker.worker_process`) polls for ready jobs and processes them sequentially: confirmed transcript → director/planner → segment (masks re-validated with the ADR-005 loader) → optional mock background → **render → verify**. Live director plans are reserved through a one-shot `LiveCallAuthorization` created by the worker, validated as v2, adapted to v1 and executed. The worker stops after persisting the plan: every ready plan waits at `awaiting_approval`, clarification waits at `awaiting_clarification`, and unsupported/rejected requests are terminal. None of those states segments or renders. After approval, the worker claims the job again, reads the persisted v1 adapter and renders exactly once without calling the director again.
- Since Milestone 4, an edit job's `completed` means: mock AI pipeline finished **and** a real MP4 was rendered and verified (`render_status="verified"`, `rendered` facts in the result). `GET /api/jobs/{id}/download` serves that file only when it is verified and present on disk; otherwise 409.
- Upload safety: filename path components stripped, extension allowlist (`.mp4/.mov/.webm/.mkv`), streaming size cap, empty/unreadable files rejected, ffprobe enforces MVP limits (video stream required, ≤720p, ≤10.5 s, ≤30 FPS). Invalid uploads leave no orphaned files or records. Per-job directories isolate all artefacts; originals are preserved on failure.
- Every worker exception is logged (with traceback) and stored as a structured `{code, message}` job error. Nothing is swallowed.

## Storage Layout (local, gitignored)

```
storage/
  uploads/<job_id>/source.<ext>
  jobs/<job_id>/job.json
  jobs/<job_id>/masks/{manifest.json, frame_000000.png, ...}
  jobs/<job_id>/masks/objects/object_<sam_id>/{manifest.json, frame_*.png}
  jobs/<job_id>/masks/previews/object_<sam_id>.png
  jobs/<job_id>/masks/selected/{manifest.json, frame_*.png}
  jobs/<job_id>/output.mp4        (verified rendered output)
  live-call-ledger.json           (per-function live-call caps; gitignored)
```

## Frontend Integration (Milestone 5)

- The studio talks only to the contracted REST endpoints via a typed client (`apps/web/src/lib/api.ts`, types mirror `docs/API_CONTRACTS.md`). Upload uses XMLHttpRequest for real progress; job polling runs every 1.5 s and stops at terminal states and at `awaiting_approval` / `awaiting_clarification`, where the plan review dialog takes over; downloads fetch the verified endpoint as a Blob (cross-origin `download` attributes are ignored by browsers).
- Plan review (6C/6D): the dialog shows the interpreted intention, subject strategy, dynamic operation count, parameters, expected outputs, dependencies, capability source (MOCK/LOCAL/LIVE/PLANNED/UNAVAILABLE), approval requirements and verification checks. SAM-detected people appear as selectable cards with source-frame previews; the stable object IDs are sent only on approval. Approve/reject/clarify call the API; the UI never decides execution locally. The step tracker is derived from the backend status, stage, render status and verified result.
- Voice: the browser records real audio with MediaRecorder (with playback). In live mode the recorded audio is uploaded to `POST /api/transcribe` and the returned transcript is shown for review; in mock mode the UI requires an explicit representative command and labels it simulated. The authoritative transcript is always the backend result stored on the job. The UI never receives credentials or provider-native payloads.
- CORS: the API allows only `http://localhost:3000` / `http://127.0.0.1:3000` (GET/POST). No credentials exist in mock mode; nothing provider-specific reaches the frontend.

## Deferred / Placeholder

- **SAM 3.1 live inference:** `SamSegmentationProvider` is implemented and offline-validated, but **no live request has been made**. Live detection quality, live stream behaviour and the Files API nested expiry encoding remain to be validated with explicit approval (ADR-019). Mock mode remains synthetic.
- **Selective person blur:** not implemented. The renderer can keep selected people sharp and blur/replace the background; it cannot blur chosen people while keeping the scene sharp.
- **Muse Image:** `background.generate` is planned but disabled; replacement uses local/mock assets, never a live image model.
- **Live legacy planner:** `EditingPlannerProvider` remains deterministic; live planning goes through the director.
- **Multi-user authorization:** there is no authentication or ownership model. The API is a local single-user service; any client that knows a job id can read or decide it. This must be added before deployment beyond localhost.
- **Live UI deployment:** `CLIPFORGE_AI_MODE=live` remains rejected; live capability is scoped per function by the two mode variables.
