# LIVE-E2E 006 — User Video, Real Muse Plan and Verified Blur Render

**Date:** 2026-11-01
**Status:** SUCCESS — real ASR → Muse Spark plan → local render → verified download saved to the
user's Videos folder.
**Scope:** one live transcription + one live director call, explicitly approved by the user.
No SAM, no Muse Image, no automatic retry.

## Input

- User-provided portrait clip: **360×640, 30 FPS, 6.177 s, AAC audio**.
- The source remains untouched; only a new output file was written.
- The video is not copied into the repository and no frames are committed.

## Instruction

Generated locally with Windows SAPI (pt-BR, `Microsoft Maria Desktop`):

> “Desfoca o fundo e mantém as duas pessoas à frente nítidas.”

Audio: 5.367 s, 236,750 bytes. No external service was used to create the instruction audio.

## Flow and measured results

| Step | Result |
|---|---|
| `POST /api/transcribe` | **HTTP 200** |
| ASR transcript | “Desfoca o fundo e mantém as duas pessoas pessoas à frente nítidas.” |
| ASR note | The provider duplicated the word “pessoas”; the intent remained clear. |
| ASR duration / session | 5,440 ms / `clipforge-8851d30f8841451595627248805d1240` |
| ASR cost | **$0.000272** |
| Upload / job | **HTTP 201** — job `24b7a3edc1ca4d3db89ae2cb9a3b6ce8` |
| Director outcome | `plan_ready`, approval `not_required` |
| Director operations | `subject.isolate`, `background.blur`, `audio.preserve`, `video.render_mp4`, `output.verify` |
| Director usage | 2,792 prompt + 2,293 completion = **5,085 tokens** |
| Director request / server id | `req_03bff7ae260f` / `6096b398-7ce7-46ba-b4bf-c7a693cabbe7` |
| Director cost | **$0.000738** (Contributor rates) |
| Audit | `accepted`, HTTP 200, `finish_reason=stop`, `actual_cost_usd=null` |
| Render | 360×640, 30 FPS, **177 frames**, 6.177007 s, **166,088 bytes**, audio preserved |
| Download | **HTTP 200** |
| Output | `Facebook_clipforge_blur.mp4` in the user's `Videos\Video` folder |
| SHA-256 | `8C41BEA607D6108DA2846B58FE54E84D83269E9C82527FEBD63669694A6A52BB` |

**Cost this run:** $0.000272 + $0.000738 = **$0.001010**.
**Ledger after the run:** `transcription=3`, `director=2` (97/23 remaining under the 100/25
testing caps). User-indicated Meta balance: **$31.78** before the run; approximate remaining
balance **~$31.779**.

## Verification

- ffprobe confirms video + audio, 360×640, 30 FPS, 6.177007 s, 166,088 bytes.
- The original file is unchanged.
- Frames inspected at 1 s and 5 s.

## Known limitation (confirmed in the output)

Segmentation remains the **mock synthetic ellipse** (a narrow vertical mask centered on the
portrait frame). It does not track the two people:

- at 1 s the left subject is sharp and the right subject is blurred;
- at 5 s the right subject is sharp and the left subject is blurred.

The render, audio preservation, plan validation, audit persistence and download are real;
the subject cutout is not. Keeping both people sharp requires SAM 3.1 or a manual subject
mask. This limitation is expected from ADR-001/ADR-007 and is not a renderer failure.

## Safety

- One live transcription and one live director request; no retries.
- No SAM, Muse Image, ElevenLabs or external media service.
- No API key, raw audio or user video is committed to the repository.
- The historical failed job was not modified.
