# ClipForge — Product Audit

**Audit date:** 2026-11-01
**Product state:** Milestone 6C complete (plan review, approval, rejection, clarification and resume)
**Execution mode for this audit:** `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=mock`, `CLIPFORGE_DIRECTOR_MODE=mock`
**Live calls made while producing this audit:** none

This audit separates what is **verified working**, what is **mock/simulated**, and what is
**not implemented or blocked**. A passing API response is not treated as proof of a working
video: every render claim below is backed by a real local MP4 inspected with ffprobe, and
the browser workflows were driven in system Chrome at desktop and mobile viewports.

## Legend

| Label | Meaning |
|---|---|
| **Verified live** | Exercised against the real Meta endpoint in a previously approved live run, with measured usage/cost. No live call is made by the mock workflow. |
| **Verified local** | Real local computation with no external AI: FFmpeg, OpenCV, ffprobe, FastAPI, worker, browser. |
| **Mock** | Deterministic local simulation. Clearly labelled in the product; not the real AI capability. |
| **Planned / blocked** | Not implemented. Must not be advertised or executed until its provider contract is verified and the user approves a controlled test. |

## Executive summary

ClipForge now completes the intended user-controlled loop in mock mode:

**upload → voice or typed instruction → transcript → v2 Director plan → review →
approve/reject/clarify → real local render → independent verification → before/after →
download**

The largest previous product gap — the AI Director planned and rendered without the user
being able to inspect or control the decision — is closed. Every ready plan, including a
blur-only plan, now stops at `awaiting_approval`; the worker renders only after an atomic
API approval. Rejection, unsupported requests and pending clarifications never render.

The remaining product limitation is **subject quality, not workflow**: segmentation is
still a synthetic moving ellipse, so the sharp region is not a real person cutout. Real SAM
3.1 tracking and Muse Image background generation remain blocked and unimplemented.

## End-to-end flow

| Stage | Status | Evidence / limitation |
|---|---|---|
| Video upload | **Verified local** | Extension/size/stream/duration/resolution/FPS validation with ffprobe. Original file preserved. |
| Voice capture | **Verified local** | Real browser MediaRecorder capture with playback and permission-denied handling. |
| Voice transcription | **Verified live** (opt-in) / **Mock** default | Live Muse Voice Transcribe was exercised in LIVE-E2E 005 and 006, including cost and session id. Mock mode requires an explicit fixture and never interprets audio. |
| Transcript review | **Verified local** | Editable transcript, explicit confirmation; the worker never re-transcribes confirmed text. |
| Intent understanding | **Verified live** (opt-in) / **Mock** default | Both modes produce the same normalized v2 contract. Mock is deterministic. Live uses Muse Spark with registry validation. |
| Plan review | **Verified local** | Inline dialog shows interpreted intent, subject strategy, every dynamic operation, relevant parameters, capability source (MOCK/LOCAL/LIVE/PLANNED/UNAVAILABLE), approval requirements and verification checks. |
| Approval / rejection | **Verified local** | Backend-enforced atomic transitions. No render before approval; rejected plans are terminal. |
| Clarification | **Verified local** | Inline answer, original context preserved, maximum 3 rounds, revised plan re-enters review; no render before approval. |
| Unsupported requests | **Verified local** | Terminal `unsupported` state, named unavailable capability, no render. |
| Subject identification | **Mock** | Synthetic moving ellipse. **No real person tracking; not SAM.** |
| Background blur | **Verified local** | Real OpenCV compositing + FFmpeg encode, original audio preserved. |
| Background replacement | **Verified local** (rendering) / **Mock** (asset) | Real local composite using local/mock background assets. **Not Muse Image.** |
| Output verification | **Verified local** | ffprobe checks streams, resolution, frame count, duration and audio before download is exposed. |
| Before/after + download | **Verified local** | Verified MP4 served only after `render_status="verified"`. Browser downloads re-probed. |
| Plan history / audit | **Verified local** | `state_history` records actor, status/stage before/after, timestamp and note in `job.json`. Director audit persists on success and failure. |
| Multi-user authorization | **Not implemented** | The app is local single-user. Jobs are addressed by unguessable id but there is no authentication or ownership model. See gaps. |

