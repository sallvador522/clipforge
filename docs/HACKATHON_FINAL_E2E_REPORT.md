# ClipForge — Final Hackathon E2E Report (`final-e2e-rescue`, 2026-11-04)

Classification key: **LIVE E2E** real app+backend · **LIVE META** real Meta call · **LOCAL MEDIA** real FFmpeg/OpenCV · **UNIT** isolated logic · **NOT EXECUTED** · **BLOCKED**.

## A. Application overview
Tested from first visit (empty Studio) through project creation, UI upload, asset registration/selection/download, reload persistence, text/Properties editing, Muse tool proposals with explicit confirmation, multitrack Montar, final export download, director interview, captions/cover tools and Magic Background — against the real Next.js Studio + FastAPI + persistent worker + FFmpeg/OpenCV, in forced-mock AI mode on isolated stacks (API :8001/:8003/:8004, web :3001/:3003/:3004, storage `storage/_e2e_final*`, removed after the run). Zero paid calls.

## B. User journey results (LIVE E2E, `apps/web/scripts/qa-final-e2e.mjs` — PASS, 0 console errors)
- A1 first visit: app loads, empty state + creation entry visible.
- A2 UI upload of `meu vídeo (teste).mp4` (spaces/accents/parentheses): job + project (`prj_…`) created, session card shows the file.
- A3 **original download**: new download action on the session card and on every library row; downloaded bytes **SHA-256 identical** to the uploaded file (208,533 bytes), suggested filename preserved with accents.
- A4 invalid upload: `.exe` rejected **422 `unsupported_extension`**, no asset record created.
- A5 reload: project + asset persist (backend `ProjectStore`, not only local state).
- A6 timeline zoom 1 → 1.25 functional.
- A7 Montar: real compose → `completed`, `render_status=verified`.
- A8 Exportar: final MP4 downloaded and ffprobe-validated (h264 + aac, 5.0 s).

Scenario B (director creates): interview → proposal → Executar → idea with options — **LIVE E2E PASS** (`qa-chat.mjs`, `qa-chat2.mjs`: style/duration/format chips, idea created with `documentary · 30s · 9:16`). Full storyboard render not re-run this mission (worker render path proven by MagicBG + idea pipeline tests).
Scenario C (edit existing): **LIVE E2E PASS** (`qa-rescue.mjs`: text edit + colour grade + Muse `text.update` + Montar verified).
Scenario D (direct editor): **LIVE E2E PASS** (select/deselect/reselect, Properties, inline edit, drag state, T1 sync — `qa-rescue.mjs`).
Scenario E (voice): **NOT EXECUTED** in a browser (headless has no microphone; hardware-mic coverage pre-exists from milestone 5.2). Voice→transcribe→chat path is code-covered by UNIT tests.
Scenario F (failures): invalid upload (above), ambiguity clarification (UNIT `test_clip_texts.py`), edit-window 409s (UNIT), unsupported capabilities named (UNIT/chat). Network-interruption and expired-access cases: **NOT EXECUTED**.

## C. Left panel
Project/Assets (Recursos): import (multi-file), filters/search (pre-existing), selection drives Properties + preview, two-step remove, generated-asset badge. **Fixed this mission (P1): no download action existed** — the session clip's asset row is hidden by dedupe and library rows had no download either. Added real download anchors (`GET /api/projects/{id}/assets/{id}/file`, `Content-Disposition` filename) on the session card and every row; integrity proven in A3. Empty state honest; upload progress is real XHR progress; errors surface in-panel.

## D. Properties and editing
Text overlays are real project data (`PUT/GET /texts`, `/colour`): content, style, size/scale, weight, 8 colours, position (drag + numeric), timing (Properties + T1 drag/trim) persist on the JobRecord, update preview/T1/Properties from one state, and burn into the Montar MP4 (pixel-verified in prior rescue; re-verified by `test_texts_render_e2e.py` UNIT/LOCAL MEDIA). Colour contrast/brightness/saturation is a real per-frame grade with explicit Aplicar. SVG/shape/image overlay selection: no such overlay model exists — **not faked, declared limitation** (library assets place on V1/V2/A1/A2 only).

## E. Muse Director
Deterministic router + 10+ validated tools (`project.inspect, job.status, texts.list/get, text.create/update/delete, colour.get/set, timeline.inspect, captions.create/create_from_turns/cover/translate`) execute for real after the `Posso executar?` confirmation (Executar/Ajustar/Cancelar). Proven LIVE E2E: `text.update`, `captions.create` (exactly one `/tools/execute`), `captions.cover` persisted, translate proposal shows price and does not execute in mock. Ambiguity rule: several texts + “aquele texto” → clarification, never a silent pick (UNIT). Sequential edits work (colour after text in deliverable 2). **LIVE META Muse Spark reasoning: NOT EXECUTED this mission** (no per-call cost approval; AGENTS rule 5). Previously live-validated historically (LIVE-E2E 005/006, chat ADR-053/054).

