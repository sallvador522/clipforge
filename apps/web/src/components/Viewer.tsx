"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ClipTextLayer } from "./ClipTextLayer";
import type { ClipTextOverlay } from "@/lib/textOverlays";
import { formatTime } from "./MediaPanel";

export type ViewMode = "before" | "compare" | "after";

interface SubjectChip {
  object_id: string;
  previewUrl: string;
  selected: boolean;
}

interface Props {
  originalUrl: string | null;
  editedUrl: string | null;
  resultReady: boolean;
  primaryRef: React.RefObject<HTMLVideoElement | null>;
  currentTime: number;
  duration: number;
  playing: boolean;
  onTogglePlay: () => void;
  onSeek: (time: number) => void;
  onTimeUpdate: (time: number, duration: number) => void;
  onPlayState: (playing: boolean) => void;
  onFileDrop: (file: File) => void;
  subjects: SubjectChip[] | null;
  selectionVisible: boolean;
  onToggleSubject: (objectId: string) => void;
  displayFormat: "reels" | "youtube";
  onFormatChange: (format: "reels" | "youtube") => void;
  /** Fase 1 preview-only clip texts (anime.js overlay, not burned into MP4). */
  clipTexts?: ClipTextOverlay[];
  selectedTextId?: string | null;
  onSelectText?: (id: string | null) => void;
  onMoveText?: (id: string, x: number, y: number) => void;
  onCommitText?: (id: string, text: string) => void;
}

