# ClipForge — Hackathon Demo (60–90 s)

**Demo asset (do not overwrite):** `storage/muse_image_live_validation/live-attempt-1/luanda_sunset_demo_v2.mp4`
(recommended; 1080×1920 center-crop plate, zero distortion — see §9).
Validated original: `luanda_sunset_demo.mp4` (identical content, 15.6% anamorphic squeeze from the 2:3 stretch).
Both: 360×640, 177 frames, 30 FPS, 6.177 s, H.264 + AAC, decoded PCM identical to the original.

## 1. What the video proves

Two real people, segmented by live **SAM 3.1**, composited over a live **Muse Image 1.0** Luanda-sunset plate by the real FFmpeg/OpenCV renderer, with the **original audio** preserved bit-for-bit.

## 2. Honest lineage (say this on stage)

- The **masks** in this MP4 are real SAM 3.1 output: job `20c603cd…`, HTTP 200, request `a6b54e67-…`, IDs `0`+`1`, 177/177 frames each. No synthetic masks.
- The **background** is real Muse Image 1.0 output: HTTP 200, request `c515a42f-…`, 1280×1920 PNG, SHA-256 `47f6f008…9d29a9f27e`. Text prompt only; no video or masks were sent.
- The **composition** is the existing local renderer (`replace_background`, 5 px feather, 6.2 s) plus ffprobe verification and PCM comparison.
- The **Director (Muse Spark, live)** was validated separately in LIVE-E2E 005/006 — it is **not** in this MP4's lineage. This MP4's prompt was authored for the demo and its SAM job ran with a typed transcript + mock director. Do not claim all three models ran in one execution.

## 3. 60–90 s sequence

| Time | Show | Say |
|---|---|---|
| 0:00–0:10 | Play `luanda_sunset_demo.mp4` full-screen with audio | “Two people, filmed on a phone, placed into an AI-painted Luanda sunset — original sound intact.” |
| 0:10–0:25 | Studio: upload → typed/voice instruction → consent dialog → plan review | “Voice in, plan out. Live SAM needs explicit consent before anything leaves the device — unchecked by default.” |
| 0:25–0:40 | Subject cards: Subject 0 / Subject 1, “177 detected” each | “SAM found two distinct people, tracked across all 177 frames with zero overlap. I pick who stays sharp.” |
| 0:40–0:55 | `background.png` (1280×1920) + `background.json` provenance | “One Muse Image call, text only — $0.01. PNG validated, hashed, stored with its request id.” |
| 0:55–1:20 | `before-after.png`: original vs composed at 0/1.5/3/4.5/5.7 s; replay MP4 | “Same two people, new world, same voices. ffprobe + PCM check prove the audio is untouched.” |
| 1:20–1:30 | Limitations slide (below) | “Honest gaps: label holes, squeeze, no occlusion test — and what we’d do next.” |

## 4. How the models collaborate (30 s version)

Voice instruction → Muse Spark writes a validated editing plan (typed operations, never raw code) → SAM 3.1 segments each person into per-frame masks after explicit user consent → the user selects who stays sharp → Muse Image 1.0 paints one background plate from text alone → the local renderer composites subjects over it with a feathered alpha, muxes the **original** audio back, and ffprobe verifies streams, frames and duration before download. Every live call is ledger-budgeted, one-shot, no retries.

## 5. Evidence to have open (offline, no calls)

- `docs/SAM_31_LIVE_TEST_REPORT.md` — request id, 2 subjects, 177/177, cleanup `deleted`.
- `docs/MUSE_IMAGE_LIVE_TEST_REPORT.md` — request id, 1280×1920, SHA-256, PCM match.
- `storage/…/live-attempt-1/run-log.json` — one image reservation (0→1), timings, render facts.
- `docs/LIVE_E2E_AUDIO_BLUR_REPORT.md` — live Director evidence (separate runs).

## 6. Known limitations (disclose, don’t hide)

1. **Label holes:** the money-sticker rectangles on both chests are mask holes — sunset shows through. Real SAM behavior on overlaid graphics; masks were not edited to hide it.
2. **15.6% anamorphic squeeze:** the 2:3 plate (1280×1920) is direct-stretched to 9:16 (360×640), not cropped. Looks natural here; geometric scenes would reveal it.
3. **Meme captions vanish:** top text sits outside the person masks, so replacement removes it by design.
4. **Lighting mismatch:** neutral-cool subjects on a warm sunset plate; no relighting is done.
5. **One easy scene:** no occlusion, no crossing, 360×640 — not a tracking stress test.
6. **Stale UI copy:** plan operation footnotes can still read “mock masks in this build” even on a live-SAM run (badge itself is correct: LIVE). Don’t dwell; acknowledge if asked.

## 7. Presentation blockers checked

- Consent dialog: correct copy, unchecked default, decline sends nothing — OK.
- Capability badges derive from actual provider/result (`LIVE`/`MOCK`/`UNAVAILABLE`) — OK.
- Stale `expected_output` footnote on live runs (item 6 above) — cosmetic only.
- No blockers requiring code changes before the demo.

## 8. Proposed local improvement (no credits, not executed)

Center-crop the 1280×1920 plate to 1080×1920 **before** compositing to remove the anamorphic squeeze, rendering to a *new* file. Zero risk to sources, masks or the judged artifact — proposed only; the validated MP4 above stays byte-stable unless you approve the variant.

## 9. v2 polish result (2026-11-01, local only)

Executed the §8 proposal: `background_v2_1080x1920.png` (SHA-256 `836a1ae7…3772`, source plate untouched), re-rendered with the same real masks + original video → `luanda_sunset_demo_v2.mp4` (270,249 B, 177 frames, PCM identical, render 4.86 s). Comparison sheet: `v1-vs-v2.png` (5 samples).

**Verdict: v2 is visually superior.** Zero geometric distortion (exact 9:16, no stretch) while the crop removes nothing important — sun, clouds, coastline, palms and cliffs all survive; only peripheral cliff/grass edges are trimmed. The difference is subtle (the scene has no hard geometric references) but v2 is the geometrically correct presentation master. v1 remains byte-stable as the first validated render. Same known defects in both (label holes, caption removal, lighting mismatch) — unchanged, undamaged, honestly preserved.
