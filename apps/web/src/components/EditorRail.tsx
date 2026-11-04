"use client";

/* Icon rail (44px) — organization borrowed from professional editors:
 * assets/text swap the left column (Fase 1 preview-only); remaining slots
 * stay honestly disabled: disabled means disabled, no fake panels. */

const ITEMS: { id: string; label: string; selectable?: boolean; path: React.ReactNode }[] = [
  {
    id: "assets",
    label: "Recursos",
    selectable: true,
    path: (
      <>
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
      </>
    ),
  },
  {
    id: "text",
    label: "Texto",
    selectable: true,
    path: <path d="M5 5h14M12 5v14" />,
  },
  {
    id: "audio",
    label: "Áudio",
    path: <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />,
  },
  {
    id: "effects",
    label: "Efeitos",
    path: <path d="M6 18 18 6M15 4l.7 1.8L17.5 6.5l-1.8.7L15 9l-.7-1.8L12.5 6.5l1.8-.7L15 4ZM6 15l.5 1.3L7.8 16.8l-1.3.5L6 18.6l-.5-1.3L4.2 16.8l1.3-.5L6 15Z" />,
  },
  {
    id: "transitions",
    label: "Transições",
    path: <path d="m6 7 5 5-5 5M13 7l5 5-5 5" />,
  },
  {
    id: "captions",
    label: "Legendas",
    path: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M10.5 10.2a2.4 2.4 0 1 0 0 3.6M17.5 10.2a2.4 2.4 0 1 0 0 3.6" />
      </>
    ),
  },
  {
    id: "adjust",
    label: "Ajustes",
    path: <path d="M5 7h9M18 7h1M5 12h3M12 12h7M5 17h11M20 17h-1M14 4.5v5M10 9.5v5M16 14.5v5" />,
  },
];

export function EditorRail({ active = "assets", onSelect }: { active?: string; onSelect?: (id: "assets" | "text") => void }) {
  return (
    <nav aria-label="Ferramentas do editor" className="hidden w-11 shrink-0 flex-col items-center gap-1 border-r border-border/60 py-2 lg:flex">
      {ITEMS.map((item) => {
        const selectable = Boolean(item.selectable);
        const isActive = item.id === active;
        return (
        <button
          key={item.id}
          type="button"
          disabled={!selectable}
          onClick={() => {
            if (selectable && (item.id === "assets" || item.id === "text")) onSelect?.(item.id);
          }}
          aria-current={isActive ? "page" : undefined}
          aria-label={selectable ? item.label : `${item.label} — ainda não disponível`}
          title={selectable ? item.label : `${item.label} — ainda não disponível nesta versão`}
          className={`flex h-9 w-9 items-center justify-center rounded-md transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
            isActive
              ? "bg-accent/15 text-accent"
              : selectable
                ? "text-muted hover:bg-raised hover:text-foreground"
                : "cursor-not-allowed text-muted/45"
          }`}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            {item.path}
          </svg>
        </button>
        );
      })}
      <span className="mt-auto flex h-9 w-9 items-center justify-center text-muted/40" aria-hidden>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><path d="m9 6 6 6-6 6" /></svg>
      </span>
    </nav>
  );
}
