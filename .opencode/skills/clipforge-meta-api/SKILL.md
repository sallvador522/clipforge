---
name: clipforge-meta-api
description: Governs all Meta AI integrations (SAM 3.1 segmentation, transcription, reasoning/planning, image generation). Use before writing any provider adapter, touching packages/providers, or discussing live Meta API calls.
---

# ClipForge Meta API Rules

- Mock-first (ADR-004): `CLIPFORGE_AI_MODE=mock` is default. No external Meta calls during development, tests, or demos. Remaining budget ~$30 — protect it.
- Never assume model names, endpoints, request fields, SDKs, or response schemas. Verify against current official Meta documentation (Context7/official docs) before writing live code. User-supplied details are unverified until confirmed.
- If an API is unavailable or unverified, keep the typed provider interface plus a clearly labelled mock. Never present a mock as a real integration.
- All Meta communication is server-side only. Never expose credentials to the frontend or commit them.
- Define ClipForge's own normalized internal contracts first (packages/contracts); map the verified Meta schema into them inside the adapter only. Do not hardcode undocumented assumptions.
- No automatic retries that could cause billable requests. Live mode requires explicit config change, explicit user approval, request logging, idempotency where supported, and budget tracking.
- Handle timeouts and failed segmentation jobs with explicit error states; job retries must reuse an idempotency key so inference is never duplicated.
