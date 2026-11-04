"use client";

import { useEffect, useRef, useState } from "react";
import { assetFileUrl, readTimelineDrag } from "@/lib/api";
import type { TimelineClipData, TimelineTrack } from "@/lib/types";
import { formatTime } from "./MediaPanel";

export interface TimelineAnimation {
  primitive: string;
  target: string;
  /** Offset inside the scene, seconds. */
  start: number;
  /** Length, seconds. */
  duration: number;
}

export interface TimelineOverlay {
  id: string;
  title: string;
  start: number;
  duration: number;
}

export interface TimelineScene {
  id: string;
  title: string;
  lines?: string[];
  start: number;
  duration: number;
  thumbUrl?: string | null;
  animations?: TimelineAnimation[];
  transitionIn?: string | null;
  transitionOut?: string | null;
}

export interface ClipTrimWindow {
  start: number;
  end: number;
  original: number;
}

interface Props {
  file: File | null;
  duration: number;
  currentTime: number;
  hasAudio: boolean | null;
  onSeek: (time: number) => void;
  /** ADR-041 upload trim window (absolute seconds in the original file). */
  trim?: ClipTrimWindow | null;
  /** Idea scenes: read-only visualisation, click to seek. No drag/trim. */
  scenes?: TimelineScene[] | null;
  /** Idea overlays (ADR-040 multitrack layer 1): global blocks, click to seek. */
  overlays?: TimelineOverlay[] | null;
  activeSceneId?: string | null;
  onSeekScene?: (time: number) => void;
  trackLabel?: string;
  /** Idea V1 drag-reorder (ADR-039). Omitido = faixa sÃ³ navega. */
  onReorderScene?: (dragId: string, targetId: string, before: boolean) => void;
  /** Upload-clip track: shown when the verified render exists. Honest badge only. */
  editedReady?: boolean;
  /** ADR-044 assembly: explicit user arrangement with DnD + clip blocks. */
  assembly?: {
    clips: TimelineClipData[];
    programDuration: number;
    rendering: boolean;
    renderError: string | null;
    canRender: boolean;
    /** ADR-051 output canvas chosen by the user (default preserves source). */
    format: "source" | "landscape" | "portrait";
    onFormatChange: (format: "source" | "landscape" | "portrait") => void;
    /** Smart drop: the timeline routes by asset kind, never refuses a lane. */
    onAddClip: (t: number, asset: { asset_id: string; kind: string; duration: number; name?: string }) => void;
    onMoveClip: (clipId: string, newStart: number) => void;
    onTrimClip: (clipId: string, edge: "start" | "end", newT: number) => void;
    onRemoveClip: (clipId: string) => void;
    onRender: () => void;
  } | null;
  /** Asset filenames for block labels. */
  assetNames?: Record<string, string>;
  /** Session asset id: clicking its blocks seeks the preview (exact mapping). */
  sessionAssetId?: string | null;
  /** Project id for per-clip filmstrip capture. */
  projectId?: string | null;
  /** Fase 1 preview-only clip texts (T1 lane, local-only, no backend). */
  clipTexts?: { id: string; title: string; start: number; duration: number }[] | null;
  selectedTextId?: string | null;
  onSelectText?: (id: string | null) => void;
  onSeekText?: (time: number) => void;
  onMoveText?: (id: string, newStart: number) => void;
  onTrimText?: (id: string, edge: "start" | "end", newT: number) => void;
  onRemoveText?: (id: string) => void;
}

const THUMB_COUNT = 10;
const PEAK_COUNT = 72;
const MIN_H = 150;
const MAX_H = 560;
const DEFAULT_H = 250;
const HEIGHT_KEY = "clipforge.timelineH";

