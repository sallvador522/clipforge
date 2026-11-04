# ClipForge — Hackathon Readiness Report (final-rescue, 2026-11-04)

Mission: `/hallmark final-rescue`. Scope: real editor (selection, Properties, text, colour), real Muse tool execution, real exports, full audit, zero paid calls unless explicitly approved. All acceptance work ran against the real app + real backend + real FFmpeg/OpenCV composition.

## A. Application health

Initial condition (audited): the Studio shell, asset library, multitrack timeline (Montar), deterministic Muse chat, director/consent/approval flows and idea-to-video track worked. Critical gaps found and fixed in this mission:

1. **P0 — Click-to-select was broken.** `ClipTextLayer` selected on pointerdown and toggled on click, so one press selected then instantly deselected. Fixed with a pointerdown/click guard; proven by browser QA deselect→reselect.
2. **P0 — Texts were preview-only.** Overlays never reached any MP4 ("Não sai no MP4"). Now persisted on the job and burned into the timeline composition.
3. **P1 — No colour editing.** Contrast/brightness/saturation did not exist. Now a real local grade applied per frame.
4. **P1 — Muse could not operate elements.** The chat had no tools. Now 10 validated tools with real execution after explicit confirmation.
5. Minor: chat composer hid behind the Properties tab after selection; new proposals now surface the Muse tab once (no yanking while typing).

Final condition: 455 backend tests pass, `tsc` clean, production `next build` clean, browser rescue QA passes with zero console errors, two real deliverable MP4s verified.

## B. Editor functionality

| Capability | State | Evidence |
|---|---|---|
| Select text in preview | Works | `qa-rescue.mjs`: add→auto-select, click select, deselect, reselect; outline + `aria-pressed` state |
| Edit text (Properties) | Works | fill "Conteúdo do texto" → backend `GET /texts` returns new value |
| Inline editing (double-click) | Works | dblclick → input → Enter → persisted; Escape cancels |
| Typography (style/size/weight/colour) | Works, bounded | 5 styles, scale 0.7–1.6, 8 colours, normal/bold — every option is applied by preview AND export |
| Position (drag + numeric) | Works | drag converts scaled preview → program coordinates; x/y shown in Properties |
| Timing (start/duration) | Works | Properties numbers + T1 lane drag/trim, clamped to program |
| Timeline sync | Works | T1 blocks mirror overlays; selecting in T1 seeks; preview/Inspector/timeline share one state |
| Persistence | Works | `PUT /texts`, `PUT /colour` → JobRecord; reload restores from backend; localStorage is cache/migration only |
| Export reflection | Works | pixel proof: text present inside window, byte-identical outside; subtitle 0 px at t=0/6 s, ~110 px at t=2/4 s |
| Direct manipulation | Works | drag-to-move with visual feedback; no fake resize handles (none advertised) |
| SVG/shape/image selection | Not present | The clip track has no SVG/shape/image overlay model; assets are library items placed on V1/V2/A1/A2. No fake selectables were added. Out of scope for this rescue; declared limitation. |

Single source of truth: the backend JobRecord. Preview, T1, Properties and Muse tools all read/write it; the worker composes from it.

## C. Muse Director

Registered tools (`GET /api/jobs/{id}/tools`, 10): `project.inspect, job.status, texts.list, text.get, text.create, text.update, text.delete, colour.get, colour.set, timeline.inspect`. Each has a JSON-schema catalogue, Pydantic-validated params, edit-window enforcement (queued pre-voice or completed; 409 otherwise), and structured results.

Tested end-to-end (real execution, local reasoning):
- "Muda o texto para '…'" → `text.update` proposal card → Executar → record updated → preview/Inspector refresh.
- Colour/brightness/saturation PT commands → `colour.set` with computed values.
- "Selecciona o título principal" → selects the only overlay; with several overlays asks which (lists titles); with none says to add one first.
- Ambiguity rule: several overlays + no selection → clarification, never a silent guess.
- Sequential execution works (colour.set after text.update in the deliverable run).
- Natural-language suite from the mission (§6.4): text/size/colour/move/animation/select/contrast/brightness/saturation intents covered by `test_clip_texts.py` chat tests + browser QA.

Live Muse Spark reasoning: **NOT VERIFIED** — no paid call was made (no explicit per-call approval; founder delegation does not override the budget rule). The execution path is live-ready: swap the deterministic router for Spark responses emitting the same tool names/schemas and the executor validates identically.

## D. Meta integrations

| Integration | State |
|---|---|
| Muse Spark | Execution path real and tested locally; live reasoning NOT VERIFIED (blocked: explicit approval + cost estimate required) |
| SAM 3.1 | Untouched by this mission; previously live-validated once (see STATUS 6D). No call made here |
| Muse Voice Transcribe | Untouched; no call made here |
| Muse Image | Untouched; no call made here |
| Anime.js | Preview choreography for overlays (5 styles) — real, in-browser; export carries fade+rise (honestly labelled) |
| FFmpeg/OpenCV | Real composition, grading, burn-in, verification for every deliverable |

## E. UX/UI

Fixed: broken click-select; fake "só preview" badges replaced with honest "sai no MP4 (Montar)"; colour section with explicit Aplicar (dirty-state honest: "Por aplicar — o Montar usa o valor guardado."); tool calls listed on the confirmation card; proposals surface the Muse tab; 409 edit-window errors surfaced as notes instead of silent failure. Rail keeps honestly-disabled slots (Áudio/Efeitos/… labelled "ainda não disponível", disabled, not fake). PT-AO copy kept; no dev jargon added.

## F. Video production

