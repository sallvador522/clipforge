# ClipForge — Architecture Decision Records

Decisions are never silently changed. Superseding a decision requires a new ADR referencing the old one.

## ADR-001: Hosted SAM 3.1 via Meta Model API
- **Status:** Approved (integration deferred, see ADR-004).
- **Decision:** Subject segmentation/tracking will use SAM 3.1 through Meta hosted inference, accessed only from server-side code with a Bearer API key held server-side. A dedicated SAM provider adapter isolates the integration so it can change without rewriting the video pipeline.
- **Consequences:** The Python worker must NOT download, install, or host SAM checkpoints. No PyTorch, CUDA, or local SAM inference dependencies. The worker prepares input video, submits segmentation requests, decodes results into the internal mask contract (ADR-005), and passes masks to rendering.
- **Uncertainty:** User-supplied integration details (model name, base URL, endpoint) are recorded as unverified. Request/response schema, mask encoding, sync vs async execution, and polling must be confirmed against current official Meta documentation before any live code is written. Until then the live adapter is an explicit placeholder.

## ADR-002: FFmpeg + OpenCV Python Video Stack
- **Status:** Approved.
- **Decision:** Python worker uses FFmpeg for video decoding, normalization, audio preservation, encoding and final export; OpenCV for frame processing, mask operations, compositing, and visual transformations.
- **Consequences:** Rendering is CPU-based; no GPU/CUDA infrastructure unless profiling demonstrates necessity (ADR-006). Original video/audio preserved until output is verified.

## ADR-003: MediaBunny Excluded from MVP
- **Status:** Approved.
- **Decision:** MediaBunny (including `@mediabunny/server`) is removed from the MVP architecture and must not be installed.
- **Consequences:** All media processing is Python FFmpeg + OpenCV. MediaBunny may only be reconsidered when a clearly justified browser-side media processing requirement appears, via a new ADR.

## ADR-004: Mock-First Development
- **Status:** Approved. Mandatory.
- **Context:** Remaining external AI API budget is ~$30. The entire application must be completed and validated without consuming external AI credits.
- **Decision:** All AI functionality is implemented with deterministic local mocks and fixtures behind typed provider interfaces (`TranscriptionProvider`, `EditingPlannerProvider`, `SegmentationProvider`, `BackgroundGenerationProvider`), each with a deterministic mock, an unimplemented live placeholder, and a shared normalized internal contract. Default configuration is `CLIPFORGE_AI_MODE=mock`. Rendering is never mocked.
- **Consequences:** Mock mode makes zero external requests (verified by tests), needs no credentials, never silently falls back to live, and uses deterministic fixtures for repeatable tests. Live mode requires an explicit configuration change plus explicit user approval.
- **Live integration gate:** Real providers are activated only after frontend, backend, mocks end-to-end, FFmpeg/OpenCV rendering, error handling, automated tests, and documentation are complete; then official docs (schemas, media inputs, mask encoding, sync/async, polling, rate limits, pricing) are verified, and a single controlled integration test is proposed. No automatic retries that could cause billable requests; request logging, idempotency where supported, and application-level budget tracking are required for live mode.

## ADR-005: PNG Mask Sequence + manifest.json
- **Status:** Approved.
- **Decision:** Canonical internal mask representation is one lossless 8-bit grayscale PNG per frame (`frame_%06d.png`, 0=background, 255=subject, intermediate=soft alpha/confidence) plus `manifest.json` recording video dimensions, frame count, FPS, frame timestamps or the derivation rule `timestamp_ms = round(index * 1000 / fps)`, subject identifier, mask encoding, filenames/frame indices, and source video identifier or hash. Never lossy JPEG for masks.
- **Consequences:** A mask writer and validating loader are implemented in the worker. The loader rejects missing frames, invalid files, wrong dimensions (never silently resized), unexpected indices, and corrupt masks; both binary and grayscale masks are accepted. Explicit resize, when necessary, uses nearest-neighbour only. Edge smoothing is applied separately during rendering, never in the loader. No alternative format (FFV1, packed arrays) until profiling demonstrates a concrete need.

## ADR-006: CPU Rendering Performance
- **Status:** Approved.
- **Decision:** CPU rendering is mandatory. No processing times are promised before benchmarks. The benchmark unit is 300 frames, 1280x720, 30 FPS, 10-second source, measured independently for background blur and background replacement, capturing: total processing time, FPS, peak RAM, CPU usage, output file size, audio synchronization, frame integrity. Test machine specifications are recorded with measurements.
- **Consequences:** Implementation starts with sequential frame processing and bounded memory. Bounded frame pipelining, parallel processing, downscale-blur, and other optimizations are introduced only after profiling, and never by sacrificing mask correctness or visual quality without measuring the trade-off.

