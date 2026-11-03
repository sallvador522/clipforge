# Idea-to-Video — Product Flow (Studio workspace + approvals + verified MP4)

Status: implemented, offline-verified. **No paid API call was made for this slice.**
The agent does not generate demo videos and does not run the live flow; the
user tests the full flow manually. Live providers stay behind explicit,
per-step approvals (see "Live mode" below).

Related: ADR-025 (vertical slice), ADR-027 (first real generation, user-approved),
ADR-028 (this product flow). Prototype notes remain in `docs/IDEA_TO_VIDEO.md`.

## What it is

A second creation mode beside the upload editor, on the same design tokens
(dark `#14110c`, accent `#ff7659`, Manrope + Plex Mono, 3-column workspace):

- **Edit a Video** — the Studio flow when a session clip exists.
- **Create from an Idea** — the same Studio page (`/`, no second route): when
  the platform is empty, the assistant routes the confirmed instruction into
  an idea job: brief → storyboard → plan review → images → local render →
  verified MP4 download.

The deliverable is always a real verified MP4 (FFmpeg + ffprobe), never a
storyboard JSON, slideshow, or placeholder download. Rendering is local
(Playwright/Chromium capture of the shared `SceneRenderer` + FFmpeg); mocks
simulate AI only, never rendering.

## UI (PT-PT)

Single route `/` (`Studio`, no `?mode=` split). The assistant detects the
empty platform (no session clip, no edit job) and sends the confirmed
instruction into an idea job; with a clip, the edit flow is unchanged. The
created `idea_id` persists to `localStorage` (`clipforge.idea.last`) and
`?idea=` so reload/deep-link restores the job.

- Right (`AssistantPanel` + `IdeaStatusPanel`): voice/typed instruction with
  review-and-confirm. On an empty platform the confirm button reads "Create
  video from this idea" and the two approvals, live progress, per-asset
  states, deterministic QA and result render below the assistant in the same
  column. Every paid step shows MOCK vs LIVE badges; mock work is `$0.00`.
- Centre (`IdeaPreview`): the real `SceneRenderer` engine (same component
  the worker captures), play/pause + scrub, scene-segmented progress,
  9:16/16:9 badge. After a verified render, the final MP4 becomes the
  primary view with the storyboard kept for inspection. While the worker
  runs, a progress bar mirrors the worker sidecar. Shown whenever an idea
  job is active and no edit job exists; otherwise the edit `Viewer`.
- `/render/[ideaId]` is a headless capture surface (noindex), not a product
  page. `/idea` remains a dev-only fixture harness, unlinked from the UI.

Deferred: editable timeline, music (only user-imported audio is in scope),
subtitles/forced alignment (blocked on word-level timestamps).

## State machine

```
create → awaiting_approval/awaiting_storyboard_cost
  → approve-storyboard → queued/planning
  → worker plans → awaiting_approval/awaiting_plan_approval
  → approve-assets → queued/generating_assets (plates) or queued/rendering (programmatic)
  → worker generates → renders → completed
  → failed (explicit error code) | rejected_by_user | cancelled_by_user
```

 Guards: approvals are stage-checked (`idea_stage_conflict` on mismatch);
`PATCH /storyboard` requires `expected_hash` (`storyboard_hash_mismatch`);
re-render requires the same `storyboard_hash`; cancel only works on
`queued`/`processing`; download/result only serve a QA-verified version
(`render_not_verified` otherwise). Corrupt store records are skipped on
list, never crash it.

## API (`apps/api/clipforge_api/ideas.py`)

The API validates and enqueues only. It never plans, generates, or renders.

| Method + path | Purpose |
|---|---|
| `GET /api/ideas/config` | modes (`director`/`image` mock/live), `transcribe_mode`, prices, cap, defaults |
| `POST /api/ideas` | validate brief + options, pre-plan estimate, cap-check, create job |
| `GET /api/ideas` | list recent jobs (tolerates corrupt records) |
| `GET /api/ideas/{id}` | full payload + `can_approve_*`/`can_render`/`can_download`/`can_cancel` |
| `POST /api/ideas/{id}/approve-storyboard` | approval 1/2: records `max_cost_usd` + brief hash + modes, queues `planning` |
| `GET /api/ideas/{id}/storyboard` | board + hash + estimate + approvals + assets |
| `PATCH /api/ideas/{id}/storyboard` | validated board edit before final approval (hash-guarded, rebuilds assets + estimate) |
| `POST /api/ideas/{id}/approve-assets` | approval 2/2: plate selection or `programmatic_only`, image cost + cap checks, queues `generating_assets` or `rendering` |
| `POST /api/ideas/{id}/reject` | terminal reject, nothing generated |
| `POST /api/ideas/{id}/render` | re-render a finished/failed job with the same board hash |
| `POST /api/ideas/{id}/cancel` | cancel queued now; flag `cancel_requested` while processing |
| `GET /api/ideas/{id}/render-manifest` | validated manifest for the capture surface (board, asset URLs, W/H/fps/frames) |
| `GET /api/ideas/{id}/assets/{assetId}` | generated plate PNG (404 until generated) |
| `GET /api/ideas/{id}/download` | verified MP4 (409 until `completed` + file on disk) |
| `GET /api/ideas/{id}/result` | status/stage/render/versions/spend/error |

