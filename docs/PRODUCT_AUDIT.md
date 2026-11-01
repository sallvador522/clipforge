# ClipForge — Product Audit

**Audit date:** 2026-11-01
**Product state:** Milestone 6D complete for implementation/offline validation (real SAM 3.1 provider, subject selection, explicit consent gate). A post-audit live SAM test succeeded on 2026-11-01 (1 request, 2 subjects, verified renders); see `docs/SAM_31_LIVE_TEST_REPORT.md`.
**Execution mode for this audit:** `CLIPFORGE_AI_MODE=mock`, `CLIPFORGE_TRANSCRIBE_MODE=mock`, `CLIPFORGE_DIRECTOR_MODE=mock`, `CLIPFORGE_SEGMENTATION_MODE=mock`
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

Milestone 6D now implements the real SAM 3.1 provider, official parser, per-object masks,
source-frame previews and user subject selection. One live SAM request succeeded on
2026-11-01 (2 subjects, 177/177 frames each; see `docs/SAM_31_LIVE_TEST_REPORT.md`);
broader detection quality is still unproven, and mock mode uses two synthetic tracks.
Muse Image background generation remains unimplemented. Selective person blur remains
unsupported.

## End-to-end flow

| Stage | Status | Evidence / limitation |
|---|---|---|
| Video upload | **Verified local** | Extension/size/stream/duration/resolution/FPS validation with ffprobe. Original file preserved. |
| Voice capture | **Verified local** | Real browser MediaRecorder capture with playback and permission-denied handling. |
| Voice transcription | **Verified live** (opt-in) / **Mock** default | Live Muse Voice Transcribe was exercised in LIVE-E2E 005 and 006, including cost and session id. Mock mode requires an explicit fixture and never interprets audio. |
| Transcript review | **Verified local** | Editable transcript, explicit confirmation; the worker never re-transcribes confirmed text. |
| Intent understanding | **Verified live** (opt-in) / **Mock** default | Both modes produce the same normalized v2 contract. Mock is deterministic. Live uses Muse Spark with registry validation. |
| Plan review | **Verified local** | Inline dialog shows interpreted intent, subject strategy, every dynamic operation, relevant parameters, capability source (MOCK/LOCAL/LIVE/PLANNED/UNAVAILABLE), approval requirements and verification checks. |
| Subject detection | **SAM 3.1 verified live once / Mock verified** | One real 2-subject clip produced 177/177-frame masks and previews; broader quality is not claimed. Mock mode remains two deterministic preview subjects. |
| Subject selection | **Verified local (live or mock detection)** | Stable object IDs, source-frame previews, single auto-select and explicit multi-select; selection is sent on approval. |
| Approval / rejection | **Verified local** | Backend-enforced atomic transitions. No render before approval; rejected plans are terminal. |
| Clarification | **Verified local** | Inline answer, original context preserved, maximum 3 rounds, revised plan re-enters review; no render before approval. |
| Unsupported requests | **Verified local** | Terminal `unsupported` state, named unavailable capability, no render. |
| Subject identification | **SAM 3.1 verified live once / Mock verified** | Mock: two synthetic ellipses. SAM: one real inference produced two distinct subjects. No identity recognition is performed. |
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
| Identify primary person | **SAM 3.1 verified live once / Mock verified** | Mock uses two ellipses. One real SAM request detected two people by a `"person"` prompt; broader quality is not claimed. |
| Segment / track person | **SAM 3.1 verified live once / Mock verified** | One real clip produced stable IDs, 177/177-frame sequences, previews and selection renders. Occlusion/720p quality remain unproven. |
| Keep selected people sharp | **Verified local with real and mock masks** | Selected per-object masks are unioned and rendered; real SAM masks drove three verified renders. |
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

## What Milestone 6D added

1. **Real SAM 3.1 API implementation.** `SamSegmentationProvider` uses the official
   Responses contract (`sam-3.1`, `input_video.file_id`, `stream=true`), the Files API
   (`purpose=user_data`, 1-hour expiration, delete in `finally`) and the official
   `meta-sam-parser==0.1.0`.
2. **Per-object masks and stable IDs.** SAM box-local rasters are converted to full-frame
   ADR-005 PNG sequences per object, with a union sequence. Object IDs, frame indices,
   dimensions, source hash, provider/model and completion status are preserved.
3. **Subject detection before review.** The worker detects subjects before
   `awaiting_approval`, persists per-object masks and source-frame previews, and still
   renders only after approval.