export function Viewer({
  originalUrl, editedUrl, resultReady, primaryRef, currentTime, duration, playing,
  onTogglePlay, onSeek, onTimeUpdate, onPlayState, onFileDrop,
  subjects, selectionVisible, onToggleSubject, displayFormat, onFormatChange,
  clipTexts, selectedTextId, onSelectText, onMoveText, onCommitText,
}: Props) {
  const [mode, setMode] = useState<ViewMode>("compare");
  const [split, setSplit] = useState(50);
  const stageRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLVideoElement>(null);

  // Keep the edited overlay in sync with the primary video in every mode.
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    if (Math.abs(overlay.currentTime - currentTime) > 0.35) overlay.currentTime = currentTime;
    if (playing && overlay.paused) void overlay.play().catch(() => {});
    if (!playing && !overlay.paused) overlay.pause();
  }, [currentTime, playing, mode]);

  useEffect(() => {
    if (!resultReady) setMode("before");
    else setMode("compare");
  }, [resultReady]);

  function toggleFullscreen() {
    const el = stageRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  }

  return (
    <section id="viewer" aria-label="Pré-visualização" className="flex min-h-0 min-w-0 flex-1 flex-col bg-canvas">
      <div
        ref={stageRef}
        className="relative flex min-h-0 flex-1 items-center justify-center p-4 md:p-6"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) onFileDrop(f);
        }}
      >
        {/* Format card: always visible, sized by the chosen format (9:16 tall,
            16:9 wide). The video fills it undistorted; empty it invites import.
            The export itself cover-crops to the format on the backend. */}
        <div
          className="relative max-h-full max-w-full overflow-hidden rounded-lg border border-border/70 bg-black"
          style={
            displayFormat === "reels"
              ? { aspectRatio: "9 / 16", height: "100%" }
              : { aspectRatio: "16 / 9", width: "100%", maxHeight: "100%" }
          }
        >
          {!originalUrl ? (
            <div className="absolute inset-0">
              <span className="sr-only">Palco vazio. Importa um clipe no painel Recursos ou larga um vídeo aqui.</span>
            </div>
          ) : (
            <>
              <video
                ref={primaryRef}
                src={originalUrl ?? undefined}
                className="absolute inset-0 h-full w-full object-contain"
                playsInline
                preload="auto"
                onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime, e.currentTarget.duration || 0)}
                onLoadedMetadata={(e) => onTimeUpdate(e.currentTarget.currentTime, e.currentTarget.duration || 0)}
                onPlay={() => onPlayState(true)}
                onPause={() => onPlayState(false)}
                aria-label="Vídeo original"
              />
              {/* The edited render stays mounted once verified so mode switches
                  never abort an in-flight blob fetch (console-safe). */}
              {resultReady && editedUrl && (
                <video
                  ref={overlayRef}
                  src={editedUrl}
                  muted
                  playsInline
                  preload="auto"
                  aria-label="Vídeo editado"
                  className="pointer-events-none absolute inset-0 h-full w-full object-contain"
                  style={{
                    clipPath: mode === "compare" ? `inset(0 0 0 ${split}%)` : undefined,
                    visibility: mode === "before" ? "hidden" : "visible",
                  }}
                />
              )}
            </>
          )}
          {selectionVisible && subjects && subjects.length > 0 && (
            <div className="absolute bottom-3 left-3 flex max-w-[70%] flex-wrap gap-1.5" role="group" aria-label="Select subjects on the preview">
              {subjects.map((subject) => (
                <button
                  key={subject.object_id}
                  type="button"
                  data-testid={`preview-subject-${subject.object_id}`}
                  aria-pressed={subject.selected}
                  aria-label={`Seleccionar pessoa ${subject.object_id} na pré-visualização`}
                  onClick={() => onToggleSubject(subject.object_id)}
                  className={`flex items-center gap-1.5 rounded-md border bg-black/75 py-1 pl-1 pr-2 backdrop-blur transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                    subject.selected ? "border-accent" : "border-border hover:border-muted"
                  }`}
                >
                  <img
                    src={subject.previewUrl}
                    alt=""
                    aria-hidden
                    className="h-8 w-8 rounded object-cover"
                    loading="lazy"
                  />
                  <span className={`text-[10px] ${subject.selected ? "font-semibold text-accent" : "text-muted"}`} title={subject.object_id}>
                    {subject.selected ? "✓ " : ""}Pessoa {subject.object_id.slice(0, 8)}
                  </span>
                </button>
              ))}
            </div>
          )}
          {clipTexts && clipTexts.length > 0 && onSelectText && onMoveText && (
            <ClipTextLayer
              texts={clipTexts}
              currentTime={currentTime}
              selectedId={selectedTextId ?? null}
              onSelect={onSelectText}
              onMove={onMoveText}
              onCommitText={onCommitText}
            />
          )}
          {originalUrl && (
            <AnimatePresence mode="wait">
              <motion.span
                key={mode + String(resultReady)}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                className="pointer-events-none absolute bottom-3 right-3 rounded bg-black/70 px-2 py-0.5 font-mono text-[11px] text-muted"
              >
                {clipTexts && clipTexts.length > 0
                  ? "Texto · sai no MP4 (Montar)"
                  : mode === "after"
                    ? "Versão final (verificada)"
                    : mode === "compare" && resultReady
                      ? "Antes / depois"
                      : "Origem"}
              </motion.span>
            </AnimatePresence>
          )}
        </div>
      </div>

      <div className="shrink-0 px-5 py-2.5">
        <div className="relative flex min-h-8 items-center gap-x-2">
          <span className="shrink-0 whitespace-nowrap font-mono text-[11px] tabular-nums">
            <span className="text-accent">{formatTime(currentTime)}</span> <span className="text-muted">/ {formatTime(duration)}</span>
          </span>
          <button
            type="button"
            onClick={onTogglePlay}
            disabled={!originalUrl}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-foreground transition-colors hover:bg-raised disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-accent sm:absolute sm:left-1/2 sm:-translate-x-1/2 z-10"
            aria-label={playing ? "Pausa" : "Reproduzir"}
          >
            {playing ? (
              <svg width="11" height="12" viewBox="0 0 11 12" aria-hidden><rect x="1" y="1" width="3" height="10" fill="currentColor" /><rect x="7" y="1" width="3" height="10" fill="currentColor" /></svg>
            ) : (
              <svg width="11" height="12" viewBox="0 0 11 12" aria-hidden><path d="M1 1.5v9l9-4.5-9-4.5Z" fill="currentColor" /></svg>
            )}
          </button>
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            <div className="flex overflow-hidden rounded-[6px] border border-border" role="radiogroup" aria-label="Formato">
              {([
                { key: "reels", label: "9:16" },
                { key: "youtube", label: "16:9" },
              ] as const).map((f) => (
                <button
                  key={f.key}
                  type="button"
                  role="radio"
                  aria-checked={displayFormat === f.key}
                  onClick={() => onFormatChange(f.key)}
                  className={`px-2.5 py-1.5 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                    displayFormat === f.key ? "bg-raised font-semibold text-foreground" : "text-muted hover:text-foreground"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={toggleFullscreen}
              disabled={!originalUrl}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] text-muted transition-colors hover:bg-raised hover:text-foreground disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-accent"
              aria-label="Ecrã inteiro"
              title="Ecrã inteiro"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>
            </button>
          </div>
        </div>
        {mode === "compare" && resultReady && (
          <label className="mt-1 flex items-center gap-3 text-[11px] text-muted">
            Divisória
            <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))} className="flex-1" aria-label="Posição da divisória" />
            <span className="tabular-nums">{split}%</span>
          </label>
        )}
      </div>
    </section>
  );
}
