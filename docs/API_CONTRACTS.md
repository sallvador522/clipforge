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

Configuration: `CLIPFORGE_TRANSCRIBE_MODE=mock` (default) or `live`; live additionally requires `MODEL_API_KEY` (server-side). `CLIPFORGE_AI_MODE=mock` stays the default; live mode for other providers is not implemented.

`POST /api/transcribe` — multipart:
- `file`: the browser recording (`.webm`, `.ogg`, `.oga`, `.wav`, `.m4a`, `.mp4`, `.mp3`), max 25 MB, max 60 s, must contain an audio stream.
- `mock_fixture_id` (optional, mock mode only): the explicitly selected mock command. Mock mode never interprets audio and returns 422 `mock_fixture_required` without it.

The API converts with FFmpeg to mono 16-bit PCM WAV at 24 kHz (`-ac 1 -ar 24000 -c:a pcm_s16le -map_metadata -1`) and verifies the converted file with ffprobe before use. Temporary audio is deleted after the request.

Response: the normalized `TranscriptResult` plus `transcribe_mode` (`mock`|`live`). Errors: `400 empty_audio`, `413 audio_too_large`, `422 unsupported_audio_extension`/`invalid_audio`/`no_audio_stream`/`audio_too_long`/`conversion_failed`/`mock_fixture_required`, `503 transcription_not_configured`, `504 transcription_timeout`, `429 transcription_rate_limited`, `502 transcription_failed`.

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
| `GET /health` | live | `{status, ai_mode, storage_root}` |
| `POST /api/uploads` | live | Multipart video upload; validated (extension allowlist, size cap, ffprobe: video stream, ≤720p, ≤10.5 s, ≤30 FPS); creates a `queued` job (stage `awaiting_voice`); 201 |
| `POST /api/jobs/{job_id}/voice` | live | Body `{audio_fixture_id}`; attaches the voice instruction and makes the job claimable; 409 if not queued/awaiting |
| `GET /api/jobs/{job_id}` | live | Job status: `queued`, `processing`, `completed`, `failed`, plus `stage` progress detail |
| `GET /api/jobs` | live | List all jobs |
| `GET /api/jobs/{job_id}/result` | live | Pipeline result (transcript, plan, segmentation, background, `render_status`); 409 until `completed` |
| `GET /api/jobs/{job_id}/download` | live (Milestone 4) | Serves the rendered MP4 (`video/mp4`) **only** when the job is `completed`, `render_status` is `"verified"`, and the file exists on disk; otherwise 409 `download_not_ready`. No fake downloads. |

Error shape: `{ "error": { "code": string, "message": string } }` (404 `job_not_found`, 409 conflicts, 422 upload validation, 413 oversize, 400 empty file).

Note: since Milestone 4, an edit job's `completed` includes a real rendered + verified MP4. The result's `rendered` object reports measured facts (mode, resolution, fps, frame count, duration, file size, audio presence) from ffprobe verification of the actual file. Clarification/unsupported jobs complete without rendering and keep `render_status="not_implemented"`.

## Live Provider Mapping (TBD)

To be completed only after official documentation verification of: request/response schemas, supported media inputs, mask encoding, sync vs async execution, polling, rate limits, pricing. Until then the mapping section stays empty by design.
