# CLIPFORGE — AI Creative Production Engine (architecture plan, read-only)

Post-MVP direction (user-approved): "Create from an Idea" 20 s 9:16 reels, $1 cap
for the first real generation. No code changed, no installs, no API calls, no
commits in this pass. All findings verified by reading source, tests and docs.

## 1. Reconciliation: P0 Workspace vs audit (RESOLVED, no duplicate work)

- The P0 report is TRUE in the working tree and the audit is TRUE against HEAD.
  Every P0 file is real, wired and tested — but UNCOMMITTED (other session):
  `packages/jobs/.../project_store.py` (ProjectStore: create/get/list/rename,
  asset records, atomic writes, id-pattern validation), `contracts/project.py`
  (ProjectRecord `prj_*`, AssetRecord `ast_*`, kinds video/audio/image/text/
  graphics, provenance, sanitized flag), `api/assets.py` (upload/probe,
  PNG/JPG/WebP decode check, audio stream check, full SVG sanitizer:
  allowlisted elements/attributes, no DOCTYPE/entities/scripts/external refs),
  `api/exports.py`, full project/asset CRUD + job association in `main.py`,
  Asset Library in `MediaPanel.tsx` (search, filter, preview incl. sanitized
  SVG-as-image, upload progress, two-step delete), `types.ts`/`api.ts` client.
- Evidence: `tests/test_project_workspace.py` + `test_exports.py` pass;
  `pytest tests/test_project_workspace.py tests/test_exports.py
  tests/test_storyboard.py` → **28 passed** on this tree.
- Decision: DO NOT reimplement. Prerequisite for everything below is the other
  session committing P0 (their files, their commit). Depending plans must treat
  committed-P0 as the dependency, never duplicate it.
- Open collision risk (observed this session): a concurrent `next build`
  corrupted the dev server's `.next` (500s on `/` and `/idea`); a foreign
  `next start` held :3000. Coordinate dev-server/build ownership before any
  renderer work: one owner per port, never build while dev serves.

## 2. One application (non-negotiable)

- Edit-a-Video and Create-from-an-Idea share: Studio shell, Project Workspace,
  Asset Library, video preview, export/download, ledger/budget rails.
- `/idea` stays a hidden prototype: its engine moves INTO a shared
  `SceneRenderer` component used by Studio preview AND headless export.
  The Chromium surface is an implementation detail, never a deliverable.
- Honest status events only (map §8 messages 1:1 to backend job stages).
  Never invent percentages or model-execution events.

## 3. Anime.js 4.5.0 — evaluated (installed; timeline/seek verified in our engine)

Verified by use + source reads (`dist/modules`):
- `createTimeline({autoplay:false})` / `timeline.add(t,p,pos)` / `timeline.seek(ms, true)`:
  WORKS. Critical finding: on a never-played timeline under seek-only rendering,
  COMPLETED tweens do not stick — our engine pins every tween's end values with
  a trailing `tl.set` (hold pattern). `seek(ms, true)` mutes callbacks, so
  `onUpdate`-driven values need deterministic twins (our `syncCounters`).
- `animate()`: single-shot only — preview flourishes at most, NEVER export path.
- SVG (`svg.*`): `createDrawable()` = official line-draw (adopt; replaces our
  manual dashoffset tween), `createMotionPath()` = path-following (adopt later;
  our parametric x/y covers the PoC), `morphTo()` = REJECT for v1 (fragile
  across arbitrary user SVGs).
- Text: `splitText()` (chars/words/lines, addEffect) = ADOPT (replaces our
  manual char splitter); `scrambleText()` = DEFER (deterministic via seed, nice
  for counters/titles later).
- `stagger()`: exists; our per-target `addHold` loop proved more predictable
  under seek — keep the loop, do not reintroduce stagger on the export path.
- Engine caveats, all verified in implementation: completed tweens don't stick
  on a never-played timeline under seek-only rendering → every tween pins end
  values with a trailing `set` (hold pattern); `onUpdate` muted during seek →
  deterministic `syncCounters`; React-commit race produced empty timelines →
  post-commit build + refuse-capture-on-failed-seek guard; READY gate awaits
  `document.fonts.ready` + image decode; camera moves target the backdrop
  layer only (whole-section zoom clipped the typography — caught by layout
  QA); text renders plain unless a kinetic step targets it; layout QA checks
  typography only (effect bleed past the frame is by design).

Justified allowlist deltas: ADD `svg_draw_official` (createDrawable),
`motion_path_follow` (createMotionPath); KEEP the 14; REJECT `morphTo`,
`animate()`-only effects, WAAPI-synced animations on the export path.

## 4. Single rendering architecture (NO Python animation engine)

- One `SceneRenderer` React component: props = storyboard JSON + assets.
  Studio preview mounts it visibly; export worker mounts the SAME component
  headless. Same definitions govern preview and export by construction.
