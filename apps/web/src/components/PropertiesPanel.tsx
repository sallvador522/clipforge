"use client";

/* Right-column inspector, above the Muse chat.
 * Empty state mirrors a professional editor: nothing selected, nothing
 * invented. When a job / plan / active scene exists it shows only facts
 * the backend already reported. Idea approvals render as `children`. */

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { ClipTrimAudio, type ClipAudio, type ClipTrim } from "./ClipTrimAudio";
import { CLIP_TEXT_COLOURS } from "@/lib/textOverlays";
import type { VideoAnalysisData } from "@/lib/api";

export type VideoAnalysisStatus =
  | "idle" | "loading" | "confirm" | "working" | "done" | "error" | "stale";

export interface VideoAnalysisPanelState {
  status: VideoAnalysisStatus;
  analysis: VideoAnalysisData | null;
  error: string | null;
  estimateText: string;
  onCheck: () => void;
  onStartConfirm: () => void;
  onCancelConfirm: () => void;
  onAnalyze: () => void;
}

export interface SelectedAssetInfo {
  asset_id: string;
  original_filename: string;
  kind: string;
  duration_seconds?: number | null;
  size_bytes: number;
  width?: number | null;
  height?: number | null;
  audio_codec?: string | null;
  provenance: string;
}

const ASSET_KIND_LABELS: Record<string, string> = {
  video: "Vídeo",
  audio: "Áudio",
  image: "Imagem",
  text: "Texto",
  graphics: "Gráficos",
};

export function formatAssetBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface ActiveSceneInfo {
  title: string;
  start: number;
  duration: number;
  lines: string[];
  transitionOut: string | null;
}

export interface ClipTextEditInfo {
  id: string;
  text: string;
  style: string;
  start: number;
  duration: number;
  x: number;
  y: number;
  scale: number;
  color: string;
  weight: "normal" | "bold";
  styleOptions: { id: string; label: string }[];
}

interface Props {
  children?: ReactNode;
  fileName: string | null;
  statusText: string | null;
  meta: { width: number; height: number; duration_seconds: number; has_audio: boolean; frame_count: number; fps: number } | null;
  planSummary: string | null;
  resultReady: boolean;
  activeScene: ActiveSceneInfo | null;
  onOpenPlanReview: () => void;
  hasPlan: boolean;
  /** ADR-044: the library asset selected in Recursos. */
  selectedAsset?: SelectedAssetInfo | null;
  /** ADR-057: native video understanding for the selected video asset. */
  videoAnalysis?: VideoAnalysisPanelState | null;
  onClearSelection?: () => void;
  clipEdit?: {
    canEdit: boolean;
    busy: boolean;
    duration: number | undefined;
    trim: ClipTrim | null;
    audio: ClipAudio | null;
    hasAudio: boolean | null;
    onSaveTrim: (start: number, end: number) => Promise<unknown>;
    onClearTrim: () => Promise<unknown>;
    onSaveAudio: (gain: number, fadeIn: number, fadeOut: number) => Promise<unknown>;
  } | null;
  /** Fase 1 preview-only clip text selected in Viewer/Timeline/Texto. */
  selectedText?: ClipTextEditInfo | null;
  onUpdateText?: (patch: Partial<ClipTextEditInfo>) => void;
  onDeleteText?: () => void;
  colourEdit?: {
    contrast: number;
    brightness: number;
    saturation: number;
    busy: boolean;
    onSave: (colour: { contrast: number; brightness: number; saturation: number }) => Promise<unknown> | void;
    note?: string | null;
  } | null;
}

function Row({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="shrink-0 text-[11px] text-muted">{label}</dt>
      <dd className={`truncate text-right text-[12px] text-foreground/90 ${mono ? "font-mono tabular-nums" : ""}`} title={value}>{value}</dd>
    </div>
  );
}

