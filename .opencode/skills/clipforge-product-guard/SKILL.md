---
name: clipforge-product-guard
description: Enforces ClipForge MVP scope from docs/PRODUCT_SPEC.md. Use when planning features, reviewing scope, or when a request might add unrelated functionality, fake features, or bypass the voice-first flow.
---

# ClipForge Product Guard

- The MVP is exactly the 12-step flow in `docs/PRODUCT_SPEC.md` (upload → voice → transcribe → plan → identify → segment → sharp subject → blur/replace background → generate background → render MP4 with original audio → before/after + download). Reject or defer anything outside it.
- Constraints: 10-second clips, 720p, up to 30 FPS.
- Voice-first: when the intended subject is ambiguous, the agent asks a spoken clarification. Never silently pick a person.
- No fake functionality: no placeholder downloads, fake loading percentages, fake waveforms, or mock results presented as real inference.
- Mocks are allowed for AI services only (ADR-004), never for rendering (ADR-002).
- If a request conflicts with PRODUCT_SPEC.md or an ADR, stop, state the conflict, and ask. Never silently change an established decision; supersede only via a new ADR in `docs/DECISIONS.md`.
