# SAM 3.1 Integration — Milestone 6D

**Status date:** 2026-11-01
**Live SAM inference validated:** **NO**
**Offline parser / mask / renderer validation:** **YES**
**Live API call made in this milestone:** **NO**

This document separates three different milestones that must not be conflated:

1. **SAM API implementation complete** — the provider, Files API upload, streamed
   Responses request, official parser, mask conversion and cleanup are implemented.
2. **Offline parser/renderer validation complete** — protocol-compatible recorded events,
   per-object masks, selection union and the real FFmpeg/OpenCV renderer were validated
   locally with no network.
3. **Real SAM inference validated** — **not done.** No request was sent to Meta, no credits
   were consumed, and detection quality on real footage is unknown.

## Official contract implemented

Sources verified on 2026-11-01:

- https://dev.meta.ai/docs/sam/overview
- https://dev.meta.ai/docs/sam/segmenting
- https://dev.meta.ai/docs/sam/reading-segmentation
- https://dev.meta.ai/docs/sam/client-libraries
- https://dev.meta.ai/docs/file-handling
- https://dev.meta.ai/docs/api-reference/files/schemas

| Item | Implemented value |
|---|---|
| Model | `sam-3.1` |
| Endpoint | `POST https://api.meta.ai/v1/responses` |
| Auth | `Authorization: Bearer MODEL_API_KEY`, server-side only |
| Prompt | `input_text` = short noun phrase, default `"person"` |
| Video | `input_video` with `file_id` from the Files API |
| Streaming | `stream: true`; SSE read until `response.completed` |
| Masks | `metadata.mask_encoding: "one_bit"` |
| Output | special-token text in the `output_text` lane |
| Max objects | 16 per frame |
| Parser | `meta-sam-parser==0.1.0` (`meta_sam_parser`) |

No `video_url`, public URL or base64 data URL is used for user footage. No full v2 or
invented request fields are sent.

Request shape (asserted by tests):

```json
{
  "model": "sam-3.1",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {"type": "input_text", "text": "person"},
        {"type": "input_video", "file_id": "file-..."}
      ]
    }
  ],
  "stream": true,
  "metadata": {"mask_encoding": "one_bit"}
}
```

## Video preparation and privacy

`SamSegmentationProvider` creates a temporary **video-only** MP4 before upload:

- The source is probed with ffprobe and must match the job width, height, FPS and frame
  count.
- H.264/H.265/MPEG-4 in MP4/MOV is stream-copied with `-an -movflags +faststart`
  (frames/timestamps unchanged).
- Other inputs are transcoded to H.264/yuv420p at the original FPS and verified again.
- The temporary file must contain exactly one video stream, no audio, the exact
  dimensions, FPS and frame count. A mismatch is a hard error.
- The original upload is never modified. A SHA-256 of the original is stored in every
  mask manifest.

Files API path:

- `POST /v1/files` with `purpose=user_data`.
- `expires_after[anchor]=created_at`, `expires_after[seconds]=3600` (the documented
  minimum).
- The returned `file_id` is used in `input_video`.
- `DELETE /v1/files/{file_id}` runs in `finally`, after success and after failure.
- Cleanup failure is logged and recorded in `SegmentationResult.file_cleanup="failed"`
  plus a diagnostic. It never exposes the API key.
- No public URL is created.

**Not yet live-validated:** the exact multipart encoding of the nested `expires_after`
object (`expires_after[anchor]` / `expires_after[seconds]`) follows the documented schema
and OpenAI-compatible SDK convention but has not been exercised against Meta.

## Parser and stream handling

- `parse_responses_stream(events, video_segmentation_format())` from
  `meta-sam-parser==0.1.0` consumes the SSE `output_text` lane.
- `decode_mask_to_raster(record.mask)` decodes masks; ClipForge does not hand-decode the
  base85/range-coded payload.
- `response.completed` is required. An `incomplete` outcome raises
  `SamIncompleteStreamError`; no masks are written.
- Parser diagnostics with `severity="error"` reject the output. Warnings are retained in
  the result diagnostics.
- Transport errors, timeout, 429 and 5xx are mapped to safe provider errors; **no automatic
  retries**.
- `final_result` is consumed once; no second stream iteration or retry.

## Mask conversion and mapping

SAM mask records are box-local rasters with half-open bounds. For each record:

- The raster dimensions must equal the box bounds. A mismatch is rejected; the provider
  never silently resizes a SAM raster.
- The decoded 0/1 raster is pasted at `(bounds.left, bounds.top)` into a full-frame
  `uint8` mask.
- `0 → 0`, `1 → 255`.
- A frame with no SAM record for an object produces an all-zero mask **only after** the
  stream completed and validation passed.
- Frame markers are read explicitly. Arrival order is not treated as frame order;
  out-of-order records are grouped and written in source frame order.
- Object IDs are preserved exactly as strings. IDs are not assumed contiguous or equal to
  list positions. Per-object manifests/store paths use `object_<id>`.
- Duplicate object/frame records are rejected unless the parser explicitly reports a newer
  revision (the official parser increments revisions for streamed updates).
- More than 16 objects on one frame is rejected.
- Frames outside `0..frame_count-1` and bounds outside the source frame are rejected.

Output layout for a job:

