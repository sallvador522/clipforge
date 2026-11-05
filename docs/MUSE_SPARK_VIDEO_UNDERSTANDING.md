# ClipForge — Muse Spark Video Understanding

Traceability: ADR-057. Status labels used below: VERIFIED (official docs read
2026-11-04), OBSERVED (seen in a real run), IMPLEMENTED (in the tree, tested
offline), PROPOSED (designed, not built), UNKNOWN (not yet established).

## 1. Existing Muse integration (IMPLEMENTED)

- Chat director: Chat Completions, `muse-spark-1.3-contributor`, structured
  plans, no tools sent (`packages/director/clipforge_director/spark.py`).
- Subtitle translation: Chat Completions plain text
  (`clipforge_providers/translation_spark.py`).
- SAM 3.1: Responses + Files API (`clipforge_providers/sam.py`).
- Muse Image 1.0: `POST /v1/images/generations`
  (`clipforge_providers/muse_image.py`).
- Voice: `POST /v1/asr/transcribe` (`muse-spark-1.3` ASR model is
  `muse-voice-transcribe-1.0` — voice understanding stays on this path).

## 2. Verified official API contract (VERIFIED)

Source: `dev.meta.ai/docs/{video-understanding,file-handling,pricing-rate-limits,tool-calling}`,
read 2026-11-04.

- Model `muse-spark-1.3` (Contributor: `muse-spark-1.3-contributor`), base
  `https://api.meta.ai/v1`.
- Responses analysis call: `POST /v1/responses` with
  `input=[{type: message, role: user,
  content: [{input_text}, {input_video|input_file, file_id|video_url}]}]`.
- Files: `POST /v1/files` multipart (`purpose=user_data`, optional
  `expires_after {anchor: created_at, seconds: 3600..2592000}`), `id` is
  `file-*`; `DELETE /v1/files/{file_id}`; inline ≤ 50 MB; upload ≤ 1 GiB;
  team storage 100 GiB, no auto-expiry by default.
- Pricing (Contributor): $0.10 / 1M input tokens, $0.20 / 1M output tokens.
  No per-video flat fee: video frames count as input tokens. Measured live:
  ~220 tokens/s at 360×640 (≈ 5000 input tokens for 19.6 s ≈ $0.0005).
- Tool calling exists on both endpoints (Responses `function_call` items +
  `previous_response_id`; Chat Completions `tool_calls` array; `tool_choice`
  must be `"auto"`; function names allow at most one dot). ClipForge tool
  names (`captions.create`, `text.update`) satisfy the naming rule.
- Spark 1.3 audio understanding is documented as not fully supported
  (examples fall back to 1.2). ClipForge therefore analyses a **video-only**
  copy; speech stays on the verified ASR endpoint, on demand only.

## 3. Supported video input methods (IMPLEMENTED)

- Files API upload + `input_file {file_id}` (used). Reused per asset
  version; validated by source SHA-256 before reuse.
- `input_video` with `file_id` — same reference, typed block (PROPOSED
  alternative; identical cost model).
- `video_url` public URL — rejected by design: never expose private media
  publicly to simplify integration.
- Inline base64 — rejected by design for analysis (50 MB cap, no reuse,
  huge prompts).

## 4. File upload architecture (IMPLEMENTED)

- `POST /api/projects/{pid}/assets/{aid}/analyze` (explicit
  `approved_cost_usd` ≥ $0.10 ceiling, else 409).
- Resolve asset → ffprobe → normalize to video-only MP4 (stream copy when
  H.264-family MP4/MOV, else libx264 transcode; dimensions/FPS/frames
  verified, audio stripped) → upload once → Responses call → persist.
- `GET .../analysis` returns the cached record, or 404/409 (stale).
- `DELETE asset` attempts remote `DELETE` best-effort (10 s, logged, never
  fails the local delete).
- Sidecars per asset: `provider_files.json` (reusable refs), `analysis.json`
  (the validated record). No AssetRecord schema change (extra="forbid").

## 5. Media normalization (IMPLEMENTED, offline)

- Accepted as-is: MP4/MOV with h264/hevc/mpeg4 video (stream copy).
- Everything else video: H.264 yuv420p + faststart transcode with
  frame-count/dimension verification; mismatch is a hard error.
- Limits enforced before upload: video-only, ≤ 1 GiB, ≤ 15 min source
  (MVP input caps); non-video assets rejected with 422.

## 6. Video-analysis data model (IMPLEMENTED)

`VideoAnalysis` (`clipforge_contracts/video_analysis.py`): ids, source
SHA-256, provider/model/response id, duration, `raw_text` (verbatim, always
kept), optional `overall_summary`, `subjects`, `objects_seen`, `moments[]`
(`at_s` nullable, `approximate: true` always), `composition_observations`,
`editing_opportunities`, `uncertainties`, usage + cost. The lenient section
parser never invents: unparseable lines are dropped, missing stays null,
lists are truncated to contract caps.

## 7. Director context integration (IMPLEMENTED)

- `build_chat_context` attaches `analysis_summary` (summary + moments +
  opportunities, ≤ asset version match) to each project asset.
