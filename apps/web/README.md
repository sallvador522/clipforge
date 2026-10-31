# apps/web — ClipForge Studio (Milestone 5, implemented)

Next.js 15 + React 19 + TypeScript + Tailwind CSS 4 + Motion for React. Customised shadcn-style primitives live in `src/components/ui/` (variant-driven, design-token based; no Radix dependency added).

Run the full local stack (mock mode):
1. API: `uvicorn clipforge_api.main:app --port 8000` (repo PYTHONPATH over `packages/*`, `apps/*`).
2. Worker: `python -m clipforge_worker.worker_process --storage storage`.
3. Web: `npm install` once, then `npm run dev` (or `npm run build && npm run start`) on port 3000. API base defaults to `http://localhost:8000`, override with `NEXT_PUBLIC_API_URL`.

Flow: upload (real progress, server-side validation) → record a voice instruction with MediaRecorder → confirm the matching mock transcription command (clearly labelled simulated, ADR-004) → submit → watch real job stages (polling stops at completed/failed) → transcript/plan/verified-render facts → before/after/compare preview → download the verified MP4 (blob download; the backend only serves verified files).

Checks: `npm run typecheck`, `npm run build`. QA harnesses (dev-only, `npm install --no-save playwright-core`, system Chrome):

- `node scripts/qa-editor.mjs <outDir>` — 1440×900 / 1280×800 / 1024×768 / 390×844 layout facts + screenshots, blur and replacement flows, verified downloads.
- `node scripts/qa-interactions.mjs <outDir>` — export gating, playback/playhead sync, seek, view modes, compare split, polling stop, permission-denied microphone state.
- `node scripts/qa-mic.mjs <outDir>` — real microphone (headed Chrome; only the permission prompt is auto-accepted, the actual input device is used).
- `node scripts/qa-facebook.mjs <outDir>` — real-footage run against a 10 s excerpt (mock masks do not track people).

There is no frontend unit-test runner yet; behaviour is covered by the backend test suite plus these browser verifications (see docs/STATUS.md).