function ToolButton({ label, active, disabled, children }: { label: string; active?: boolean; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={label}
      title={disabled ? `${label} — ainda nÃ£o disponÃ­vel` : label}
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
        active ? "bg-accent/15 text-accent" : disabled ? "cursor-not-allowed text-muted/40" : "text-muted hover:bg-raised hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

const iconProps = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

/** Left gutter cell: track code + monitor toggles (decorative, like NLEs). */
function TrackHeader({ code, title }: { code: string; title: string }) {
  return (
    <div className="flex h-full flex-col items-start justify-center gap-1 px-2" title={title}>
      <span className="font-mono text-[9px] font-semibold text-muted">{code}</span>
      <span className="flex items-center gap-1 text-muted/45" aria-hidden>
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M11 5 6 9H3v6h3l5 4V5ZM15 9a4 4 0 0 1 0 6" /></svg>
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z" /><circle cx="12" cy="12" r="2.5" /></svg>
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="7" width="12" height="11" rx="2" /><path d="m15 11 6-3v9l-6-3" /></svg>
      </span>
    </div>
  );
}

const stripCache = new Map<string, string[]>();

async function captureStrip(url: string, sourceIn: number, duration: number): Promise<string[]> {
  const count = Math.max(3, Math.min(10, Math.round(Math.max(0.5, duration) / 2)));
  const video = document.createElement("video");
  video.crossOrigin = "anonymous";
  video.muted = true;
  video.preload = "auto";
  video.src = url;
  await new Promise<void>((resolve, reject) => {
    const to = window.setTimeout(() => reject(new Error("thumb load timeout")), 15000);
    video.onloadedmetadata = () => {
      window.clearTimeout(to);
      resolve();
    };
    video.onerror = () => {
      window.clearTimeout(to);
      reject(new Error("thumb load failed"));
    };
  });
  const canvas = document.createElement("canvas");
  canvas.width = 96;
  canvas.height = 54;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const t = sourceIn + ((i + 0.5) / count) * duration;
    await new Promise<void>((resolve, reject) => {
      const to = window.setTimeout(() => reject(new Error("thumb seek timeout")), 8000);
      const done = () => {
        window.clearTimeout(to);
        video.removeEventListener("seeked", done);
        resolve();
      };
      video.addEventListener("seeked", done);
      video.currentTime = Math.max(0, Math.min(t, (video.duration || t + 1) - 0.05));
    });
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    out.push(canvas.toDataURL("image/jpeg", 0.55));
  }
  video.removeAttribute("src");
  video.load();
  return out;
}

function ClipFilmstrip({ projectId, assetId, sourceIn, duration }: { projectId: string; assetId: string; sourceIn: number; duration: number }) {
  const [thumbs, setThumbs] = useState<string[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const key = `${projectId}:${assetId}:${Math.round(sourceIn * 10)}:${Math.round(duration * 10)}`;
    const cached = stripCache.get(key);
    if (cached) {
      setThumbs(cached);
      return;
    }
    setThumbs(null);
    void (async () => {
      try {
        const shots = await captureStrip(assetFileUrl(projectId, assetId), sourceIn, duration);
        if (!cancelled) {
          stripCache.set(key, shots);
          setThumbs(shots);
        }
      } catch {
        if (!cancelled) setThumbs([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, assetId, sourceIn, duration]);
  if (!thumbs || thumbs.length === 0) return null;
  return (
    <span className="pointer-events-none absolute inset-0 flex overflow-hidden" aria-hidden>
      {thumbs.map((src, i) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={i} src={src} alt="" draggable={false} className="h-full min-w-0 flex-1 object-cover" />
      ))}
    </span>
  );
}
export function Timeline({ file, duration, currentTime, hasAudio, onSeek, scenes, activeSceneId, onSeekScene, trackLabel, editedReady, onReorderScene, overlays, trim, assembly, assetNames, sessionAssetId, projectId, clipTexts, selectedTextId, onSelectText, onSeekText, onMoveText, onTrimText, onRemoveText }: Props) {
  const [thumbs, setThumbs] = useState<string[]>([]);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [dropHint, setDropHint] = useState<{ track: TimelineTrack; t: number } | null>(null);
  const [selectedClip, setSelectedClip] = useState<string | null>(null);
  const [dragGhost, setDragGhost] = useState<{ clipId: string; start: number; inn: number; out: number } | null>(null);
  const blockDrag = useRef<{ clipId: string; mode: "move" | "trim-l" | "trim-r"; startX: number; origStart: number; origIn: number; origOut: number } | null>(null);
  // A real drag must not trigger the click-to-preview-seek below.
  const suppressClick = useRef(false);
  const textDrag = useRef<{ textId: string; mode: "move" | "trim-l" | "trim-r"; startX: number; origStart: number; origEnd: number } | null>(null);
  const [textGhost, setTextGhost] = useState<{ textId: string; start: number; end: number } | null>(null);
  const [height, setHeight] = useState<number>(() => {
    try {
      const raw = window.localStorage.getItem(HEIGHT_KEY);
      const n = raw ? Number(raw) : NaN;
      if (Number.isFinite(n)) return Math.min(MAX_H, Math.max(MIN_H, n));
    } catch { /* fresh default */ }
    return DEFAULT_H;
  });
  const trackRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ y: number; h: number } | null>(null);

  // Filmstrip: capture real frames from the actual file. No stock imagery.
  useEffect(() => {
    setThumbs([]);
    if (!file) return;
    let cancelled = false;
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.src = url;
    const canvas = document.createElement("canvas");
    canvas.width = 96;
    canvas.height = 54;
    const captured: string[] = [];
    const windowStart = trim && trim.original > 0 ? Math.min(trim.start, trim.original) : 0;
    const windowEnd = trim && trim.original > 0 ? Math.min(trim.end, trim.original) : 0;

    video.addEventListener("loadedmetadata", () => {
      const total = video.duration || 0;
      const span = windowEnd > windowStart ? windowEnd - windowStart : total;
      const base = windowEnd > windowStart ? windowStart : 0;
      let index = 0;
      const captureNext = () => {
        if (cancelled) return;
        if (index >= THUMB_COUNT || (span || total) <= 0) {
          setThumbs(captured);
          URL.revokeObjectURL(url);
          return;
        }
        video.currentTime = base + ((span || total) * (index + 0.5)) / THUMB_COUNT;
      };
      video.addEventListener("seeked", () => {
        if (cancelled) return;
        const ctx = canvas.getContext("2d");
        if (ctx && video.videoWidth > 0) {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          captured.push(canvas.toDataURL("image/jpeg", 0.6));
        }
        index += 1;
        captureNext();
      });
      captureNext();
    });
    return () => {
      cancelled = true;
      video.removeAttribute("src");
      video.load();
      URL.revokeObjectURL(url);
    };
  }, [file, trim?.start, trim?.end, trim?.original]);

  // Audio peaks decoded from the actual file with WebAudio — real data or nothing.
  useEffect(() => {
    setPeaks(null);
    if (!file || hasAudio === false) return;
    let cancelled = false;
    (async () => {
      try {
        const buffer = await file.arrayBuffer();
        const ctx = new AudioContext();
        const audio = await ctx.decodeAudioData(buffer.slice(0));
        await ctx.close();
        if (cancelled) return;
        const channel = audio.getChannelData(0);
        const block = Math.floor(channel.length / PEAK_COUNT) || 1;
        const values: number[] = [];
        for (let i = 0; i < PEAK_COUNT; i++) {
          let peak = 0;
          for (let j = i * block; j < Math.min((i + 1) * block, channel.length); j += 16) {
            peak = Math.max(peak, Math.abs(channel[j]));
          }
          values.push(peak);
        }
        if (trim && trim.original > 0 && trim.end > trim.start) {
          const from = Math.max(0, Math.floor((trim.start / trim.original) * PEAK_COUNT));
          const to = Math.min(PEAK_COUNT, Math.ceil((trim.end / trim.original) * PEAK_COUNT));
          setPeaks(values.slice(from, Math.max(from + 1, to)));
        } else {
          setPeaks(values);
        }
      } catch {
        if (!cancelled) setPeaks(null);
      }
    })();
    return () => { cancelled = true; };
  }, [file, hasAudio, trim?.start, trim?.end, trim?.original]);

  function seekFromPointer(e: React.PointerEvent) {
    const track = trackRef.current;
    if (!track || duration <= 0) return;
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(ratio * duration);
  }

  function beginResize(e: React.PointerEvent) {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    dragRef.current = { y: e.clientY, h: height };
  }
  function moveResize(e: React.PointerEvent) {
    const start = dragRef.current;
    if (!start) return;
    setHeight(Math.min(MAX_H, Math.max(MIN_H, Math.round(start.h + (start.y - e.clientY)))));
  }
  function endResize() {
    dragRef.current = null;
    try { window.localStorage.setItem(HEIGHT_KEY, String(height)); } catch { /* ignore */ }
  }

  const playheadPct = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;
  // Adaptive ruler: at most ~140 ticks even for 15-min programs.
  const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const tickEvery = STEPS.find((s) => duration / s <= 140) ?? 600;
  const ticks: number[] = [];
  for (let t = 0; t <= Math.max(duration, 0) + 0.001; t += tickEvery) ticks.push(t);
  const ideaMode = Boolean(scenes && scenes.length > 0);

  // Lane heights: tall enough to read, matching the gutter cells.
  const H = ideaMode
    ? { v1: "h-10", t1: "h-7", fx: "h-8", a1: "h-7", ov: "h-8", v2: "h-8", a2: "h-7" }
    : { v1: "h-16", t1: "h-7", a1: "h-10", v2: "h-12", a2: "h-10" };

  function rulerLabel(t: number): string {
    if (Math.abs(t % 1 - 0.5) < 0.001) return "15f";
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function shortPrimitive(primitive: string): string {
    return primitive
      .replace("kinetic_typography", "kinetic")
      .replace("text_reveal", "reveal")
      .replace("particle_burst", "particles")
      .replace("shockwave_ring", "shockwave")
      .replace("motion_path", "path")
      .replace("camera_zoom", "zoom")
      .replace("camera_pan", "pan")
      .replace("chart_bar", "bars")
      .replace("mask_reveal", "mask")
      .replace("elastic_pop", "pop")
      .replace("gradient_shift", "hue");
  }

  const ruler = (
    <div className="relative h-5 shrink-0 border-b border-border/60">
      {ticks.map((t, i) => (
        <span key={t} className={`absolute top-1 font-mono text-[9px] tabular-nums text-muted/70 ${i === 0 ? "" : i === ticks.length - 1 ? "-translate-x-full" : "-translate-x-1/2"}`} style={{ left: `${duration ? (t / duration) * 100 : 0}%` }}>
          {rulerLabel(t)}
        </span>
      ))}
      {ticks.length === 0 && <span className="absolute left-0 top-1 font-mono text-[9px] text-muted/70">00:00</span>}
    </div>
  );

  const emptyLane = (label: string) => (
    <div className="overflow-hidden rounded bg-black/25" aria-hidden>
      <div className="h-full w-full border-y border-dashed border-border/40" title={label} />
    </div>
  );

  // ---- ADR-044 assembly interactions (clip mode with assembly only) ----
  const prog = Math.max(assembly?.programDuration ?? duration, 0.01);

  function laneTime(clientX: number): number | null {
    const el = trackRef.current;
    if (!el || prog <= 0) return null;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return null;
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * prog;
  }

  function laneOverAt(track: TimelineTrack) {
    return (e: React.DragEvent) => {
      if (!assembly) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      const t = laneTime(e.clientX);
      if (t !== null) setDropHint({ track, t });
    };
  }

  function laneDropAt(track: TimelineTrack) {
    return (e: React.DragEvent) => {
      e.preventDefault();
      const asset = readTimelineDrag(e.dataTransfer);
      setDropHint(null);
      if (!assembly || !asset) return;
      const t = laneTime(e.clientX) ?? 0;
      // Smart drop: the lane is only a hint — Studio routes by asset kind.
      assembly.onAddClip(t, { ...asset, name: asset.name });
    };
  }

  function ghostFromEvent(
    d: { mode: "move" | "trim-l" | "trim-r"; startX: number; origStart: number; origIn: number; origOut: number },
    clientX: number,
  ): { start: number; inn: number; out: number } {
    const el = trackRef.current;
    const dt = el && el.getBoundingClientRect().width > 0
      ? ((clientX - d.startX) / el.getBoundingClientRect().width) * prog
      : 0;
    if (d.mode === "move") return { start: d.origStart + dt, inn: d.origIn, out: d.origOut };
    if (d.mode === "trim-l") return { start: d.origStart + dt, inn: d.origIn + dt, out: d.origOut };
    return { start: d.origStart, inn: d.origIn, out: d.origOut + dt };
  }

  function blockDown(clip: TimelineClipData, mode: "move" | "trim-l" | "trim-r") {
    return (e: React.PointerEvent) => {
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      suppressClick.current = false;
      blockDrag.current = {
        clipId: clip.clip_id, mode, startX: e.clientX,
        origStart: clip.timeline_start_s, origIn: clip.source_in_s, origOut: clip.source_out_s,
      };
      setSelectedClip(clip.clip_id);
      setDragGhost({ clipId: clip.clip_id, start: clip.timeline_start_s, inn: clip.source_in_s, out: clip.source_out_s });
    };
  }

  function blockMove(e: React.PointerEvent) {
    const d = blockDrag.current;
    if (!d || !assembly) return;
    if (Math.abs(e.clientX - d.startX) > 4) suppressClick.current = true;
    const g = ghostFromEvent(d, e.clientX);
    setDragGhost({ clipId: d.clipId, ...g });
  }

  function blockUp(e: React.PointerEvent) {
    const d = blockDrag.current;
    if (!d || !assembly) return;
    blockDrag.current = null;
    setDragGhost(null);
    const g = ghostFromEvent(d, e.clientX);
    if (d.mode === "move") assembly.onMoveClip(d.clipId, g.start);
    else if (d.mode === "trim-l") assembly.onTrimClip(d.clipId, "start", g.start);
    else assembly.onTrimClip(d.clipId, "end", g.start + (g.out - g.inn));
  }

  function blockUpCancel() {
    blockDrag.current = null;
    setDragGhost(null);
  }

  // ---- Fase 1 clip texts (T1 lane, local-only, no backend) ----
  function textGhostFromEvent(
    d: { mode: "move" | "trim-l" | "trim-r"; startX: number; origStart: number; origEnd: number },
    clientX: number,
  ): { start: number; end: number } {
    const el = trackRef.current;
    const dt = el && el.getBoundingClientRect().width > 0
      ? ((clientX - d.startX) / el.getBoundingClientRect().width) * prog
      : 0;
    if (d.mode === "move") {
      const len = d.origEnd - d.origStart;
      return { start: d.origStart + dt, end: d.origStart + dt + len };
    }
    if (d.mode === "trim-l") return { start: d.origStart + dt, end: d.origEnd };
    return { start: d.origStart, end: d.origEnd + dt };
  }

  function textDown(textId: string, start: number, end: number, mode: "move" | "trim-l" | "trim-r") {
    return (e: React.PointerEvent) => {
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      textDrag.current = { textId, mode, startX: e.clientX, origStart: start, origEnd: end };
      onSelectText?.(textId);
      setTextGhost({ textId, start, end });
    };
  }

  function textMove(e: React.PointerEvent) {
    const d = textDrag.current;
    if (!d) return;
    setTextGhost({ textId: d.textId, ...textGhostFromEvent(d, e.clientX) });
  }

  function textUp(e: React.PointerEvent) {
    const d = textDrag.current;
    if (!d) return;
    textDrag.current = null;
    setTextGhost(null);
    const g = textGhostFromEvent(d, e.clientX);
    if (d.mode === "move") onMoveText?.(d.textId, g.start);
    else if (d.mode === "trim-l") onTrimText?.(d.textId, "start", g.start);
    else onTrimText?.(d.textId, "end", g.end);
  }

  function textUpCancel() {
    textDrag.current = null;
    setTextGhost(null);
  }

  function renderClipTextLane(heightClass: string) {
    const items = clipTexts ?? [];
    if (items.length === 0) {
      return (
        <div className={`${heightClass} flex items-center overflow-hidden rounded bg-black/30 px-1.5`} aria-label="T1 texto (vazio)">
          <span className="truncate text-[10px] text-muted/60">sem textos — adiciona no painel Texto</span>
        </div>
      );
    }
    return (
      <div className={`relative ${heightClass} overflow-hidden rounded bg-black/30 p-0.5`} role="group" aria-label="T1 textos do clipe">
        {items.map((item) => {
          const ghost = textGhost?.textId === item.id ? textGhost : null;
          const start = ghost?.start ?? item.start;
          const dur = ghost ? ghost.end - ghost.start : item.duration;
          const total = Math.max(prog, 0.01);
          const left = Math.min(100, Math.max(0, (start / total) * 100));
          const width = Math.min(100 - left, Math.max(4, (dur / total) * 100));
          const selected = selectedTextId === item.id;
          return (
            <div
              key={item.id}
              role="button"
              tabIndex={0}
              aria-label={`Texto ${item.title}, ${dur.toFixed(1)} segundos`}
              title={`${item.title} Â· ${dur.toFixed(1)}s — arrasta para mover, pegas para aparar`}
              onPointerDown={textDown(item.id, item.start, item.start + item.duration, "move")}
              onPointerMove={textMove}
              onPointerUp={textUp}
              onPointerCancel={textUpCancel}
              onClick={(e) => {
                e.stopPropagation();
                onSelectText?.(selected ? null : item.id);
                onSeekText?.(item.start + 0.01);
              }}
              onKeyDown={(e) => {
                if ((e.key === "Delete" || e.key === "Backspace") && onRemoveText) onRemoveText(item.id);
              }}
              className={`absolute inset-y-0.5 overflow-hidden rounded-[4px] border text-left focus-visible:outline-2 focus-visible:outline-accent ${
                selected ? "border-accent bg-accent/25" : "border-accent/40 bg-accent/15 hover:bg-accent/25"
              }`}
              style={{ left: `${left}%`, width: `${width}%` }}
            >
              <span
                aria-hidden
                onPointerDown={textDown(item.id, item.start, item.start + item.duration, "trim-l")}
                onPointerMove={textMove}
                onPointerUp={textUp}
                onPointerCancel={textUpCancel}
                className="absolute inset-y-0 left-0 w-2 cursor-ew-resize touch-none"
                title="Aparar inÃ­cio"
              />
              <span className="flex h-full items-center gap-1 overflow-hidden px-1.5">
                <span className="truncate text-[10px] leading-[20px] text-foreground/90">T “{item.title}”</span>
              </span>
              <span
                aria-hidden
                onPointerDown={textDown(item.id, item.start, item.start + item.duration, "trim-r")}
                onPointerMove={textMove}
                onPointerUp={textUp}
                onPointerCancel={textUpCancel}
                className="absolute inset-y-0 right-0 w-2 cursor-ew-resize touch-none"
                title="Aparar fim"
              />
            </div>
          );
        })}
      </div>
    );
  }


  function renderAssemblyLane(track: TimelineTrack, heightClass: string, isAudio: boolean, emptyHint?: string) {
    if (!assembly) return null;
    const blocks = assembly.clips.filter((c) => c.track === track);
    const dropping = dropHint?.track === track;
    return (
      <div
        className={`relative ${heightClass} overflow-hidden rounded bg-black/40 ${dropping ? "outline-2 outline-accent" : ""}`}
        onDragOver={laneOverAt(track)}
        onDragLeave={() => setDropHint((current) => (current?.track === track ? null : current))}
        onDrop={laneDropAt(track)}
        role="group"
        aria-label={`Faixa ${track} — larga assets aqui`}
      >
        {blocks.length === 0 && emptyHint && (
          <span className="pointer-events-none absolute inset-0 flex items-center px-2 text-[10px] italic text-muted/70">
            {emptyHint}
          </span>
        )}
        {blocks.map((clip) => {
          const ghost = dragGhost?.clipId === clip.clip_id ? dragGhost : null;
          const start = ghost?.start ?? clip.timeline_start_s;
          const dur = ghost ? ghost.out - ghost.inn : clip.source_out_s - clip.source_in_s;
          const left = Math.min(100, Math.max(0, (start / prog) * 100));
          const width = Math.max(2, Math.min(100 - left, (dur / prog) * 100));
          const name = assetNames?.[clip.asset_id] ?? clip.asset_id.slice(0, 12);
          const selected = selectedClip === clip.clip_id;
          return (
            <div
              key={clip.clip_id}
              role="button"
              tabIndex={0}
              aria-label={`${name}, ${dur.toFixed(1)} segundos na faixa ${track}`}
              title={`${name} Â· ${dur.toFixed(1)}s — arrasta para mover, pegas para aparar`}
              onPointerDown={blockDown(clip, "move")}
              onPointerMove={blockMove}
              onPointerUp={blockUp}
              onPointerCancel={blockUpCancel}
              onClick={(e) => {
                if (suppressClick.current) {
                  suppressClick.current = false;
                  return;
                }
                e.stopPropagation();
                setSelectedClip(clip.clip_id);
                // Honest preview seek: only the session asset maps 1:1 onto
                // the viewer. Other assets just select (no fake sync).
                if (sessionAssetId && clip.asset_id === sessionAssetId) {
                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  const ratio = rect.width > 0 ? Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)) : 0;
                  onSeek(clip.source_in_s + ratio * (clip.source_out_s - clip.source_in_s));
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Delete" || e.key === "Backspace") assembly.onRemoveClip(clip.clip_id);
              }}
              className={`absolute inset-y-0.5 overflow-hidden rounded-[4px] border text-left focus-visible:outline-2 focus-visible:outline-accent ${
                isAudio ? "border-[#7a6a55]/60 bg-[#7a6a55]/20" : "border-accent/50 bg-accent/20"
              }${selected ? " outline-2 outline-accent" : ""}`}
              style={{ left: `${left}%`, width: `${width}%` }}
            >
              <span
                aria-hidden
                onPointerDown={blockDown(clip, "trim-l")}
                onPointerMove={blockMove}
                onPointerUp={blockUp}
                onPointerCancel={blockUpCancel}
                className="absolute inset-y-0 left-0 w-2 cursor-ew-resize touch-none"
                title="Aparar inÃ­cio"
              />
              {!isAudio && projectId && (
                <ClipFilmstrip
                  projectId={projectId}
                  assetId={clip.asset_id}
                  sourceIn={clip.source_in_s}
                  duration={clip.source_out_s - clip.source_in_s}
                />
              )}
              <span className="absolute left-1 top-1 flex max-w-[calc(100%-8px)] items-center gap-1 rounded bg-black/70 px-1.5 py-0.5">
                <span className="truncate text-[10px] font-medium text-foreground">
                  {name}
                </span>
                <span className="shrink-0 font-mono text-[9px] tabular-nums text-muted">
                  {dur.toFixed(1)}s
                </span>
                {selected && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      assembly.onRemoveClip(clip.clip_id);
                    }}
                    aria-label={`Remover ${name} da timeline`}
                    title="Remover da timeline"
                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-muted hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
                  </button>
                )}
              </span>
              <span
                aria-hidden
                onPointerDown={blockDown(clip, "trim-r")}
                onPointerMove={blockMove}
                onPointerUp={blockUp}
                onPointerCancel={blockUpCancel}
                className="absolute inset-y-0 right-0 w-2 cursor-ew-resize touch-none"
                title="Aparar fim"
              />
            </div>
          );
        })}
        {dropping && dropHint && (
          <span
            className="pointer-events-none absolute inset-y-0 w-0.5 bg-accent"
            style={{ left: `${Math.min(100, Math.max(0, (dropHint.t / prog) * 100))}%` }}
            aria-hidden
          />
        )}
      </div>
    );
  }

  return (
    <section aria-label="Linha de tempo" style={{ height }} className="relative flex shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-surface">
      {/* Resize grip: drag to change the timeline height. */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Altura da linha de tempo — arrasta para redimensionar"
        onPointerDown={beginResize}
        onPointerMove={moveResize}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        className="absolute inset-x-0 top-0 z-20 h-1.5 cursor-ns-resize touch-none hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp") setHeight((h) => Math.min(MAX_H, h + 12));
          if (e.key === "ArrowDown") setHeight((h) => Math.max(MIN_H, h - 12));
        }}
      />
      {/* Toolbar — tools left, scene pill centre, zoom right. */}
      <div className="relative flex h-10 shrink-0 items-center gap-0.5 border-b border-border px-3 pt-1">
        <ToolButton label="Selecionar" active>
          <svg {...iconProps}><path d="m5 3 14 7-6.5 1.5L9 18 5 3Z" /></svg>
        </ToolButton>
        <ToolButton label="Cortar" disabled>
          <svg {...iconProps}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><path d="M8 7.5 20 19M8 16.5 20 5" /></svg>
        </ToolButton>
        <ToolButton label="Duplicar" disabled>
          <svg {...iconProps}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></svg>
        </ToolButton>
        <ToolButton label="Eliminar" disabled>
          <svg {...iconProps}><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" /></svg>
        </ToolButton>
        <span className="mx-1 h-4 w-px bg-border" aria-hidden />
        <span className="hidden font-mono text-[10px] tabular-nums text-muted sm:inline">{formatTime(currentTime)} / {formatTime(duration)}</span>

        <span className="ml-auto flex items-center gap-0.5">
          {assembly && (
            <select
              value={assembly.format}
              onChange={(e) => assembly.onFormatChange(e.target.value as "source" | "landscape" | "portrait")}
              disabled={assembly.rendering}
              aria-label="Formato de saída"
              title="Original mantém o formato do vídeo; 16:9 e 9:16 forçam o canvas"
              className="mr-1 h-7 shrink-0 rounded-[6px] border border-border bg-raised px-1.5 text-[11px] text-foreground focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
            >
              <option value="source">Original</option>
              <option value="landscape">16:9</option>
              <option value="portrait">9:16</option>
            </select>
          )}
          {assembly && (
            <button
              type="button"
              onClick={assembly.onRender}
              disabled={!assembly.canRender || assembly.rendering}
              title="CompÃµe o programa com FFmpeg/OpenCV e verifica o MP4"
              className="mr-1 flex h-7 shrink-0 items-center rounded-[6px] bg-accent px-2.5 text-[11px] font-semibold text-[#14110C] transition-colors hover:bg-[#ff8a70] disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-accent"
            >
              {assembly.rendering ? "A montar…" : "Montar"}
            </button>
          )}
          <ToolButton label="Íman de posiÃ§Ã£o" active>
            <svg {...iconProps}><path d="M6 3v8a6 6 0 0 0 12 0V3M6 3h4v5H6zM14 3h4v5h-4z" /></svg>
          </ToolButton>
          <button type="button" onClick={() => setZoom((z) => Math.max(0.75, +(z - 0.25).toFixed(2)))} aria-label="Afastar linha de tempo" className="flex h-7 w-7 items-center justify-center rounded-[6px] text-muted hover:bg-raised hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">
            <svg {...iconProps}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5M8 11h6" /></svg>
          </button>
          <input type="range" min={0.75} max={3} step={0.25} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} aria-label="Zoom da linha de tempo" className="w-20 sm:w-28" />
          <button type="button" onClick={() => setZoom((z) => Math.min(3, +(z * 1 + 0.25).toFixed(2)))} aria-label="Aproximar linha de tempo" className="flex h-7 w-7 items-center justify-center rounded-[6px] text-muted hover:bg-raised hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">
            <svg {...iconProps}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5M8 11h6M11 8v6" /></svg>
          </button>
        </span>
      </div>
      {assembly?.renderError && (
        <p role="alert" className="shrink-0 border-b border-danger/40 bg-danger/10 px-3 py-1 text-[11px] text-danger">
          {assembly.renderError}
        </p>
      )}

      {/* Lanes: gutter + scrollable multitrack area. Read-only, click to seek. */}
      <div className="flex min-h-0 flex-1">
        <div className="w-14 shrink-0 border-r border-border" aria-hidden={!ideaMode}>
          <div className="h-5 border-b border-border/60" />
          {ideaMode ? (
            <>
              <div className={`${H.v1} border-b border-border/40`}><TrackHeader code="V1" title="VÃ­deo — cenas" /></div>
              <div className={`${H.t1} border-b border-border/40`}><TrackHeader code="T1" title="Texto no ecrÃ£" /></div>
              <div className={`${H.fx} border-b border-border/40`}><TrackHeader code="FX" title="AnimaÃ§Ãµes" /></div>
              <div className={`${H.a1} border-b border-border/40`}><TrackHeader code="A1" title="Áudio" /></div>
              <div className={`${H.ov} border-b border-border/40`}><TrackHeader code="OV" title="SobreposiÃ§Ãµes" /></div>
              <div className={`${H.v2} border-b border-border/40`}><TrackHeader code="V2" title="Faixa de vÃ­deo vazia" /></div>
              <div className={`${H.a2}`}><TrackHeader code="A2" title="Faixa de Ã¡udio vazia" /></div>
            </>
          ) : (
            <>
              <div className={`${H.v1} border-b border-border/40`}><TrackHeader code="V1" title="VÃ­deo — origem" /></div>
              <div className={`${H.t1} border-b border-border/40`}><TrackHeader code="T1" title="Texto (sÃ³ preview)" /></div>
              <div className={`${H.a1} border-b border-border/40`}><TrackHeader code="A1" title="Áudio original" /></div>
              <div className={`${H.v2} border-b border-border/40`}><TrackHeader code="V2" title="Faixa de vÃ­deo vazia" /></div>
              <div className={`${H.a2}`}><TrackHeader code="A2" title="Faixa de Ã¡udio vazia" /></div>
            </>
          )}
        </div>

        <div
          className="min-w-0 flex-1 overflow-auto"
          {...(assembly && !ideaMode
            ? {
                role: "group" as const,
                "aria-label": "Faixas da montagem — arrasta assets para aqui",
              }
            : {
                role: "slider" as const,
                "aria-label": "Procurar na linha de tempo",
                "aria-valuemin": 0,
                "aria-valuemax": Math.round(duration * 10) / 10,
                "aria-valuenow": Math.round(currentTime * 10) / 10,
                tabIndex: 0,
                onKeyDown: (e: React.KeyboardEvent) => {
                  if (e.key === "ArrowRight") onSeek(Math.min(duration, currentTime + 0.5));
                  if (e.key === "ArrowLeft") onSeek(Math.max(0, currentTime - 0.5));
                },
              })}
        >
          <div
            ref={trackRef}
            className={`relative min-h-full select-none ${assembly && !ideaMode ? "" : "cursor-pointer"}`}
            style={{ width: `max(100%, ${Math.ceil(Math.max(prog, 0.01) * 48 * zoom)}px)` }}
            onPointerDown={assembly && !ideaMode ? undefined : seekFromPointer}
          >
            {ruler}
            <div className="space-y-1.5 p-1.5">
              {ideaMode && scenes ? (
                <>
                  <div className={`flex ${H.v1} gap-0.5 overflow-hidden rounded bg-black/40 p-0.5`} role="group" aria-label="V1 cenas do vÃ­deo">
                    {scenes.map((scene) => {
                      const active = scene.id === activeSceneId;
                      const draggable = Boolean(onReorderScene);
                      return (
                        <button
                          key={scene.id}
                          type="button"
                          draggable={draggable}
                          onDragStart={(e) => { e.dataTransfer.setData("text/plain", scene.id); e.dataTransfer.effectAllowed = "move"; }}
                          onDragOver={(e) => { if (!draggable) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTarget(scene.id); }}
                          onDragLeave={() => setDropTarget((c) => (c === scene.id ? null : c))}
                          onDrop={(e) => {
                            e.preventDefault(); setDropTarget(null);
                            const dragId = e.dataTransfer.getData("text/plain");
                            if (!dragId || !onReorderScene) return;
                            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                            onReorderScene(dragId, scene.id, e.clientX < rect.left + rect.width / 2);
                          }}
                          title={`${scene.title} Â· ${scene.duration.toFixed(1)}s${draggable ? " Â· arrasta para reordenar" : ""}`}
                          aria-label={`Ir para a cena: ${scene.title}`}
                          onClick={(e) => { e.stopPropagation(); onSeekScene?.(scene.start + 0.01); }}
                          className={`relative h-full min-w-0 overflow-hidden rounded-[4px] text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${active ? "bg-accent/25" : "bg-raised hover:bg-border/60"}${dropTarget === scene.id ? " outline-2 outline-accent" : ""}`}
                          style={{ flexGrow: Math.max(scene.duration, 0.01), flexBasis: 0 }}
                        >
                          <span className="flex h-full items-center gap-1 px-1.5">
                            {scene.thumbUrl && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={scene.thumbUrl} alt="" aria-hidden className="h-5 w-5 shrink-0 rounded-sm object-cover" loading="lazy" />
                            )}
                            <span className={`truncate text-[10px] leading-none ${active ? "font-semibold text-accent" : "text-muted"}`}>{scene.title}</span>
                            <span className="ml-auto hidden shrink-0 font-mono text-[9px] tabular-nums text-muted/70 sm:inline">{scene.duration.toFixed(1)}s</span>
                          </span>
                          {active && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-accent" aria-hidden />}
                        </button>
                      );
                    })}
                  </div>
                  <div className={`flex ${H.t1} gap-0.5 overflow-hidden rounded bg-black/30 p-0.5`} role="group" aria-label="T1 texto no ecrÃ£">
                    {scenes.map((scene) => {
                      const active = scene.id === activeSceneId;
                      const first = scene.lines?.[0] ?? scene.title;
                      const extra = (scene.lines?.length ?? 1) - 1;
                      return (
                        <button key={scene.id} type="button" title={scene.lines?.join(" / ") ?? scene.title} aria-label={`Texto da cena ${scene.title}: ${first}`} onClick={(e) => { e.stopPropagation(); onSeekScene?.(scene.start + 0.01); }} className={`h-full min-w-0 overflow-hidden rounded-[4px] px-1.5 text-left focus-visible:outline-2 focus-visible:outline-accent ${active ? "bg-accent/15" : "bg-raised/60 hover:bg-border/50"}`} style={{ flexGrow: Math.max(scene.duration, 0.01), flexBasis: 0 }}>
                          <span className="block truncate text-[10px] leading-[20px] text-foreground/80">“{first}”{extra > 0 ? ` +${extra}` : ""}</span>
                        </button>
                      );
                    })}
                  </div>
                  <div className={`flex ${H.fx} gap-0.5 overflow-hidden rounded bg-black/30 p-0.5`} role="group" aria-label="FX animaÃ§Ãµes">
                    {scenes.map((scene) => (
                      <div key={scene.id} className="relative h-full min-w-0 overflow-hidden rounded-[4px] bg-raised/40" style={{ flexGrow: Math.max(scene.duration, 0.01), flexBasis: 0 }} title={`${scene.animations?.length ?? 0} animaÃ§Ãµes em ${scene.id}`}>
                        {(scene.animations ?? []).map((step, i) => {
                          const left = Math.min(100, Math.max(0, (step.start / Math.max(scene.duration, 0.01)) * 100));
                          const width = Math.min(100 - left, Math.max(4, (step.duration / Math.max(scene.duration, 0.01)) * 100));
                          return (
                            <button key={i} type="button" title={`${step.primitive} â†’ ${step.target}`} aria-label={`AnimaÃ§Ã£o ${step.primitive} em ${step.target}, cena ${scene.title}`} onClick={(e) => { e.stopPropagation(); onSeekScene?.(scene.start + step.start + 0.01); }} className="absolute top-0.5 h-5 overflow-hidden rounded bg-accent/30 px-1 text-left hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-accent" style={{ left: `${left}%`, width: `${width}%` }}>
                              <span className="block truncate font-mono text-[8px] leading-[20px] text-accent">{shortPrimitive(step.primitive)}</span>
                            </button>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                  <div className={`flex ${H.a1} items-center overflow-hidden rounded bg-black/40 px-1.5`} aria-label="A1 Ã¡udio da ideia">
                    <span className="truncate text-[10px] text-muted">sem Ã¡udio gerado — grava a tua narraÃ§Ã£o</span>
                  </div>
                  <div className={`relative flex ${H.ov} overflow-hidden rounded bg-black/30`} role="group" aria-label="OV sobreposiÃ§Ãµes globais">
                    {(overlays ?? []).length === 0 ? (
                      <div className="flex w-full items-center px-1.5"><span className="truncate text-[10px] text-muted/60">sem sobreposiÃ§Ãµes — adiciona em Propriedades</span></div>
                    ) : (
                      (overlays ?? []).map((overlay) => {
                        const left = duration > 0 ? Math.min(100, (overlay.start / duration) * 100) : 0;
                        const width = duration > 0 ? Math.min(100 - left, Math.max(3, (overlay.duration / duration) * 100)) : 0;
                        return (
                          <button key={overlay.id} type="button" title={`${overlay.title} Â· ${overlay.start.toFixed(1)}s`} aria-label={`SobreposiÃ§Ã£o ${overlay.title}`} onClick={(e) => { e.stopPropagation(); onSeekScene?.(overlay.start + 0.01); }} className="absolute top-1 h-5 overflow-hidden rounded bg-accent/25 px-1 text-left hover:bg-accent/45 focus-visible:outline-2 focus-visible:outline-accent" style={{ left: `${left}%`, width: `${width}%` }}>
                            <span className="block truncate text-[9px] leading-[20px] text-accent">â—† {overlay.title}</span>
                          </button>
                        );
                      })
                    )}
                  </div>
                  <div className={H.v2}>{emptyLane("Faixa de vÃ­deo vazia")}</div>
                  <div className={H.a2}>{emptyLane("Faixa de Ã¡udio vazia")}</div>
                </>
              ) : assembly ? (
                <>
                  {renderAssemblyLane("V1", H.v1, false, file || assembly.clips.length > 0 ? "Arrasta vÃ­deos para aqui" : "Importa um clipe e arrasta-o para aqui")}
                  {renderClipTextLane(H.t1)}
                  {renderAssemblyLane("A1", H.a1, true)}
                  {renderAssemblyLane("V2", H.v2, false)}
                  {renderAssemblyLane("A2", H.a2, true)}
                </>
              ) : (
                <>
                  <div className={`relative flex ${H.v1} overflow-hidden rounded bg-black/50`}>
                    {thumbs.length > 0 ? (
                      thumbs.map((src, i) => (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img key={i} src={src} alt="" width={96} height={54} loading="lazy" className="h-full flex-1 object-cover" draggable={false} />
                      ))
                    ) : (
                      <div className="flex w-full items-center border-y border-dashed border-border/50 px-2 text-[10px] text-muted">
                        {file ? "A ler fotogramas…" : "Importa um clipe — os fotogramas alinham nesta faixa"}
                      </div>
                    )}
                    <span className="absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px] text-foreground">V1 Â· Origem</span>
                    {trim && trim.original > 0 && trim.end > trim.start && (
                      <span className="absolute bottom-1 left-1 rounded bg-accent/85 px-1 font-mono text-[9px] text-[#14110C]" title={`Corte ${trim.start.toFixed(1)}s â†’ ${trim.end.toFixed(1)}s`}>
                        corte {trim.start.toFixed(1)}–{trim.end.toFixed(1)}s
                      </span>
                    )}
                    {editedReady && (
                      <span className="absolute bottom-1 right-1 rounded bg-success/85 px-1 text-[9px] font-semibold text-[#0b0906]">Editado Â· verificado</span>
                    )}
                  </div>
                  {renderClipTextLane(H.t1)}
                  <div className={`relative flex ${H.a1} items-center overflow-hidden rounded bg-black/40 px-0.5`}>
                    {!file ? (
                      <span className="px-1 text-[10px] text-muted/70">sem clipe</span>
                    ) : hasAudio === false ? (
                      <span className="px-1 text-[10px] text-muted">origem sem Ã¡udio</span>
                    ) : peaks ? (
                      peaks.map((p, i) => (
                        <span key={i} className="mx-px w-full rounded-sm bg-[#7a6a55]" style={{ height: `${Math.max(12, p * 100)}%` }} />
                      ))
                    ) : (
                      <span className="px-1 text-[10px] text-muted">sem forma de onda para este formato</span>
                    )}
                  </div>
                  <div className={H.v2}>{emptyLane("Faixa de vÃ­deo vazia")}</div>
                  <div className={H.a2}>{emptyLane("Faixa de Ã¡udio vazia")}</div>
                </>
              )}
            </div>
            <div className="pointer-events-none absolute inset-y-0 z-10" style={{ left: `${playheadPct}%` }} aria-hidden>
              <div className="h-full w-px bg-accent" />
              <div className="absolute -left-[5px] top-0 h-2.5 w-[11px] rounded-b bg-accent" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