## ADR-007: Synthetic Testing Limitations
- **Status:** Approved. Limitation accepted for MVP.
- **Decision:** Mock segmentation uses deterministic synthetic fixtures covering: static subject, moving subject, multiple subjects crossing, partial occlusion, missing masks, mask holes, irregular edges, temporal mask jitter, and different foreground/background lighting conditions.
- **Consequences:** These fixtures validate the rendering pipeline and mask-handling behaviour, **not** real SAM tracking quality. This limitation is accepted. Where suitable licensed footage is available, at least one real-world video with manually prepared masks should be added; this must not trigger any AI API request.

## ADR-008: Transcription Is the First Live-Capable Provider
- **Status:** Approved (Milestone 6A). No live calls performed yet.
- **Context:** Muse Voice Transcribe is available through Meta Model API with a verified file endpoint, schema and pricing. The remaining budget is ~$30, so live inference must be tightly scoped and explicitly approved.
- **Decision:** Transcription gains a real provider (`MetaVoiceTranscriptionProvider`, model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe`, Bearer `MODEL_API_KEY`, multipart `request` JSON + `audio` WAV). It is enabled only by `CLIPFORGE_TRANSCRIBE_MODE=live` plus `MODEL_API_KEY`; `CLIPFORGE_AI_MODE=mock` remains the default and all other providers (planning, segmentation, image generation) remain mocks. The frontend receives real audio from MediaRecorder, the API converts it with FFmpeg to mono 16-bit PCM WAV at 24 kHz, and calls the provider exactly once. The user reviews and edits the transcript before it reaches the planner.
- **Consequences:** No automatic retries of transcription requests (a failed call is reported; retry requires an explicit user action). Timeouts, 429 and API errors have distinct, safe messages. `sessionId` is generated per request and logged; raw audio and the API key are never logged, and temporary audio is deleted after each request. Mock mode never interprets audio: it requires an explicitly selected mock command and labels the transcript simulated. The first live request requires a reviewed cost estimate and explicit user approval.

## ADR-009: Professional Editing Director Architecture
- **Status:** Approved (Milestone 6B-PREP). No live model integration.
- **Context:** ClipForge needs professional editing intelligence that understands intent, plans with real tools, explains decisions and verifies results. The previous mock planner mapped phrases into a minimal v1 `EditingPlan`; there was no capability registry, approval concept or truthful director stage model.
- **Decision:**
  - **Capability registry** in `packages/contracts` is the single authority. Statuses are `available_mock`, `available_local`, `available_live`, `planned`, `disabled`. Local FFmpeg/OpenCV work is `available_local` (never described as live AI); mock segmentation is `available_mock` and explicitly not SAM; local/mock background assets are not Muse Image.
  - **Dual contracts:** v1 `EditingPlan` remains the worker execution contract, untouched. v2 `ProfessionalEditingPlan` adds request id, interpretation, subject strategy, typed capability operations, dependencies, providers, stages, expected results, verification, explanations, clarification and approval. A validated `to_execution_plan()` adapter bridges v2 to v1. Model output can never contain paths, shell commands or arbitrary parameters.
  - **Mock director** is implemented independently from the worker (`packages/director`), deterministic and offline. It is not wired into execution in this milestone.
  - **Runtime playbook** (`apps/api/clipforge_api/prompts/professional_editing_director.md`) is versioned system-instruction content for the future Muse Spark integration, loaded by a validating loader. The **development skill** (`.opencode/skills/clipforge-editing-director`) guides the coding agent only and is never sent to the runtime model.
  - **Transparency:** ten validated director stages prepare truthful progress; approval, rejection, cancellation and revisions are contracts/documentation only until a plan actually gates execution.
- **Consequences:** Muse Spark can be integrated later by loading the playbook and registry, emitting v2 plans, validating and adapting to v1 for execution. Unsupported capabilities cannot be invented. No live model, SAM or image generation call is made in this milestone; the worker and renderer are unchanged.

## ADR-010: Video-Use Methodology Adaptation (6B-PREP-R)
- **Status:** Approved. Read-only audit of browser-use/video-use at pinned commit `43cfc56`.
- **Context:** The upstream skill is a coding-agent editing workstation with shell access, segment pipelines and hosted ElevenLabs transcription. ClipForge is a hosted web app with a capability registry, typed contracts and local rendering.
- **Decision:**
  - Adapt methodology only: audio-first reasoning, bounded on-demand visuals, Ask → Confirm → Execute → Iterate (max 3) → Persist, declarative EDL, objective self-evaluation with explicit human review.
  - Reject execution model: no segment extract/concat, no subtitle/fade/cut-boundary rules, no invented tools or raw FFmpeg strings, no ElevenLabs, no animation engines, no new dependencies.
  - EDL v2 is a projection of ready v2 plans with capability-typed params, registry-resolved handlers, timing forbidden while `timeline.trim` is disabled, and canonical provenance hashes.
  - Evaluation separates objective media checks from subjective quality; visual corrections require a new render plus re-inspection.
  - History reuses `job.json` via immutable `EditHistoryEntry`; no new database, memory service, read API or endpoint.
  - Licensing: MIT text preserved in `LICENSES/video-use-MIT.txt` and attributed in `docs/THIRD_PARTY_NOTICES.md`; no upstream code copied.
- **Consequences:** Spark can later reason with the adapted playbook while staying registry-gated. Timing/segment features remain disabled until their capabilities, handlers and verification exist.

## ADR-011: Muse Spark Director Integration Prep (6B-LIVE, no live call)
- **Status:** Prepared, NOT live-tested. No request sent; no approval granted yet.
- **Context:** Muse Spark 1.3 is verified on Model API (`muse-spark-1.3`, base `https://api.meta.ai/v1`, Bearer `MODEL_API_KEY`, Standard mode $1.25/1M in + $4.25/1M out). ClipForge needs plan generation only for the first test — no tool execution, rendering, SAM, image or audio input.
- **Decision:**
  - **Protocol: Chat Completions** (`POST /v1/chat/completions`), not Responses API. Single-turn plan generation needs no reasoning replay or server-managed history; structured output via `response_format` (`json_schema`, Pydantic-derived, `strict: false`) has a documented guaranteed-conformance contract; stateless with no `store`/`previous_response_id`. Responses `text.format` must never be sent here.
  - **Provider:** `MetaEditingDirectorProvider` (`packages/director/.../spark.py`) loads the v1.1 playbook + registry summary, takes the confirmed transcript text plus registered video metadata, emits one validated v2 plan. No `tools` are sent (plan generation only), no web search, no audio bytes, Standard model only (Contributor variants rejected).
  - **Security:** Pydantic + registry validation, capability/param match, dependency order, approval rules, echo enforcement (`request_id`, `raw_instruction`), truncation/tool-call rejection, safe error mapping, single POST, no retries, key never logged.
  - **Accounting:** `usage.{prompt,completion,total}_tokens` → cost at Standard rates; rough pre-request size estimate (`estimate_tokens`, chars/4, not a billing figure).
- **Consequences:** The first live call remains blocked on explicit approval of the measured proposal. All other providers stay mock; the worker, renderer and UI are unchanged.

## ADR-012: First Live Director Call — Contributor Medium (6B-LIVE LIVE-CALL 001)
- **Status:** APPROVED for exactly one call; NOT yet executed (no key in `.env`).
- **Context:** ADR-011 prepared a Standard-mode provider. The approved live call uses the Contributor variant with medium reasoning effort: model id `muse-spark-1.3-contributor` (verified in the Models and Pricing docs fetched the same day), Contributor rates $0.10/1M input + $0.20/1M output (150 RPM / 4M TPM for the Contributor variant row), `reasoning_effort: "medium"` (verified accepted value; `none` is rejected for Spark). There is NO `context`-size parameter in the verified Chat Completions contract — “medium context” is interpreted as the default 1,048,576-token window carrying a ~3.2k-token prompt, and only `reasoning_effort` is sent.
- **Decision:**
  - Model must be exactly `muse-spark-1.3-contributor` (`require_contributor=True`); every other model string, including Standard, is rejected in this mode.
  - Endpoint `POST https://api.meta.ai/v1/chat/completions`, Bearer `MODEL_API_KEY` (canonical env var name per official docs and repo-wide use; no `META_API_KEY` exists anywhere).
  - `response_format` json_schema `ProfessionalEditingPlan` (`strict: false`), `max_completion_tokens: 1500`, no tools, no web search, transcript text + benchmark-unit video metadata only.
  - Accounting at Contributor rates from actual `usage`; cached-token breakdown not modeled.
  - Exactly one POST, no retries; a second call needs fresh approval. Key never printed, logged or committed.
- **Consequences:** Provider gains `require_contributor` and `reasoning_effort` options (defaults preserve Standard-only safety). All other providers stay mock; worker, renderer and UI unchanged.


