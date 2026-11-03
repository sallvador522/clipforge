# Idea-to-Video — Cinematic AI Video Engine (post-MVP vertical slice)

Status: implemented and verified offline. **No paid API call was made.**
Live Spark/Image wiring exists behind explicit approval; tests use mocks and fixtures.

## What it is

A new creation mode beside the existing upload editor:

- **Edit a Video** (existing Studio flow, untouched).
- **Create from an Idea** (this document): idea → storyboard → assets → animated scenes → MP4 → AI review → revision → download.

## Contracts

`packages/contracts/clipforge_contracts/storyboard.py`
- `Storyboard`: project metadata, 1–12 scenes, asset plan, narration, sources, music cues. Scene durations must sum to the project duration (±500 ms); asset scene refs must exist.
- `SceneSpec`: 1–15 s, narrative purpose, visual description, image prompt, foreground/background elements, on-screen text (≤6), narration segment, 1–12 animation steps (each must fit the scene), transitions, scientific claims, references.
- `AnimationStep`: one of 14 allowlisted `AnimationPrimitive`s (camera_zoom/pan, parallax, text_reveal, kinetic_typography, svg_draw, motion_path, particle_burst, shockwave_ring, flash, counter, chart_bar, fade, slide), target element id, start/duration ms, params, ease.
- No code, paths, or URLs: `extra="forbid"` everywhere; `apply_correction()` accepts only allowlisted primitives.

`packages/contracts/clipforge_contracts/quality.py`
- `QualityReview`: overall_verdict (pass/needs_fix/reject), per-scene reviews (severity, timestamp, category, explanation, suggested fix, correction type, asset-regeneration flag). `auto_fixable` is true only for animation/text patches.
- `MockQualityCritic`: deterministic fixture critic.

`DirectorAudit.wire_schema` gained `"storyboard"`.

## Creative director

`packages/director/clipforge_director/creative.py`
- `MockCreativeDirector`: deterministic fixture (asteroid, 20 s, 9:16, 4 scenes). Offline only.
- `CreativeDirectorProvider(MetaEditingDirectorProvider)`: live Muse Spark storyboard planning — single POST, no retries, ledger authorization, `user_request` echo check, usage audit. Covered by mocked-transport tests (exactly one POST asserted); **no live call made**.
- `CREATIVE_BRIEF`: playbook text (conservative scientific claims, assumptions labelled, clarification-or-assumptions rule).

## Scene engine (web)

`apps/web/src/app/idea/page.tsx` + Anime.js 4.5 (`createTimeline`/`add`/`seek`).
- Data-driven composition from a validated storyboard JSON (720×1280 stage).
- Fixed builders per primitive; unknown primitives/targets are ignored.
- `autoplay: false`; `window.__idea.seek(ms)` + `?t=ms` for deterministic capture; `document.title = "READY"` signals build completion.
- Race fixed: the timeline builds in a post-commit effect (building inside `requestAnimationFrame` raced the React commit and produced empty timelines).

## Offline render pipeline

`scripts/render_idea_to_video.py`
1. Validates the storyboard JSON.
2. Playwright + headless Chromium loads `/idea`, asserts the engine responds to seek (refuses to capture on failure).
3. Seeks per frame (`duration × fps`), screenshots `#idea-stage` (exact 720×1280).
4. FFmpeg encodes libx264/yuv420p + faststart.
5. Deterministic QA: frame count/order, unreadable files, black frames (mean < 2.0), frozen-run detector (>10 identical consecutive frames), ffprobe stream check.

`scripts/gen_idea_fixtures.py` generates the procedural fixture assets (labelled local fixtures, not AI imagery).

## Measured PoC run

- Storyboard `E se um asteroide gigante atingisse a Terra?`: 20 s, 9:16, 24 fps → **480 frames**.
- Capture: ~68 s wall (≈7.1 fps capture rate) on this machine.
- QA: 480/480 frames, 0 missing, 0 black, 20 frozen runs (all genuine static holds, verified by inspection); remaining QA note: heat-only tweens (`onUpdate` counters) are set deterministically via `syncCounters` because callbacks are muted during seek.
- Output: `storage/idea_poc/idea.mp4` — 720×1280, 20.00 s, 480 frames, h264, silent (no narration/TTS in the slice; no fake audio).

## Quality review and correction

- Deterministic QA runs first; only QA-passed drafts reach the critic.
- `auto_fixable` reviews map to `apply_correction()` patches (validated, allowlisted, refit-checked). One revision cycle max; asset regeneration always needs explicit user approval.
- Real Spark video-understanding review is **not wired** (contract unverified → placeholder by rule 3). Mock critic proves the schema and loop.

## What is real vs. mock

| Piece | Status |
|---|---|
| Storyboard schema + validation | Real, tested |
| Mock creative director + fixture | Real, offline |
| Live Spark storyboard provider | Implemented, tested via mock transport, **never called live** |
| Anime.js engine + seek capture | Real, verified MP4 |
| FFmpeg encode + QA | Real, verified MP4 |
| Mock critic + 1-cycle correction | Real, tested |
| Muse Image scene assets | **Not generated** (would bill $0.01/image); procedural fixtures stand in |
| Real Spark video review | **Placeholder** (unverified contract) |
| Narration/TTS | **Absent by design** (no approved TTS; user records) |
| Studio UI for the new mode | **Not built** (preview/demo page only) |

## First real generation (requires explicit approval, ≤$1 cap)

1. Approve storyboard generation (Spark, a few thousand tokens ≈ $0.01–0.03).
2. Review/approve storyboard JSON; approve asset plan (N images × $0.01).
3. Replace fixture PNGs with generated plates (same filenames) and re-run the offline pipeline.
4. Record/upload narration; mux with FFmpeg (existing audio tooling).
5. Optional: Spark review of the draft (price TBD — verify before approving).
