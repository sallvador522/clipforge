---
name: clipforge-context-keeper
description: Keeps ClipForge project context accurate across sessions. Use at the start and end of every implementation task, when updating docs, or when producing a session handoff.
---

# ClipForge Context Keeper

Before every task:
1. Read `AGENTS.md`, `docs/STATUS.md`, and the relevant task in `docs/TASKS.md`.
2. Inspect only relevant code and dependencies. Never scan `node_modules`, `.venv`, build outputs, or generated files.

After every task:
1. Run appropriate verification (tests; actual media-file inspection for video work; real browser for UI work).
2. Update `docs/STATUS.md` (current state, blockers, next milestone), check off `docs/TASKS.md`, and record architectural changes only as new ADRs in `docs/DECISIONS.md`.
3. Report: files created/modified, test results, unresolved issues, next recommended milestone.

Rules:
- Never silently change an established architectural decision.
- Keep docs concise and factual; record measured numbers only (no promised performance, no invented API details; mark unverified items UNVERIFIED).
- At milestone end, write a concise handoff in STATUS.md so the next session can start from AGENTS.md + STATUS.md + TASKS.md alone.
- Load only relevant skills; total project skills must stay ≤10 (5 external, 5 custom).
