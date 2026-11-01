# SAM 3.1 — Live Validation Plan

**Status:** PREPARED — **NOT EXECUTED**
**Date:** 2026-11-01
**Live SAM requests:** 0
**Files uploaded to Meta:** 0
**Credits consumed:** 0
**Muse Image:** not touched

This document prepares the first real SAM 3.1 inference validation. It does not
claim that SAM inference has been validated. The three milestones remain separate:

| Milestone | State |
|---|---|
| SAM API implementation | Complete |
| Offline parser/mask/renderer validation | Complete |
| Real SAM inference validated | **Not done** |

## 1. Code inspection results

| Area | Finding |
|---|---|
| Provider | `packages/providers/clipforge_providers/sam.py` implements `SamSegmentationProvider` with the official `sam-3.1` Responses request, one-shot ledger authorization, Files API upload/delete and no automatic retries. |
| Subject previews | `subject_previews.py` reads the actual source frame at the first detected frame, tints the mask, draws its contour and writes a local 320px-max PNG. No network. |
| Files upload | `_upload()` uses `purpose=user_data`, `expires_after[anchor]=created_at`, `expires_after[seconds]=3600`, and the file multipart part is last. `_delete()` removes the file in a `finally` block. |
| Responses request | `_request_payload()` uses `model=sam-3.1`, one `input_text` noun phrase (`person`), `input_video.file_id`, `stream=true`, and `metadata.mask_encoding=one_bit`. |
| SSE | `_http_event_stream()` posts to `/responses`, reads `data:` SSE events, and hands them to the official parser. No second request or retry loop. |
| Parser | `meta-sam-parser==0.1.0`; `parse_responses_stream(..., video_segmentation_format())` and `decode_mask_to_raster`. `_convert()` rejects any outcome other than `completed`, parser error diagnostics, non-mask text, malformed dimensions and incomplete data. |
| Masks | ADR-005 PNG grayscale sequences + manifest. Per-object and union sequences, stable SAM object IDs, no resize, incomplete manifests never rendered. `MaskSequenceWriter` keeps memory bounded. |
| Subject API | `GET /plan` returns subjects/previews/selection metadata; `GET /subjects/{object_id}/preview` serves a job-scoped PNG; `POST /approve` accepts and validates `subject_ids`. Single subject auto-selects; multiple require a choice. |
| Worker/renderer | Detection runs before plan review; rendering remains blocked until approval. Selected per-object masks are unioned and consumed by the real FFmpeg/OpenCV renderer. Selective person blur is not supported. |
| Budget | Worker creates `LiveCallAuthorization(LiveCallBudget(storage), "segmentation")`; the provider reserves exactly once immediately before the Responses POST. Ledger is fail-closed. |

**No correction was needed for the SAM request or multipart encoding.** The
pre-send privacy disclosure/consent gap found during preparation is now
implemented as ADR-020 (section 8); it remains a required part of the live
validation.

## 2. Official API compliance

Verified against the current official documentation on 2026-11-01:

- https://dev.meta.ai/docs/sam/overview
- https://dev.meta.ai/docs/sam/segmenting
- https://dev.meta.ai/docs/sam/reading-segmentation
- https://dev.meta.ai/docs/sam/client-libraries
- https://dev.meta.ai/docs/file-handling
- https://dev.meta.ai/docs/api-reference/files/schemas
- https://dev.meta.ai/docs/pricing-rate-limits

| Requirement | Implemented |
|---|---|
| Model | `sam-3.1` |
| Endpoint | `POST https://api.meta.ai/v1/responses` |
| Input text | short noun phrase `person` |
| Input video | `input_video` with `file_id` |
| Streaming | `stream=true` |
| Mask encoding | `metadata.mask_encoding="one_bit"` |
| Completed stream | official parser; `_convert` requires `outcome.status == "completed"` |
| Files purpose | `user_data` |
| File expiry | `expires_after` = 3600 seconds (documented minimum) |
| File deletion | `DELETE /v1/files/{file_id}` in `finally` |
| Retries | none |

`response.completed` is consumed through the official parser. The parser requires
the output-text lane to be finalized before the completed event. The exact live
event sequence is still unverified and is one of the validation checks.

### Multipart verification