- `context_for_prompt` renders it for live chat (mock label included).
- `answer_project_question`: analysis requests and content questions are
  answered from the cache; without cache the router points at the
  «Analisar vídeo» button instead of guessing or proposing execution.

## 8. Tool-calling integration (PROPOSED, deferred)

Docs-verified and compatible with the existing `tools.execute` dispatcher,
but deliberately not built yet: analysis feeds the existing director
(proposals + Executar with approval). A bounded multi-turn agentic loop is a
separate, explicitly approved follow-up.

## 9. Audio separation (IMPLEMENTED as policy + path)

Visual analysis always runs on the video-only copy. Transcription runs only
when the user asks about speech, via the verified ASR provider; timings, if
any, come from real ASR turns, never from the vision model.

## 10. Muse Voice Transcribe relationship (IMPLEMENTED elsewhere)

Unchanged. `POST /api/transcribe` + `captions.create_from_turns` remain the
only speech-timing source (ADR-049).

## 11. SAM 3.1 relationship (IMPLEMENTED elsewhere, boundaries kept)

- Spark understands and reasons; SAM segments; ClipForge renders.
- Spark never claims to create masks; SAM never reasons creatively.
- The analysis upload pipeline reuses the SAM Files-API pattern but keeps a
  separate ledger slot and separate file refs.

## 12. Frontend interaction (IMPLEMENTED)

- PropertiesPanel video-asset block: «Analisar vídeo» → inline confirm
  (sends-to-Meta disclosure + $0.10 ceiling) → «A analisar o vídeo…» (one
  honest busy state, no fake percentages) → rendered summary / moments /
  opportunities / uncertainties, or explicit error / stale states.
- Chat answers content questions from the cache; otherwise points at the
  button. No decorative states.

## 13. Loading, errors and cost control (IMPLEMENTED)

- One logical analysis = one ledger slot (`video_analysis`, default 2,
  advisory; override `CLIPFORGE_LIVE_VIDEO_LIMIT`). No retries, no auto
  re-upload on stale/invalid refs (explicit re-analysis instead).
- Failures are explicit codes: 404 project/asset/analysis, 422
  not-video/unusable, 409 cap-exceeded/source-changed/stale, 503
  not-configured/budget-integrity/locked/unauthorized, 429
  rate-limited/budget-exhausted, 504 timeout, 502 failed.
- The long sync endpoint runs the blocking provider calls in a worker
  thread (`anyio.to_thread.run_sync`) so chat stays responsive.

## 14. Security and retention (IMPLEMENTED)

- `MODEL_API_KEY` server-side only; browser never sees file IDs as
  capabilities (every id is re-validated against project + asset + sha).
- Per-asset file refs; re-upload on source change; remote delete on asset
  delete (best effort); temp analysis copies deleted after success and
  overwritten on retry; originals never modified.

## 15. Cost considerations (OBSERVED live 2026-11-04)

- Ledger counts are advisory; spend confirmed on the Meta billing panel
  before the first paid analysis (mission cap: $5 approved by the user).
- Live measurement, Facebook_2 (19.6 s, 360×640, 25 fps): 4993 input
  tokens + 1049 output tokens = **$0.000709** (≈ 220 video tokens/s at
  360p; the Files upload itself is unbilled). A failed first attempt
  (default high reasoning consumed the whole 1200-token cap, empty output,
  no retry) taught: `reasoning.effort: minimal` + cap 2000 are mandatory.
- A $0.10 per-analysis approval ceiling stays generous (typical short-clip
  analysis ≈ $0.001).

## 16. Test results (IMPLEMENTED + LIVE-VALIDATED, $0.0007 spent)

- `tests/test_video_analysis.py` (21 tests): section parser (lenient,
  no-invention, truncation), provider with MockTransport (upload once,
  usage + cost math, 429, invalid JSON, missing key, missing auth,
  no-retry assertion, reasoning-minimal payload), real-ffmpeg normalization
  (audio stripped, dimensions preserved; non-video rejected), endpoint mock
  flow (zero cost, no ledger touch, cached GET, approval gate 409,
  non-video 422, missing 404, stale-after-tamper 409, delete cleans
  sidecars), live path with mocked transport (upload-once-then-reuse,
  2 ledger slots, no-key 503).
- Full backend suite (553 passed) + `tsc` + `next build`: recorded in STATUS.md.
- Live TEST 1+2 (approved $0.10): upload + one Responses analysis of a
  real 19.6 s clip returned a correct visual description (split-screen
  adcopy.ai demo, presenter, yellow captions, Skool/webinar CTA);
  persisted, served via GET + chat; second analyze call reused the file
  (no re-upload).

## 17. Remaining limitations (KNOWN)

- Video input token counts now measured once (~220 tokens/s at 360p);
  other resolutions/durations are still estimates.
- Timestamps are approximate by contract; never frame-accurate.
- No identity inference, ever.
- No autonomous tool-calling loop yet (PROPOSED follow-up).
- Chat cannot start an analysis by itself; it points at the button
  (PROPOSED follow-up: Executar-card integration).
- Remote file cleanup on asset delete is best-effort only.
