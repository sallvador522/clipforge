"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { formatTime } from "./MediaPanel";

export type ViewMode = "before" | "compare" | "after";

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
}

export function Viewer({
  originalUrl, editedUrl, resultReady, primaryRef, currentTime, duration, playing,
  onTogglePlay, onSeek, onTimeUpdate, onPlayState, onFileDrop,
}: Props) {
  const [mode, setMode] = useState<ViewMode>("compare");
  const [split, setSplit] = useState(50);
  const stageRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLVideoElement>(null);

  // Keep the edited overlay in sync with the primary video in compare mode.
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay || mode !== "compare") return;
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

  const activeSrc = mode === "after" && resultReady ? editedUrl : originalUrl;

  return (
    <section id="viewer" aria-label="Viewer" className="flex min-h-0 min-w-0 flex-col bg-[#0B0906]">
      <div
        ref={stageRef}
        className="relative flex min-h-0 flex-1 items-center justify-center bg-black"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) onFileDrop(f);
        }}
      >
        {!originalUrl ? (
          <div className="px-6 text-center">
            <p className="text-lg font-semibold">Import a clip to start editing</p>
            <p className="mt-1.5 text-sm text-muted">Drop a video anywhere on this stage, or use the Media panel.</p>
            <p className="mt-3 font-mono text-[11px] text-muted">Up to 10 seconds · 720p · your original is always preserved</p>
          </div>
        ) : (
          <>
            <video
              key={activeSrc ?? "none"}
              ref={primaryRef}
              src={activeSrc ?? undefined}
              className="max-h-full w-full object-contain"
              style={{ aspectRatio: "auto" }}
              playsInline
              preload="auto"
              onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime, e.currentTarget.duration || 0)}
              onLoadedMetadata={(e) => onTimeUpdate(e.currentTarget.currentTime, e.currentTarget.duration || 0)}
              onPlay={() => onPlayState(true)}
              onPause={() => onPlayState(false)}
              aria-label={mode === "after" ? "Edited video" : "Original video"}
            />
            {mode === "compare" && resultReady && editedUrl && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
                <video ref={overlayRef} src={editedUrl} muted playsInline preload="auto" className="max-h-full w-full object-contain" aria-label="Edited video overlay" />
              </div>
            )}
            {mode === "compare" && (
              <span className="pointer-events-none absolute left-3 top-3 rounded bg-black/70 px-2 py-0.5 font-mono text-[11px]">ORIGINAL</span>
            )}
            {mode === "compare" && resultReady && (
              <span className="pointer-events-none absolute right-3 top-3 rounded bg-black/70 px-2 py-0.5 font-mono text-[11px] text-accent">EDITED</span>
            )}
            <AnimatePresence mode="wait">
              <motion.span
                key={mode + String(resultReady)}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                className="pointer-events-none absolute bottom-3 right-3 rounded bg-black/70 px-2 py-0.5 font-mono text-[11px] text-muted"
              >
                {mode === "after" ? "Edited render (verified)" : mode === "compare" && resultReady ? "Before / after" : "Original source"}
              </motion.span>
            </AnimatePresence>
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-3 py-2">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onTogglePlay}
            disabled={!originalUrl}
            className="flex h-8 w-8 items-center justify-center rounded-md bg-raised text-foreground transition-colors hover:bg-border disabled:opacity-30"
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? (
              <svg width="11" height="12" viewBox="0 0 11 12" aria-hidden><rect x="1" y="1" width="3" height="10" fill="currentColor" /><rect x="7" y="1" width="3" height="10" fill="currentColor" /></svg>
            ) : (
              <svg width="11" height="12" viewBox="0 0 11 12" aria-hidden><path d="M1 1.5v9l9-4.5-9-4.5Z" fill="currentColor" /></svg>
            )}
          </button>
          <span className="font-mono text-xs tabular-nums">
            {formatTime(currentTime)} <span className="text-muted">/ {formatTime(duration)}</span>
          </span>
          <input
            type="range"
            min={0}
            max={Math.max(duration, 0.01)}
            step={0.01}
            value={Math.min(currentTime, duration || 0)}
            disabled={!originalUrl}
            onChange={(e) => onSeek(Number(e.target.value))}
            className="min-w-0 flex-1"
            aria-label="Seek"
          />
          <div className="flex overflow-hidden rounded-md border border-border" role="tablist" aria-label="View mode">
            {(["before", "compare", "after"] as ViewMode[]).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                disabled={!originalUrl || (m !== "before" && !resultReady)}
                onClick={() => setMode(m)}
                className={`px-2.5 py-1.5 font-mono text-[11px] capitalize transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                  mode === m ? "bg-accent font-semibold text-[#14110C]" : "text-muted hover:text-foreground disabled:opacity-30"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={toggleFullscreen}
            disabled={!originalUrl}
            className="hidden h-8 items-center rounded-md px-2 font-mono text-[11px] text-muted transition-colors hover:text-foreground disabled:opacity-30 sm:flex"
            aria-label="Fullscreen preview"
          >
            Fullscreen
          </button>
        </div>
        {mode === "compare" && resultReady && (
          <label className="mt-2 flex items-center gap-3 font-mono text-[11px] text-muted">
            Compare split
            <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))} className="flex-1" aria-label="Compare split position" />
            <span className="tabular-nums">{split}%</span>
          </label>
        )}
      </div>
    </section>
  );
}