The documented Files API schema defines `expires_after` as an object with
`anchor=created_at` and `seconds` 3600..2592000. The OpenAI Python SDK, which the
official examples use, serializes nested multipart fields with brackets:
`expires_after[anchor]` and `expires_after[seconds]` (verified locally from
`openai==3.42.0` `_serialize_multipartform`, `nested_format="brackets"`).

A local `httpx.Request` using the exact production fields produced this part order:

```text
purpose
expires_after[anchor]
expires_after[seconds]
file
```

The file part is last. No upload was performed. This matches the official SDK
shape and the API reference schema. Meta's live acceptance of the nested fields
remains to be confirmed by the approved test.

## 3. Available video assets

| Asset | Properties | Suitability |
|---|---|---|
| `C:\Users\New User\Videos\Video\Facebook.mp4` | 360×640, 30 FPS, 177 frames, video 5.900 s, container 6.177 s, AAC audio, H.264 | **Chosen.** Two men visible together for the clip. Not 720p and not 10 s. |
| `C:\Users\New User\Videos\Video\Facebook_2.mp4` | 360×640, 25 FPS, 490 frames, 19.605 s, AAC audio | Not suitable: >10.5 s upload limit and only one person (plus an ad screen). |
| `C:\Users\New User\Videos\Video\Facebook_clipforge_blur.mp4` | Prior rendered output | Not a source clip. |
| `benchmarks\assets\source_720p_10s.mp4` | 1280×720, 30 FPS, 300 frames, 10 s, testsrc2 | Full-resolution renderer benchmark only; no people; **not** SAM detection evidence. |

### Proposed validation clip

`Facebook.mp4` selected by explicit user instruction:

- Real two-person footage (American Psycho scene with burned-in meme captions).
- Video track: 360×640, 30 FPS, 177 frames, 5.900 s.
- Container: 6.177 s because the AAC audio is longer than the video track.
- Two men visible together in the sampled frames (0.00 s, 2.95 s, 5.70 s).
- No meaningful full occlusion; identity-after-occlusion cannot be evaluated with
  this clip.
- Not 720p and not approximately 10 s. A 1280×720 two-person clip is still needed
  if the goal is product-quality 720p detection evidence.

The preparation script created and validated a local video-only copy:

- Original: `Facebook.mp4`, SHA-256
  `8037599ea2c41953ec75517270ec4d164cf5550b58c866e431ad61d047e9b491`
- Original unchanged after preparation.
- Copy: `storage/sam_live_validation/Facebook_sam_input.mp4`
- Copy: H.264, 360×640, 30 FPS, 177 frames, 5.900 s, **no audio**, 232,951 bytes.
- Copy SHA-256:
  `717280fd16a2164d6b0a0c64a87b79371bfbe612ed717cfe05fcf1084823cad4`
- No upload occurred.

## 4. Exact request preview

Prepared payload (the `file_id` is a placeholder; the real value comes from the
Files API upload):

```json
{
  "model": "sam-3.1",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [
        {"type": "input_text", "text": "person"},
        {"type": "input_video", "file_id": "file-DRYRUN"}
      ]
    }
  ],
  "stream": true,
  "metadata": {"mask_encoding": "one_bit"}
}
```

Files API request preview:

```text
POST https://api.meta.ai/v1/files
Authorization: Bearer <server-side key>
Content-Type: multipart/form-data

purpose: user_data
expires_after[anchor]: created_at
expires_after[seconds]: 3600
file: Facebook_sam_input.mp4 (video/mp4), last part
```

Responses endpoint: `POST https://api.meta.ai/v1/responses`.

Delete: `DELETE https://api.meta.ai/v1/files/{file_id}` in `finally`; 404 is
treated as already deleted/expired. If deletion fails, the result records
`file_cleanup="failed"` and relies on the 1-hour expiration.

## 5. Budget and authorization

- Ledger: `storage/live-call-ledger.json`
- Limits: transcription 100, director 25, **segmentation 2**
- Used: transcription 3, director 2, **segmentation 0**
- Remaining segmentation slots: **2**
- Ledger lock: absent
- Prepared authorization: function `segmentation`, reserved **false**
- The preparation did not reserve a slot.

