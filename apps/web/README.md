# apps/web — ClipForge Studio (Milestone 5, implemented)

Next.js 15 + React 19 + TypeScript + Tailwind CSS 4 + Motion for React. Customised shadcn-style primitives live in `src/components/ui/` (variant-driven, design-token based; no Radix dependency added).

Run the full local stack (mock mode):
1. API: `uvicorn clipforge_api.main:app --port 8000` (repo PYTHONPATH over `packages/*`, `apps/*`).
2. Worker: `python -m clipforge_worker.worker_process --storage storage`.
3. Web: `npm install` once, then `npm run dev` (or `npm run build && npm run start`) on port 3000. API base defaults to `http://localhost:8000`, override with `NEXT_PUBLIC_API_URL`.

Flow: upload (real progress, server-side validation) → record a voice instruction with MediaRecorder → confirm the matching mock transcription command (clearly labelled simulated, ADR-004) → submit → watch real job stages (polling stops at completed/failed) → transcript/plan/verified-render facts → before/after/compare preview → download the verified MP4 (blob download; the backend only serves verified files).

Checks: `npm run typecheck`, `npm run build`. Responsive QA (optional, dev-only): `npm install --no-save playwright-core` then `node scripts/responsive-check.mjs <outDir>` — drives system Chrome at 1440×900, 1280×800, 1024×768 and 390×844, runs the real mock flow, and writes layout facts + screenshots. `playwright-core` is not a shipped dependency. There is no frontend unit-test runner yet; behaviour is covered by the backend test suite plus real-browser verification (see docs/STATUS.md).
