# ClipForge — Hackathon Demo Guide (10 minutes)

Setup first: follow [`docs/JUDGE_QUICKSTART.md`](JUDGE_QUICKSTART.md) (clone → setup script → your own `MODEL_API_KEY` → `start_judge.ps1` → http://localhost:3000). Judge Mode bills **your** Meta account and makes no request until you act.

## The journey
1. **Upload (1 min).** Drop a ≤10 s MP4. Observe: real progress, session card, timeline filmstrip + waveform appear.
2. **Instruct (1 min).** Type or speak: "Desfoca o fundo e mantém-me nítido." Observe: transcript confirmation, nothing renders yet.
3. **Consent (30 s).** The SAM dialog appears unchecked. Decline once to show nothing happens; authorize to continue. Consent is source-bound and logged.
4. **Plan review (2 min).** Muse Spark's plan shows operations, parameters and LIVE/LOCAL badges. Ask the room: approve, reject, or answer the clarification.
5. **Subject selection (1 min).** Real SAM preview cards with stable IDs. Pick the subject.
6. **Render + verify (2 min).** Watch truthful stages (planning → rendering → verifying). Before/after compare.
7. **Download (1 min).** MP4 + original download. Re-probe with ffprobe if challenged: h264 + aac, correct duration.
8. **Director tools (1 min).** Add a text overlay, ask Muse in Portuguese to change it, confirm the tool call, re-render.

## Fallback (no key / no network)
Run the mock stack (`scripts/dev_api.py`, `scripts/dev_worker.py`, `npm run dev` in `apps/web`): the full journey works with labelled mock AI and real rendering — $0.00, same Studio, same verified MP4s.

## If something fails live
A failed live call fails the job visibly — never a fake success. Check `scripts/stop_judge.ps1` for port conflicts, `storage/logs/judge-api*.log`, and the error table in `JUDGE_QUICKSTART.md`. Fall back to mock mode rather than retrying billable calls.
