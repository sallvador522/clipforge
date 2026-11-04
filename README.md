# ClipForge

**Voice-first AI video editing studio — speak the edit, get a real MP4.**

Created by **António Salvador (Angola)**, with significant development assistance from
**Meta's Muse Wonder**. Product direction, concept and ownership belong to António Salvador;
Muse Wonder contributed to how the application was built, not to what runs inside it —
no runtime code path calls Muse Wonder.

Built for the **Meta Global Hackathon**. ClipForge is not a UI mockup: rendering is real
FFmpeg + OpenCV, outputs are verified with ffprobe, and live runs use Meta Muse models for
transcription and editing direction.

![ClipForge editor with a clip loaded, timeline populated and a voice instruction ready](docs/assets/clipforge-editor.png)

---

## Hackathon judges — start here

**You can run ClipForge on your own computer with your own Meta API key.** No deployment, no shared service.

```powershell
git clone https://github.com/sallvador522/clipforge.git
cd clipforge
powershell -ExecutionPolicy Bypass -File .\scripts\setup_judge.ps1
# paste your Meta API key into .env (MODEL_API_KEY=...), then:
powershell -ExecutionPolicy Bypass -File .\scripts\start_judge.ps1
# open http://localhost:3000 — stop everything with Ctrl+C
```

Full guide (requirements, macOS/Linux, costs, privacy, troubleshooting): [`docs/JUDGE_QUICKSTART.md`](docs/JUDGE_QUICKSTART.md).

Judge Mode enables all four live providers (Muse Voice, Muse Spark, SAM 3.1, Muse Image 1.0) explicitly and locally. Live calls bill **your own** Meta account; nothing is requested until you act in the Studio.

## Real-user testing — full live workflow, no mocks

The same stack, driven as a normal user: `scripts/real-user.env` activates the real
providers with no mock fallback. One command starts API + worker + Studio on 127.0.0.1,
then you upload, instruct, review the real plan, select real subjects, approve, optionally
generate a real background, and download the verified MP4:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_real_user.ps1
# open http://localhost:3000
```

Full walkthrough, per-model call rules, and limits: [`docs/REAL_USER_TESTING.md`](docs/REAL_USER_TESTING.md).
The per-job MODELS USED panel shows exactly which providers executed (LIVE) and which were
not called — status always comes from execution metadata, never from configuration.

---

## Why ClipForge

Video editing is powerful but slow to learn. Creators know what they want — “blur the
background and keep me sharp” — but translating that into tracks, masks, keyframes and
export settings is the hard part.

ClipForge turns a spoken instruction into a validated editing plan and a real rendered file:

1. Upload a short clip.
2. Record the edit by voice.
3. Review the transcript.
4. Review the Director's editing plan — subject, operations, parameters and what will change.
5. Select which detected people stay sharp.
6. Approve, reject, or answer a clarification.
7. ClipForge renders a verified MP4 and you download the result.

The MVP targets 10-second clips at up to 720p / 30 FPS.

---

## What works today

- Real voice capture in the browser and real transcription through **Meta Muse Voice
  Transcribe** when live mode is enabled.
- Editing direction through **Meta Muse Spark** (lite plan schema, Contributor model),
  validated against a capability registry before execution.
- **Plan review with explicit approval**: every plan shows what ClipForge understood,
  its dynamic operations, parameters and mock/local/live status. Nothing renders until you
  approve. You can reject or answer up to three inline clarification rounds.
- **Subject selection**: detected people appear as source-frame preview cards with stable
  SAM object IDs. Choose one or more to keep sharp before rendering.
- **Explicit SAM consent**: when segmentation is live, an unchecked Portuguese disclosure
  appears before the voice request. Declining sends nothing; authorizing persists a
  source-bound consent record. Plan approval is separate. Mock mode has no prompt.
- Real background blur and background replacement with **FFmpeg + OpenCV**.
- A real SAM 3.1 provider (official Responses/Files contract + `meta-sam-parser`), fully
  implemented, offline-validated and live-validated on one prepared clip on 2026-11-01;
  broader detection quality is not claimed.
- Original audio preserved; output verified for stream presence, resolution, frame count,
  duration and audio before download is allowed.
- A five-area editor workspace: Media, Viewer, Timeline, AI Assistant and Top Bar.
- A persistent worker, file-based job store, progress stages and explicit error states.
- A fail-closed live-call budget ledger and one-shot provider authorization, with no automatic retries.

One measured live end-to-end run: Portuguese audio → transcript → 5-operation Muse plan →
320×180 blur render → verified download. Details in
[`docs/LIVE_E2E_AUDIO_BLUR_REPORT.md`](docs/LIVE_E2E_AUDIO_BLUR_REPORT.md).

---

## Architecture

```text
Browser (Next.js / React)
        │ REST
        ▼
