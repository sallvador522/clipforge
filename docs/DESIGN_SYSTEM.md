# ClipForge — Design System

Editorial cinematic editing studio. The video preview is the composition; voice interaction is the main visual element.

## Tokens

- Foundation (finalized Milestone 5): background `#14110C`, surface `#1C1813`, raised `#242019`, border `#2E2820`, foreground `#F3EDE3` (warm off-white), muted `#A79E8F`, signal orange accent `#FF7659`, danger `#FF6B57`, success `#9BC49B`.
- Typography: warm light (off-white, warm grey scale). Manrope for interface text; IBM Plex Mono for technical metadata (timecodes, job IDs, stream info).
- Accent: signal orange, used sparingly for primary actions, recording state, and progress.
- No purple/blue AI gradients, no decorative glassmorphism, no random illustrations, no emoji icons.

## Composition

- Strong, large video preview (before/after) as the dominant element.
- Minimal interface: voice control first, everything else subordinate. Avoid generic SaaS dashboard layouts and excessive cards.
- Fake waveforms and fake loading percentages are forbidden. Loading states must reflect real job state from the backend.

## Editor Workspace (Milestone 5.1 redesign, reorganizado ADR-043)

Full-viewport professional workstation, cinco zonas mais rail, sem hero/marketing chrome dentro da app:

```
┌ TopBar (44px): logo · projecto · estado · Export ┐
├ rail (44px) + Recursos (256px) ┬ Viewer (flexível, maior área) ┬ Propriedades / Muse (360px) ┤
├ Timeline (~133px, full width): toolbar · ruler · faixas com headers · playhead ┤
└─────────────────────────────────────────────────────────────────────────┘
```

- Painéis em superfícies flat separadas por hairlines (`#2E2820`), raios pequenos (8px painéis, 6px controlos), grid 8px. Sem sombras decorativas.
- A esquerda tem um icon-rail de 44px (só Recursos ativo; resto disabled honesto) e o painel Recursos com cabeçalho `Recursos | list/grid | sort | Import`, dropzone densa e Biblioteca com filtros/search.
- A direita divide-se em Propriedades (contextual: cena ativa, factos do clipe, cartões de aprovação) e Muse (chat + composer sempre acessíveis). Vazio honesto, nada inventado.
- O microfone continua o elemento bold (disco signal-orange, level real). Todo o resto quieto e disciplinado.

- Panels are flat surfaces separated by hairline borders (`#2E2820`), small radii (8px panels, 6px controls), 8px spacing grid. No nested decorative cards.
- The microphone is the single bold element (signal-orange disc, real level ring). Everything else stays quiet and disciplined.
- Timeline thumbnails are frames captured from the actual file; audio peaks are decoded from the actual file (WebAudio). Playhead and seeking are synchronized with the real `<video>` element. The timeline advertises no multitrack/trim/keyframe abilities the product does not have.
- Responsive: ≥1280px full three-column grid; 1024–1280px narrower media panel (208px) + assistant 300px; below 1024px the grid stacks (viewer first, assistant, media) with the timeline pinned under the viewer, keeping preview and voice controls usable on mobile.

## Animation (Motion for React)

- Every animation has a functional purpose; prioritize opacity and transform.
- Spring transitions for appropriate interactions; respect `prefers-reduced-motion`.
- No continuous animation loops, no layout-triggering effects.

Interface work must load the `frontend-design`, `web-design-guidelines`, and (for complex transitions) `/motion` skills before implementation or review, and must be inspected in a real browser.
