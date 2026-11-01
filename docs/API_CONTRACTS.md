# ClipForge — API Contracts

All contracts below are **internal ClipForge contracts**. Meta's actual SAM/transcription/reasoning/image schemas are **UNVERIFIED**: no Meta endpoint fields or response structures are defined, assumed, or hardcoded anywhere in this codebase. Live adapters must map the verified Meta schema into these internal contracts at integration time (mapping TBD, documented here when verified).

## Provider Mode

`CLIPFORGE_AI_MODE=mock` (default). Mock mode makes zero external requests and needs no credentials. `live` currently raises an explicit error: live adapters are integration placeholders.

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
- `SegmentationResult`: `job_id`, `subject_id`, `mask_manifest_path`, `frame_count`, `width`, `height`, `fps`, `provider_name`, `is_mock`. Backed by real local mask files, never a bare success flag.
- `BackgroundResult`: `asset_id`, `image_path` (real local file), `width`, `height`, `orientation` (`landscape`|`portrait`), `simulated_prompt`, `provider_name`, `is_mock`.

## Transcription API and Provider (ADR-008, Milestone 6A)

Configuration: `CLIPFORGE_TRANSCRIBE_MODE=mock` (default) or `live`; live additionally requires `MODEL_API_KEY` (server-side). `CLIPFORGE_DIRECTOR_MODE=mock` (default) or `live` selects the director independently (ADR-014). `CLIPFORGE_AI_MODE=mock` stays the default; live mode for segmentation/background/legacy planner is not implemented. Live-call caps default to 2 transcription + 2 director per phase (`storage/live-call-ledger.json`); local testing can raise them with `CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT` and `CLIPFORGE_LIVE_DIRECTOR_LIMIT` (positive integers, ADR-015). Raising a limit does not reset usage.

`POST /api/transcribe` — multipart:
- `file`: the browser recording (`.webm`, `.ogg`, `.oga`, `.wav`, `.m4a`, `.mp4`, `.mp3`), max 25 MB, max 60 s, must contain an audio stream.
- `mock_fixture_id` (optional, mock mode only): the explicitly selected mock command. Mock mode never interprets audio and returns 422 `mock_fixture_required` without it.

The API converts with FFmpeg to mono 16-bit PCM WAV at 24 kHz (`-ac 1 -ar 24000 -c:a pcm_s16le -map_metadata -1`) and verifies the converted file with ffprobe before use. Temporary audio is deleted after the request.

Response: the normalized `TranscriptResult` plus `transcribe_mode` (`mock`|`live`). Errors: `400 empty_audio`, `413 audio_too_large`, `422 unsupported_audio_extension`/`invalid_audio`/`no_audio_stream`/`audio_too_long`/`conversion_failed`/`mock_fixture_required`, `503 transcription_not_configured`, `504 transcription_timeout`, `429 transcription_rate_limited` or `429 live_budget_exhausted` (no provider call; the message names the configured limit and env override), `502 transcription_failed`.

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
- `manifest.json` fields: `schema_version`, `video_width`, `video_height`, `frame_count`, `fps`, `timestamp_rule`, `subject_id`, `encoding` (`png-grayscale-8bit`), `source_video_id`, `source_sha256` (optional), `frames[]` each `{index, filename, timestamp_ms}`.
- Timestamp derivation rule: `timestamp_ms = round(index * 1000 / fps)` when explicit timestamps are absent; the rule used is recorded in `timestamp_rule`.
- Loader validation rejects: missing frames, corrupt/invalid files, dimension mismatches (**never silently resized**), unexpected or duplicate frame indices, manifest/frame-count disagreement. Explicit resize is a separate operation using nearest-neighbour only; edge smoothing happens in the renderer, not the loader.

## Internal REST API (implemented Milestone 3, except download)

| Endpoint | Status | Purpose |
|---|---|---|
| `GET /health` | live | `{status, ai_mode, transcribe_mode, director_mode, live_transcription_available, live_call_limits, live_calls_used, storage_root}` |
| `POST /api/uploads` | live | Multipart video upload; validated (extension allowlist, size cap, ffprobe: video stream, ≤720p, ≤10.5 s, ≤30 FPS); creates a `queued` job (stage `awaiting_voice`); 201 |
| `POST /api/jobs/{job_id}/voice` | live | Body `{audio_fixture_id}`; attaches the voice instruction and makes the job claimable; 409 if not queued/awaiting |
| `GET /api/jobs/{job_id}` | live | Job status: `queued`, `processing`, `completed`, `failed`, plus `stage` progress detail |
| `GET /api/jobs` | live | List all jobs |
| `GET /api/jobs/{job_id}/result` | live | Pipeline result (transcript, plan, segmentation, background, `rendered`, `render_status`, `director_plan`, `director_usage`, `director_request_id`, `director_audit`, `requires_approval`); 409 until `completed` |
| `GET /api/jobs/{job_id}/download` | live (Milestone 4) | Serves the rendered MP4 (`video/mp4`) **only** when the job is `completed`, `render_status` is `"verified"`, and the file exists on disk; otherwise 409 `download_not_ready`. No fake downloads. |

Error shape: `{ "error": { "code": string, "message": string } }` (404 `job_not_found`, 409 conflicts, 422 upload validation, 413 oversize, 400 empty file).

Note: since Milestone 4, an edit job's `completed` includes a real rendered + verified MP4. The result's `rendered` object reports measured facts (mode, resolution, fps, frame count, duration, file size, audio presence) from ffprobe verification of the actual file. Clarification/unsupported jobs complete without rendering and keep `render_status="not_implemented"`. Since ADR-014, approval-required/rejected live director plans complete as `awaiting_approval` with `render_status="awaiting_approval"` and no output file.

## Professional Editing Director Contracts (ADR-009, ADR-014, ADR-016)

Director contracts are internal Pydantic models. Since ADR-014, the live worker executes ready plans through the v1 adapter and exposes `director_plan`, `director_usage`, `director_request_id` and `director_audit` in `GET /api/jobs/{job_id}/result` (read-only; there is no director-specific endpoint).

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

`ProfessionalEditingPlan.to_execution_plan()` produces the existing v1 `EditingPlan` used by the worker: keep-subject-sharp + blur/replace, preserve audio; clarification and unsupported map to v1 intents. Since ADR-014 the live worker validates v2, adapts it to v1 and executes that plan; v2 is never passed to the renderer directly.

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
- **Live wiring (ADR-014):** `CLIPFORGE_DIRECTOR_MODE=live` selects `LiteMetaEditingDirectorProvider` with `muse-spark-1.3-contributor`, `reasoning_effort=medium`, `max_completion_tokens=16000` (override `CLIPFORGE_DIRECTOR_MAX_TOKENS`) and 180 s timeout (`CLIPFORGE_DIRECTOR_TIMEOUT_SECONDS`). Each call reserves one director slot in the ledger immediately before the HTTP request. LIVE-E2E 005 measured 2,781 in / 1,856 out = **$0.000649**, request `req_2c45fa340028`.

### Approval / cancel / revision

The live worker implements the **approval gate**: `approval_status` `required`/`rejected` completes the job as `awaiting_approval` with no render. Approval, rejection, cancellation and revision *resume* are still contract fields only — **no endpoints or UI exist** to continue an awaiting job. Mock-mode execution keeps the legacy auto-execute behaviour.

## Live Provider Mapping (TBD)

To be completed only after official documentation verification of: request/response schemas, supported media inputs, mask encoding, sync vs async execution, polling, rate limits, pricing. Until then the mapping section stays empty by design.
