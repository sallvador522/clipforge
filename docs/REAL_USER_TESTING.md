# ClipForge Real-User Testing

Use ClipForge exactly as a normal user would: real providers end to end, no mocks, no fallbacks. You perform the paid workflow manually in the Studio; nothing here consumes credits by itself.

## 1. Configure the existing API key

One credential funds all four live providers: the server-side `MODEL_API_KEY` in the
gitignored `.env` at the repository root.

```dotenv
MODEL_API_KEY=your_key_here
```

Rules: never print, expose, commit or overwrite it. It never reaches the browser (the only `NEXT_PUBLIC_` variable is the local API URL). Factory startup raises a clear error when live mode is requested without a key — there is no silent mock fallback.

## 2. Activate REAL USER mode

`scripts/real-user.env` explicitly enables the existing providers — no new variables:

```dotenv
CLIPFORGE_TRANSCRIBE_MODE=live
CLIPFORGE_DIRECTOR_MODE=live
CLIPFORGE_SEGMENTATION_MODE=live
CLIPFORGE_IMAGE_MODE=live
CLIPFORGE_DEV_ALLOW_LIVE=1
```

MOCK stays the default everywhere else (dev launchers, automated tests). REAL USER mode never makes MOCK the default: without the key, startup refuses to launch.

## 3. Start the complete application

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_real_user.ps1
# macOS/Linux: bash scripts/start_real_user.sh
```

This verifies the key (presence only), checks ports 8000/3000, refuses duplicate workers, and starts the API + worker + Studio on 127.0.0.1. No model request happens at startup (only local `/health` polls). Studio: **http://localhost:3000**. Stop with Ctrl+C, or `scripts/stop_real_user.ps1` if the terminal was closed.

## 4. Use the Studio normally

1. Upload your MP4/MOV (≤10 s, ≤720p, ≤30 FPS) and preview it. The original is preserved untouched.
2. Speak or type the instruction. Typed text goes straight to the Director — transcription is never called.
3. The real Muse Spark plan appears for review: interpretation, operations, warnings, per-capability LIVE/MOCK badges.
4. For SAM, consent explicitly in the dialog, then select one or more real subjects (stable object IDs, 177-frame-style coverage shown per card).
5. Approve. Nothing renders or generates before approval. Blur-only jobs never touch Muse Image.
6. If the approved plan replaces the background, exactly one Muse Image generation runs, then the real FFmpeg/OpenCV render composites the real SAM masks over it with your original audio.
7. Compare before/after, check the per-job MODELS USED panel (execution record, never config), and download the verified MP4.

## 5. Which operations invoke each model

- **Muse Voice** — only the Mic transcribe button. Typed instructions skip it.
- **Muse Spark** — every confirmed instruction produces one validated plan. No re-runs, no prompt rewriting.
- **SAM 3.1** — after consent, one segmentation per job. Video-only copy, 1-hour expiry, deleted after.
- **Muse Image 1.0** — only for approved `replace_background` plans, exactly once per job, text prompt only.
- **FFmpeg/OpenCV** — all compositing, audio muxing and verification, local and free.

Failures stay visible: failed jobs show the real error code, never a fake success; ledger caps refuse new calls instead of retrying.

## 6. Stop the services

Ctrl+C in the startup terminal, or `scripts/stop_real_user.ps1` (`stop_real_user.sh` on macOS/Linux). Both ports are verified free afterwards.

## 7. Known limitations

- Live runs bill your Meta account (rough magnitudes: voice/director fractions of a cent per run; SAM ≈ $0.20/1,000 frames; one image flat $0.01 — confirm in Meta billing). Current ledger: transcription 4, director 3, segmentation 1, image 1.
- **Observed 2026-11-01:** an external Studio session consumed one transcription + one director call; the live Director returned `strategy: "mock-segmentation"`, which the validator correctly rejected (`DirectorValidationError`, job failed, no render, no SAM/image calls). Fail-closed behavior worked as designed. If you see this, retry with a shorter, clearer instruction.
- Overlaid on-video graphics (stickers, captions) fall outside person masks and may show background through them; source meme text outside masks is replaced by design.
- The 1280×1920 plate is direct-stretched to 9:16 (~15.6% squeeze); the v2 center-crop variant (`luanda_sunset_demo_v2.mp4`) removes it.
- No occlusion/720p stress test yet; single-user local service, no authentication.
