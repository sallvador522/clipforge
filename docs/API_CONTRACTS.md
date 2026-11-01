# ClipForge — API Contracts

All contracts below are **internal ClipForge contracts**. Three Meta schemas are verified and implemented: Muse Voice Transcribe (ADR-008), Muse Spark Chat Completions (ADR-011 to ADR-014) and SAM 3.1 Responses/parsing (ADR-019). SAM implementation is offline-validated only; **no live SAM inference has been performed**. Muse Image remains **UNVERIFIED and unimplemented**: no endpoint, field or response structure for it is assumed or hardcoded. Its adapter must map a verified official schema into these internal contracts when integration is explicitly approved.

## Provider Mode

`CLIPFORGE_AI_MODE=mock` (default). Mock mode makes zero external requests and needs no credentials. Three providers can be enabled live independently: `CLIPFORGE_TRANSCRIBE_MODE=live`, `CLIPFORGE_DIRECTOR_MODE=live` and `CLIPFORGE_SEGMENTATION_MODE=live`; all require a server-side `MODEL_API_KEY`. Background generation and the legacy planner remain mocked. `CLIPFORGE_AI_MODE=live` itself is not supported. There is no silent fallback. SAM live is implemented but **not live-validated**.

## EditingPlan (packages/contracts, Pydantic, schema_version "1.0")

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | Currently `"1.0"` |
| `plan_id` | string | Deterministic in mock mode (derived from transcript) |
| `raw_transcript` | string | Source transcript text |
| `language` | string | e.g. `pt-BR` |
| `intent` | enum | `blur_background`, `replace_background`, `keep_sharp_blur_rest`, `clarification_needed`, `unsupported` |
| `subject` | object | `description`, `is_ambiguous`, `clarification_question` (required when ambiguous) |
| `operations` | discriminated union | `keep_subject_sharp`, `blur_background {strength 0..1}`, `replace_background {prompt, asset_id?}` |
| `preserve_audio` | bool | Always `true` for MVP |
| `output_format` | string | `mp4` |

Every generated plan is validated against this schema. Model/provider output is never executed without validation.

## Normalized Provider Responses (packages/contracts)

- `TranscriptResult`: `text`, `language`, `confidence` (nullable — Muse Voice Transcribe documents no confidence, so it is never invented), `provider_name`, `is_mock`, `session_id` (nullable), `audio_duration_ms` (nullable).
- `RenderResult`: verified facts about the rendered file.
- `SegmentationResult`: `job_id`, `subject_id`, `mask_manifest_path`, `frame_count`, `width`, `height`, `fps`, `provider_name`, `is_mock`, optional `model`, `subjects[]`, `source_sha256`, `status`, `diagnostics[]` and `file_cleanup`. `subjects[]` carries stable `object_id`, generic `label`, per-object `mask_manifest_path`, preview path, first/last frame, detected-frame count and optional confidence. Backed by real local mask files, never a bare success flag.
- `BackgroundResult`: `asset_id`, `image_path` (real local file), `width`, `height`, `orientation` (`landscape`|`portrait`), `simulated_prompt`, `provider_name`, `is_mock`.

## Transcription API and Provider (ADR-008, Milestone 6A)

Configuration: `CLIPFORGE_TRANSCRIBE_MODE=mock` (default) or `live`; live additionally requires `MODEL_API_KEY` (server-side). `CLIPFORGE_DIRECTOR_MODE=mock` (default) or `live` selects the director independently (ADR-014). `CLIPFORGE_SEGMENTATION_MODE=mock` (default) or `live` selects the SAM provider independently (ADR-019); it is implemented but not live-validated. `CLIPFORGE_AI_MODE=mock` stays the default; background generation and the legacy planner remain mocked. Dev launchers force all three live functions to mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is explicitly set (ADR-017). Live-call caps default to 2 transcription + 2 director + 2 segmentation per phase (`storage/live-call-ledger.json`); local testing can raise them with `CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT`, `CLIPFORGE_LIVE_DIRECTOR_LIMIT` and `CLIPFORGE_LIVE_SEGMENTATION_LIMIT` (positive integers, ADR-015/ADR-019). Raising a limit does not reset usage. The ledger is fail-closed; live providers require a one-shot authorization before their POST.

