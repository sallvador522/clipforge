# packages/director — Professional Editing Director (Milestone 6B-PREP)

Deterministic, offline director that turns a confirmed transcript into a
`ProfessionalEditingPlan` (v2). **Not wired into the worker or live models.**

- `MockProfessionalEditingDirector` — scenarios A–E: blur, background replacement,
  simulated cinematic background, clarification, unsupported.
- Uses the capability registry from `packages/contracts`; only available capabilities
  can be planned.
- No network, credentials or paid inference. The runtime playbook lives in
  `apps/api/clipforge_api/prompts/`; the development skill is separate.
