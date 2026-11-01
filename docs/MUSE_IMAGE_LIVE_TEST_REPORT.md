# Muse Image 1.0 Live Test Report

**Date:** 2026-11-01
**Result:** **SUCCESS on the single authorized request.** One real AI background generated and composited with the previously persisted real SAM masks into a verified MP4 with the original audio preserved.

## 1. Outcome summary

- **1** real `POST /v1/images/generations` request, HTTP **200**, `x-request-id: c515a42f-57e9-4662-ad6e-e55a378c6b8e`.
- **0** SAM calls, **0** retries, **0** second alternatives. Ledger segmentation stayed at 1; image went 0 → 1 of 2.
- Real generated PNG: **1280×1920**, SHA-256 `47f6f0086af46e33f7a5721f808a797e547f7f84da691a6ade35949d29a9f27e`.
- Persisted real SAM masks (job `20c603cd58a64803a53a1b44e7700e44`, `meta-sam`, `is_mock=false`, IDs `0`+`1`) reused without modification.
- Final render: 360×640, 177 frames, 30 FPS, 6.177 s, H.264 + AAC, 270,190 B, decoded PCM **identical** to the original.

## 2. SAM reuse verification (before the request)

| Check | Result |
|---|---|
| Provider / model | `meta-sam` / `sam-3.1`, `is_mock=false` |
| Subjects | `0` (older man, right), `1` (younger man, left), 177/177 frames each |
| Dims / FPS / frame count vs original | 360×640, 30 FPS, 177 — all match |
| Mask SHA vs original file SHA | **differ by design**: masks bind the video-only SAM input (`717280fd…`), the render source is the original with audio (`8037599e…`) |
| Decoded-frame identity (original vs SAM input) | **177/177 frame MD5s identical, 0 differing frames** — masks map 1:1 onto original frames |
| Original audio present | AAC stereo, 134 audio frames |

The masks were reused on geometric grounds (bit-identical decoded frames), not by bypassing validation — the difference is documented, not hidden.

## 3. Generation request

- Endpoint `POST https://api.meta.ai/v1/images/generations`, `model=muse-image-1.0`, `n=1`, `response_format=b64_json`, `output_format=png`, `size=1024x1536` (portrait source), `reasoning_strength=low`, all planner tools disabled.
- Text-only prompt (the approved demonstration direction); **no video, frame, mask or audio was sent**.
- One-shot `LiveCallAuthorization` reserved the ledger immediately before the POST.
- Generation time: **44.97 s**. Returned PNG decoded and validated (format, dimensions, hash) before saving to `background.png` + `background.json` provenance sidecar.

## 4. Composition and verification

- `combine_subject_masks` unioned the persisted real masks for IDs `0`+`1` (177 frames, 2.0 s).
- `render_video` in `replace_background` mode composited both people over the generated plate using the **original audio-bearing video** (6.2 s).
- ffprobe: H.264 360×640, 30 FPS, 177 frames; AAC 44.1 kHz stereo; duration 6.177 s.
- Decoded PCM MD5 identical to the original.
- Before/after contact sheet at 0.0 / 1.5 / 3.0 / 4.5 / 5.7 s confirms both people sharp against the sunset coastline in every sample.
- Original video untouched (SHA-256 `8037599e…b491` unchanged).

## 5. Visual quality (honest)

- The plate is clean: no people, no text, no logos — coastal cliffs, palms, amber sunset match the direction.
- Subject boundaries, hair and crossed arms track cleanly at 360×640 across all samples.
- **Known defects, not altered:** the overlaid money-label mask holes now show sunset through the labels on both chests; the source meme captions (top text) are outside the person masks, so background replacement removes them by design; subject lighting is neutral-cool against a warm sunset plate.
- No mask was dilated, filled or edited to hide these.

## 6. Cost and billing

- Estimated: **USD 0.01** (flat per-image price). Token usage echoed by the API (12,996 in / 1,178 out) is informational only.
- **Actual billed cost is not available from the API response** — confirm in Meta billing.

## 7. Remaining limitations

- One 360×640/5.9 s scene, no occlusion; 720p quality untested.
- `effective_prompt` has a cosmetic double period when the input prompt ends with “.” (provenance only, no visual effect).
- Capability badge path for a live background was verified against the persisted-style result offline; the demo composition ran outside the job state machine to avoid a second SAM call, so no new job record carries it.

## 8. Explicit confirmation

- Muse Image requests: **1** (HTTP 200, request id above). SAM requests: **0**.
- Generated background actually used in the final render: **yes** (`background.png` → renderer `background_path`, sunset visible in output).
- Mock fallback used: **no**. Original modified: **no**.

Artifacts (local, git-ignored): `storage/muse_image_live_validation/live-attempt-1/` — `background.png`, `background.json`, `luanda_sunset_demo.mp4`, `before-after.png`, `run-log.json`, union masks, frame-identity and reuse verification scripts.