FastAPI API ──► JobStore (local files) ──► Persistent worker
        │                                      │
        │                                      ├─► Meta Muse providers (live, opt-in)
        │                                      ├─► Mock providers (default)
        │                                      └─► FFmpeg + OpenCV renderer
        ▼
Verified MP4 download
```

| Layer | Location | Responsibility |
|---|---|---|
| Web | `apps/web` | Next.js 15, React 19, Tailwind 4, Motion; editor workspace, voice capture and plan review |
| API | `apps/api` | Upload validation, transcription, jobs, plan review/approve/reject/clarify, subject previews, results, downloads |
| Worker | `apps/worker` | Job processing, subject detection gating, masks/selection union, FFmpeg/OpenCV renderer, output verification |
| Contracts | `packages/contracts` | EditingPlan, v2 director plan, capability registry, EDL, SAM mask metadata |
| Providers | `packages/providers` | Mock adapters, live Muse Voice Transcribe, SAM 3.1 provider/parser |
| Director | `packages/director` | Mock director, Muse Spark provider, canonical plan validation, per-call audit and live-call ledger |
| Jobs | `packages/jobs` | Shared job state machine, auditable transitions and atomic file store |

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Meta models

ClipForge coordinates specialized Meta models through a structured application:
models reason and perceive; the application validates, executes and renders.
No model output ever reaches the renderer unvalidated — every plan passes Pydantic
validation and the capability registry first.

| Purpose | Model | Receives → returns | Mode |
|---|---|---|---|
| Speech-to-text | `muse-voice-transcribe-1.0` | Browser audio (mono 16-bit WAV 24 kHz) → `{transcript, audioDurationMs, turns}` (`POST /v1/asr/transcribe`, `mode=PUSH_TO_TALK`, `languageBias=["Portuguese"]`) | Live, opt-in (`CLIPFORGE_TRANSCRIBE_MODE=live`) |
| Editing director | `muse-spark-1.3-contributor` (lite schema, medium reasoning, cap 16,000) | Transcript + video metadata → validated `ProfessionalEditingPlan` (5 ops: isolate → background → audio → render → verify) | Live, opt-in (`CLIPFORGE_DIRECTOR_MODE=live`) |
| Subject segmentation | `sam-3.1` (Responses + Files API, `meta-sam-parser`) | Temporary video-only copy (`purpose=user_data`, 1 h expiry) → per-object PNG mask sequences + manifest | Live-validated on one clip; opt-in (`CLIPFORGE_SEGMENTATION_MODE=live`) |
| Background generation | `muse-image-1.0` | Text-only prompt → PNG/Base64 plate, one per approved job (`POST /v1/images/generations`) | Implemented, opt-in (`CLIPFORGE_IMAGE_MODE=live`) |
| Chat rewrite | `muse-spark-1.3-contributor` (minimal reasoning, cap 600) | Conversation + project snapshot → reply text only; the deterministic router keeps deciding intent | Live, opt-in (`CLIPFORGE_CHAT_MODE=live`) |

Model output never contains file paths, shell commands or arbitrary parameters. Plans are
validated by Pydantic and the capability registry, then adapted to the worker's v1
execution contract.

```mermaid
flowchart TD
    U[User speaks or types in the Studio] --> S[ClipForge Studio]
    S --> D[Muse Spark Director]
    D --> T[Muse Voice Transcribe: audio to text]
    D --> SAMR[SAM 3.1: subject masks]
    D --> IMG[Muse Image: background plate]
    D --> OPS[Validated local tools: texts, colour, timeline, captions]
    T --> D
    SAMR --> C[FFmpeg/OpenCV compositor: foreground sharp, background replaced]
    IMG --> A[Project Asset Library]
    OPS --> P[Project and timeline state]
    A --> R[Scene renderer + Anime.js motion]
    P --> R
    R --> F[FFmpeg encode, original audio preserved]
    C --> F
    F --> MP4[Verified MP4, ffprobe-checked]
    MP4 --> V[Director review and download]
    V --> S