`POST /api/transcribe` — multipart:
- `file`: the browser recording (`.webm`, `.ogg`, `.oga`, `.wav`, `.m4a`, `.mp4`, `.mp3`), max 25 MB, max 60 s, must contain an audio stream.
- `mock_fixture_id` (optional, mock mode only): the explicitly selected mock command. Mock mode never interprets audio and returns 422 `mock_fixture_required` without it.

The API converts with FFmpeg to mono 16-bit PCM WAV at 24 kHz (`-ac 1 -ar 24000 -c:a pcm_s16le -map_metadata -1`) and verifies the converted file with ffprobe before use. Temporary audio is deleted after the request.

Response: the normalized `TranscriptResult` plus `transcribe_mode` (`mock`|`live`). Errors: `400 empty_audio`, `413 audio_too_large`, `422 unsupported_audio_extension`/`invalid_audio`/`no_audio_stream`/`audio_too_long`/`conversion_failed`/`mock_fixture_required`, `503 transcription_not_configured`, `504 transcription_timeout`, `429 transcription_rate_limited` or `429 live_budget_exhausted` (no provider call; the message names the configured limit and env override), `503 live_budget_not_configured` (live mode without a ledger), `503 live_budget_integrity_error` (corrupt/unreadable ledger), `503 live_budget_locked` (ledger lock held), `503 live_budget_not_authorized` (provider guard refused), `502 transcription_failed`.

Muse Voice Transcribe (verified against official docs): `POST https://api.meta.ai/v1/asr/transcribe?sessionId=<clipforge-id>`, `Authorization: Bearer MODEL_API_KEY`, multipart parts `request` (JSON with `model: "muse-voice-transcribe-1.0"`, `audioEncoding: "WAV"`, `mode: "PUSH_TO_TALK"`, `languageBias: ["Portuguese"]`) and `audio` (WAV). Response `{sessionId, transcript, audioDurationMs, turns}`. Exactly one HTTP request per user action; no automatic retries. Pricing: $0.18 per hour of audio, billed per whole second.

`POST /api/jobs/{job_id}/voice` now accepts exactly one of:
- `audio_fixture_id` (legacy mock path), or
- `transcript` (the reviewed/confirmed text, 1–500 chars) with optional `transcription_session_id`. The planner consumes the confirmed text; no transcription is repeated.

## Mask Contract (ADR-005) — canonical internal segmentation format

```
<job_id>/masks/manifest.json
<job_id>/masks/frame_000000.png ... frame_NNNNNN.png
```

- 8-bit grayscale PNG, lossless only (never JPEG). 0 = background, 255 = subject, intermediate = soft alpha/confidence.
- `manifest.json` fields: `schema_version`, `video_width`, `video_height`, `frame_count`, `fps`, `timestamp_rule`, `subject_id`, `encoding` (`png-grayscale-8bit`), `source_video_id`, `source_sha256` (optional), optional SAM provenance `sam_object_id`, `sam_object_ids[]`, `provider_name`, `model`, `segmentation_status` (`completed`/`incomplete`), and `frames[]` each `{index, filename, timestamp_ms}`. The loader rejects `segmentation_status="incomplete"`.
- Timestamp derivation rule: `timestamp_ms = round(index * 1000 / fps)` when explicit timestamps are absent; the rule used is recorded in `timestamp_rule`.
- Loader validation rejects: missing frames, corrupt/invalid files, dimension mismatches (**never silently resized**), unexpected or duplicate frame indices, manifest/frame-count disagreement. Explicit resize is a separate operation using nearest-neighbour only; edge smoothing happens in the renderer, not the loader.

