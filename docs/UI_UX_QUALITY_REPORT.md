# ClipForge — UI/UX Quality Report (`/ui-ux-rescue`, 2026-11-04)

Scope: frontend interactions only. No AI/provider/rendering changes, zero paid calls. All checks against the real Studio + mock API/worker on isolated stacks (`storage/_ux_*`, removed after the run).

## Initial state
Shell, library, multitrack Montar, deterministic Muse chat, interview, captions/cover tools and Magic Background worked (proven by prior rescue + final-E2E). Open UX debts: raw English backend errors shown to users, failed upload left a fake loaded session, TopBar status contradicted the error banner, rename was a silent no-op before any import.

## Problems found → root cause → fix
| # | Sev | Finding | Root cause | Fix | State |
|---|---|---|---|---|---|
| 1 | P1 | Failed upload left session card + viewer + timeline looking loaded with no backend job ("Upload failed" + "Pronto") | `uploadFileObject` catch kept local `file`/blob/meta | Catch now clears file/blob/meta/duration/playing → empty state + banner only | FIXED + TESTED |
| 2 | P1 | Raw English errors leaked: "Uploaded file is empty.", "Cannot reach the ClipForge API at http://localhost:8000…" | `e.message` rendered directly; `api_unreachable` embeds URL + English | `friendlyApiError()` in `lib/api.ts` maps codes → PT-AO; all 20+ call sites in Studio/MediaPanel/ClipTrimAudio use it; banners render only the friendly text | FIXED + TESTED |
| 3 | P1 | TopBar showed "Pronto" while the error banner was up | `studioStatus` ignored `error`/`apiError` | Status returns "Sem ligação" / "Precisa de atenção" (attention tone) first | FIXED + TESTED |
| 4 | P2 | Rename opened an editor with no project; commit silently did nothing | `handleRenameProject` early-return; button always enabled | `TopBar canRename={Boolean(project)}`: disabled + "disponível após importar um clipe" before import; enabled + persists after (`Projecto Auditoria` verified) | FIXED + TESTED |
| 5 | P2 | Transport showed `00:00.0 / 00:06.0` on the empty stage after a failed upload | `duration` state survived the failure | Catch resets `currentTime`/`duration`/`playing` | FIXED + TESTED |
| 6 | — | `next start` chunk 400s during QA | Stale server predating a rebuild (shared `.next`) | Restart server after every rebuild; verified consistent before each suite | TESTED (harness) |
| 7 | — | Playwright `postDataBuffer` truncation → 400 `empty_file` on UI upload | Known Playwright XHR-streaming artifact, not a product bug | Backend correctly rejects; UI path above now handles it honestly; suites use direct-API upload | NOT A DEFECT |

Audit-only checks (no change needed): aspect pills are a real `radiogroup` with `aria-checked`, honest empty stage on toggle; no h-overflow at 1920/1440/1366/390 empty AND populated; `:focus-visible` ×8 in served CSS; chat rapid-Enter sends once; T1/two-overlay persistence; library + session download links; rename persists via PATCH.

## Timeline / Properties / Muse / Panels
- Timeline: zoom 1→1.25, ruler seek, V1 auto-place, T1 mirror of overlays, play/pause — TESTED (audit3 + final-e2e + rescue).
- Properties: empty state guides ("selecciona…"); two overlays persist; edits via Properties/inline/chat reflected — TESTED.
- Muse: reply order, `Posso executar?` card, single execution, interview chips → options proposal, captions/cover tools, translate price shown without executing — TESTED (chat/chat2/magicbg).
- Project/Assets: selection, preview, search/filters (pre-existing), two-step remove, downloads SHA-256-identical — TESTED.
- Menus/dialogs: rename inline input (Enter commits, Escape cancels, blur commits); no dead primary controls found; honestly-disabled rail slots unchanged.

## Browser tests executed (all zero console errors)
- `qa-ux-audit2.mjs` (new, temp): 13/13 PASS — overflow ×4, aspect honesty, rename disabled/enabled, chat, properties empty state, focus-visible.
- `qa-ux-audit3.mjs` (new, temp): 9/9 PASS — download link, rename persist, zoom, 2 overlays, no-dupe send, overflow populated 1440/390.
- `qa-final-e2e.mjs`, `qa-rescue.mjs`, `qa-chat.mjs`, `qa-chat2.mjs` (+CLIP_PATH), `qa-magicbg.mjs`: all PASS.
- `tsc --noEmit` clean; production `next build` clean; backend suite re-run (see STATUS).

## Remaining limitations
- P2: dialogs (plan review/consent) Escape/outside-click covered by pre-existing suites, not re-run this mission (stacks were occupied by the parallel session's ports when attempted — used 8003/8004 instead; chat2/magicbg pass).
- P3: narrow-screen side-panel stacking reuses existing responsive rules; no new 390-specific defects found.
- Voice→chat path still headless-untestable (pre-existing hardware-mic coverage stands).

## Files changed
- `apps/web/src/lib/api.ts` (+`friendlyApiError`)
- `apps/web/src/components/Studio.tsx` (mapper everywhere, failure clears session, truthful status, `canRename`)
- `apps/web/src/components/TopBar.tsx` (`canRename`, disabled + honest label)
- `apps/web/src/components/MediaPanel.tsx`, `ClipTrimAudio.tsx` (PT errors)
- `apps/web/scripts/qa-chat.mjs` (interview flow, from prior mission — unchanged here)