4. **Subject selection.** The plan dialog shows preview cards for each stable object id.
   One subject is preselected; multiple require an explicit choice. Approval carries
   `subject_ids` and the backend validates them.
5. **Renderer integration.** Selected per-object masks are unioned with bounded memory and
   consumed by the existing renderer. Audio, resolution and frame timing remain verified.
6. **Full-resolution validation.** 300-frame 1280×720 30 FPS 10 s clip with audio rendered
   at 1.74 FPS, peak 637.7 MB, 300 frames and AAC audio verified.
7. **Zero-detection handling.** A valid empty SAM result becomes a terminal
   `NoSubjectsDetected` job; no render occurs.
8. **External-processing consent.** Live SAM requires explicit, unchecked-by-default
   consent in the Studio before the voice request. The API persists a source-bound record
   (job, SHA-256, timestamp, disclosure version, provider, model, live mode), rejects
   missing/false consent before ready/worker/upload, and the worker/provider revalidate it.
   Plan approval is separate. Mock mode has no consent prompt.
9. **Scope honesty.** SAM live was validated once on a prepared clip (2026-11-01); broader
   quality, 720p/occlusion behavior and the overlaid-label mask artifact remain open.
   Selective person blur is not supported.

## Verified evidence

### Backend and rendering

- Full backend suite: **277 tests passed** in mock mode.
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
| Blur, desktop 1440×900 | Plan reviewed; two detected subjects shown with previews; Subject 0 selected; approved, rendered, downloaded; **5 dynamic operations**; MOCK label present. |
| Blur, mobile 390×844 | Same selection/approval flow; dialog usable at mobile width. |
| Background replacement | Subject selection required; export disabled before approval; rendered with a local/mock asset after approval. |
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
| **Real SAM inference validated once** | The provider/parser/mask pipeline completed one live request with 2 subjects; broader quality (720p, occlusion, overlaid-label holes) is not established. | **Validated on one prepared clip**; further quality tests pending. |
| **No Muse Image generation** | Replacement backgrounds are local/mock assets. The product must not claim generated imagery. | **Planned**, not implemented. |
| **No authentication / ownership** | API is local single-user. Any client that knows a job id can read/decide it. Acceptable for a local demo; not for deployment. | **Not implemented.** Must be addressed before multi-user or public hosting. |
| **No crash recovery mid-render** | A hard worker crash after claim can leave a job in `processing` with its claim lock. Clean restarts before claiming work fine; no automatic stale-lock recovery exists. | **Known limitation.** Manual verification required before removing a lock. |
| **Selective person blur unsupported** | The renderer can keep selected people sharp and blur/replace the background; it cannot blur chosen people while keeping the scene sharp. | **Not implemented; must not be advertised.** |
| **No frontend unit-test runner** | Behaviour is covered by backend tests, typecheck and browser E2E. | Tooling gap, not a product claim. |
| **Agent budget still constrained** | Live testing is capped by the ledger and needs explicit approval. | Intentional safety control. |
| **No multi-user/cloud/payments** | Out of MVP scope. | Out of scope. |

## Security and cost posture

- No credentials reach the browser; live providers require a server-side `MODEL_API_KEY`.
- Dev launchers force mock unless `CLIPFORGE_DEV_ALLOW_LIVE=1` is explicitly set.
- The live-call ledger is fail-closed, atomic and never automatically reset; direct live
  provider calls require a one-shot authorization.
- No live calls, SAM calls or Muse Image calls were made in Milestone 6C or 6D.
- Live SAM consent is explicit, source-bound and persisted; mock segmentation does not
  require or display it. A malicious local API client can still assert consent, since the
  app has no authentication model; the disclosure itself is a UI responsibility.
- The API does not expose provider credentials, raw provider payloads or internal audit
  secrets. `state_history` remains in `job.json`; the public job response does not expose it.

## Recommended next steps

1. **Run one controlled live SAM 3.1 validation** with explicit approval, a cost estimate,
   a ledger slot and a real clip; verify upload/privacy, stream parsing and cleanup live.
2. **Validate subject quality on real footage** (multiple people, occlusion, motion) before
   claiming person tracking.
3. **Then evaluate Muse Image** as a separate approved step; keep local/mock assets until
   its contract is verified.
4. **Consider selective person blur** only as a separately scoped renderer/operation
   feature; it is not supported today.
4. **Add authentication/ownership** before any deployment beyond localhost.
5. **Add stale-claim recovery** (with explicit operator validation) if the worker will run
   unattended.
6. Only then consider new editing capabilities (trim, captions, transitions) — none are in
   this MVP and none should be advertised yet.
