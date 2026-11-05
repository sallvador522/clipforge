"use client";

/* Icon rail (44px) — only real destinations: assets/text swap the left
 * column. No disabled placeholders: what is not available is not shown. */

const ITEMS: { id: "assets" | "text"; label: string; path: React.ReactNode }[] = [
  {
    id: "assets",
    label: "Recursos",
    path: (
      <>
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
      </>
    ),
  },
  {
    id: "text",
    label: "Texto",
    path: <path d="M5 5h14M12 5v14" />,
  },
];

export function EditorRail({ active = "assets", onSelect }: { active?: string; onSelect?: (id: "assets" | "text") => void }) {
  return (
    <nav aria-label="Ferramentas do editor" className="hidden w-11 shrink-0 flex-col items-center gap-1 border-r border-border/60 py-2 lg:flex">
      {ITEMS.map((item) => {
        const isActive = item.id === active;
        return (
        <button
          key={item.id}
          type="button"
          onClick={() => onSelect?.(item.id)}
          aria-current={isActive ? "page" : undefined}
          aria-label={item.label}
          title={item.label}
          className={`flex h-9 w-9 items-center justify-center rounded-md transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
            isActive
              ? "bg-accent/15 text-accent"
              : "text-muted hover:bg-raised hover:text-foreground"
          }`}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            {item.path}
          </svg>
        </button>
        );
      })}
    </nav>
  );
}