## MVP capability matrix

| Capability | Product status | Honest description |
|---|---|---|
| Upload ≤10 s, ≤720p, ≤30 FPS | **Verified local** | Enforced by the API, not only the UI. |
| Record / type instruction | **Verified local** | Both paths are supported; voice is primary. |
| Transcribe Portuguese speech | **Verified live** (opt-in) | Live ASR tested. Mock mode does not fake understanding of recorded audio. |
| Interpret editing intention | **Verified live** (opt-in) / **Mock** default | v2 plan with typed operations and registry validation. |
| Identify primary person | **Mock** | Ellipse only. Not a person detector. |
| Segment / track person | **Mock** | Synthetic mask sequence. Real SAM 3.1 is **blocked**. |
| Keep subject sharp | **Verified local, limited by mask** | Compositing is real; the mask does not follow a real person. |
| Blur background | **Verified local** | Real Gaussian blur outside the mask. |
| Generate new background | **Not implemented** | `background.generate` is `planned`; Muse Image is not integrated. |
| Replace background | **Verified local with mock/local asset** | Composite is real; the asset is not generated by Muse Image. |
| Render final MP4 | **Verified local** | CPU FFmpeg + OpenCV; original audio preserved. |
| Verify output | **Verified local** | ffprobe verification gates completion and download. |
| Before/after and download | **Verified local** | Compare view and real MP4 download. |
| Review / approve / reject plan | **Verified local** | Added in Milestone 6C. |
| Clarification | **Verified local** | Added in Milestone 6C; 3-round limit. |
| Unsupported explanation | **Verified local** | Added in Milestone 6C; terminal state. |
| Idempotent approval / single render | **Verified local** | Atomic transition lock + one worker claim + tests for duplicate/concurrent approvals and restart. |

## What Milestone 6C changed

1. **Mock Director v2 is wired into the worker.** `CLIPFORGE_DIRECTOR_MODE=mock` uses
   `MockProfessionalEditingDirector`; the legacy keyword planner is no longer the worker's
   mock path. Live mode keeps `LiteMetaEditingDirectorProvider` and its existing validation.
   There is no silent fallback to v1 when v2 fails.
2. **Explicit review state machine.** New statuses: `awaiting_approval`,
   `awaiting_clarification`, `rejected`, `unsupported`. Approval returns the job to
   `queued` with stage `approved`; an explicit separate `approved` status was not added
   because the existing stage field already carries that meaning without duplicating state.
3. **Atomic, auditable transitions.** `JobStore.transition()` validates the expected current
   status, the allowed target status and writes under a cross-process `transition.lock`.
   Every user/worker status/stage change appends a `JobStateEntry`.
4. **Backend approval gate.** Approval, rejection and clarification are enforced by the API
   and the worker, not by hiding buttons. Every ready plan stops for review. The worker
   re-enters directly at rendering from the persisted plan and does **not** call the
   Director again.
5. **Clarification loop.** A pending question blocks rendering; the answer and original
   instruction are sent to the Director; the revised plan is persisted and reviewed.
6. **Truthful UI.** The step tracker derives completion from `status`, `stage`,
   `render_status` and the actual result. It no longer marks rendering or verification done
   for jobs that have not rendered. Percentages are never invented.
7. **Idempotency.** Duplicate and concurrent approvals yield exactly one accepted transition;
   a single claim lock and a single worker execution prevent duplicate output. A clean worker
   restart can claim the approved job and render it once.
8. **Mock background honesty.** Replacement uses local/mock assets, labelled as such. The
   UI never claims Muse Image generated them.

## Verified evidence

### Backend and rendering