Error codes (stable, surfaced in UI): `idea_not_found`, `brief_too_short`,
`idea_stage_conflict`, `storyboard_invalid`, `storyboard_hash_mismatch`,
`assets_disabled`, `asset_unknown`, `asset_not_found`, `cost_cap_exceeded`,
`render_not_verified`, `rejected_by_user`, `cancelled_by_user`, plus
worker-side `approval_required`, `approval_stale`, `provider_mode_mismatch`,
`storyboard_failed`, `asset_not_approved`, `asset_attempt_exists`,
`asset_generation_failed`, `asset_validation_failed`,
`image_provider_unavailable`, `scene_engine_unresponsive`,
`render_surface_timeout`, `render_surface_error`, `layout_qa_failed`,
`qa_failed`, `render_failed`, `idea_worker_error`.

## Worker (`apps/worker/clipforge_worker/idea_processor.py`, `idea_renderer.py`)

- Claims one job per run (`O_EXCL` claim, 30-min TTL); honours cancel
  sidecars before each paid/capture step; clears claim + cancel on rerender.
- `_plan`: re-checks the storyboard approval (brief hash + modes match,
  spend within approval), runs mock or exactly-one live director call,
  validates the board against options, builds assets (`MAX_PLATES=6`),
  re-estimates, parks at `awaiting_plan_approval`.
- `_assets`: re-checks the assets approval (selection + prompt hashes +
  modes), one attempt per plate, no retries; mock writes deterministic
  gradient plates labelled as mock; live calls the image provider once per
  plate with one-shot authorization. Failures stop the job explicitly.
- `_render`: re-checks the board hash, captures each frame from
  `/render/<ideaId>` (waits `document.title === "READY"`, safe
  first-scene seek probe, asset gate, layout QA), encodes with FFmpeg,
  verifies with ffprobe (streams, resolution, fps, frame count, SHA-256),
  quarantines failed outputs, delivers only verified versions.
- Progress sidecars (`progress.json`) drive the Studio progress bars.

## Capture surface (`apps/web/src/app/render/[ideaId]/page.tsx`)

Headless only: fetches the manifest (idea id in route; no board/path/URL
from query), mounts the shared `SceneRenderer` at exact W/H, sets
`document.title = "READY"` after engine + fonts + images are ready, exposes
`window.__idea.seek/durationMs/debug` for deterministic capture. The worker
screenshots `#idea-stage` per frame (never the viewport), so the MP4 matches
the previewed engine.

## Pricing and modes

`packages/director/clipforge_director/pricing.py` (advisory, no billing):

- `CLIPFORGE_PRICE_STORYBOARD_USD` default `0.002` (conservative headroom
  over the measured `$0.000872`).
- `CLIPFORGE_PRICE_STORYBOARD_XHIGH_USD` default `0.02` (uncalibrated
  ceiling for the xhigh reasoning effort; replaced once the first xhigh call
  is measured — the ledger stays source of truth).
- `CLIPFORGE_PRICE_IMAGE_USD` default `0.01`.
- `CLIPFORGE_IDEA_CAP_USD` default `0.10` per video (create + both approvals
  refuse above it with `cost_cap_exceeded`).

`idea_modes()` reads `CLIPFORGE_CREATIVE_DIRECTOR_MODE` and
`CLIPFORGE_IDEA_IMAGE_MODE`, each defaulting to `mock` and independent from
the editing director/image switches. Any typo collapses to `mock`. Effort
comes from `CLIPFORGE_CREATIVE_DIRECTOR_EFFORT` (default `medium`, verified
`minimal`/`low`/`medium`/`high`/`xhigh` only and applied to the live
storyboard call alone; unknown values raise loudly instead of billing at a
silent effort). xhigh 504s at the Meta gateway, so the real-user profile pins
`high` with a scaled 300 s client timeout (medium stays 60 s). The assets approval budgets image calls only; the storyboard
cost was approved separately and already sits in `spent_usd`. UI badges always
show the effective modes, including non-default effort (`DIRECTOR LIVE XHIGH`).