```

Every LIVE badge in the Studio derives from execution metadata, never from configuration.

---

## Real vs. mocked

| Area | Status |
|---|---|
| Transcription | **Real** Meta Muse Voice Transcribe when live; deterministic fixtures otherwise |
| Editing direction | **Real** Muse Spark when live; deterministic mock scenarios otherwise |
| Plan review / approval | **Real** backend-enforced gate; no render before approval |
| Subject detection | **SAM 3.1 live-validated on one clip**; mock mode uses two synthetic tracks |
| Subject selection | **Real local UI/backend** (live SAM or mock detection depending on mode) |
| Background replacement | **Muse Image when live**, local/mock asset otherwise |
| Rendering | **Real** FFmpeg decode/encode + OpenCV compositing |
| Audio | **Real** original audio preserved in the output |
| Output verification | **Real** ffprobe checks; download only after verification |
| Selective person blur | **Not implemented** |
| Future SAM 3.1 live validation | Pending explicit approval and cost estimate |

This distinction is deliberate: ClipForge never presents mock AI as a live model call.

## Capability status (verified 2026-11-04)

| Capability | Status | Evidence / limitation |
|---|---|---|
| Muse Spark direction + tool calling | IMPLEMENTED AND VERIFIED | Live plans + 10+ validated local tools executed after explicit confirmation; `test_clip_texts.py`, browser `qa-rescue` |
| Create from an Idea (20–60 s, 9:16) | IMPLEMENTED AND VERIFIED (mock); live storyboard live-validated once | Offline render pipeline 480/480 verified MP4; one live generation within the $1 cap (ADR-027) |
| Existing-video editing | IMPLEMENTED AND VERIFIED | Upload → plan → approve → render → verified download, browser-proven end to end |
| SAM 3.1 segmentation | IMPLEMENTED BUT PARTIALLY VERIFIED | Live-validated on clips (1–2 subjects, full-frame masks, verified renders); 720p/occlusion quality open |
| Muse Voice Transcribe | IMPLEMENTED AND VERIFIED | Live-validated (PT + EN turns); mock mode labelled, never interpreted |
| Muse Image generation | IMPLEMENTED BUT PARTIALLY VERIFIED | Live-validated once (1280×1920 plate composited with real masks); one image per approved job |
| Anime.js motion design | IMPLEMENTED AND VERIFIED | Scene engine + text choreography in preview and export (fade+rise in MP4) |
| Interactive multitrack timeline | IMPLEMENTED AND VERIFIED | V1/V2/A1/A2, move/trim/remove, zoom, seek sync, verified `Montar` compose |
| Properties Inspector + selection | IMPLEMENTED AND VERIFIED | Texts/colour/timing persisted, preview-synced, burned into export |
| Original + final MP4 downloads | IMPLEMENTED AND VERIFIED | Byte-identical originals (SHA-256 proven); ffprobe-verified finals |
| Magic Background | IMPLEMENTED AND VERIFIED | Mock programmatic + live-SAM compositions with original audio |
| Captions with real timing | IMPLEMENTED AND VERIFIED | Transcribe turns → timed lines → burned-in, verified on 19.6 s footage |
| Selective person blur | NOT IMPLEMENTED | — |
| Multi-user accounts | NOT IMPLEMENTED | Local single-user service by design for the demo |

---

## Quick start (mock mode, no credentials)

### Prerequisites

- Python 3.11+ (developed with 3.13)
- Node.js 20+ and npm
- FFmpeg and ffprobe available on `PATH`

### 1. Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,api,worker]"
```

Create the local configuration:

```powershell
Copy-Item .env.example .env
```

Mock mode is the default and needs no API key.

### 2. Run the stack

In separate terminals, from the repository root:

```powershell
python scripts/dev_api.py       # http://localhost:8000
python scripts/dev_worker.py    # persistent worker over storage/
```

### 3. Frontend

```powershell
cd apps/web
npm install
npm run dev                     # http://localhost:3000
```

The frontend defaults to `http://localhost:8000`. If the API runs elsewhere:

```powershell
$env:CLIPFORGE_API_PORT="8001"
$env:NEXT_PUBLIC_API_URL="http://localhost:8001"
```

`NEXT_PUBLIC_API_URL` is compiled into production builds, so set it before `npm run build`.

---

## Live mode (explicit opt-in)

Live calls are never enabled silently. Add to `.env` (gitignored, never committed):

```dotenv
CLIPFORGE_TRANSCRIBE_MODE=live
CLIPFORGE_DIRECTOR_MODE=live
CLIPFORGE_SEGMENTATION_MODE=live
MODEL_API_KEY=your_server_side_key
# Development launchers only honour the live flags above with this explicit opt-in:
CLIPFORGE_DEV_ALLOW_LIVE=1
```

SAM live is implemented but has **not** been validated against Meta. When enabled, the
Studio requires explicit, source-bound consent before the voice request; the API and worker
reject live segmentation without it. Do not enable live mode without a separate approval
and cost estimate.

Safety rails:

- `MODEL_API_KEY` stays server-side; it is never exposed to the browser.
- Dev launchers force transcription, the director and segmentation to mock unless
  `CLIPFORGE_DEV_ALLOW_LIVE=1` is set explicitly.
- Each function has a fail-closed file-backed ledger in `storage/live-call-ledger.json`.
  Defaults are 2 transcription + 2 director + 2 segmentation calls. Local testing can raise
  them with `CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT`, `CLIPFORGE_LIVE_DIRECTOR_LIMIT` and
  `CLIPFORGE_LIVE_SEGMENTATION_LIMIT`.