- Full backend suite: **234 tests passed** in mock mode.
- Coverage includes: approval/rejection/clarification/unsupported, duplicate approval,
  concurrent transition locking, worker restart resume, clarification limit, render failure
  audit, failure after render but before status persistence, original preservation, verified
  download and truthfulness of result states.
- Real MP4 outputs were produced and re-probed: video + audio streams present, expected
  resolution, frame count and duration.

### Browser E2E

Run with the mock API (`:8001`), persistent worker and Next.js app (`:3000`) using
`apps/web/scripts/qa-approval.mjs`:

| Scenario | Result |
|---|---|
| Blur, desktop 1440×900 | Plan reviewed, approved, rendered, downloaded; **5 dynamic operations**; MOCK mask label present. |
| Blur, mobile 390×844 | Same flow; dialog usable at mobile width. |
| Background replacement | Approval required; export disabled before approval; rendered with a local/mock asset after approval. |
| Reject | No render; original intact; export remains disabled. |
| Clarification | Ambiguous instruction → inline question → answer → revised plan → approval → render. |
| Unsupported | Clear unsupported explanation; export disabled; no render. |
| Console errors | **Zero.** |

Downloaded files: four real MP4s (blur desktop, blur mobile, replacement, clarification),
each 64×36, 1.0 s, video + audio.

### Frontend

- `npm run typecheck` passes.
- Production build is part of `scripts/check.ps1`.
- Existing workspace layout is preserved; the review experience is an overlay consistent
  with the established visual language.

## Functional gaps and risks

| Gap | Impact | Status |
|---|---|---|
| **No real subject tracking** | The sharp/blurred boundary is an ellipse, not a person. Blur and replacement prove the pipeline, not real cutout quality. | **Blocked** on SAM 3.1 approval and provider verification. |
| **No Muse Image generation** | Replacement backgrounds are local/mock assets. The product must not claim generated imagery. | **Planned**, not implemented. |
| **No authentication / ownership** | API is local single-user. Any client that knows a job id can read/decide it. Acceptable for a local demo; not for deployment. | **Not implemented.** Must be addressed before multi-user or public hosting. |
| **No crash recovery mid-render** | A hard worker crash after claim can leave a job in `processing` with its claim lock. Clean restarts before claiming work fine; no automatic stale-lock recovery exists. | **Known limitation.** Manual verification required before removing a lock. |
| **Mock masks do not track real people** | Real user footage can look partially sharp on one side. | **Blocked** on SAM. |
| **No frontend unit-test runner** | Behaviour is covered by backend tests, typecheck and browser E2E. | Tooling gap, not a product claim. |
| **Agent budget still constrained** | Live testing is capped by the ledger and needs explicit approval. | Intentional safety control. |
| **No multi-user/cloud/payments** | Out of MVP scope. | Out of scope. |

## Security and cost posture

- No credentials reach the browser; live providers require a server-side `MODEL_API_KEY`.
- Dev launchers force mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is explicitly set.
- The live-call ledger is fail-closed, atomic and never automatically reset; direct live
  provider calls require a one-shot authorization.
- No live calls, SAM calls or Muse Image calls were made in Milestone 6C.
- The API does not expose provider credentials, raw provider payloads or internal audit
  secrets. `state_history` remains in `job.json`; the public job response does not expose it.

## Recommended next steps

1. **Get explicit approval for a real SAM 3.1 integration**, verify the official hosted
   contract, and replace the synthetic mask provider behind the existing mask contract.
2. **Validate subject quality on real footage** (multiple people, occlusion, motion) before
   claiming person tracking.
3. **Then evaluate Muse Image** as a separate approved step; keep local/mock assets until
   its contract is verified.
4. **Add authentication/ownership** before any deployment beyond localhost.
5. **Add stale-claim recovery** (with explicit operator validation) if the worker will run
   unattended.
6. Only then consider new editing capabilities (trim, captions, transitions) — none are in
   this MVP and none should be advertised yet.
