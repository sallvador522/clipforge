"use client";

import { useEffect, useRef, useState } from "react";
import { formatTime } from "./MediaPanel";

interface Props {
  file: File | null;
  duration: number;
  currentTime: number;
  hasAudio: boolean | null;
  onSeek: (time: number) => void;
}

const THUMB_COUNT = 10;
const PEAK_COUNT = 72;

export function Timeline({ file, duration, currentTime, hasAudio, onSeek }: Props) {
  const [thumbs, setThumbs] = useState<string[]>([]);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);

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

    video.addEventListener("loadedmetadata", () => {
      const total = video.duration || 0;
      let index = 0;
      const captureNext = () => {
        if (cancelled) return;
        if (index >= THUMB_COUNT || total <= 0) {
          setThumbs(captured);
          URL.revokeObjectURL(url);
          return;
        }
        video.currentTime = (total * (index + 0.5)) / THUMB_COUNT;
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
      // Detach before revoking so the decoder never requests a revoked blob.
      video.removeAttribute("src");
      video.load();
      URL.revokeObjectURL(url);
    };
  }, [file]);

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
        setPeaks(values);
      } catch {
        if (!cancelled) setPeaks(null); // container not decodable in-browser; we show no fake waveform
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [file, hasAudio]);

  function seekFromPointer(e: React.PointerEvent) {
    const track = trackRef.current;
    if (!track || duration <= 0) return;
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(ratio * duration);
  }

  const playheadPct = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;
  const tickEvery = duration > 5 ? 1 : 0.5;
  const ticks: number[] = [];
  for (let t = 0; t <= Math.max(duration, 0) + 0.001; t += tickEvery) ticks.push(t);

  return (
    <section aria-label="Timeline" className="shrink-0 border-t border-border bg-surface">
      <div className="flex items-center justify-between px-3 pt-1.5">
        <h2 className="font-mono text-[11px] font-medium tracking-wider text-muted">TIMELINE</h2>
        <span className="ml-2 truncate font-mono text-[11px] tabular-nums text-muted">
          {formatTime(currentTime)} / {formatTime(duration)} <span className="hidden sm:inline">· single clip (MVP)</span>
        </span>
      </div>

      <div
        ref={trackRef}
        className="relative mx-3 mb-2.5 mt-1 cursor-pointer select-none rounded focus-visible:outline-2 focus-visible:outline-accent"
        onPointerDown={seekFromPointer}
        role="slider"
        aria-label="Timeline seek"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration * 10) / 10}
        aria-valuenow={Math.round(currentTime * 10) / 10}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") onSeek(Math.min(duration, currentTime + 0.5));
          if (e.key === "ArrowLeft") onSeek(Math.max(0, currentTime - 0.5));
        }}
      >
        {/* ruler */}
        <div className="relative h-4 border-b border-border/60">
          {ticks.map((t, i) => (
            <span
              key={t}
              className={`absolute top-0 font-mono text-[9px] tabular-nums text-muted/70 ${i === 0 ? "" : i === ticks.length - 1 ? "-translate-x-full" : "-translate-x-1/2"}`}
              style={{ left: `${duration ? (t / duration) * 100 : 0}%` }}
            >
              {t.toFixed(tickEvery < 1 ? 1 : 0)}s
            </span>
          ))}
        </div>
        {/* video clip strip */}
        <div className="relative mt-1 flex h-11 overflow-hidden rounded bg-black/50">
          {thumbs.length > 0 ? (
            thumbs.map((src, i) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={i} src={src} alt="" width={96} height={54} loading="lazy" className="h-full flex-1 object-cover" draggable={false} />
            ))
          ) : (
            <div className="flex w-full items-center px-2 font-mono text-[10px] text-muted">
              {file ? "Reading frames…" : "Import a clip — its frames will line this track"}
            </div>
          )}
          <span className="absolute bottom-0.5 left-1 rounded bg-black/70 px-1 font-mono text-[9px] text-foreground">V1 · SOURCE</span>
        </div>
        {/* audio track */}
        <div className="relative mt-1 flex h-6 items-center overflow-hidden rounded bg-black/40 px-0.5">
          {!file ? (
            <span className="px-1.5 font-mono text-[9px] text-muted">A1 · NO CLIP IMPORTED</span>
          ) : hasAudio === false ? (
            <span className="px-1.5 font-mono text-[9px] text-muted">A1 · NO AUDIO IN SOURCE</span>
          ) : peaks ? (
            <>
              {peaks.map((p, i) => (
                <span key={i} className="mx-px w-full rounded-sm bg-[#7A6A55]" style={{ height: `${Math.max(12, p * 100)}%` }} />
              ))}
              <span className="absolute bottom-0 left-1 rounded bg-black/70 px-1 font-mono text-[9px]">A1 · ORIGINAL AUDIO</span>
            </>
          ) : (
            <span className="px-1.5 font-mono text-[9px] text-muted">A1 · AUDIO PEAKS UNAVAILABLE FOR THIS CONTAINER</span>
          )}
        </div>
        {/* playhead */}
        <div className="pointer-events-none absolute inset-y-0" style={{ left: `${playheadPct}%` }} aria-hidden>
          <div className="h-full w-px bg-accent" />
          <div className="absolute -left-[5px] top-0 h-2.5 w-[11px] rounded-b bg-accent" />
        </div>
      </div>
    </section>
  );
}