SAM pricing: **$0.20 per 1,000 video frames**, minimum 50 billed frames.
177 frames → **$0.0354** for one segmentation request. A second request would be
another $0.0354 and consume the second slot. This plan recommends **one** SAM
request; use the persisted per-object masks for both-person evaluation.
The last recorded Meta budget available was **$31.78**; this request is a small
fraction of it, but it still requires explicit approval.

No transcription, director, Muse Image or other billable call is needed for this
validation. Planned mode: transcription mock, director mock, **segmentation live
only**.

## 6. Expected outputs

After the approved live run:

- Job status reaches `awaiting_approval`, never `completed`, before approval.
- `result.segmentation.provider_name == "meta-sam"`.
- `result.segmentation.is_mock == false`, `model == "sam-3.1"`.
- `subjects[]` contains actual SAM object IDs with preview paths.
- `masks/manifest.json` (union), `masks/objects/object_<id>/manifest.json`
  (per object), `masks/previews/object_<id>.png`.
- Each per-object manifest has 177 frames, 360×640, 30 FPS, source hash and
  `segmentation_status="completed"`.
- The review dialog shows actual source-frame previews with tinted masks.
- Selecting a subject creates `masks/selected/manifest.json`.
- Approving produces a real FFmpeg/OpenCV render and a verified MP4 with audio.
- Download is available only after verification.
- `state_history` and worker logs provide inference/render timing.

## 7. Visual acceptance criteria

Evaluate each detected person independently using the previews and per-object
masks. Do not claim perfect tracking.

| Criterion | Acceptance |
|---|---|
| Object count | Both visible men are detected as separate objects. Extra objects must be explained (e.g. background/text) and must not be sold as identity. |
| Detection coverage | For each man visible in the clip, `frames_detected` ≥ 150 of 177 (~85%). The sampled frames show both men visible throughout; a lower count must be investigated. |
| Identity continuity | The same object ID follows the same man while visible; no left/right ID swap. Any swap without occlusion is a failure. |
| Occlusion | **N/A for this clip.** No full occlusion is present. Do not claim identity survival after occlusion/exit. |
| Boundary quality | Inspect frames 0.0, 1.5, 3.0, 4.5 and 5.7 s per object: hair, face, hands, sweater/suit edges. No large background inclusion, no large holes through the torso, no missing head. |
| Missing masks | Record every frame without a mask for a visibly present man. Isolated misses are noted; systematic gaps fail coverage. |
| Incorrect foreground/background | Check background between the crossed arms, suit edges, the other man, and the burned-in captions. Text must not be treated as a person. |
| Identity change after occlusion | Not testable; mark **N/A** and do not generalize. |
| Selected overlay | Selecting a person updates the preview/selection and the selected union contains that object. |
| Real render | One selected-subject blur render must keep the selected person(s) sharp and blur the background. |
| Output verification | ffprobe: 360×640, 177 frames, 30 FPS, ~5.9 s video (container may be ~6.177 s with audio), AAC audio present, file readable. |
| Timing | Record SAM inference time (worker logs/state timestamps), selection-union time and render time. No invented ETA. |
| Both people separately | Inspect each per-object preview and mask sequence. For separate per-person renders, reuse the persisted masks locally (no second SAM call) unless a second live request is explicitly approved. |

## 8. Consent gate — implemented (ADR-020)

The pre-send disclosure and backend gate are now implemented:

- When `/health` reports `segmentation_mode=live`, confirming the transcript opens
  a Portuguese consent dialog **before** the voice request.
- The consent checkbox is unchecked by default; “Cancelar” sends nothing.
- “Autorizar e continuar” sends `subject_detection_consent=true`.
- The dialog states that a temporary video-only copy is sent to Meta SAM 3.1,
  that the original is not modified, that a one-hour expiration is requested and
  that deletion is attempted after processing. It says detection happens before
  the plan review. It does not claim “only on your device” or guaranteed
  immediate deletion.
- The API rejects missing/false consent with **422
  `subject_detection_consent_required`** before the job becomes ready.
- The persisted record binds job, source SHA-256, timestamp, disclosure version,
  provider, model and live mode.
- The worker re-hashes the source and validates the record before creating the
  one-shot authorization or calling the provider.