## F. Timeline
Real multitrack (ADR-044): drag assets to V1/V2/A1/A2, move/trim/remove blocks, adaptive ruler, zoom 0.75–3×, playhead/seek sync, T1 text lane mirroring overlays, scene strip for ideas, `Montar` composes with FFmpeg/OpenCV (z-order, audio mix) and verifies. Export timing: qa-final A7/A8 (5.0 s in = 5.0 s out). Split at playhead for idea scenes (ADR-039, UNIT); clip-track split is **not supported** and not advertised. Waveform/filmstrip: real WebAudio peaks + captured thumbnails (pre-existing browser proof).

## G. Meta integrations
| Model | This mission | Historical |
|---|---|---|
| Muse Spark (director/chat) | NOT EXECUTED ($0.00) | live-validated (plans, refinement, translation) |
| SAM 3.1 | NOT EXECUTED ($0.00); mock flow LIVE E2E PASS (`qa-magicbg.mjs`: proposal → subject selection → approve → verified MP4, 617,760 downloaded bytes) | live-validated (2 subjects, $0.025/$0.098 runs) |
| Muse Voice Transcribe | NOT EXECUTED | live-validated ($0.000184–$0.00190 runs) |
| Muse Image | NOT EXECUTED | live-validated once (1280×1920 PNG) |
No request IDs this mission — no Meta request was made.

## H. Loading, errors and UX — defects found & fixed
1. **P1 — No original-asset download** (session card + library rows). Fixed; SHA-256 proof.
2. **P2 — `qa-chat.mjs` stale** after the ADR-048 interview: updated to answer chips; PASS.
3. Test-harness findings (not product bugs): stale `.next` server after rebuild (chunk 400) — restart required; QA proxies must forward `Content-Disposition` and set `CLIP_PATH` for attach rebuilds. Both documented in the scripts' behaviour.
4. Honestly-disabled rail slots (Áudio/Efeitos/Transições/Legendas/Ajustes) stay `disabled` with “ainda não disponível” — no fake panels. No fake percentages; progress is real XHR/worker state.

## I. Download and export — outputs in `C:\Users\New User\Videos\Video`
- `ClipForge_E2E_PropertiesEditing.mp4` — 1,117,991 B, 6.0 s, 1280×720 h264+aac (texts + grade, LOCAL MEDIA).
- `ClipForge_E2E_ExistingVideoEdit.mp4` — 1,177,154 B, 6.0 s, 1280×720 h264+aac (Muse tool edit + re-render).
- `ClipForge_E2E_Timeline.mp4` — 196,036 B, 5.0 s, 320×180 h264+aac (source-format Montar from the browser E2E job).
- Magic Background deliverables from earlier today remain (`ClipForge_MagicBackground_*`, incl. live-SAM). Sources are FFmpeg synthetic clips, labelled as such — pipeline proof, not camera footage.

## J. Tests
- Backend: **509 passed** (`pytest -q`, 134 s); targeted re-run 36 passed (workspace/texts/chat/timeline).
- Frontend: `tsc --noEmit` clean; production `next build` clean (route `/` 97.9 kB).
- Browser (real Chrome, 1440×900, all zero console errors): `qa-final-e2e.mjs` PASS (A1–A8), `qa-rescue.mjs` PASS, `qa-chat.mjs` PASS, `qa-chat2.mjs` PASS (with `CLIP_PATH`), `qa-magicbg.mjs` PASS. Other viewports: pre-existing `qa-editor.mjs` matrix; not re-run this mission.

## K. API usage (cumulative mission budget $5.00)
Existing ledger on entry (not reset): `transcription 24 · director 27 · segmentation 8 · image 16 · chat 17` (advisory meter, ADR-022). This mission: **0 calls, $0.00 spent**; ledger byte-identical on exit.
| Model | Purpose | Calls | Est. | Actual |
|---|---|---:|---:|---:|
| Muse Spark | — | 0 | $0 | $0 |
| SAM 3.1 | — | 0 | $0 | $0 |
| Muse Voice Transcribe | — | 0 | $0 | $0 |
| Muse Image | — | 0 | $0 | $0 |
| **Total this mission** | | **0** | | **$0.00 / $5.00** |

## L. Remaining defects
- P0/P1: none known open.
- P2: live Meta reasoning not re-verified this mission (policy, not a defect); voice browser flow not re-run (no mic in headless); network-interruption/expired-access failure cases not executed.
- P3: full viewport matrix not re-run for newest panels; SVG/shape overlay model absent (declared, not faked).

## M. Final readiness verdict
**READY WITH LIMITATIONS.** A judge can open the app, create a project implicitly by uploading, find/select/download the original (byte-identical), edit text and colour with real persistence, ask Muse (mock router in demo mode) to execute validated tools after confirmation, use the timeline and Montar, and download a verified MP4 reflecting the edits — all proven this mission with real browser + backend + FFmpeg evidence and zero paid spend. Limitations: live Meta models are historically validated but were not re-executed (no per-call approval), and voice control was not browser-tested this mission.