Animation targets are engine vocabulary, enforced by
`validate_board_targets` at plan time, on PATCH and as a render pre-check
(`storyboard_static`): exact `data-el` ids, fixed targets per effect
primitive, resolvable text lines, verified easings only, and a motion budget
per scene (≥2 overlapping motion steps, motion inside the first second and
the last 500 ms, ≥3 distinct primitives per video). Descriptive names animate
nothing and are rejected in seconds. The 19 primitives include mask_reveal,
elastic_pop, shake, gradient_shift and tracking alongside camera/text/particle
moves; only the 9 verified Anime.js easings execute. Capture samples frame
centres (never scene boundaries) and verifies every seek advanced the
timeline; the asset check uses streaming GET (the file route answers GET
only). Multiplane depth (C): `AssetSpec`/`IdeaAsset.role` (`background`/
`foreground`), ≤1 of each per scene, ≤6 plates total; the engine mounts the
foreground as a bottom-anchored band drifting against the backdrop via
differential parallax (`bgAssetFor`/`fgAssetFor`); prompts are foreground-aware
server-side; the review UI tags each plate FUNDO/FRENTE.

## Storage (`packages/jobs/clipforge_jobs/idea_store.py`)

```
storage/ideas/<idea_id>/idea.json
storage/ideas/<idea_id>/assets/<asset_id>.png
storage/ideas/<idea_id>/renders/v<N>/out.mp4
storage/ideas/<idea_id>/renders/v<N>/frames/frame_NNNNN.png
storage/ideas/<idea_id>/progress.json   (worker sidecar)
storage/ideas/<idea_id>/.claim          (cross-process lock)
```

Atomic writes (temp + `os.replace`); ids validated before any path is
built; `list()` skips corrupt records.

## Contracts

`packages/contracts/clipforge_contracts/idea.py`: `IdeaOptions`
(720×1280 9:16 / 1280×720 16:9, `frame_count = duration × fps`),
`CostEstimate`, `IdeaApproval` (scope, `approved_usd`, modes, brief hash,
asset ids + prompt hashes), `IdeaAsset` (prompt built server-side, hash
pinned at approval), `RenderVersion` (only delivered after QA),
`IdeaStatus` (`queued`/`processing`/`awaiting_approval`/`completed`/
`failed`/`rejected`), `brief_hash`/`storyboard_hash`. Model output never
carries paths, shell, or arbitrary params (`extra="forbid"`).

## Live mode (explicit approval only)

1. Review `/health` + the Meta billing panel first; record the cost
   estimate shown in the Studio.
2. Set exactly what the approval covers, e.g.
   `CLIPFORGE_CREATIVE_DIRECTOR_MODE=live` (storyboard only) and/or
   `CLIPFORGE_IDEA_IMAGE_MODE=live` (plates only). Mock stays default.
3. Approve the storyboard in the Studio (single call, no retry/fallback).
   Review the plan; approve only the plates to generate (or
   programmatic-only for `$0.00` images).
4. The worker re-validates hashes/modes before each paid call; any drift
   fails the job instead of spending. One attempt per plate; no automatic
   retries. Restart the API after env changes; keep `MODEL_API_KEY`
   server-side only.

## Manual test checklist (user-run; agent runs nothing live)

1. Restart API + Studio (see Handoff commands below), open `/?mode=idea`.
2. Create a brief (mock): estimate `$0.00`, status `awaiting_approval`.
3. Approve storyboard → `queued/planning`; run the idea worker once;
   expect `awaiting_plan_approval` with 2–4 scenes and checked plates.
4. Toggle plates / programmatic-only; approve assets → `queued/rendering`;
   confirm the manifest (`/api/ideas/<id>/render-manifest`) shows the
   right W/H/fps/`frame_count` and `asset_urls` (empty when programmatic).
5. Open `/render/<id>`: expect `document.title === "READY"`,
   `#idea-stage` exactly W×H, `__idea.seek()` + opacity probe working.
6. Run the render worker; expect `completed` with QA
   (captured/missing/black/frozen), ffprobe-verified MP4, download works.
7. Failure paths: wrong-stage approvals → `idea_stage_conflict`; unknown
   asset → `asset_unknown`; stale hash on re-render →
   `storyboard_hash_mismatch`; over-cap approvals → `cost_cap_exceeded`;
   cancel/reject stop the job with explicit codes.
8. Confirm MOCK/LIVE badges match the backend modes and the ledger is
   unchanged unless a live approval was explicitly granted.

## Verification evidence (this slice)

- `tests/test_idea_contracts.py`, `tests/test_idea_api.py`,
  `tests/test_idea_worker.py`: 26 passed (contracts/pricing, approval
  guards, manifest, mock plan + plates, real encode/ffprobe QA).
- Full backend suite: 365 passed. Frontend: `npm run typecheck` clean,
  `npm run build` clean (`/`, `/render/[ideaId]`).
- Isolated browser check (temp API `:8010` all-mock + temp Studio `:3100`):
  created a plan, both approvals, manifest 720×1280/480, `/render/<id>`
  `READY` with exact stage size and working seek/opacity probe. No render
  worker was run from the agent; no paid calls (live ledger unchanged).