```
jobs/<job_id>/masks/
  manifest.json                 union of all detected objects
  frame_000000.png ...
  objects/object_<id>/
    manifest.json               one stable SAM object
    frame_000000.png ...        all frames, zeros where absent
  previews/object_<id>.png      source frame + mask overlay for the review UI
  selected/                     union of the user's selected object IDs
    manifest.json
```

Every per-object and union manifest keeps the ADR-005 PNG-grayscale contract and adds
optional provenance: `sam_object_id`, `sam_object_ids`, `provider_name`, `model`,
`source_sha256`, `segmentation_status`. The loader rejects a manifest marked
`segmentation_status="incomplete"`.

## Subject selection

Detection runs **before plan review** because the user needs the detected objects to choose
who stays sharp. In live mode this means the SAM request is spent before the approval
decision; rejecting the plan does **not** refund that call. The ledger reservation is
consumed once.

1. Director produces a ready v2 plan.
2. Worker runs SAM (live) or the mock detection provider and persists per-object masks.
3. Job stops at `awaiting_approval`.
4. The plan dialog shows each detected subject with a real source-frame preview, stable
   object ID, first/last detected frame and detected-frame count.
5. User selects one or more subjects (single subject is preselected; multiple subjects
   require an explicit choice).
6. `POST /api/jobs/{id}/approve` carries `subject_ids`; the backend validates them against
   the persisted SAM IDs.
7. Worker unions the selected per-object masks into `masks/selected/` and renders.

The UI does not perform identity recognition. Labels are generic
("Detected person"/"Subject <object_id>"). It never assumes largest, central or leftmost
is the user. Zero detections is a valid result and becomes a terminal `unsupported` job
with `NoSubjectsDetected`; it never renders.

## Explicit consent gate (ADR-020)

Live external processing is now gated before any upload:

- `POST /api/jobs/{job_id}/voice` accepts `subject_detection_consent: bool | None`.
- When `CLIPFORGE_SEGMENTATION_MODE=live` and consent is absent or false, the API returns
  **422 `subject_detection_consent_required`** and does not mark the job ready. No worker
  can claim it and no SAM upload/inference is scheduled.
- With true consent, the API binds a `SubjectDetectionConsent` record to the job, source
  SHA-256, provider (`meta-sam`), model (`sam-3.1`), disclosure version
  (`sam31-external-video-v1`) and live mode, and persists it atomically with the voice
  instruction before the job becomes claimable.
- The worker re-hashes the source and validates the record before creating the one-shot
  ledger authorization or calling the provider. A source change invalidates consent.
- `SamSegmentationProvider.segment()` validates the consent again **before the Files API
  upload**. A direct provider call with only an authorization is rejected.
- Editing-plan approval is separate and can never substitute for SAM consent.
- Mock segmentation does not require consent and never shows the disclosure.

The UI displays the Portuguese disclosure before the voice request. Consent is an
unchecked checkbox; “Cancelar” sends nothing and “Autorizar e continuar” submits the
explicit field. No deletion guarantee or “only on your device” claim is made.

## Renderer integration

`combine_subject_masks()` streams one mask per selected object per frame, computes the
union and writes the canonical PNG sequence with `MaskSequenceWriter` (bounded memory).
The existing renderer consumes that union:

- **Background blur**: selected people stay sharp, everything outside the union is blurred.
- **Background replacement**: selected people are composited over the replacement asset.

Original audio, resolution and frame timing are preserved and verified by ffprobe.

**Selective person blur is not supported.** The current renderer can keep masked people
sharp and blur/replace the background. It cannot blur selected people while keeping the
rest of the scene sharp. This capability must not be advertised until a separate operation,
renderer path and verification exist.

## Full-resolution benchmark

`scripts/benchmark_sam_render.py` uses the existing 300-frame 1280×720 30 FPS 10 s local
clip with audio and deterministic two-subject mock masks (no SAM request):

| Measurement | Result |
|---|---|
| Segmentation fixture generation | 25.46 s |
| Selection union (object `0`) | 6.69 s |
| Real blur render | 172.68 s (1.74 FPS) |
| Peak RAM (process tree) | 637.7 MB |
| Output | 1280×720, 300 frames, 10.0 s, 1,103,667 bytes |
| Audio | AAC stream present |
| Verification | ffprobe counted 300 frames, 1280×720, 30 FPS |

Raw result: `benchmarks/results/sam_render_benchmark.json`.
This proves contract and renderer behaviour at full resolution; it does **not** measure
SAM detection quality.

## Tests

- Offline fixture suites cover one person, multiple people, stable IDs, entering/leaving,
  occlusion, frames without subjects, empty output, incomplete streams, malformed masks,
  wrong dimensions, duplicate records, out-of-order frames, >16 objects, cleanup success
  and failure, upload expiry fields, request contract, source preservation and renderer
  integration.
- Full backend suite: see `docs/STATUS.md` (updated with the current count).
- No live network request is made by any test.

## Remaining limitations

- **Real SAM inference is unvalidated.** The first live test still needs explicit approval,
  a cost estimate, a ledger slot and a controlled request. The consent gate is implemented;
  it does not validate live SAM behavior by itself.
- Detection quality, real object continuity through occlusion and prompt tuning on real
  footage are unknown.
- The Files API nested expiration encoding is not live-validated.
- Cleanup failure leaves the file to expire after one hour; it is recorded but cannot be
  retried automatically.
- Mock masks are synthetic ellipses; the browser/demo flow proves the contract, not SAM.
- Selective person blur is not implemented.
- No authentication/ownership; the API remains local single-user.