- `SamSegmentationProvider.segment()` validates again before the Files API upload.
- Plan approval is separate and never substitutes for SAM consent.
- Mock segmentation does not show the dialog and works without credentials.

Browser E2E (`apps/web/scripts/qa-consent.mjs`) verified the live-like disclosure
on desktop/mobile, unchecked consent, disabled authorize action, decline with
zero voice requests, explicit consent field, completed mock workflow, no dialog
in mock mode and **zero requests to `api.meta.ai`**. Backend tests cover missing/
false consent, no ready/worker, persistence, changed source, another-job reuse,
approval-without-consent and provider-level refusal.

## 9. Prepared execution command — NOT EXECUTED

This starts a live-capable stack. The command itself makes no SAM request; the
SAM call happens when the UI job is confirmed. The consent gate is implemented;
live execution still requires explicit approval of the cost and scope. **Do not
run until that approval is recorded.**

```powershell
# Terminal 1 — API (loads .env; MODEL_API_KEY stays server-side)
$env:CLIPFORGE_AI_MODE="mock"
$env:CLIPFORGE_TRANSCRIBE_MODE="mock"
$env:CLIPFORGE_DIRECTOR_MODE="mock"
$env:CLIPFORGE_SEGMENTATION_MODE="live"
$env:CLIPFORGE_DEV_ALLOW_LIVE="1"
.\.venv\Scripts\python.exe scripts\dev_api.py

# Terminal 2 — worker (same environment)
$env:CLIPFORGE_AI_MODE="mock"
$env:CLIPFORGE_TRANSCRIBE_MODE="mock"
$env:CLIPFORGE_DIRECTOR_MODE="mock"
$env:CLIPFORGE_SEGMENTATION_MODE="live"
$env:CLIPFORGE_DEV_ALLOW_LIVE="1"
.\.venv\Scripts\python.exe scripts\dev_worker.py

# Terminal 3 — web
cd apps/web
$env:NEXT_PUBLIC_API_URL="http://localhost:8001"
npm run dev
```

UI sequence with the consent gate:

1. Upload `C:\Users\New User\Videos\Video\Facebook.mp4`.
2. Type: `Desfoca o fundo e mantém-me nítido.`
3. Confirm the transcript only after accepting the video-only SAM disclosure.
4. Wait for detection; the job must stop at `awaiting_approval`.
5. Inspect both preview cards and per-object coverage.
6. Select both people (or one for a focused render).
7. Approve and render.
8. Verify the MP4 with ffprobe and inspect the before/after.

## 10. Remaining blockers

1. **Clip is below the product target:** 360×640, 5.900 s video, no occlusion. Good for API/parser/mask validation, not 720p product-quality detection evidence.
2. **Live `response.completed` event sequence is unverified.** The official parser is used, but the real stream must be observed.
3. **Files API nested expiry fields are verified against the official SDK and local multipart encoding, not against Meta live.**
4. **Live cleanup/delete behavior is unverified.**
5. **No cost approval yet:** one SAM request estimated at **$0.0354**.
6. **No 720p two-person asset** is available. A 1280×720, ~10 s, 30 FPS, two-person clip with movement/partial occlusion is required if that evidence is mandatory.
7. Live detection quality remains unknown until the test.

## 11. Preparation artifacts

Created by `scripts/prepare_sam_live_validation.py` (offline):

- `storage/sam_live_validation/Facebook_sam_input.mp4`
- `storage/sam_live_validation/preparation_report.json`
- `storage/sam_live_validation/request_preview.json`
- `storage/sam_live_validation/source_frames/frame_0_0.00s.png`
- `storage/sam_live_validation/source_frames/frame_1_2.95s.png`
- `storage/sam_live_validation/source_frames/frame_2_5.70s.png`

The script verified:

- source exists and is a valid H.264 MP4;
- video-only copy exists, has no audio, exact 360×640 / 30 FPS / 177 frames;
- original SHA-256 unchanged;
- exact request payload;
- multipart fields and file-last order;
- no retry loop;
- cleanup in `finally`;
- ledger integrity, no lock, segmentation remaining 2;
- authorization not reserved;
- no upload and no SAM request.

**Prepared, not executed. No SAM call was made.**