- SAM uploads use the Files API (`purpose=user_data`, 1-hour expiration) and are deleted in
  a `finally` block; no public video URL is used.
- A one-shot `LiveCallAuthorization` reserves immediately before the network request; no
  request is made when the cap is exhausted, the ledger is corrupt/unreadable, or the lock
  is held. Direct provider calls without authorization are rejected.
- No automatic retries of billable calls; a reservation is not released after an uncertain
  network outcome.
- Original uploads are preserved until a rendered output is verified.

`GET /health` reports the selected modes, configured limits and current usage.

---

## Tests and checks

From the repository root:

```powershell
.\scripts\check.ps1
```

The script runs the backend suite, the frontend typecheck and a production build. If
PowerShell blocks local scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Manual equivalent:

```powershell
pytest -q
cd apps/web
npm run typecheck
npm run build
```

Current backend suite: **513 tests passing** (run 2026-11-04). The frontend typecheck and production build
also pass. Browser E2E suites in `apps/web/scripts/` (`qa-final-e2e`, `qa-rescue`,
`qa-chat`, `qa-chat2`, `qa-magicbg`, `qa-ux-rescue`) run against an isolated mock stack
(API `:8001` + web `:3001`) with zero paid calls. No GitHub Actions or paid CI is required;
checks run locally.

Full-resolution SAM-compatible benchmark: `scripts/benchmark_sam_render.py` rendered 300
frames at 1280×720 / 30 FPS / 10 s with audio (1.74 FPS, 637.7 MB peak). It uses mock masks
and does not measure SAM detection quality.

---

## Project structure

```text
apps/
  api/          FastAPI endpoints and audio validation
  web/          Next.js editor workspace
  worker/       Job processor, masks, renderer, verification
packages/
  contracts/    Shared Pydantic contracts and capability registry
  providers/    Mock providers, live transcription adapter and SAM 3.1 provider/parser
  director/     Mock/live director, plan validation, ledger
  jobs/         Job state machine and atomic store
docs/           Architecture, API contracts, decisions, status, reports
scripts/        Dev launchers and controlled live-call/E2E scripts
tests/          Backend test suite
```

---

## Documentation

- [Product audit](docs/PRODUCT_AUDIT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API contracts](docs/API_CONTRACTS.md)
- [SAM 3.1 integration](docs/SAM_31_INTEGRATION.md)
- [SAM 3.1 live validation plan](docs/SAM_31_LIVE_VALIDATION_PLAN.md)
- [SAM 3.1 live test report](docs/SAM_31_LIVE_TEST_REPORT.md)
- [Decisions (ADRs)](docs/DECISIONS.md)
- [Status and handoff](docs/STATUS.md)
- [Tasks](docs/TASKS.md)
- [Live end-to-end report](docs/LIVE_E2E_AUDIO_BLUR_REPORT.md)
- [User-video live run](docs/LIVE_E2E_006_USER_VIDEO_REPORT.md)
- [Director hardening report](docs/LIVE_DIRECTOR_HARDENING_REPORT.md)
- [Live budget safety hardening](docs/LIVE_BUDGET_SAFETY_HARDENING.md)
- [Prepared plan-only test proposal](docs/LIVE_CALL_006_PROPOSAL.md)
- [Product spec](docs/PRODUCT_SPEC.md)

---

## Current limitations

- The SAM 3.1 provider, official parser, subject selection and mask pipeline are implemented,
  offline-validated and live-validated on one prepared clip (2026-11-01; see
  `docs/SAM_31_LIVE_TEST_REPORT.md`). Broader detection quality, 720p/occlusion behavior and
  the overlaid-label mask artifact remain open; mock mode uses synthetic ellipses.
- Selective person blur is not implemented. Background blur/replacement keeps selected
  subjects sharp and treats the rest of the frame.
- Background replacement uses Muse Image when live, otherwise a local/mock asset.
- There is no authentication/ownership model; the API is a local single-user service.
- A hard worker crash after claiming a job can leave it in `processing` with a claim lock;
  there is no automatic stale-lock recovery.
- The MVP is scoped to short clips (up to 10 s, 720p, 30 FPS).
- The system FFmpeg build is old; a newer build is recommended for production.

---

## Hackathon

Built for the **Meta Global Hackathon** around a real-use goal: let creators edit video by
speaking, while keeping the execution honest and verifiable. The project demonstrates
live Meta models, strict contracts, real media rendering and a mock-first development
discipline.

## Creator and acknowledgment

**Created by António Salvador — Angola.** Product direction, concept and project ownership
belong to António Salvador. ClipForge was built with substantial development assistance
from **Meta's Muse Wonder** — an AI-assisted approach combining human product direction
with advanced AI development tools. Muse Wonder is credited for development contribution;
it is not a runtime component of the product and is not its owner.

## License

MIT — see [LICENSE](LICENSE). Third-party notices are listed in
[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).
