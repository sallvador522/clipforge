# SAM 3.1 Live Test Report

**Date:** 2026-11-01  
**Result:** **SUCCESS on attempt 1.** One real inference request, two real subjects, valid masks, and three verified local renders. No retry was made.

## 1. Outcome summary

- **1** real SAM Responses request, HTTP **200**.
- **1** Files API upload; the provider reported `file_cleanup=deleted`.
- **2** distinct subjects, stable object IDs **`0`** and **`1`**, each detected in **177/177** frames.
- Real per-object mask sequences, manifests and previews were written and validated.
- Person A, person B and both people were rendered locally from the persisted masks with the existing FFmpeg/OpenCV pipeline.
- All three renders preserve the original audio bit-for-bit at the decoded PCM level.
- The real approval path was exercised once for person A; it reused the persisted masks and made **no additional SAM request**.
- The original video was not modified.

## 2. Configuration and consent

| Item | Value |
|---|---|
| API/worker mode | `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=mock`, `CLIPFORGE_DIRECTOR_MODE=mock`, `CLIPFORGE_SEGMENTATION_MODE=live`, `CLIPFORGE_DEV_ALLOW_LIVE=1` |
| Test asset | `storage/sam_live_validation/Facebook_sam_input.mp4` |
| Asset properties | 177 frames, 360x640, 30 FPS, 5.900 s, H.264, no audio |
| Asset SHA-256 | `717280fd16a2164d6b0a0c64a87b79371bfbe612ed717cfe05fcf1084823cad4` |
| Original | `C:\Users\New User\Videos\Video\Facebook.mp4` |
| Original properties | 177 video frames + AAC audio, 360x640, 30 FPS, 6.177 s |
| Original SHA-256 | `8037599ea2c41953ec75517270ec4d164cf5550b58c866e431ad61d047e9b491` (unchanged after the test) |
| Job | `20c603cd58a64803a53a1b44e7700e44` |
| Consent timestamp | `2026-11-01T18:32:01.744225Z` |
| Disclosure version | `sam31-external-video-v1` |
| Consent provider/model | `meta-sam` / `sam-3.1` |

The user explicitly approved the live test before execution. The browser run then used the real Studio dialog: it verified that consent was initially unchecked, checked it, and clicked **"Autorizar e continuar"**. The consent record was created by the API and was not edited or bypassed. The source-video hash in the persisted record matches both the upload and the actual file used for inference.

## 3. Actual API requests

| Operation | Endpoint | Observed outcome | Identifier |
|---|---|---|---|
| Files upload | `POST /v1/files` | **HTTP 200**; file id returned | `file-28662222940146270` |
| Inference | `POST /v1/responses` | **HTTP 200** | `x-request-id: a6b54e67-61d4-4779-9fcc-80563b7166c9` |
| Cleanup | `DELETE /v1/files/{file_id}` | **HTTP 200**; `file_cleanup=deleted` | `file-28662222940146270` |

The worker's `httpx` log recorded HTTP 200 for the upload, the Responses request and the DELETE. The inference status and request id above are from the live response headers.

Request shape: `model=sam-3.1`, prompt `person`, `input_video.file_id=file-28662222940146270`, `stream=true`, `metadata.mask_encoding=one_bit`.

**No second inference request was made.** The ledger is now `segmentation=1` with limit `2`; no lock remains.

## 4. Inference and parser result

- SSE inference stream duration: **135.57 s**.
- Responses start to provider return (including local mask decoding/writing, previews and cleanup): **~276 s**.
- Parser outcome: **completed**.
- Parser diagnostics: **none**.
- Detected objects: **2**.
- Object IDs: **`0`** and **`1`**.
- Frames detected per object: **177 / 177**.
- Mask count: **177 PNGs per object**, plus the union sequence.
- Cleanup: **`deleted`**; Meta's DELETE returned **HTTP 200**. No follow-up GET was made, so the provider's success response is the evidence.

The provider returned `is_mock=false`, `provider_name=meta-sam` and `model=sam-3.1` in the persisted segmentation result.

## 5. Mask and manifest validation

| Property | Object `0` | Object `1` |
|---|---|---|
| Visible identity | Older man, screen right | Younger man, screen left |
| Non-empty frames | 177/177 | 177/177 |
| Mean mask area | 28,484 px (12.36%) | 32,024 px (13.90%) |
| Min / max area | 11.34% / 12.99% | 13.16% / 16.55% |
| Centroid x range | 249.2 - 283.1 px | 78.9 - 125.2 px |
| Centroid y range | 342.4 - 357.7 px | 328.3 - 337.3 px |
| Max centroid jump | 5.87 px | 4.90 px |
| Jumps over 20 px | 0 | 0 |