- Export: Playwright + headless Chromium → `seek(t)` per frame → screenshot
  `#stage` (exact 720×1280) → FFmpeg libx264/yuv420p + faststart.
- FFmpeg/OpenCV effects (explicit native list): blur/replace compositing
  (existing renderer), audio mux/normalize, encode, QA probes (ffprobe, black/
  frozen detection via OpenCV). Everything else is Anime.js.
- Measured benchmark (this machine, existing script): 20 s @24 fps = 480
  frames, ~68 s wall (~7 fps capture), 720×1280, 0 missing / 0 black.
  Budget ~70 s render per 20 s video — acceptable for v1; re-benchmark after
  shared-component move.
- Per-frame determinism rules: seeded randomness only, no wall-clock reads in
  builders, fonts+assets ready before first seek, seeks monotonic per capture.
- Recovery: seek-guard refuses capture when the engine doesn't respond
  (proven: caught a React-commit race producing empty timelines); resume =
  restart capture from frame N (frames are independent seeks).
- Verification: frame count/order, ffprobe streams, black/frozen scan,
  scene-boundary spot checks, audio presence + A/V sync after mux.

## 5. Director lifecycle (CreativeDirectorProvider exists; gaps named)

- Understand/Plan: EXISTS (`creative.py`, CREATIVE_BRIEF, storyboard schema,
  echo + registry-style validation). EXTEND brief with asset-aware context.
- Evaluate (NEW): read-only project-context tools returning stable IDs —
  `list_assets`, `inspect_asset`, scenes/timeline refs. No paths, no shell.
- Propose: storyboard review UI in Studio (GAP) + cost estimate (images ×
  $0.01 + storyboard tokens + review TBD) before any paid call.
- Produce: Muse Image via existing provider; scene plates = same endpoint.
  Approval gate per batch; persist provenance as asset records.
- Assemble: prototype engine → shared SceneRenderer (phase 1 move).
- Review: deterministic QA (exists as script; promote to worker step) +
  Spark video-understanding review (PLACEHOLDER — contract unverified, rule 3).
- Correct: `apply_correction` + 1-cycle rule exist; asset regeneration always
  needs fresh approval. Persist every storyboard revision.

## 6. Asset-aware safe operations (proposed, validated params, stable IDs)

`search_assets(query, kind)` → `inspect_asset(asset_id)` → `add_asset_to_scene
(asset_id, scene_id, layer, rect)` → `create_title_overlay(scene_id, text,
style)` → `compose_graphic(scene_id, svg_asset_id, primitive, params)` →
`add_narration_asset(asset_id)` / `add_music_asset(asset_id)` →
`retime_scene(scene_id, duration_ms)` → `apply_transition(scene_id, type)`.
All params Pydantic-validated; asset ids pattern-checked server-side
(`ast_*`); no paths/shell/JS. SVG assets arrive sanitized (P0) and animate
only through allowlisted primitives.

## 7. Output verification (real MP4 only)

Codec/resolution/fps/frame-count/duration via ffprobe; scene-boundary spot
frames; audio stream + sync after mux; black/frozen/missing-asset scans; text
inside safe margins (add a text-clipping QA check — GAP); visual continuity
by storyboard intent. Technical QA and Spark subjective review stay separate
artifacts; never label unverified output completed.

## 8. UX (inside Studio, event-backed statuses)

1 idea → 2 review → 3 approve → 4 watch stages → 5 preview → 6 correct →
7 export MP4. Status lines map to backend stages (planning / assets /
composing / rendering / review / correcting). No timeline editor in v1.
No separate animation page in the product (prototype route stays dev-only).

## 9. Phases (P0-commit is phase 0, other session)

1. Shared SceneRenderer + scene model in Studio (move prototype engine, keep
   behavior identical; adopt splitText/createDrawable).
2. Export worker hardening (script → worker job type; resume-from-N; QA gates).
3. Asset-aware director tools (§6) + storyboard review UI + cost estimate.
4. Muse Image plates with approval + provenance-as-assets.
5. Review wiring (deterministic QA in worker; Spark review still placeholder
   until contract verified) + bounded correction.
6. Full Create-from-an-Idea Studio flow.
Smallest end-to-end slice proving the concept: phases 1+2 on the existing
asteroid storyboard (already rendered 480/480 offline) — preview and export
from ONE component. No disabled editing capabilities.

## 10. Acceptance criteria (first slice) / risks / benchmark

Accept: storyboard renders identically in Studio preview and headless export
(pixel-compare a sampled frame); 480/480 frames, 0 missing/black; MP4
720×1280 20.00 s verified; font+asset ready gate before first seek; 1-cycle
correction demo on fixtures; zero paid calls in tests.
Risks: concurrent-session collisions (observed — coordinate first); capture
speed (~7 fps) bounds iteration speed; Spark review pricing/supported shapes
unknown until contract verification; `next build` vs dev-server sharing
`.next` (never overlap).