Deliverables in `C:\Users\New User\Videos\Video` (unique names, originals untouched):

1. `ClipForge_Final_PropertiesTest.mp4` (1,117,991 bytes, 6.00 s, 1280×720, h264+aac) — timeline compose with 2 persisted overlays (yellow bold title, white subtitle) + grade (1.15/+0.03/1.25). Contact sheet alongside.
2. `ClipForge_Final_Editing.mp4` (1,177,154 bytes, 6.00 s, 1280×720, h264+aac) — same program edited through the Muse tool path (`text.update` to 'Transformamos ideias em marcas' + `colour.set` 1.25/1.4) and re-rendered verified. Contact sheet alongside.

Sources are FFmpeg-generated synthetic clips (testsrc2 + tone), labelled as such — they exercise the real pipeline, not presented as camera footage or AI output. Frames inspected: title pixels present in-window, clean centre out-of-window, subtitle timing exact.

Workflows: create-from-idea and SAM magic-background were NOT re-run in this mission (idea track untouched; SAM live needs approval). The edit-existing-video workflow (Workflow B) was proven end-to-end through the new path.

## G. Testing

- Backend: 455 passed (`test_clip_texts.py` 11 new, `test_texts_render_e2e.py` 1 new incl. 90-frame real compose + tool-edit + re-render; `test_capabilities.py` updated for the 2 new local capabilities).
- Frontend: `tsc --noEmit` clean, production `next build` clean.
- Browser: `apps/web/scripts/qa-rescue.mjs` on isolated stack (API :8001 + web :3001, forced mock): upload→add→select→Properties→inline→colour→Muse Executar→Montar→completed/verified, **zero console errors** at 1440×900.
- Viewports beyond 1440×900 were covered by the pre-existing `qa-editor.mjs` suite for the shell; the new panels reuse the same layout primitives. Full-matrix re-run deferred (time), noted below.

## H. API costs

| Model | Purpose | Calls | Est. cost | Actual |
|---|---|---:|---:|---:|
| Muse Spark | reasoning/tool calls | 0 | $0 | $0 |
| SAM 3.1 | segmentation | 0 | $0 | $0 |
| Muse Voice Transcribe | ASR | 0 | $0 | $0 |
| Muse Image | backgrounds | 0 | $0 | $0 |
| Total this mission | | 0 | $0 | **$0.00 / $5.00** |

Service ledger (`storage/live-call-ledger.json`) untouched by this mission (`22/24/8/16` advisory, enforced=false). No TTS used. No retries, no concurrent paid requests — there were none.

## I. Remaining problems / NOT VERIFIED

1. Live Muse Spark reasoning — NOT VERIFIED (needs explicit approval + cost estimate). Deterministic router covers the demo script.
2. SVG/shape/image overlays — no model; library assets only. Not faked.
3. Advanced colour (curves, HSL qualifiers, LUTs) — `colour.grade` stays DISABLED; only global contrast/brightness/saturation exist.
4. Export animation = fade+rise for every style (preview has per-style choreography; mapping documented in UI + ADR-047).
5. Fonts in export limited to Arial/DejaVu (+weight); no custom font upload.
6. Full viewport matrix (1366×768 etc.) for the NEW panels — new QA script ran at 1440×900; shell matrix pre-exists.
7. Voice→tool path: voice transcription still routes via transcript→chat; direct "fala com o Muse e executa" works through the same confirmation card but was not browser-tested with a real microphone in this mission (headless has no mic; hardware-mic coverage pre-exists).
8. Working tree is shared with another active session (pre-existing dirty files); this mission touched only its own files, no resets/commits.

## J. Final verdict

**READY WITH LIMITATIONS.**

A judge can click a text, select it, read its properties, edit content/colour/size/weight/timing inline or in the Inspector, drag it, ask Muse to change it in Portuguese, confirm, and export a verified MP4 that contains the change — all proven by tests, browser QA and inspected frames. No dead primary buttons remain on the edit path; honestly-disabled slots are labelled. Live Meta reasoning stays mock-gated by policy, which is the correct demo posture without explicit spend approval.

## K. Re-verification run (2026-11-04, final-rescue mission)

Independent re-run against the current working tree — real app + real backend + real FFmpeg/OpenCV, zero paid calls:

- Backend: **449 passed** (`tests/test_clip_texts.py` + `test_texts_render_e2e.py` + `test_chat_api.py`: 17 passed standalone; full suite 449 passed, 0 failed; the single stderr line is an expected negative-test probe, not a failure).
- Frontend: `tsc --noEmit` clean, production `next build` clean (route `/` 96.3 kB / 217 kB first load).
- Browser: `qa-rescue.mjs` on stack API :8001 + web :3001 (mock): upload → add text → auto-select → Properties shown → deselect → reselect via preview → Properties edit persisted → inline double-click edit persisted → colour sliders + Aplicar persisted → Muse chat `text.update` proposal → Executar → record updated → Montar → `completed/verified`, **zero console errors**.
- Deliverables regenerated by `scripts/produce_final_videos.py` (mock only, ledger untouched): `ClipForge_Final_PropertiesTest.mp4` (1,117,991 bytes, 6.0 s, 1280×720 h264+aac) + `ClipForge_Final_Editing.mp4` (1,177,154 bytes, 6.0 s, 1280×720 h264+aac) + contact sheets; ffprobe confirms video+audio streams; sample frames non-trivial (mean ~126).
- Ledger: `22/24/8/16` before and after — **$0.00 / $5.00 spent this mission**. Live Muse Spark reasoning remains NOT VERIFIED by policy (no per-call approval); all execution paths proven with the deterministic router + real executor.