## Internal REST API (implemented Milestone 3, except download)

| Endpoint | Status | Purpose |
|---|---|---|
| `GET /health` | live | `{status, ai_mode, transcribe_mode, director_mode, segmentation_mode, subject_detection_disclosure_version, live_transcription_available, live_call_limits, live_calls_used, storage_root}` |
| `POST /api/uploads` | live | Multipart video upload; validated (extension allowlist, size cap, ffprobe: video stream, ≤720p, ≤10.5 s, ≤30 FPS); creates a `queued` job (stage `awaiting_voice`); 201 |
| `POST /api/jobs/{job_id}/voice` | live | Body with exactly one of `{audio_fixture_id}` or `{transcript, transcription_session_id?}`, plus optional `subject_detection_consent: boolean`. When segmentation is live, consent must be exactly `true` or the request returns 422 `subject_detection_consent_required` before the job is made ready; no worker/segmentation is scheduled. With true consent, a source-bound consent record is persisted atomically with the instruction. Mock segmentation requires no consent. 409 if not queued/awaiting. |
| `GET /api/jobs/{job_id}` | live | Job status: `queued`, `processing`, `awaiting_approval`, `awaiting_clarification`, `rejected`, `unsupported`, `completed`, `failed`, plus `stage` progress detail |
| `GET /api/jobs` | live | List all jobs |
| `GET /api/jobs/{job_id}/plan` | live (6C/6D) | Persisted v2 plan and review metadata. Requires a persisted plan, otherwise 409 `plan_not_ready`. Returns `status`, `stage`, `ready`, `plan`, `legacy_plan` (v1 adapter), `capabilities` (id, name, status, `simulated`, `requires_approval`, provider), `requires_approval`, `requires_clarification`, `clarification_question`, `clarification_count`, `render_status`, `error`, `subjects[]` (stable `object_id`, generic `label`, `preview_url`, first/last frame, detected count, confidence), `segmentation` (provider, model, `is_mock`, status, dimensions/fps, diagnostics, file cleanup), `selected_subject_ids`, `selection_required` and `no_subjects`. Works while awaiting review and after terminal states; it is the read path for non-completed jobs (the `/result` endpoint remains completed-only). |
| `GET /api/jobs/{job_id}/subjects/{object_id}/preview` | live (6D) | PNG preview (actual source frame + tinted mask) for a detected stable SAM object id. 404 `subject_preview_not_found` if the job has no such subject or preview. Path is constrained under the job directory. |
| `POST /api/jobs/{job_id}/approve` | live (6C/6D) | Optional body `{note?, subject_ids?: string[]}`. Atomic `awaiting_approval → queued` / stage `approved`, sets `approval_granted=true`, validates and stores `selected_subject_ids`, and sets `render_status="approved"`. One detected subject is auto-selected if `subject_ids` is omitted; multiple subjects require an explicit list. 422 `subject_selection_required` / `invalid_subject_selection`, 409 `no_subjects_detected`, 409 `approval_not_allowed`, 409 `plan_not_ready`, 409 `job_state_conflict` / `job_transition_locked`. Duplicate approvals are rejected; exactly one can win. |
| `POST /api/jobs/{job_id}/reject` | live (6C) | Optional body `{note?, ≤300}`. Atomic `awaiting_approval` or `awaiting_clarification → rejected`; terminal, preserves the original, never renders. 409 `rejection_not_allowed` for other states. |
| `POST /api/jobs/{job_id}/clarify` | live (6C) | Body `{answer: 1..300}`. Atomic `awaiting_clarification → queued` / stage `replanning`, persists the answer and increments `clarification_count`. 409 `clarification_not_allowed` for other states, 409 `clarification_limit_reached` after 3 rounds, 422 `empty_clarification`. |
| `GET /api/jobs/{job_id}/result` | live | Pipeline result (transcript, plan, segmentation, background, `rendered`, `render_status`, `director_plan`, `director_usage`, `director_request_id`, `director_audit`, `requires_approval`); 409 until `completed` |
| `GET /api/jobs/{job_id}/download` | live (Milestone 4) | Serves the rendered MP4 (`video/mp4`) **only** when the job is `completed`, `render_status` is `"verified"`, and the file exists on disk; otherwise 409 `download_not_ready`. No fake downloads. |

