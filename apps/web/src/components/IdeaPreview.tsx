"use client";

/* Centre column of the idea workspace.
 *
 * Before a render exists it plays the real scene engine (the same component
 * the worker captures), so the preview is not a mock-up. Once the worker has
 * produced a verified MP4, the final file becomes the primary view and the
 * storyboard stays available for inspection.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import SceneRenderer, { type SceneRendererHandle } from "./SceneRenderer";
import type { IdeaPayload } from "@/lib/idea-types";

const STAGE_LABELS: Record<string, string> = {
  awaiting_storyboard_cost: "À espera da aprovação do plano",
  planning: "A criar o plano",
  awaiting_plan_approval: "Plano pronto para revisão",
  generating_assets: "A gerar imagens",
  rendering: "A capturar frames",
  verifying_frames: "A verificar frames",
  encoding: "A codificar o vídeo",
  verifying_output: "A verificar o ficheiro final",
  completed: "Concluído",
  failed: "Falhou",
  rejected: "Rejeitado",
};

const WORKING_STAGES = new Set([
  "planning",
  "generating_assets",
  "rendering",
  "verifying_frames",
  "encoding",
  "verifying_output",
]);

function stageLabel(stage: string | undefined): string {
  if (!stage) return "Pronto";
  return STAGE_LABELS[stage] ?? stage;
}

function stageSize(idea: IdeaPayload): { width: number; height: number } {
  return idea.options.aspect_ratio === "16:9"
    ? { width: 1280, height: 720 }
    : { width: 720, height: 1280 };
}

function formatTime(ms: number): string {
  const total = Math.max(0, Math.round(ms / 100) / 10);
  return `${total.toFixed(1)}s`;
}

interface Props {
  idea: IdeaPayload | null;
  busy: string | null;
}

export function IdeaPreview({ idea, busy }: Props) {
  const rendererRef = useRef<SceneRendererHandle>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [scale, setScale] = useState(0.32);
  const [view, setView] = useState<"storyboard" | "video">("storyboard");

  const board = idea?.storyboard ?? null;
  const render = idea?.render ?? null;
  const size = useMemo(() => (idea ? stageSize(idea) : { width: 720, height: 1280 }), [idea]);
  const durationMs = board ? board.duration_seconds * 1000 : 0;
  const working = Boolean(idea && WORKING_STAGES.has(idea.stage));

  // The final MP4 takes over as soon as a verified render exists.
  useEffect(() => {
    if (render) setView("video");
  }, [render?.sha256]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new plan invalidates the previous playhead.
  useEffect(() => {
    setPlaying(false);
    setTime(0);
    rendererRef.current?.seek(0);
  }, [idea?.storyboard_hash]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fit the fixed-size stage inside the available column.
  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) return;
      const next = Math.min(rect.width / size.width, rect.height / size.height);
      setScale(Math.max(0.05, Math.min(next, 1)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [size.width, size.height, view]);

  // Playhead follows the Anime timeline while playing.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const current = rendererRef.current?.debug().currentTime ?? 0;
      setTime(current);
      if (durationMs > 0 && current >= durationMs - 8) {
        rendererRef.current?.pause();
        setTime(durationMs);
        setPlaying(false);
        return;
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, durationMs]);

  function togglePlay() {
    if (!rendererRef.current) return;
    if (playing) {
      rendererRef.current.pause();
      setPlaying(false);
      return;
    }
    if (durationMs > 0 && time >= durationMs - 20) {
      rendererRef.current.seek(0);
      setTime(0);
    }
    rendererRef.current.play();
    setPlaying(true);
  }

  function scrub(ms: number) {
    rendererRef.current?.pause();
    setPlaying(false);
    setTime(ms);
    rendererRef.current?.seek(ms);
  }

  const progress = idea?.progress;
  const percent =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.current / progress.total) * 100))
      : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex min-h-10 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface px-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tracking-[0.16em] text-muted">PREVIEW</span>
          {idea && (
            <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted">
              {idea.options.aspect_ratio} · {idea.options.fps} FPS
            </span>
          )}
        </div>
        {render && (
          <div className="flex items-center gap-1 rounded-full border border-border bg-raised p-0.5">
            {(["video", "storyboard"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setView(value)}
                aria-pressed={view === value}
                className={`rounded-full px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] transition-colors ${
                  view === value ? "bg-accent text-[#14110C]" : "text-muted hover:text-foreground"
                }`}
              >
                {value === "video" ? "VÍDEO FINAL" : "STORYBOARD"}
              </button>
            ))}
          </div>
        )}
      </header>

      {!idea && (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <div className="max-w-sm text-center">
            <div className="relative mx-auto mb-5 flex h-16 w-16 items-center justify-center">
              <span className="absolute inset-0 rounded-full border border-accent/30" />
              <span className="absolute inset-2 rounded-full border border-accent/50" />
              <span className="h-4 w-4 rounded-full bg-accent shadow-[0_0_28px_rgba(255,118,89,.6)]" />
            </div>
            <p className="font-mono text-[10px] tracking-[0.16em] text-accent">IDEA-TO-VIDEO</p>
            <h2 className="mt-1 text-lg font-semibold">Descreve. Aprova. Recebe o vídeo.</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-muted">
              Escreve a ideia à esquerda. O director propõe um storyboard, tu aprovas o custo e o
              worker renderiza um MP4 verificado no teu computador.
            </p>
            <p className="mt-4 font-mono text-[10px] leading-relaxed text-muted">
              Nada é gerado sem aprovação explícita.
            </p>
          </div>
        </div>
      )}

      {idea && !board && (
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] tracking-[0.16em] text-accent">
                {working ? "EM CURSO" : "PLANO"}
              </span>
              <span className="font-mono text-[10px] text-muted">{idea.status}</span>
            </div>
            <p className="mt-2 text-[15px] font-semibold">{stageLabel(idea.stage)}</p>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              {working
                ? "O worker está a preparar o plano. Esta página atualiza sozinha."
                : "Aprova o custo do plano no painel à direita para continuar."}
            </p>
            {percent !== null && (
              <>
                <div className="mt-4 h-1 overflow-hidden rounded-full bg-raised">
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-500"
                    style={{ width: `${percent}%` }}
                  />
                </div>
                <p className="mt-1.5 text-right font-mono text-[10px] text-muted">
                  {progress?.current ?? 0}/{progress?.total ?? 0}
                </p>
              </>
            )}
          </div>
        </div>
      )}

      {idea && board && view === "video" && render && (
        <div className="flex min-h-0 flex-1 flex-col bg-[#0b0906] p-4">
          <div className="flex min-h-0 flex-1 items-center justify-center">
            <video
              key={render.sha256}
              controls
              playsInline
              preload="metadata"
              src={render.url}
              className="max-h-full max-w-full rounded-md border border-border bg-black"
              style={{ aspectRatio: `${render.width} / ${render.height}` }}
            />
          </div>
          <p className="mt-2 text-center font-mono text-[10px] text-muted">
            MP4 verificado · {render.width}×{render.height} · {render.fps} FPS ·{" "}
            {render.duration_seconds.toFixed(2)}s · {render.frame_count} frames
          </p>
        </div>
      )}

      {idea && board && view === "storyboard" && (
        <>
          <div ref={wrapRef} className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden p-4">
            <div
              className="relative shrink-0 overflow-hidden rounded-md shadow-[0_0_0_1px_#2e2820,0_24px_60px_rgba(0,0,0,.45)]"
              style={{ width: size.width * scale, height: size.height * scale }}
            >
              <div style={{ transform: `scale(${scale})`, transformOrigin: "top left" }}>
                <SceneRenderer
                  ref={rendererRef}
                  board={board}
                  width={size.width}
                  height={size.height}
                />
              </div>
            </div>

            {working && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#0b0906] to-transparent px-4 pb-4 pt-10">
                <div className="mx-auto max-w-sm">
                  <div className="flex items-center justify-between font-mono text-[10px] text-muted">
                    <span>{stageLabel(idea.stage)}</span>
                    {percent !== null && <span>{percent}%</span>}
                  </div>
                  <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-raised">
                    <div
                      className="h-full rounded-full bg-accent transition-[width] duration-500"
                      style={{ width: `${percent ?? 8}%` }}
                    />
                  </div>
                </div>
              </div>
            )}

            {!working && idea.can_approve_assets && (
              <div className="pointer-events-none absolute left-4 top-4 rounded-full border border-accent/40 bg-[#14110c]/90 px-2.5 py-1 font-mono text-[10px] tracking-[0.1em] text-accent">
                PLANO POR APROVAR
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border bg-surface px-4 py-3">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={togglePlay}
                aria-label={playing ? "Pausar pré-visualização" : "Reproduzir pré-visualização"}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-[#14110C] transition-colors hover:bg-[#ff8a70] focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
              >
                {playing ? (
                  <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden>
                    <rect x="0" y="0" width="3.5" height="12" rx="1" fill="currentColor" />
                    <rect x="6.5" y="0" width="3.5" height="12" rx="1" fill="currentColor" />
                  </svg>
                ) : (
                  <svg width="11" height="12" viewBox="0 0 10 12" fill="none" aria-hidden>
                    <path d="M1 1.5v9l8-4.5-8-4.5Z" fill="currentColor" />
                  </svg>
                )}
              </button>

              <div className="min-w-0 flex-1">
                <div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-raised" aria-hidden>
                  {board.scenes.map((scene) => (
                    <span
                      key={scene.scene_id}
                      className="h-full bg-border"
                      style={{ flexGrow: scene.duration_ms }}
                    />
                  ))}
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, durationMs)}
                  step={40}
                  value={Math.min(time, durationMs)}
                  onChange={(event) => scrub(Number(event.target.value))}
                  aria-label="Posição na pré-visualização"
                  className="mt-1.5 w-full"
                />
              </div>

              <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted">
                {formatTime(time)} / {formatTime(durationMs)}
              </span>
            </div>

            <div className="mt-1 flex items-center justify-between gap-3 font-mono text-[10px] text-muted">
              <span className="truncate">
                {board.scenes.length} cenas · {board.project_title}
              </span>
              {busy === "create" && <span className="text-accent">a criar plano…</span>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
