---
name: clipforge-meta-api
description: Governs all Meta AI integrations (transcription, SAM 3.1 segmentation, reasoning/planning, image generation). Use before touching packages/providers, the transcription endpoint, or discussing live Meta API calls.
---

# ClipForge Meta API Rules

- Mock by default (ADR-004): `CLIPFORGE_AI_MODE=mock`. Only **transcription** can run live, via the explicit scoped switch `CLIPFORGE_TRANSCRIBE_MODE=live` + server-side `MODEL_API_KEY` (ADR-008). Planning, SAM and image generation remain mock, except the prepared-but-unwired `MetaEditingDirectorProvider` (ADR-011/ADR-012; LIVE-CALL 001 approved for exactly one Contributor-Medium plan-generation POST, no execution). Never enable live mode silently or automatically.
- Budget protection: remaining budget ~$30. Muse Voice Transcribe costs **$0.18 per audio hour, billed per whole second** (5 s ≈ $0.00025). The first live call requires a reviewed cost estimate and explicit user approval. No automatic retries that could create billable calls — retry only on an explicit user action.
- Verified transcription contract (official docs, Milestone 6A): model `muse-voice-transcribe-1.0`, `POST https://api.meta.ai/v1/asr/transcribe?sessionId=…`, Bearer auth, multipart `request` JSON (`model`, `audioEncoding: "WAV"`, `mode: "PUSH_TO_TALK"`, `languageBias: ["Portuguese"]`) + `audio` mono 16-bit PCM WAV at 16/24 kHz, JSON response `{sessionId, transcript, audioDurationMs, turns}`; caps 32 MB / 10 min; errors 400/406/413/429/500; 429 is not billed.
- Do not assume schemas for the other providers (SAM, planning, image generation); they remain placeholders until their docs are verified.
- Server-side only: never expose `MODEL_API_KEY` to the browser; never log the key or raw audio. Log `sessionId`, duration and outcome only. Use temporary storage and delete converted audio after each request.
- Normalize into ClipForge contracts; never invent fields (e.g. no confidence score if the response has none). The confirmed transcript is what reaches the planner — no re-transcription in the worker.
- Requests carry timeouts; 429/5xx/timeouts surface as explicit safe errors. No retry loops.