- Both mask sequences are 360x640, 8-bit grayscale, binary values `0`/`255`.
- Manifest indices are exactly `0..176`, timestamps are monotonic (`0..5867 ms`), and no frame is missing or extra.
- The manifest `source_sha256` matches the prepared input.
- **Overlap between the two subjects is 0 px in all 177 frames** (maximum IoU `0.0`). The two masks describe distinct people, not duplicate detections.
- Previews were generated as 320x569 PNGs and the preview endpoints returned **HTTP 200** for both subjects.

Sampled bounding boxes (`left,top,right,bottom`):

| Time | Object `0` | Object `1` | Overlap |
|---|---|---|---|
| 0.0 s | 142,211,328,453 | 2,156,210,456 | 0 px |
| 1.5 s | 187,208,341,456 | 12,165,200,457 | 0 px |
| 3.0 s | 191,206,350,458 | 12,166,192,457 | 0 px |
| 4.5 s | 185,204,342,456 | 8,164,185,457 | 0 px |
| 5.7 s | 188,201,342,455 | 22,159,210,456 | 0 px |

## 6. Visual inspection

Inspected frames: **0.0 s, 1.5 s, 3.0 s, 4.5 s, 5.7 s**, with source, tinted overlay, and both raw masks.

- **Subject `0`** tracks the older man on the right; **subject `1`** tracks the younger man on the left.
- Faces, hair, torsos, crossed arms and clothing boundaries are followed in every sampled frame.
- No missing detections, no identity swap and no side-to-side drift. The centroid trajectories are smooth and the two people never overlap.
- Edges are **binary and sometimes coarse**, especially around hair, the younger man's crossed arms and the bottom-right boundary. This is consistent with the requested `one_bit` mask encoding; no soft alpha is produced.
- **Visible artifact:** both masks contain a rectangular hole where the overlaid "R$ 3,75" / "R$ 12,30" labels sit on the people. The labels are therefore blurred even when their wearer is selected as sharp. This is the most noticeable quality defect.
- The clip contains no occlusion or crossing, so occlusion/re-identification behavior remains **untested**.
- Object IDs are stable **within this clip only**; the system does not perform identity recognition.

## 7. Subject selection and previews

- The Studio showed two source-frame preview cards, each labelled **177 detected**, with stable IDs `0` and `1`.
- Both cards were independently selectable.
- The detection panel correctly stated **"SAM 3.1 segmentation via meta-sam"**.
- The operation card still showed **"MOCK / SIMULATED"** for `subject.isolate`. This is a stale capability-registry label (`available_mock`), not the actual detection result; the masks and provider result are real (`is_mock=false`). It is recorded as a remaining presentation issue.

## 8. Renderer validation

All renders used the existing `combine_subject_masks` + `render_video` pipeline. The source for the three full validation renders was the original audio-bearing `Facebook.mp4`, so the visual frames match the masks exactly while the original audio can be verified.

| Render | Selected IDs | Output | Frames | Resolution | FPS | Duration | Audio | Size | Render time |
|---|---|---|---|---|---|---|---|---|---|
| Person A | `0` | `person_a.mp4` | 177 | 360x640 | 30 | 6.177 s | AAC 44.1 kHz stereo | 149,138 B | 76.08 s |
| Person B | `1` | `person_b.mp4` | 177 | 360x640 | 30 | 6.177 s | AAC 44.1 kHz stereo | 144,249 B | 70.42 s |
| Both | `0, 1` | `both.mp4` | 177 | 360x640 | 30 | 6.177 s | AAC 44.1 kHz stereo | 189,922 B | 71.46 s |
| App approval (A) | `0` | `output.mp4` | 177 | 360x640 | 30 | 5.900 s | none (input is video-only) | 107,454 B | 65.3 s |

**Audio preservation:** the decoded PCM MD5 is identical for the original and all three audio-bearing renders: `50fa3de785f99c13de94fc3f2650e58a`.

**Frame mapping to the original:** the prepared video-only derivative is decoded-frame-identical to the original (177/177 frame MD5s match), so the persisted real masks remain valid for the original frames. A new application-path regression uploads an audio-bearing source, confirms that the SAM upload has no audio, and compares decoded PCM from the rendered output with the original.

