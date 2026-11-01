# ClipForge Judge Quickstart

Run ClipForge on your own computer with your own Meta API key. No deployment, no shared service, no account needed beyond a Meta API key.

## 1. Requirements

- Windows 10/11 (PowerShell 5.1+), macOS, or Linux (bash)
- Python 3.11+ · Node.js 20+ (npm included) · FFmpeg + ffprobe on `PATH`
- A Meta API key (server-side only; never shared, never committed)
- Ports 8000 (API) and 3000 (Studio) free

## 2. Clone and install

```powershell
git clone https://github.com/sallvador522/clipforge.git
cd clipforge
powershell -ExecutionPolicy Bypass -File .\scripts\setup_judge.ps1
```

macOS/Linux: `bash scripts/setup_judge.sh`

Setup installs the Python venv + packages and `apps/web/node_modules` (skips what exists), creates `.env` from the template **without overwriting** an existing one, and makes no Meta API requests.

## 3. Add your API key

Paste **your own** Meta API key into `.env`:

```dotenv
MODEL_API_KEY=your_key_here
```

The key stays server-side: the browser bundle contains only `NEXT_PUBLIC_API_URL` (the local API address). Never commit `.env` (gitignored). Terminal output reports only whether the key is present, never its value.

## 4. Start in Judge Mode

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_judge.ps1
```

macOS/Linux: `bash scripts/start_judge.sh`

This applies `scripts/judge.env` (all four providers live: Muse Voice, Muse Spark, SAM 3.1, Muse Image 1.0), verifies the key, checks ports, and starts the API, worker, and Studio. Normal development stays mock — live is explicit to this script. **No live request is made at startup**; usage stays `0/0/0/0` until you act in the Studio.

Studio: **http://localhost:3000** · Stop everything with **Ctrl+C** in the startup terminal (the script kills its processes and frees both ports). If the terminal was closed instead, run `scripts/stop_judge.ps1` (or `scripts/stop_judge.sh`) — it also refuses to start over a still-running stack.

## 5. Supported video

MP4 / MOV / WebM / MKV · max 10 s · max 720p · max 30 FPS. Shown in the Studio upload panel; the API enforces it server-side and never modifies your original.

## 6. AI editing workflow

1. Upload a clip and preview it.
2. Speak (Mic) or type the instruction, then confirm. Typed text is never transcribed.
3. If SAM is live, an explicit consent dialog appears first (unchecked by default).
4. Review the Director plan (Muse Spark). Operations show LIVE / MOCK / LOCAL badges.
5. Select one or more detected people (real SAM previews), then approve.
6. Blur renders immediately; background replacement generates **one** Muse Image background after approval, then renders.
7. Compare before/after and download the verified MP4.

## 7. Cost and privacy warning

**Judge Mode bills YOUR Meta account.** Rough magnitudes only, not promises: voice/director are token-priced (fractions of a cent per run in past validations), SAM ≈ $0.20/1,000 detected frames, one image = flat $0.01. Check your Meta billing for actuals. A failed live call fails the job — it is never disguised as a mock result.

Privacy: everything runs locally except the data each model needs when you request it — audio for transcription, instruction text for planning, a temporary **video-only** copy for SAM (consent-gated, 1-hour expiry, deleted after), text prompt only for Muse Image. Uploads, masks, images and MP4s stay in local `storage/`. Delete them any time by removing `storage/jobs/*` (keep `storage/live-call-ledger.json`, the spend ledger, unless a new phase is explicitly approved).

## 8. Common errors

| Error | Fix |
|---|---|
| `MODEL_API_KEY is not set` | Paste your key into `.env`, retry. |
| `Port 8000/3000 is already in use` | Stop the other service or a previous run, retry. |
| `A ClipForge worker is already running` | Stop the duplicate worker first (two workers must never run). |
| `ModuleNotFoundError` / missing `node_modules` | Re-run the setup script. |
| `subject_detection_consent_required` (422) | SAM live needs the consent checkbox before voice submit. |
| `LiveBudgetExceeded` | The per-function cap was reached; raise `CLIPFORGE_LIVE_*_LIMIT` in `.env` only with approval. |
| `Backend unreachable` in Studio | API not running — start the stack first; check `storage/logs/judge-api*.log`. |
