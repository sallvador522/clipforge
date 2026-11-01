# ClipForge

**Voice-first AI video editing studio — speak the edit, get a real MP4.**

Built for the **Meta Global Hackathon**. ClipForge is not a UI mockup: rendering is real
FFmpeg + OpenCV, outputs are verified with ffprobe, and live runs use Meta Muse models for
transcription and editing direction.

![ClipForge editor with a clip loaded, timeline populated and a voice instruction ready](docs/assets/clipforge-editor.png)

---

## Why ClipForge

Video editing is powerful but slow to learn. Creators know what they want — “blur the
background and keep me sharp” — but translating that into tracks, masks, keyframes and
export settings is the hard part.

ClipForge turns a spoken instruction into a validated editing plan and a real rendered file:

1. Upload a short clip.
2. Record the edit by voice.
3. Review the transcript.
4. ClipForge plans the edit and renders a verified MP4.
5. Download the result.

The MVP targets 10-second clips at up to 720p / 30 FPS.

---

## What works today

- Real voice capture in the browser and real transcription through **Meta Muse Voice
  Transcribe** when live mode is enabled.
- Editing direction through **Meta Muse Spark** (lite plan schema, Contributor model),
  validated against a capability registry before execution.
- Real background blur and background replacement with **FFmpeg + OpenCV**.
- Original audio preserved; output verified for stream presence, resolution, frame count,
  duration and audio before download is allowed.
- A five-area editor workspace: Media, Viewer, Timeline, AI Assistant and Top Bar.
- A persistent worker, file-based job store, progress stages and explicit error states.
- A live-call budget ledger with no automatic retries.

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
| Web | `apps/web` | Next.js 15, React 19, Tailwind 4, Motion; editor workspace and voice capture |
| API | `apps/api` | Upload validation, transcription endpoint, jobs, results, downloads |
| Worker | `apps/worker` | Job processing, masks, FFmpeg/OpenCV renderer, output verification |
| Contracts | `packages/contracts` | EditingPlan, v2 director plan, capability registry, EDL |
| Providers | `packages/providers` | Mock adapters + live Muse Voice Transcribe |
| Director | `packages/director` | Mock director, Muse Spark provider, canonical plan validation, per-call audit and live-call ledger |
| Jobs | `packages/jobs` | Shared job state machine and atomic file store |

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Meta models

| Purpose | Model | Mode |
|---|---|---|
| Speech-to-text | `muse-voice-transcribe-1.0` | Live, opt-in (`CLIPFORGE_TRANSCRIBE_MODE=live`) |
| Editing director | `muse-spark-1.3-contributor` (lite schema, medium reasoning) | Live, opt-in (`CLIPFORGE_DIRECTOR_MODE=live`) |

Model output never contains file paths, shell commands or arbitrary parameters. Plans are
validated by Pydantic and the capability registry, then adapted to the worker's v1
execution contract.

---

## Real vs. mocked

| Area | Status |
|---|---|
| Transcription | **Real** Meta Muse Voice Transcribe when live; deterministic fixtures otherwise |
| Editing direction | **Real** Muse Spark when live; deterministic mock scenarios otherwise |
| Subject segmentation | **Mock** synthetic ellipse — **not SAM** and does not track a real person |
| Background replacement | **Local/mock assets** — **not Muse Image** |
| Rendering | **Real** FFmpeg decode/encode + OpenCV compositing |
| Audio | **Real** original audio preserved in the output |
| Output verification | **Real** ffprobe checks; download only after verification |
| Future SAM 3.1 | Planned, blocked on explicit approval |

This distinction is deliberate: ClipForge never presents mock AI as a live model call.

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
MODEL_API_KEY=your_server_side_key
```

Safety rails:

- `MODEL_API_KEY` stays server-side; it is never exposed to the browser.
- Each function has a file-backed call limit in `storage/live-call-ledger.json`.
  Defaults are 2 transcription + 2 director calls. Local testing can raise them with
  `CLIPFORGE_LIVE_TRANSCRIPTION_LIMIT` and `CLIPFORGE_LIVE_DIRECTOR_LIMIT`.
- A limit is reserved immediately before the network request; no request is made when the
  cap is exhausted.
- No automatic retries of billable calls.
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

Current backend suite: **211 tests passing**. The frontend typecheck and production build
also pass. No GitHub Actions or paid CI is required; checks run locally.

---

## Project structure

```text
apps/
  api/          FastAPI endpoints and audio validation
  web/          Next.js editor workspace
  worker/       Job processor, masks, renderer, verification
packages/
  contracts/    Shared Pydantic contracts and capability registry
  providers/    Mock providers and live transcription adapter
  director/     Mock/live director, plan validation, ledger
  jobs/         Job state machine and atomic store
docs/           Architecture, API contracts, decisions, status, reports
scripts/        Dev launchers and controlled live-call/E2E scripts
tests/          Backend test suite
```

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API contracts](docs/API_CONTRACTS.md)
- [Decisions (ADRs)](docs/DECISIONS.md)
- [Status and handoff](docs/STATUS.md)
- [Tasks](docs/TASKS.md)
- [Live end-to-end report](docs/LIVE_E2E_AUDIO_BLUR_REPORT.md)
- [User-video live run](docs/LIVE_E2E_006_USER_VIDEO_REPORT.md)
- [Director hardening report](docs/LIVE_DIRECTOR_HARDENING_REPORT.md)
- [Product spec](docs/PRODUCT_SPEC.md)

---

## Current limitations

- Subject segmentation is a mock synthetic ellipse; real person tracking requires SAM 3.1,
  which is not integrated yet.
- Background replacement uses local/mock assets, not Muse Image.
- Approval-required plans stop at `awaiting_approval`, but there is no approval/resume UI
  or endpoint yet.
- The MVP is scoped to short clips (up to 10 s, 720p, 30 FPS).
- The system FFmpeg build is old; a newer build is recommended for production.

---

## Hackathon

Built for the **Meta Global Hackathon** around a real-use goal: let creators edit video by
speaking, while keeping the execution honest and verifiable. The project demonstrates
live Meta models, strict contracts, real media rendering and a mock-first development
discipline.

## License

MIT — see [LICENSE](LICENSE). Third-party notices are listed in
[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).