**Post-live stabilization:** the worker now verifies the canonical source hash plus mask provenance, dimensions, frame count and FPS before rendering. Capability status is derived from the actual provider/result (`LIVE`/`MOCK`/`UNAVAILABLE`). The overlaid-label holes were documented and left untouched; no dilation or artificial filling was added.

**Selection isolation (Laplacian variance, higher = sharper):**

| Render | Selected subject | Unselected subject |
|---|---|---|
| Person A | object `0`: **398.4** | object `1`: **1.2** |
| Person B | object `1`: **209.5** | object `0`: **1.3** |
| Both | object `0`: **391.8**, object `1`: **208.3** | n/a |

Visual comparison confirms the intended behavior:

- **Person A:** the older man stays sharp; the younger man and background are blurred.
- **Person B:** the younger man stays sharp; the older man and background are blurred.
- **Both:** both people stay sharp; only the background is blurred.

The real approval route (`POST /approve` with `subject_ids=["0"]`) completed with HTTP 200 and produced a verified 177-frame output. The job ledger stayed at `segmentation=1`, and the worker log shows no SAM upload or inference after approval. The app output is silent because the prepared test input has no audio; audio preservation was verified separately against the original as described above.

Selective person blur is **not** implemented and was not attempted.

## 9. Timing and cost

| Stage | Time |
|---|---|
| Consent to worker upload | ~14 s |
| SSE inference stream | **135.57 s** |
| Responses start to provider return (incl. local mask conversion/previews/cleanup) | **~276 s** |
| Person A render | 76.08 s |
| Person B render | 70.42 s |
| Both render | 71.46 s |
| App approval render (person A) | 65.3 s |

- Estimated inference cost: **USD 0.0354** (177 frames x USD 0.20 / 1,000 frames).
- Maximum authorized for this validation: USD 0.0708 (two attempts).
- **Actual billed cost is not available from the API response.** Confirm it in Meta billing; do not treat the estimate as an invoice.
- Only one of the two permitted attempts was used.

## 10. Artifacts

Local, Git-ignored validation artifacts:

- `storage/sam_live_validation/live-attempt-1/` - consent/detection screenshots, previews, mask analysis, contact sheets, renders, audio/sharpness checks and the one-shot browser script.
- `storage/jobs/20c603cd58a64803a53a1b44e7700e44/masks/` - real per-object masks, union masks, manifests and previews.
- `storage/jobs/20c603cd58a64803a53a1b44e7700e44/output.mp4` - app-approved person-A render.

No videos, masks, previews or credentials are committed to Git.

## 11. Remaining defects and limitations

1. **Overlaid-label holes:** the SAM masks exclude the rectangular money labels on both people; those labels blur even when the person is sharp. This is the clearest visual defect.
2. **Binary/coarse edges:** masks are one-bit and show jagged hair/arm boundaries. The renderer's 5 px feather softens them but does not reconstruct missing detail.
3. **Stale UI labels:** `subject.isolate` is still registered as `available_mock`, so the plan card says "MOCK / SIMULATED" while the detection panel correctly reports live SAM. The stale `expected_output` text also says "mock masks in this build".
4. **Limited asset:** 360x640, 5.9 s, two people, no occlusion or crossing. This validates the API/parser/mask/render path, not 720p product-quality tracking.
5. **Audio test separation:** the prepared clip is video-only, so the app-path output is silent. Audio preservation was verified with the original source and the same persisted masks.
6. **Cleanup has no follow-up GET:** Meta's DELETE returned HTTP 200 and the provider reports `deleted`; an independent existence check would require another API call, which was deliberately not made.
7. **No identity recognition:** object IDs are stable within this clip only; the UI does not claim to know who is who.
8. **Billing estimate only:** actual Meta charges were not available in the response.
9. **Consent scope:** the disclosure is Portuguese-only and the app remains single-user/local.

## 12. Explicit confirmation

- Real SAM inference requests: **1**
- Retries or duplicate inference requests: **0**
- Files API uploads: **1**
- Additional SAM calls after success: **0**
- Live transcription or director calls: **0**
- Muse Image calls: **0**
- Original video modified: **no** (SHA-256 unchanged)
- SAM parser or renderer changed: **no** (only safe request/timing logging was added to `sam.py`)
- Credits consumed beyond the single authorized attempt: **none known**
