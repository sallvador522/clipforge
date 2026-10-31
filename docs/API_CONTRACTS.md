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

- `TranscriptResult`: `text`, `language`, `confidence`, `provider_name`, `is_mock`.
- `SegmentationResult`: `job_id`, `subject_id`, `mask_manifest_path`, `frame_count`, `width`, `height`, `fps`, `provider_name`, `is_mock`. Backed by real local mask files, never a bare success flag.
- `BackgroundResult`: `asset_id`, `image_path` (real local file), `width`, `height`, `orientation` (`landscape`|`portrait`), `simulated_prompt`, `provider_name`, `is_mock`.

## Mask Contract (ADR-005) — canonical internal segmentation format

```
<job_id>/masks/manifest.json
<job_id>/masks/frame_000000.png ... frame_NNNNNN.png
```

- 8-bit grayscale PNG, lossless only (never JPEG). 0 = background, 255 = subject, intermediate = soft alpha/confidence.
- `manifest.json` fields: `schema_version`, `video_width`, `video_height`, `frame_count`, `fps`, `timestamp_rule`, `subject_id`, `encoding` (`png-grayscale-8bit`), `source_video_id`, `source_sha256` (optional), `frames[]` each `{index, filename, timestamp_ms}`.
- Timestamp derivation rule: `timestamp_ms = round(index * 1000 / fps)` when explicit timestamps are absent; the rule used is recorded in `timestamp_rule`.
- Loader validation rejects: missing frames, corrupt/invalid files, dimension mismatches (**never silently resized**), unexpected or duplicate frame indices, manifest/frame-count disagreement. Explicit resize is a separate operation using nearest-neighbour only; edge smoothing happens in the renderer, not the loader.

## Internal REST API (defined here; implemented at the API milestone — not yet live)

| Endpoint | Purpose |
|---|---|
| `POST /api/uploads` | Upload source video, creates a job |
| `POST /api/jobs/{job_id}/voice` | Submit voice instruction fixture/audio reference |
| `GET /api/jobs/{job_id}` | Job status (`queued`, `transcribing`, `planning`, `segmenting`, `rendering`, `verifying`, `completed`, `failed`, `needs_clarification`) |
| `GET /api/jobs/{job_id}/result` | Before/after metadata |
| `GET /api/jobs/{job_id}/download` | Download the verified output MP4 |

Error shape: `{ "error": { "code": string, "message": string } }`. No route exists until implemented and tested; this table is the contract to implement, not a claim of functionality.

## Live Provider Mapping (TBD)

To be completed only after official documentation verification of: request/response schemas, supported media inputs, mask encoding, sync vs async execution, polling, rate limits, pricing. Until then the mapping section stays empty by design.
