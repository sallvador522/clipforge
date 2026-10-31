# ClipForge — Design System

Editorial cinematic editing studio. The video preview is the composition; voice interaction is the main visual element.

## Tokens

- Foundation: dark charcoal (e.g. `#16130F`-family, warm-tinted near-black). Exact hex values are finalized at the frontend milestone and recorded here before implementation.
- Typography: warm light (off-white, warm grey scale). Manrope for interface text; IBM Plex Mono for technical metadata (timecodes, job IDs, stream info).
- Accent: signal orange, used sparingly for primary actions, recording state, and progress.
- No purple/blue AI gradients, no decorative glassmorphism, no random illustrations, no emoji icons.

## Composition

- Strong, large video preview (before/after) as the dominant element.
- Minimal interface: voice control first, everything else subordinate. Avoid generic SaaS dashboard layouts and excessive cards.
- Fake waveforms and fake loading percentages are forbidden. Loading states must reflect real job state from the backend.

## Animation (Motion for React)

- Every animation has a functional purpose; prioritize opacity and transform.
- Spring transitions for appropriate interactions; respect `prefers-reduced-motion`.
- No continuous animation loops, no layout-triggering effects.

Interface work must load the `frontend-design`, `web-design-guidelines`, and (for complex transitions) `/motion` skills before implementation or review, and must be inspected in a real browser.