Error shape: `{ "error": { "code": string, "message": string } }` (404 `job_not_found`, 409 conflicts, 422 upload validation, 413 oversize, 400 empty file).

Note: since Milestone 4, an edit job's `completed` includes a real rendered + verified MP4. The result's `rendered` object reports measured facts (mode, resolution, fps, frame count, duration, file size, audio presence) from ffprobe verification of the actual file. Since 6C, every ready plan waits at `awaiting_approval` with `render_status="awaiting_approval"` and no output file; blurred and replacement plans follow the same gate. Clarification waits at `awaiting_clarification`; unsupported and rejected jobs are terminal with no render. Internal state transitions are recorded in `JobRecord.state_history` (actor, before/after status and stage, timestamp, note) and are not exposed in the public job response.

## Professional Editing Director Contracts (ADR-009, ADR-014, ADR-016)

Director contracts are internal Pydantic models. Since 6C, `GET /api/jobs/{job_id}/plan` exposes the persisted v2 plan and review metadata for any job that has one. A completed job's `GET /result` also contains `director_plan`, `director_usage`, `director_request_id` and `director_audit`. Both are read-only; the only director actions are the approve/reject/clarify endpoints above.

### Operation-id normalisation and audit (ADR-016)

- The lite wire accepts model-generated `operation_id` strings. Before full v2 validation the server assigns canonical ids `op_1`…`op_n` in original order, returns the complete original → canonical map, rewrites dependencies and rejects duplicate, unknown, cyclic or forward dependencies. Capability ids, params and execution semantics are unchanged; the full `DirectorOperation` pattern remains strict.
- `DirectorAudit` fields: `job_id`, `request_id`, `server_request_id`, `provider`, `model`, `execution_mode`, `service_mode`, `wire_schema`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated_cost_usd`, `actual_cost_usd` (only when reliably available; currently null), `validation_status`, `error_category`, `error_code`, `http_status`, `finish_reason`, `recorded_at`.
- The audit is persisted in `JobResult` on success and on failure. A failed director job keeps `director_audit`, `director_usage` and `director_request_id` in `job.json`; `/api/jobs/{job_id}/result` still returns 409 for non-completed jobs, so the audit is read from the job record rather than that endpoint.

### Capability registry

`packages/contracts/clipforge_contracts/capabilities.py` is authoritative. Statuses:
`available_mock`, `available_local`, `available_live`, `planned`, `disabled`.

Executable now: `subject.isolate` (mock masks, **not SAM**), `background.blur`, `background.replace` (local/mock assets, **not Muse Image**), `audio.preserve`, `video.render_mp4`, `output.verify` — all local except mock segmentation. Planned: `background.generate`. Disabled: scene cuts, trimming, transitions, keyframes, multi-track, colour grading, speed ramps, audio mixing, animated captions. Disabled/planned capabilities can be named in explanations but cannot be planned or executed.

### ProfessionalEditingPlan v2

`schema_version: "2.0"`, `request_id`, `raw_instruction`, `interpreted_intention`, `outcome` (`plan_ready` / `needs_clarification` / `unsupported`), `subject` (strategy, description, ambiguity + question), `target` (mp4, aspect, resolution, preserve audio), operations, required providers, estimated stages, expected results, verification requirements, summary/per-operation explanations, clarification questions, unsupported capabilities, `approval_status`.

Each operation: `operation_id`, `capability_id`, human title, explanation, typed params (discriminated union; no free-form commands/paths), dependencies (must appear earlier), status (`proposed` initially), expected output.

Validators reject: unknown capability, disabled/planned capability, parameter/capability mismatch, duplicate IDs, forward or missing dependencies, missing render/verify/audio when required, ready-plan without a background operation, clarification with operations, unsupported with operations, approval inconsistencies, unknown fields.

### v1 adapter

`ProfessionalEditingPlan.to_execution_plan()` produces the existing v1 `EditingPlan` used by the worker: keep-subject-sharp + blur/replace, preserve audio; clarification and unsupported map to v1 intents. Since 6C, both mock and live paths validate v2, persist it for review, adapt it to v1 and execute it only after approval; v2 is never passed to the renderer directly.

### Director stages

`DirectorStage`: `REQUEST_RECEIVED`, `ANALYZING_REQUEST`, `PLAN_READY`, `WAITING_FOR_APPROVAL`, `EXECUTING`, `VERIFYING`, `COMPLETED`, `FAILED`, `NEEDS_CLARIFICATION`, `CANCELLED`. Transitions are validated; `stage_from_job_stage()` maps current worker stages. No percentages are defined.

### Edit Decision Lists (6B-PREP-R)

`EditDecisionList` (`edl.py`) projects a ready v2 plan: one `EditDecision` per operation, dependency-ordered, with capability-typed `params`, no timing while `timeline.trim` is disabled, `DecisionTransparency` (requested/understood/why/approval/operator message) and canonical `provenance_hash`. Handlers resolve from the registry (`edl_handler_for`), never from plan input. `EditHistoryEntry` (frozen, allow-listed refs) persists via `JobRecord.edit_history` in `job.json`. `OutputEvaluationReport` separates objective checks from human review and caps corrections at 3 passes.

### Muse Spark director provider (live-tested in LIVE-E2E 005)

`MetaEditingDirectorProvider` (`packages/director/clipforge_director/spark.py`):
- Chat Completions `POST /v1/chat/completions`, model `muse-spark-1.3` Standard by default (Contributor rejected); Contributor variant via `require_contributor=True`, which accepts exactly `muse-spark-1.3-contributor` and rejects Standard strings. Optional `reasoning_effort` (`minimal`/`low`/`medium`/`high`/`xhigh`; no `context` parameter exists in the verified contract). Bearer `MODEL_API_KEY`.
- Messages: `developer` = playbook v1.1 + registry summary + output rules; `user` = confirmed transcript + video metadata + verbatim `request_id`/`raw_instruction` + ambiguity/unsupported rules.
- `response_format: {type: "json_schema", json_schema: {name: "ProfessionalEditingPlan", schema: <v2 JSON Schema>, strict: false}}`, `max_completion_tokens` (default 1500). No `tools`, no web search, no audio.
- Response: `choices[0].message.content` (JSON string) → `ProfessionalEditingPlan` validation (lite variant: `LitePlan` → `lite_to_full_plan` → full v2 validation); `finish_reason: length` and any `tool_calls` rejected; `request_id`/`raw_instruction` echo enforced; `usage` → mode-appropriate cost (`standard` $1.25/1M in + $4.25/1M out; `contributor` $0.10/1M in + $0.20/1M out).
- Errors: 401/5xx → safe `DirectorAPIError`, 429 → `DirectorRateLimitedError` (with `Retry-After`), timeout → `DirectorTimeoutError`, malformed/truncated/mismatch → `DirectorValidationError`. Exactly one POST; no retries; key/audio never logged.
- **Live wiring (ADR-014/017):** `CLIPFORGE_DIRECTOR_MODE=live` selects `LiteMetaEditingDirectorProvider` with `muse-spark-1.3-contributor`, `reasoning_effort=medium`, `max_completion_tokens=16000` (override `CLIPFORGE_DIRECTOR_MAX_TOKENS`) and 180 s timeout (`CLIPFORGE_DIRECTOR_TIMEOUT_SECONDS`). The provider requires a one-shot `LiveCallAuthorization` and reserves the director slot immediately before the HTTP request; direct `create_plan` calls without authorization are rejected before network. LIVE-E2E 005 measured 2,781 in / 1,856 out = **$0.000649**, request `req_2c45fa340028`.

### Approval / cancel / revision

Every ready plan is stopped at `awaiting_approval` with no render, regardless of provider mode or whether the capability itself requires approval. Detection runs before review so the user can select subjects. `approval_status` remains a capability-level field inside the plan; product review and subject selection are separate and mandatory. Approval resumes the persisted plan exactly once; rejection is terminal; clarification rebuilds the plan up to 3 rounds before returning to review. See ADR-018 and ADR-019. The UI reflects backend state and never decides execution locally.

## SAM 3.1 Segmentation (ADR-019) and Consent (ADR-020)

### External-processing consent record

Live SAM detection requires a persisted `SubjectDetectionConsent` bound to:

- `job_id`
- `source_video_hash` (SHA-256 of the original upload)
- `consent_given` (must be true)
- `consent_timestamp`
- `disclosure_version` (`sam31-external-video-v1`)
- `provider` (`meta-sam`)
- `model` (`sam-3.1`)
- `segmentation_mode` (`live`)

`POST /voice` rejects missing/false consent with 422 `subject_detection_consent_required`. It also rejects a source hash that no longer matches the upload with 409 `subject_detection_consent_source_mismatch`. The worker re-hashes the source and validates the record before creating the ledger authorization or calling the provider; `SamSegmentationProvider.segment()` validates again before the Files API upload. Plan approval is a separate transition and does not create or substitute consent. Mock segmentation ignores consent.

**Implementation complete; offline validation complete; live inference NOT validated.**

- Endpoint `POST https://api.meta.ai/v1/responses`, model `sam-3.1`, Bearer `MODEL_API_KEY`; one user message with `input_text` (noun phrase, default `"person"`) and `input_video.file_id`; `stream: true`; `metadata.mask_encoding: "one_bit"`. Exactly one POST, no retries.
- Video input is a temporary video-only MP4 (stream copy when compatible, otherwise H.264 transcode), verified with ffprobe for exact dimensions, FPS, frame count and absence of audio. The original is untouched.
- Files API: `POST /v1/files` with `purpose=user_data` and `expires_after` = 3600 seconds (minimum). The `file_id` is used; no public URL. `DELETE /v1/files/{file_id}` is attempted in `finally` after success and failure. Cleanup failures are recorded in `SegmentationResult.file_cleanup` and diagnostics, never with credentials.
- Parser: `meta-sam-parser==0.1.0`, `parse_responses_stream(..., video_segmentation_format())`, `decode_mask_to_raster`. `response.completed` required; incomplete streams, error diagnostics, malformed masks, wrong dimensions, out-of-range bounds, duplicate records without a newer revision and >16 objects/frame are rejected.
- Masks: SAM box-local rasters must match box bounds and are pasted at the bounds offset into full-frame 8-bit grayscale; 0/1 → 0/255. Per-object sequences and a union sequence follow ADR-005. Empty frames are written as zeros only after a completed clean stream. Object IDs are preserved exactly as strings; frame markers are explicit and arrival order is not frame order.
- Selection: `GET /plan` returns subject IDs/preview URLs; `POST /approve` takes `subject_ids`. The worker unions the selected per-object masks into `masks/selected/` and renders. Zero detections is a terminal `NoSubjectsDetected` result.
- **Not implemented:** selective person blur. Background blur/replacement only keep the selected subjects sharp and treat the rest of the frame.

Live status: no live call has been made. Detection quality, live stream behaviour, the exact nested `expires_after` multipart encoding, and live cleanup are unverified.

## Muse Image Mapping (TBD)

No mapping exists for image generation. It will be written only after official documentation verification of request/response schemas, supported media inputs, mask/asset handling, sync vs async execution, polling, rate limits and pricing. Until then replacement keeps using local/mock assets and no Muse Image adapter may be built against an assumed schema.
