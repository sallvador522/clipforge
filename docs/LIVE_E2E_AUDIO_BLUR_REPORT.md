# LIVE-E2E 005 — Audio Instruction → Muse Spark → Real Blur Render

**Date:** 2026-11-01
**Status:** SUCCESS — real Portuguese audio transcribed, planned by Muse Spark, executed by the local
renderer, downloaded and verified.
**Scope:** one end-to-end run; no SAM, no Muse Image, no ElevenLabs, no frontend redesign.

## Configuration

| Variable | Value |
|---|---|
| `CLIPFORGE_AI_MODE` | `mock` (segmentation, background and legacy planner stay mocked) |
| `CLIPFORGE_TRANSCRIBE_MODE` | `live` |
| `CLIPFORGE_DIRECTOR_MODE` | `live` |
| Director | `muse-spark-1.3-contributor`, `reasoning_effort=medium`, lite schema, cap 16,000 |
| Budget ledger | max 2 live transcription + 2 live director calls (`storage/live-call-ledger.json`) |

No API key is printed, logged or stored in this report.

## Inputs

- **Audio:** `blur-instruction.wav`, synthesized locally with Windows SAPI (`Microsoft Maria Desktop`,
  pt-BR): “Desfoca o fundo e mantém-me nítido.” 3.661859 s, 161,534 bytes, mono PCM 22.05 kHz.
  No external service was used to create the test audio.
- **Video:** `studio-clip.mp4`, 320×180, 10 FPS, 2.0 s, with audio.

## Flow and measured results

| Step | Result |
|---|---|
| `POST /api/transcribe` | **HTTP 200** |
| Transcript | `Desfoca o fundo e mantém-me nítido.` |
| Language | `pt-BR` |
| Provider / session | `meta-muse-voice-transcribe` / `clipforge-9eeb63fa8d1f443ab7c6d42b4e18296e` |
| Audio duration | 3,680 ms |
| ASR cost | **$0.000184** (3.680 s × $0.18 / 3600 s) |
| `POST /api/uploads` | **HTTP 201** — job `6b9e2dc1a95a4a60839b1312e34fc592` |
| `POST /api/jobs/{id}/voice` | **HTTP 200**, ready |
| Worker stages | `planning → rendering → completed` |
| Director outcome | `plan_ready`, approval `not_required` |
| Director operations | `subject.isolate`, `background.blur`, `audio.preserve`, `video.render_mp4`, `output.verify` |
| Director usage | 2,781 prompt + 1,856 completion = **4,637 tokens** |
| Director request id | `req_2c45fa340028` |
| Director cost | **$0.000649** (Contributor rates: $0.10/1M in + $0.20/1M out) |
| Render mode | `blur_background` |
| Rendered output | 320×180, 10 FPS, 20 frames, 2.000 s, **36,998 bytes**, audio present |
| `GET /api/jobs/{id}/download` | **HTTP 200**, 36,998 bytes saved |

Saved output:
`C:\Users\New User\AppData\Local\Temp\opencode\live-e2e\6b9e2dc1a95a4a60839b1312e34fc592.mp4`

## Independent verification

- `ffprobe` on the downloaded file: video stream 320×180 at 10/1 FPS, audio stream present,
  container duration 2.000000 s, size 36,998 bytes.
- Extracted frame at 1.0 s: the centered subject (blue/yellow oval) is sharp and the background is
  heavily blurred; the transition is feathered. Mock segmentation is a synthetic ellipse, so this
  proves the pipeline and renderer, **not** real person tracking.
- Budget ledger after the run: `{"transcription": 1, "director": 1}` — one spare call per function.
- Backend suite: **191 tests passing** (190 before the new budget-refusal test).
- Frontend: `npm run typecheck` clean; `npm run build` succeeds.
- Browser smoke (in-app Chromium at `http://localhost:3000`): Media, Viewer, Timeline and AI Assistant
  regions present; **LIVE TRANSCRIPTION** badge visible; `/health` fetched from `http://localhost:8001`;
  zero console errors. No live call was triggered by this smoke test.

## Cost

| Item | Cost |
|---|---|
| This run — ASR | $0.000184 |
| This run — director | $0.000649 |
| **This run total** | **$0.000833** |
| Known prior spend (003 + 004) | **≤ $0.000655** (003 bounded ≤ $0.00026; 004 measured $0.000395) |
| Known cumulative | **≤ ≈ $0.001488** plus LIVE-CALL 001/002 (panel unknown) |

Budget context: ~$30 remaining before this phase; these figures are local calculations from measured
durations/tokens, not a substitute for the Meta billing panel.

## Defects found and fixed during the run

1. **WAV temp-name collision (real bug).** For `.wav` uploads, the temporary input file and the
   converted output were both named `recording.wav`; FFmpeg refused to overwrite its input and the API
   returned `422 conversion_failed` before any network call. The input is now `upload{suffix}` and the
   converted output remains `recording.wav`. Regression test added.
2. **Budget reservation timing.** The transcription reservation originally happened before local
   validation/conversion, so a failed conversion consumed a live-call slot. Reservation now happens
   immediately before the provider network call; a `429 live_budget_exhausted` is returned without
   touching the provider. Regression test added (zero transport calls at the cap).
3. **Dev launcher paths.** `scripts/dev_api.py` did not include `packages/director` on `sys.path`;
   `scripts/dev_worker.py` was added to load `.env` and the same package paths.

## Integration decisions

- Live director branch: when `CLIPFORGE_DIRECTOR_MODE=live`, the worker calls the lite Muse Spark
  provider, validates the v2 plan, then adapts it to the existing v1 `EditingPlan` for rendering.
- Approval gate: `approval_status` `required`/`rejected` completes the job as `awaiting_approval` with
  `render_status="awaiting_approval"` and **no render**.
- Clarification/unsupported outcomes complete without segmentation or rendering.
- `director_plan`, `director_usage` and `director_request_id` are persisted in the job result.
- Each live call reserves a slot in the file ledger immediately before the network request; there are
  no automatic retries.

## Limitations / next gate

- Segmentation remains mock (synthetic ellipse). Real subject cutout requires SAM 3.1 and is **not**
  implemented; it waits for explicit approval.
- Background replacement still uses a local/mock asset, not Muse Image.
- The approval gate is backend-only; there is no UI/endpoint to approve and resume a plan yet.
- One transcription and one director call remained under the phase-005 ledger; a new phase needs fresh
  approval and a ledger reset.

## Follow-up — local user testing (same day)

The user used the spare transcription call while testing the UI and hit `429 live_budget_exhausted` at the
2-call cap. At their explicit request, ADR-015 made the caps configurable:

- `.env` now sets **100 transcription + 25 director** calls; defaults remain 2/2 for a fresh checkout.
- Phase-005 counts (`transcription=2`, `director=1`) were archived to
  `storage/live-call-ledger.phase-005.json`; the active ledger was reset to `0/0`.
- `GET /health` reports `live_call_limits` and `live_calls_used`.
- Worst-case cost of the 100/25 test phase at measured rates is **under $0.04**.

The measurements in this report describe the original LIVE-E2E 005 run and are unchanged.