export function PropertiesPanel({ children, fileName, statusText, meta, planSummary, resultReady, activeScene, onOpenPlanReview, hasPlan, clipEdit, selectedAsset, videoAnalysis, onClearSelection, selectedText, onUpdateText, onDeleteText, colourEdit }: Props) {
  const hasSelectedVideo = selectedAsset != null && selectedAsset.kind === "video";
  const hasContent = Boolean(children || meta || fileName || activeScene || hasPlan || clipEdit?.canEdit || selectedAsset || selectedText || colourEdit || (videoAnalysis && hasSelectedVideo));
  // Colour sliders: local draft, applied explicitly (each render is real work).
  const [contrast, setContrast] = useState(colourEdit?.contrast ?? 1);
  const [brightness, setBrightness] = useState(colourEdit?.brightness ?? 0);
  const [saturation, setSaturation] = useState(colourEdit?.saturation ?? 1);
  useEffect(() => {
    setContrast(colourEdit?.contrast ?? 1);
    setBrightness(colourEdit?.brightness ?? 0);
    setSaturation(colourEdit?.saturation ?? 1);
  }, [colourEdit?.contrast, colourEdit?.brightness, colourEdit?.saturation]);
  const colourDirty =
    colourEdit != null &&
    (contrast !== colourEdit.contrast || brightness !== colourEdit.brightness || saturation !== colourEdit.saturation);
  return (
    <section aria-label="Propriedades" className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-border px-4">
        <h2 className="text-[12px] font-semibold">Propriedades</h2>
        {statusText && <span className="truncate font-mono text-[10px] text-muted">{statusText}</span>}
      </header>
      {children ? (
        <div className="min-h-0 overflow-y-auto">{children}</div>
      ) : !hasContent ? (
        <div className="flex flex-col items-center px-6 py-8 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-lg border border-border bg-raised/60 text-muted" aria-hidden>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <path d="M5 7h9M18 7h1M5 12h3M12 12h7M5 17h11M20 17h-1" />
              <circle cx="16" cy="7" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="17" r="2" />
            </svg>
          </span>
          <p className="mt-3 text-[13px] font-semibold">Está vazio aqui</p>
          <p className="mt-1 max-w-[230px] text-[12px] leading-relaxed text-muted">
            Clica numa cena ou faixa da linha de tempo para veres as propriedades.
          </p>
        </div>
      ) : (
        <div className="min-h-0 overflow-y-auto px-4 py-2.5">
          {selectedText && (
            <div className="border-b border-border/70 pb-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-medium text-accent">Texto selecionado · sai no MP4</p>
                {onDeleteText && (
                  <button
                    type="button"
                    onClick={onDeleteText}
                    aria-label="Remover texto"
                    className="shrink-0 text-[11px] text-danger underline underline-offset-2 hover:opacity-80 focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    remover
                  </button>
                )}
              </div>
              <label className="mt-1.5 block">
                <span className="text-[11px] text-muted">Conteúdo (max 140)</span>
                <input
                  type="text"
                  value={selectedText.text}
                  maxLength={140}
                  onChange={(e) => onUpdateText?.({ text: e.target.value.slice(0, 140) })}
                  aria-label="Conteúdo do texto"
                  className="mt-1 w-full rounded-[6px] border border-border bg-raised px-2 py-1.5 text-[12px] focus-visible:outline-2 focus-visible:outline-accent"
                />
              </label>
              <div className="mt-2">
                <span className="text-[11px] text-muted">Cor</span>
                <div className="mt-1 flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="Cor do texto">
                  {CLIP_TEXT_COLOURS.map((c) => {
                    const active = (selectedText.color || "#FFFFFF").toUpperCase() === c.hex;
                    return (
                      <button
                        key={c.hex}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        title={c.label}
                        aria-label={`Cor ${c.label}`}
                        onClick={() => onUpdateText?.({ color: c.hex })}
                        className={`flex h-6 w-6 items-center justify-center rounded-full border focus-visible:outline-2 focus-visible:outline-accent ${
                          active ? "border-accent ring-1 ring-accent" : "border-border hover:border-muted"
                        }`}
                        style={{ backgroundColor: c.hex }}
                      >
                        {active && (
                          <span aria-hidden className="text-[10px] font-bold" style={{ color: c.hex === "#000000" ? "#fff" : "#000" }}>✓</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="text-[11px] text-muted">Estilo</span>
                  <select
                    value={selectedText.style}
                    onChange={(e) => onUpdateText?.({ style: e.target.value })}
                    aria-label="Estilo de animação"
                    className="mt-1 w-full rounded-[6px] border border-border bg-raised px-2 py-1.5 text-[12px] focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    {selectedText.styleOptions.map((opt) => (
                      <option key={opt.id} value={opt.id}>{opt.label}</option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-[11px] text-muted">Peso</span>
                  <select
                    value={selectedText.weight}
                    onChange={(e) => onUpdateText?.({ weight: e.target.value as "normal" | "bold" })}
                    aria-label="Peso da fonte"
                    className="mt-1 w-full rounded-[6px] border border-border bg-raised px-2 py-1.5 text-[12px] focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    <option value="bold">Negrito</option>
                    <option value="normal">Normal</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-[11px] text-muted">Tamanho</span>
                  <input
                    type="range"
                    min={0.7}
                    max={1.6}
                    step={0.1}
                    value={selectedText.scale}
                    onChange={(e) => onUpdateText?.({ scale: Number(e.target.value) })}
                    aria-label="Tamanho do texto"
                    className="mt-2 w-full"
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] text-muted">Início (s)</span>
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={Number(selectedText.start.toFixed(2))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isFinite(v) && v >= 0) onUpdateText?.({ start: v });
                    }}
                    aria-label="Início do texto em segundos"
                    className="mt-1 w-full rounded-[6px] border border-border bg-raised px-2 py-1.5 font-mono text-[12px] tabular-nums focus-visible:outline-2 focus-visible:outline-accent"
                  />
                </label>
                <label className="block">
                  <span className="text-[11px] text-muted">Duração (s)</span>
                  <input
                    type="number"
                    min={0.5}
                    max={8}
                    step={0.1}
                    value={Number(selectedText.duration.toFixed(2))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isFinite(v) && v >= 0.5) onUpdateText?.({ duration: Math.min(8, v) });
                    }}
                    aria-label="Duração do texto em segundos"
                    className="mt-1 w-full rounded-[6px] border border-border bg-raised px-2 py-1.5 font-mono text-[12px] tabular-nums focus-visible:outline-2 focus-visible:outline-accent"
                  />
                </label>
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
                Posição x {Math.round(selectedText.x * 100)}% · y {Math.round(selectedText.y * 100)}% — arrasta no palco. Duplo clique no palco edita o texto. Incluído no MP4 do Montar.
              </p>
            </div>
          )}
          {selectedAsset && (
            <div className="border-b border-border/70 pb-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-medium text-accent">Asset selecionado</p>
                {onClearSelection && (
                  <button
                    type="button"
                    onClick={onClearSelection}
                    aria-label="Limpar seleção"
                    className="shrink-0 text-[11px] text-muted underline underline-offset-2 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    limpar
                  </button>
                )}
              </div>
              <p className="mt-0.5 truncate text-[12px] font-medium" title={selectedAsset.original_filename}>
                {selectedAsset.original_filename}
              </p>
              <dl className="mt-1 divide-y divide-border/50">
                <Row label="Tipo" value={ASSET_KIND_LABELS[selectedAsset.kind] ?? selectedAsset.kind} mono={false} />
                {selectedAsset.duration_seconds ? (
                  <Row label="Duração" value={`${selectedAsset.duration_seconds.toFixed(1)}s`} />
                ) : null}
                {selectedAsset.width && selectedAsset.height ? (
                  <Row label="Resolução" value={`${selectedAsset.width} × ${selectedAsset.height}`} />
                ) : null}
                {selectedAsset.kind === "audio" && selectedAsset.audio_codec ? (
                  <Row label="Áudio" value={selectedAsset.audio_codec} mono={false} />
                ) : null}
                <Row label="Tamanho" value={formatAssetBytes(selectedAsset.size_bytes)} />
                {selectedAsset.provenance === "generated" ? (
                  <Row label="Origem" value="Gerado pelo Muse" mono={false} />
                ) : null}
              </dl>
              {(selectedAsset.kind === "video" || selectedAsset.kind === "audio") && selectedAsset.duration_seconds ? (
                <p className="mt-1 text-[11px] leading-relaxed text-muted">
                  Arrasta para uma faixa da timeline para usar.
                </p>
              ) : null}
              {selectedAsset.kind === "video" && videoAnalysis && (
                <div className="mt-2 rounded-[6px] border border-border/70 bg-raised/40 p-2.5" role="group" aria-label="Análise do vídeo">
                  <p className="text-[11px] font-medium">Análise do vídeo</p>
                  {videoAnalysis.status === "idle" && (
                    <div className="mt-1.5">
                      <button
                        type="button"
                        onClick={videoAnalysis.onCheck}
                        className="w-full rounded-[6px] border border-accent/50 px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-accent hover:text-[#14110C] focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        Analisar vídeo
                      </button>
                    </div>
                  )}
                  {videoAnalysis.status === "loading" && (
                    <p className="mt-1.5 text-[11px] text-muted" role="status">A verificar análise…</p>
                  )}
                  {videoAnalysis.status === "confirm" && (
                    <div className="mt-1.5">
                      <p className="text-[11px] leading-relaxed text-muted">
                        Isto envia o vídeo para a Meta para análise visual. {videoAnalysis.estimateText}
                      </p>
                      <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                        <button
                          type="button"
                          onClick={videoAnalysis.onAnalyze}
                          className="rounded-[6px] bg-accent px-2.5 py-1.5 text-[12px] font-semibold text-[#14110C] transition-colors hover:bg-[#ff8a70] focus-visible:outline-2 focus-visible:outline-accent"
                        >
                          Analisar
                        </button>
                        <button
                          type="button"
                          onClick={videoAnalysis.onCancelConfirm}
                          className="rounded-[6px] border border-border px-2.5 py-1.5 text-[12px] text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  )}
                  {videoAnalysis.status === "working" && (
                    <p className="mt-1.5 text-[11px] text-muted" role="status">A analisar o vídeo… pode demorar um minuto. Não feches o painel.</p>
                  )}
                  {videoAnalysis.status === "error" && (
                    <div className="mt-1.5">
                      <p className="text-[11px] leading-relaxed text-danger" role="alert">{videoAnalysis.error ?? "A análise falhou. Tenta de novo."}</p>
                      <button
                        type="button"
                        onClick={videoAnalysis.onCheck}
                        className="mt-1.5 w-full rounded-[6px] border border-border px-2.5 py-1.5 text-[12px] text-muted transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        Tentar de novo
                      </button>
                    </div>
                  )}
                  {videoAnalysis.status === "stale" && (
                    <div className="mt-1.5">
                      <p className="text-[11px] leading-relaxed text-muted">O vídeo mudou desde a última análise.</p>
                      <button
                        type="button"
                        onClick={videoAnalysis.onStartConfirm}
                        className="mt-1.5 w-full rounded-[6px] border border-accent/50 px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-accent hover:text-[#14110C] focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        Analisar de novo
                      </button>
                    </div>
                  )}
                  {videoAnalysis.status === "done" && videoAnalysis.analysis && (
                    <div className="mt-1.5 space-y-1.5">
                      {videoAnalysis.analysis.is_mock && (
                        <p className="text-[10px] font-medium text-accent">Análise simulada — sem chamada ao modelo.</p>
                      )}
                      {videoAnalysis.analysis.overall_summary && (
                        <p className="text-[12px] leading-relaxed">{videoAnalysis.analysis.overall_summary}</p>
                      )}
                      {!videoAnalysis.analysis.overall_summary && videoAnalysis.analysis.raw_text && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[11px] text-muted underline underline-offset-2 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">
                            Ver análise completa (texto do modelo)
                          </summary>
                          <p className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap text-[12px] leading-relaxed text-foreground/90">{videoAnalysis.analysis.raw_text}</p>
                        </details>
                      )}
                      {videoAnalysis.analysis.important_moments.length > 0 && (
                        <div>
                          <p className="text-[10px] font-medium uppercase tracking-wide text-muted">Momentos</p>
                          <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[12px] leading-relaxed">
                            {videoAnalysis.analysis.important_moments.slice(0, 4).map((m, i) => (
                              <li key={i}>
                                {m.at_s != null && (
                                  <span className="font-mono text-[11px] text-accent">
                                    {String(Math.floor(m.at_s / 60)).padStart(2, "0")}:{String(Math.floor(m.at_s % 60)).padStart(2, "0")}{" "}
                                  </span>
                                )}
                                {m.label}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {videoAnalysis.analysis.editing_opportunities.length > 0 && (
                        <div>
                          <p className="text-[10px] font-medium uppercase tracking-wide text-muted">Melhorias</p>
                          <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[12px] leading-relaxed">
                            {videoAnalysis.analysis.editing_opportunities.slice(0, 4).map((op, i) => (
                              <li key={i}>{op}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {videoAnalysis.analysis.uncertainties.length > 0 && (
                        <p className="text-[11px] leading-relaxed text-muted">
                          Por confirmar: {videoAnalysis.analysis.uncertainties.slice(0, 2).join(" · ")}
                        </p>
                      )}
                      <button
                        type="button"
                        onClick={videoAnalysis.onStartConfirm}
                        className="w-full text-center text-[11px] text-muted underline underline-offset-2 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        Analisar de novo
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          {activeScene && (
            <div className="border-b border-border/70 pb-2">
              <p className="text-[10px] font-medium text-accent">Cena selecionada</p>
              <p className="mt-0.5 truncate text-[12px] font-medium" title={activeScene.title}>{activeScene.title}</p>
              <dl className="mt-1 divide-y divide-border/50">
                <Row label="Início" value={`${activeScene.start.toFixed(1)}s`} />
                <Row label="Duração" value={`${activeScene.duration.toFixed(1)}s`} />
                <Row label="Transição" value={activeScene.transitionOut ?? "corte"} />
                {activeScene.lines[0] && <Row label="Texto" value={activeScene.lines[0]} mono={false} />}
              </dl>
            </div>
          )}
          {(meta || fileName) && (
            <dl className="divide-y divide-border/50">
              {fileName && <Row label="Ficheiro" value={fileName} mono={false} />}
              {meta && <Row label="Resolução" value={`${meta.width} × ${meta.height}`} />}
              {meta && <Row label="Duração" value={`${meta.duration_seconds.toFixed(1)}s`} />}
              {meta && <Row label="Fotogramas" value={`${meta.frame_count} @ ${meta.fps.toFixed(0)} fps`} />}
              {meta && <Row label="Áudio" value={meta.has_audio ? "com áudio" : "sem áudio"} />}
              <Row label="Resultado" value={resultReady ? "editado · verificado" : "por gerar"} />
            </dl>
          )}
          {clipEdit?.canEdit && clipEdit.duration !== undefined && (
            <div className="mt-1">
              <ClipTrimAudio
                duration={clipEdit.duration}
                trim={clipEdit.trim}
                audio={clipEdit.audio}
                hasAudio={clipEdit.hasAudio}
                busy={clipEdit.busy}
                onSaveTrim={clipEdit.onSaveTrim}
                onClearTrim={clipEdit.onClearTrim}
                onSaveAudio={clipEdit.onSaveAudio}
              />
            </div>
          )}
          {colourEdit && (
            <div className="mt-1 border-b border-border/70 pb-2.5">
              <p className="text-[10px] font-medium text-accent">Cor do vídeo · sai no MP4</p>
              {[
                { label: "Contraste", min: 0.5, max: 1.5, step: 0.05, value: contrast, set: setContrast, fmt: (v: number) => v.toFixed(2) },
                { label: "Brilho", min: -0.3, max: 0.3, step: 0.05, value: brightness, set: setBrightness, fmt: (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2) },
                { label: "Saturação", min: 0, max: 2, step: 0.1, value: saturation, set: setSaturation, fmt: (v: number) => v.toFixed(1) },
              ].map((row) => (
                <label key={row.label} className="mt-1.5 block">
                  <span className="flex items-baseline justify-between text-[11px] text-muted">
                    <span>{row.label}</span>
                    <span className="font-mono tabular-nums text-foreground/80">{row.fmt(row.value)}</span>
                  </span>
                  <input
                    type="range"
                    min={row.min}
                    max={row.max}
                    step={row.step}
                    value={row.value}
                    disabled={colourEdit.busy}
                    onChange={(e) => row.set(Number(e.target.value))}
                    aria-label={row.label}
                    className="mt-1 w-full"
                  />
                </label>
              ))}
              <div className="mt-1.5 flex items-center gap-2">
                <button
                  type="button"
                  disabled={!colourDirty || colourEdit.busy}
                  onClick={() => void colourEdit.onSave({ contrast, brightness, saturation })}
                  className="rounded-[6px] bg-accent px-2.5 py-1.5 text-[11px] font-semibold text-[#14110C] transition-colors hover:bg-[#ff8a70] disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {colourEdit.busy ? "A guardar…" : "Aplicar cor"}
                </button>
                {colourDirty && (
                  <span className="text-[11px] text-muted">Por aplicar — o Montar usa o valor guardado.</span>
                )}
              </div>
              {colourEdit.note && <p className="mt-1 text-[11px] text-danger">{colourEdit.note}</p>}
            </div>
          )}
          {hasPlan && (
            <div className="mt-2 rounded-md border border-border bg-raised/40 p-2.5">
              <p className="text-[11px] font-medium">Plano do Muse</p>
              {planSummary && <p className="mt-0.5 line-clamp-3 text-[11px] leading-relaxed text-muted">{planSummary}</p>}
              <button type="button" onClick={onOpenPlanReview} className="mt-1.5 text-[11px] font-medium text-accent underline underline-offset-2 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">
                Rever plano
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
