"use client";

/* Left-column Texto panel — ADR-047: real project data.
 * Swaps with Recursos when the rail T tab is active. Overlays persist on
 * the job, burn into the Montar/Export MP4 and stay in sync across palco,
 * faixa T1, Propriedades e Muse. */

import { CLIP_TEXT_STYLES, type ClipTextOverlay, type ClipTextStyleId } from "@/lib/textOverlays";

interface Props {
  texts: ClipTextOverlay[];
  selectedId: string | null;
  canAdd: boolean;
  onAdd: (style: ClipTextStyleId) => void;
  onSelect: (id: string | null) => void;
  onDelete: (id: string) => void;
  onSeekText: (time: number) => void;
}

export function TextPanel({ texts, selectedId, canAdd, onAdd, onSelect, onDelete, onSeekText }: Props) {
  return (
    <section aria-label="Texto" className="flex min-h-0 min-w-0 flex-1 flex-col bg-surface lg:h-full">
      <header className="flex h-11 shrink-0 items-center gap-1.5 border-b border-border px-2.5">
        <h2 className="text-[13px] font-semibold">Texto</h2>
        {texts.length > 0 && (
          <span className="rounded-full border border-border px-1.5 font-mono text-[9px] text-muted">
            {texts.length}
          </span>
        )}
        <span className="flex-1" />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">
        <p
          role="note"
          className="rounded-[6px] border border-accent/40 bg-accent/10 px-2 py-1.5 text-[11px] leading-relaxed text-foreground/90"
        >
          Sai no MP4 — o Montar queima o texto no vídeo. Anima com anime.js no palco; o export usa
          fundido + subida.
        </p>

        <h3 className="mb-1.5 mt-3 text-[11px] font-semibold text-muted">Estilos (max 5)</h3>
        <ul className="space-y-1.5">
          {CLIP_TEXT_STYLES.map((style) => (
            <li
              key={style.id}
              className="flex items-center gap-2 rounded-[6px] border border-border bg-raised/50 px-2 py-1.5"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12px] font-medium">{style.label}</span>
                <span className="block truncate font-mono text-[10px] text-muted">
                  {style.description}
                </span>
              </span>
              <button
                type="button"
                disabled={!canAdd}
                onClick={() => onAdd(style.id)}
                aria-label={`Adicionar texto ${style.label} na posição do playhead`}
                title={canAdd ? "Adicionar na posição do playhead" : "Importa um clipe primeiro"}
                className="flex h-7 shrink-0 items-center rounded-[6px] bg-accent px-2.5 text-[11px] font-semibold text-[#14110C] transition-colors hover:bg-[#ff8a70] disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-accent"
              >
                Adicionar
              </button>
            </li>
          ))}
        </ul>

        <h3 className="mb-1.5 mt-4 text-[11px] font-semibold text-muted">Na timeline</h3>
        {texts.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-muted">
            Nenhum texto. Escolhe um estilo acima — aparece no palco e na faixa T1.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {texts.map((t) => {
              const selected = t.id === selectedId;
              return (
                <li
                  key={t.id}
                  className={`overflow-hidden rounded-[6px] border bg-raised/50 transition-colors ${
                    selected ? "border-accent/60" : "border-border hover:border-muted"
                  }`}
                >
                  <div className="flex items-center gap-1.5 px-2 py-1.5">
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(selected ? null : t.id);
                        onSeekText(t.start + 0.01);
                      }}
                      aria-label={`Selecionar texto ${t.text}`}
                      title={`${t.text} · ${t.start.toFixed(1)}s`}
                      className="min-w-0 flex-1 truncate text-left text-[12px] font-medium focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      {t.text || "(sem texto)"}
                    </button>
                    <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted">
                      {t.start.toFixed(1)}s
                    </span>
                    <button
                      type="button"
                      onClick={() => onDelete(t.id)}
                      aria-label={`Remover texto ${t.text}`}
                      title="Remover"
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted/60 hover:bg-border/60 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
