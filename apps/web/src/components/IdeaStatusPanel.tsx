"use client";

/* Right column of the idea workspace: the two approvals, live progress,
 * deterministic QA and the verified result. Nothing here renders video; the
 * worker does. This panel only records decisions and explains state honestly.
 */

import { useState } from "react";
import type { IdeaAssetData, IdeaConfigData, IdeaPayload, StoryboardScene } from "@/lib/idea-types";
import { Button } from "./ui/button";

const STAGE_LABELS: Record<string, string> = {
  awaiting_storyboard_cost: "À espera da aprovação do plano",
  planning: "A criar o plano",
  awaiting_plan_approval: "Plano pronto para revisão",
  generating_assets: "A gerar imagens",
  rendering: "A montar as cenas",
  verifying_frames: "A verificar",
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

const ASSET_LABELS: Record<IdeaAssetData["status"], string> = {
  planned: "planeada",
  approved: "aprovada",
  generating: "a gerar",
  generated: "gerada",
  failed: "falhou",
  skipped: "ignorada",
};

function usd(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "$0.00";
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

function stageLabel(stage: string | undefined): string {
  if (!stage) return "Pronto";
  return STAGE_LABELS[stage] ?? stage;
}

function formatBytes(bytes: number | undefined): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function shortHash(hash: string | undefined): string {
  if (!hash) return "—";
  return `${hash.slice(0, 10)}…${hash.slice(-6)}`;
}

function ModeBadge({
  label,
  mode,
  extra,
}: {
  label: string;
  mode: string | undefined;
  extra?: string;
}) {
  const live = mode === "live";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${
        live ? "border-accent/50 text-accent" : "border-border text-muted"
      }`}
      title={live ? "Serviço real — cada passo precisa da tua aprovação" : "Simulado localmente, sem custo"}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-accent" : "bg-muted"}`} />
      {label} · {live ? "direto" : "simulação"}
      {live && extra ? ` ${extra}` : ""}
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "completed"
      ? "border-success/40 text-success"
      : status === "failed" || status === "rejected"
        ? "border-danger/40 text-danger"
        : status === "awaiting_approval"
          ? "border-accent/40 text-accent"
          : "border-border text-muted";
  const labels: Record<string, string> = {
    queued: "Na fila",
    processing: "Em curso",
    awaiting_approval: "A aguardar",
    completed: "Concluído",
    failed: "Falhou",
    rejected: "Rejeitado",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] ${tone}`}>
      {labels[status] ?? status}
    </span>
  );
}

function ProgressBar({ current, total }: { current: number; total: number }) {
  const percent = total > 0 ? Math.min(100, Math.max(0, Math.round((current / total) * 100))) : 0;
  return (
    <>
      <div
        className="mt-2 h-1 overflow-hidden rounded-full bg-raised"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={current}
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${total > 0 ? Math.max(2, percent) : 4}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-muted">
        <span>progresso</span>
        <span>{total > 0 ? `${current}/${total}` : "—"}</span>
      </div>
    </>
  );
}

interface Props {
  idea: IdeaPayload | null;
  config: IdeaConfigData | null;
  busy: string | null;
  error: string | null;
  selectedAssets: string[];
  programmaticOnly: boolean;
  storyboardCost: number;
  assetCost: number;
  onToggleAsset: (assetId: string) => void;
  onProgrammaticOnly: (value: boolean) => void;
  onApproveStoryboard: () => void;
  onApproveAssets: () => void;
  onCancel: () => void;
  onReject: () => void;
  onRerender: () => void;
  onNewIdea: () => void;
  onSaveSceneText: (sceneId: string, lines: string[]) => void;
  onDeleteScene: (sceneId: string) => void;
  onApplyRefinement: () => void;
  onRejectRefinement: () => void;
  onTrimScene: (sceneId: string, durationMs: number) => void;
  onSplitScene: (sceneId: string) => void;
  onMoveScene: (sceneId: string, direction: -1 | 1) => void;
  onSetTransition: (sceneId: string, transition: string) => void;
  onSetTransitionMs: (sceneId: string, ms: number) => void;
  onAddOverlay: (text: string, startMs: number, endMs: number, kind: "text" | "image", assetId?: string) => void;
  onUpdateOverlayText: (overlayId: string, text: string) => void;
  onDeleteOverlay: (overlayId: string) => void;
  plates: { asset_id: string; label: string }[];
}

const TRANSITION_LABELS: Record<string, string> = {
  cut: "corte",
  fade: "fundido",
  dissolve: "dissolver",
  wipe: "cortina",
  zoom_blur: "zoom",
};

const PATCH_OP_LABELS: Record<string, string> = {
  set_scene_text: "texto",
  set_text_style: "tipografia",
  set_animation_step: "animação",
  add_animation_step: "nova animação",
  remove_animation_step: "remover animação",
  delete_scene: "eliminar cena",
  add_scene: "nova cena",
  set_scene_visual: "visual da cena",
  set_tone: "tom do vídeo",
  set_transition: "transição",
  add_overlay: "nova sobreposição",
  set_overlay_text: "texto da sobreposição",
  remove_overlay: "remover sobreposição",
  set_scene_duration: "duração da cena",
  split_scene: "dividir cena",
  move_scene: "mover cena",
};

/**
 * Edição 1-2: texto em linha + eliminação de cena. O guardar chama o PATCH
 * validado (pré-aprovação ou pós-conclusão); o re-render continua explícito
 * no botão "Renderizar de novo". Sem edições silenciosas, sem custo escondido.
 */
function SceneTextEditor({
  scene,
  busy,
  onSave,
}: {
  scene: StoryboardScene;
  busy: boolean;
  onSave: (sceneId: string, lines: string[]) => void;
}) {
  const [lines, setLines] = useState<string[]>(scene.on_screen_text);
  const dirty =
    lines.length !== scene.on_screen_text.length ||
    lines.some((line, index) => line !== scene.on_screen_text[index]);
  const invalid = lines.some((line) => line.length > 140);
  return (
    <div className="mt-2 space-y-1.5">
      {lines.map((line, index) => (
        <label key={index} className="block">
          <span className="sr-only">{`Texto da cena, linha ${index + 1}`}</span>
          <input
            value={line}
            maxLength={140}
            disabled={busy}
            onChange={(event) =>
              setLines((current) =>
                current.map((entry, entryIndex) =>
                  entryIndex === index ? event.target.value : entry,
                ),
              )
            }
            className="w-full rounded border border-border bg-raised/40 px-2 py-1 text-[12px] text-foreground focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>
      ))}
      {lines.length === 0 && (
        <p className="font-mono text-[10px] text-muted">cena sem texto — só imagem e movimento</p>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          className="px-3 py-1 text-[12px]"
          disabled={busy || !dirty || invalid}
          onClick={() => onSave(scene.scene_id, lines.map((line) => line.trim()).filter((line) => line.length > 0))}
        >
          {busy ? "A guardar…" : "Guardar texto"}
        </Button>
        {invalid && (
          <span className="text-[10px] text-danger">Máximo 140 caracteres por linha.</span>
        )}
      </div>
    </div>
  );
}

/**
 * Controlos de timeline por cena (ADR-039): trim de duração, split e ordem.
 * Tudo via PATCH validado + re-render explícito; sem custo, sem drag aqui
 * (o arrasto vive na faixa V1 da timeline, com estes botões como alternativa
 * por teclado). Edição de texto continua no SceneTextEditor.
 */
function SceneTimelineControls({
  scene,
  index,
  total,
  busy,
  canSplit,
  onTrimScene,
  onSplitScene,
  onMoveScene,
  onSetTransition,
  onSetTransitionMs,
}: {
  scene: StoryboardScene;
  index: number;
  total: number;
  busy: boolean;
  canSplit: boolean;
  onTrimScene: (sceneId: string, durationMs: number) => void;
  onSplitScene: (sceneId: string) => void;
  onMoveScene: (sceneId: string, direction: -1 | 1) => void;
  onSetTransition: (sceneId: string, transition: string) => void;
  onSetTransitionMs: (sceneId: string, ms: number) => void;
}) {
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? scene.duration_ms / 1000;
  const dirty = draft !== null && Math.round(draft * 1000) !== scene.duration_ms;
  const smallBtn =
    "shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted hover:text-foreground disabled:opacity-40";
  return (
    <div className="mt-2 space-y-1.5 rounded border border-border/60 bg-raised/30 p-2">
      <div className="flex items-center gap-2">
        <label htmlFor={`trim-${scene.scene_id}`} className="shrink-0 text-[11px] text-muted">
          Duração
        </label>
        <input
          id={`trim-${scene.scene_id}`}
          type="range"
          min={1}
          max={15}
          step={0.5}
          value={shown}
          disabled={busy}
          onChange={(event) => setDraft(Number(event.target.value))}
          className="min-w-0 flex-1"
          aria-label={`Duração da cena ${index + 1} em segundos`}
        />
        <span className="w-10 shrink-0 text-right font-mono text-[11px] tabular-nums">
          {shown.toFixed(1)}s
        </span>
        <Button
          variant="secondary"
          className="px-2 py-0.5 text-[11px]"
          disabled={busy || !dirty}
          onClick={() => {
            onTrimScene(scene.scene_id, Math.round((draft ?? shown) * 1000));
            setDraft(null);
          }}
        >
          Guardar
        </Button>
      </div>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={busy || index === 0}
          onClick={() => onMoveScene(scene.scene_id, -1)}
          aria-label={`Mover cena ${index + 1} para trás`}
          title="Mover para trás"
          className={smallBtn}
        >
          ◀
        </button>
        <button
          type="button"
          disabled={busy || index === total - 1}
          onClick={() => onMoveScene(scene.scene_id, 1)}
          aria-label={`Mover cena ${index + 1} para a frente`}
          title="Mover para a frente"
          className={smallBtn}
        >
          ▶
        </button>
        <button
          type="button"
          disabled={busy || !canSplit}
          onClick={() => onSplitScene(scene.scene_id)}
          aria-label={`Dividir cena ${index + 1}`}
          title="Divide na posição atual (ou ao meio); cada metade repete a animação ajustada"
          className={smallBtn}
        >
          dividir
        </button>
        {index < total - 1 ? (
          <>
            <label className="flex min-w-0 items-center gap-1">
              <span className="sr-only">Transição de saída da cena {index + 1}</span>
              <select
                value={scene.transition_out ?? "cut"}
                disabled={busy}
                onChange={(event) => onSetTransition(scene.scene_id, event.target.value)}
                aria-label={`Transição de saída da cena ${index + 1}`}
                title="Transição para a cena seguinte"
                className="min-w-0 flex-1 rounded border border-border bg-raised px-1 py-0.5 font-mono text-[10px] text-muted focus-visible:outline-2 focus-visible:outline-accent"
              >
                {Object.entries(TRANSITION_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex shrink-0 items-center gap-1" title="Duração da transição">
              <span className="sr-only">Duração da transição em milissegundos</span>
              <select
                value={scene.transition_ms ?? 400}
                disabled={busy || (scene.transition_out ?? "cut") === "cut"}
                onChange={(event) => onSetTransitionMs(scene.scene_id, Number(event.target.value))}
                aria-label={`Duração da transição da cena ${index + 1}`}
                className="rounded border border-border bg-raised px-1 py-0.5 font-mono text-[10px] text-muted focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
              >
                {[200, 400, 600, 800, 1000].map((ms) => (
                  <option key={ms} value={ms}>
                    {ms}ms
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <span className="font-mono text-[9px] text-muted/50" title="A última cena não tem transição de saída">
            fim
          </span>
        )}
        <span className="ml-auto hidden font-mono text-[9px] text-muted/70 xl:inline">trim · split · ordem</span>
      </div>
    </div>
  );
}

/**
 * Camada de sobreposição (ADR-040/041 multitrack): global por cima das
 * cenas, com janela temporal. Texto local ou imagem já gerada (sem custo).
 * Máximo 3 por vídeo; o servidor valida limites e unicidade.
 */
function OverlaySection({
  overlays,
  plates,
  totalMs,
  busy,
  onAdd,
  onUpdateText,
  onDelete,
}: {
  overlays: { overlay_id: string; kind?: string; text: string; asset_id?: string | null; start_ms: number; end_ms: number }[];
  plates: { asset_id: string; label: string }[];
  totalMs: number;
  busy: boolean;
  onAdd: (text: string, startMs: number, endMs: number, kind: "text" | "image", assetId?: string) => void;
  onUpdateText: (overlayId: string, text: string) => void;
  onDelete: (overlayId: string) => void;
}) {
  const [kind, setKind] = useState<"text" | "image">("text");
  const [text, setText] = useState("");
  const [assetId, setAssetId] = useState("");
  const totalSeconds = Math.max(1, Math.round(totalMs / 100) / 10);
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState("");
  const startMs = Math.round(Number.parseFloat(start || "0") * 1000);
  const endMs = end.trim() === "" ? totalMs : Math.round(Number.parseFloat(end) * 1000);
  const effectiveAsset = assetId || plates[0]?.asset_id || "";
  const valid =
    Number.isFinite(startMs) &&
    Number.isFinite(endMs) &&
    startMs >= 0 &&
    endMs > startMs &&
    endMs <= totalMs &&
    overlays.length < 3 &&
    (kind === "image" ? Boolean(effectiveAsset) : text.trim().length > 0 && text.trim().length <= 140);
  return (
    <section aria-labelledby="idea-overlays-title" className="rounded-lg border border-border bg-surface p-3.5">
      <h2 id="idea-overlays-title" className="text-[15px] font-semibold">
        Sobreposição
      </h2>
      <p className="mt-1 text-[12px] leading-relaxed text-muted">
        Camada global por cima das cenas (faixa OV na timeline). Texto local ou imagem já gerada — sem custo. Máx 3 por vídeo.
      </p>
      {overlays.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {overlays.map((overlay) => (
            <OverlayRow
              key={overlay.overlay_id}
              overlay={overlay}
              busy={busy}
              onUpdateText={onUpdateText}
              onDelete={onDelete}
            />
          ))}
        </ul>
      ) : (
        <p className="mt-2 font-mono text-[10px] text-muted">nenhuma sobreposição</p>
      )}
      <div className="mt-3 space-y-1.5 rounded border border-border/60 bg-raised/30 p-2">
        <div className="flex gap-1.5" role="group" aria-label="Tipo de sobreposição">
          {(["text", "image"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setKind(value)}
              aria-pressed={kind === value}
              disabled={busy || (value === "image" && plates.length === 0)}
              title={value === "image" && plates.length === 0 ? "Gera as imagens primeiro (passo 2)" : undefined}
              className={`rounded-full px-2.5 py-0.5 font-mono text-[11px] transition-colors disabled:opacity-40 ${
                kind === value ? "bg-accent font-semibold text-[#14110C]" : "border border-border text-muted"
              }`}
            >
              {value === "text" ? "Texto" : "Imagem"}
            </button>
          ))}
        </div>
        {kind === "text" ? (
          <input
            value={text}
            maxLength={140}
            disabled={busy}
            onChange={(event) => setText(event.target.value)}
            placeholder="Texto da sobreposição (máx 140)"
            aria-label="Texto da nova sobreposição"
            className="w-full rounded border border-border bg-raised/40 px-2 py-1 text-[12px] text-foreground focus-visible:outline-2 focus-visible:outline-accent"
          />
        ) : (
          <label className="block">
            <span className="sr-only">Plate gerada para a sobreposição</span>
            <select
              value={effectiveAsset}
              disabled={busy || plates.length === 0}
              onChange={(event) => setAssetId(event.target.value)}
              className="w-full rounded border border-border bg-raised/40 px-2 py-1 text-[12px] focus-visible:outline-2 focus-visible:outline-accent"
            >
              {plates.map((plate) => (
                <option key={plate.asset_id} value={plate.asset_id}>
                  {plate.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex items-center gap-2">
          <label className="flex min-w-0 flex-1 items-center gap-1 text-[11px] text-muted">
            Início
            <input
              value={start}
              disabled={busy}
              onChange={(event) => setStart(event.target.value)}
              inputMode="decimal"
              aria-label="Início em segundos"
              className="w-full rounded border border-border bg-raised/40 px-1.5 py-0.5 font-mono text-[11px] tabular-nums"
            />
          </label>
          <label className="flex min-w-0 flex-1 items-center gap-1 text-[11px] text-muted">
            Fim
            <input
              value={end}
              disabled={busy}
              onChange={(event) => setEnd(event.target.value)}
              inputMode="decimal"
              placeholder={`${totalSeconds.toFixed(1)}`}
              aria-label="Fim em segundos (vazio = fim do vídeo)"
              className="w-full rounded border border-border bg-raised/40 px-1.5 py-0.5 font-mono text-[11px] tabular-nums"
            />
          </label>
          <Button
            variant="secondary"
            className="px-3 py-1 text-[12px]"
            disabled={busy || !valid}
            onClick={() => {
              onAdd(text.trim(), Math.max(0, startMs), Math.min(totalMs, endMs), kind, kind === "image" ? effectiveAsset : undefined);
              setText("");
            }}
          >
            Adicionar
          </Button>
        </div>
      </div>
    </section>
  );
}

function OverlayRow({
  overlay,
  busy,
  onUpdateText,
  onDelete,
}: {
  overlay: { overlay_id: string; kind?: string; text: string; asset_id?: string | null; start_ms: number; end_ms: number };
  busy: boolean;
  onUpdateText: (overlayId: string, text: string) => void;
  onDelete: (overlayId: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? overlay.text;
  const dirty = draft !== null && draft.trim() !== overlay.text && draft.trim().length > 0;
  const isImage = (overlay.kind ?? "text") === "image";
  return (
    <li className="rounded-md border border-border bg-surface p-2.5">
      <div className="flex items-center gap-2">
        <span className="shrink-0 font-mono text-[10px] text-accent">{overlay.overlay_id}</span>
        <span className="shrink-0 rounded border border-border px-1 font-mono text-[9px] text-muted">
          {isImage ? "imagem" : "texto"}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[10px] tabular-nums text-muted">
          {(overlay.start_ms / 1000).toFixed(1)}s → {(overlay.end_ms / 1000).toFixed(1)}s
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDelete(overlay.overlay_id)}
          aria-label={`Eliminar sobreposição ${overlay.overlay_id}`}
          className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted hover:border-danger/50 hover:text-danger disabled:opacity-40"
        >
          eliminar
        </button>
      </div>
      {isImage ? (
        <p className="mt-1.5 truncate font-mono text-[11px] text-muted" title={overlay.asset_id ?? ""}>
          {overlay.asset_id ?? "—"}
        </p>
      ) : (
        <div className="mt-1.5 flex items-center gap-2">
          <input
            value={shown}
            maxLength={140}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
            aria-label={`Texto da sobreposição ${overlay.overlay_id}`}
            className="min-w-0 flex-1 rounded border border-border bg-raised/40 px-2 py-1 text-[12px] focus-visible:outline-2 focus-visible:outline-accent"
          />
          <Button
            variant="secondary"
            className="px-3 py-1 text-[12px]"
            disabled={busy || !dirty}
            onClick={() => {
              onUpdateText(overlay.overlay_id, (draft ?? "").trim());
              setDraft(null);
            }}
          >
            Guardar
          </Button>
        </div>
      )}
    </li>
  );
}

export function IdeaStatusPanel({
  idea,
  config,
  busy,
  error,
  selectedAssets,
  programmaticOnly,
  storyboardCost,
  assetCost,
  onToggleAsset,
  onProgrammaticOnly,
  onApproveStoryboard,
  onApproveAssets,
  onCancel,
  onReject,
  onRerender,
  onNewIdea,
  onSaveSceneText,
  onDeleteScene,
  onApplyRefinement,
  onRejectRefinement,
  onTrimScene,
  onSplitScene,
  onMoveScene,
  onSetTransition,
  onSetTransitionMs,
  onAddOverlay,
  onUpdateOverlayText,
  onDeleteOverlay,
  plates,
}: Props) {
  const modes = idea?.modes ?? config?.modes ?? { director: "mock", image: "mock", effort: "medium" };
  const liveDirector = modes.director === "live";
  const liveImages = modes.image === "live";
  // Reasoning effort only matters for the live storyboard call; surface it
  // whenever it is above the default so xhigh usage is never silent.
  const directorEffort =
    liveDirector && modes.effort && modes.effort !== "medium"
      ? modes.effort.toUpperCase()
      : undefined;
  const working = Boolean(
    idea && (idea.status === "queued" || idea.status === "processing") && WORKING_STAGES.has(idea.stage),
  );
  const failed = idea?.status === "failed" || idea?.status === "rejected";
  const effectivePlateCount = programmaticOnly ? 0 : selectedAssets.length;
  const cap = config?.cap_usd ?? idea?.estimate?.cap_usd ?? 0.1;

  return (
    <div className="flex flex-col gap-4 p-4">
      {error && (
        <div
          role="alert"
          className="rounded-md border border-danger/40 bg-danger/10 p-3 text-[12px] leading-relaxed text-danger"
        >
          {error}
        </div>
      )}

      {!idea && (
        <section aria-labelledby="idea-how-title">
          <p className="text-[11px] text-accent">Como funciona</p>
          <h2 id="idea-how-title" className="mt-1 text-[15px] font-semibold">
            Três passos, dois consentimentos
          </h2>
          <ol className="mt-3 space-y-3">
            {[
              ["01", "Plano", "O Muse escreve um plano com cenas, texto e animações."],
              ["02", "Imagens", "Reves cada imagem e escolhes quais gerar; o resto fica programático."],
              ["03", "Vídeo final", "O sistema monta as cenas e verifica o MP4 antes de entregar."],
            ].map(([number, title, body]) => (
              <li key={number} className="flex gap-2.5">
                <span className="mt-0.5 font-mono text-[10px] text-accent">{number}</span>
                <div>
                  <p className="text-[12px] font-semibold">{title}</p>
                  <p className="text-[11px] leading-relaxed text-muted">{body}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-4 flex flex-wrap gap-1.5">
            <ModeBadge label="Director" mode={modes.director} extra={directorEffort} />
            <ModeBadge label="Imagens" mode={modes.image} />
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Limite por vídeo: {usd(cap)} · sem custos automáticos
          </p>
        </section>
      )}

      {idea?.pending_clarification_question && (
        <section aria-labelledby="refine-question-title" className="rounded-lg border border-accent/30 bg-accent/[0.04] p-3.5">
          <h2 id="refine-question-title" className="text-[15px] font-semibold">
            O Muse precisa de um esclarecimento
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            {idea.pending_clarification_question}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            Responde no chat (voz ou texto) e o ajuste continua daí.
          </p>
        </section>
      )}

      {idea?.pending_patch && (
        <section aria-labelledby="refine-patch-title" className="rounded-lg border border-accent/30 bg-accent/[0.04] p-3.5">
          <p className="text-[11px] text-accent">Ajuste proposto pelo Muse</p>
          <h2 id="refine-patch-title" className="mt-1 text-[15px] font-semibold">
            {idea.pending_patch.summary}
          </h2>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {idea.pending_patch.operations.map((operation, index) => (
              <li
                key={index}
                className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted"
              >
                {PATCH_OP_LABELS[operation.op] ?? operation.op}
                {operation.scene_id ? ` · ${operation.scene_id}` : ""}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] leading-relaxed text-muted">
            Nada muda sem aprovares. Depois de aplicar, a pré-visualização
            actualiza já; o vídeo final muda quando renderizares de novo.
          </p>
          <Button className="mt-3 w-full" onClick={onApplyRefinement} disabled={busy !== null}>
            {busy === "apply-refinement" ? "A aplicar…" : "Aplicar ajuste"}
          </Button>
          <Button variant="ghost" className="mt-1.5 w-full" onClick={onRejectRefinement} disabled={busy !== null}>
            {busy === "reject-refinement" ? "A rejeitar…" : "Rejeitar ajuste"}
          </Button>
        </section>
      )}

      {idea && idea.can_approve_storyboard && (
        <section
          aria-labelledby="approve-plan-title"
          className="rounded-lg border border-accent/30 bg-accent/[0.04] p-3.5"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-accent">Passo 1 de 2</p>
            <ModeBadge label="Director" mode={modes.director} extra={directorEffort} />
          </div>
          <h2 id="approve-plan-title" className="mt-1 text-[15px] font-semibold">
            Aprovar o plano
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            {liveDirector
              ? "Esta aprovação autoriza uma única chamada real ao Muse. Sem repetições automáticas."
              : "O plano é simulado localmente. Sem custos, sem serviços externos."}
          </p>

          <dl className="mt-3 space-y-1.5 font-mono text-[11px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Plano</dt>
              <dd className="tabular-nums">{usd(storyboardCost)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">
                Imagens previstas ({idea.estimate?.image_count ?? 0})
              </dt>
              <dd className="tabular-nums">{usd(idea.estimate?.images_usd ?? 0)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-t border-border pt-1.5">
              <dt className="text-muted">Limite por vídeo</dt>
              <dd className="tabular-nums">{usd(cap)}</dd>
            </div>
          </dl>

          <Button
            className="mt-3 w-full"
            onClick={onApproveStoryboard}
            disabled={busy !== null}
          >
            {busy === "approve-storyboard"
              ? "A aprovar…"
              : liveDirector
                ? `Aprovar plano — até ${usd(storyboardCost)}`
                : "Aprovar plano (sem custo)"}
          </Button>
          <Button
            variant="ghost"
            className="mt-1.5 w-full"
            onClick={onReject}
            disabled={busy !== null}
          >
            {busy === "reject" ? "A rejeitar…" : "Rejeitar"}
          </Button>
          <p className="mt-2 text-[10px] leading-relaxed text-muted">
            Nada é gerado antes desta aprovação. O custo real fica registado.
          </p>
        </section>
      )}

      {idea && idea.can_approve_assets && idea.storyboard && (
        <section aria-labelledby="approve-assets-title">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-accent">Passo 2 de 2</p>
            <ModeBadge label="Imagens" mode={modes.image} />
          </div>
          <h2 id="approve-assets-title" className="mt-1 text-[15px] font-semibold">
            Rever o plano
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            Desmarca as cenas sem imagens geradas. Só as imagens marcadas são criadas.
          </p>

          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-[10px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Cenas</dt>
              <dd>{idea.storyboard.scenes.length}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Duração</dt>
              <dd>{idea.storyboard.duration_seconds}s</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Formato</dt>
              <dd>{idea.storyboard.aspect_ratio}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">FPS</dt>
              <dd>{idea.storyboard.output_fps}</dd>
            </div>
          </dl>

          <ul className="mt-3 space-y-2">
            {idea.storyboard.scenes.map((scene, index) => {
              const plates = idea.assets.filter((asset) =>
                asset.scene_ids.includes(scene.scene_id),
              );
              return (
                <li key={scene.scene_id} className="rounded-md border border-border bg-surface p-2.5">
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 font-mono text-[10px] text-accent">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-medium">
                        {scene.on_screen_text[0] ?? scene.narrative_purpose}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-muted">
                        {(scene.duration_ms / 1000).toFixed(1)}s ·{" "}
                        {scene.animation_sequence.length} animações
                      </p>
                    </div>
                    {(idea.storyboard?.scenes.length ?? 0) > 1 && (
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => onDeleteScene(scene.scene_id)}
                        aria-label={`Eliminar cena ${index + 1}`}
                        title="Eliminar esta cena (a duração é redistribuída)"
                        className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted hover:border-danger/50 hover:text-danger disabled:opacity-40"
                      >
                        eliminar
                      </button>
                    )}
                  </div>
                  <SceneTextEditor
                    key={`${idea.idea_id}:${idea.storyboard_hash ?? ""}:${scene.scene_id}`}
                    scene={scene}
                    busy={busy !== null}
                    onSave={onSaveSceneText}
                  />
                  <SceneTimelineControls
                    key={`tl:${idea.idea_id}:${idea.storyboard_hash ?? ""}:${scene.scene_id}`}
                    scene={scene}
                    index={index}
                    total={idea.storyboard?.scenes.length ?? 0}
                    busy={busy !== null}
                    canSplit={scene.duration_ms >= 2000 && (idea.storyboard?.scenes.length ?? 0) < 12}
                    onTrimScene={onTrimScene}
                    onSplitScene={onSplitScene}
                    onMoveScene={onMoveScene}
                    onSetTransition={onSetTransition}
                    onSetTransitionMs={onSetTransitionMs}
                  />
                  {plates.length > 0 ? (
                    <ul className="mt-2 space-y-1.5">
                      {plates.map((plate) => {
                        const checked = Boolean(
                          !programmaticOnly && selectedAssets.includes(plate.asset_id),
                        );
                        const roleLabel =
                          plate.role === "foreground" ? "Frente" : "Fundo";
                        return (
                          <li key={plate.asset_id}>
                            <label className="flex cursor-pointer items-start gap-2 rounded border border-border/70 bg-raised/40 p-2">
                              <input
                                type="checkbox"
                                checked={checked}
                                disabled={programmaticOnly || busy !== null}
                                onChange={() => onToggleAsset(plate.asset_id)}
                                className="mt-0.5 accent-[#ff7659]"
                              />
                              <span className="min-w-0">
                                <span className="flex items-center gap-1.5 text-[10px] text-foreground">
                                  {plate.asset_id}
                                  <span className="rounded border border-border px-1 py-px text-[10px] text-accent">
                                    {roleLabel}
                                  </span>
                                  <span className="text-muted">
                                    {liveImages ? `· ${usd(config?.prices.image_usd ?? 0.01)}` : "· simulação"}
                                  </span>
                                </span>
                                <span className="mt-0.5 line-clamp-2 block text-[10px] leading-relaxed text-muted">
                                  {plate.prompt}
                                </span>
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p className="mt-2 rounded border border-dashed border-border px-2 py-1 font-mono text-[10px] text-muted">
                      fundo programático
                    </p>
                  )}
                </li>
              );
            })}
          </ul>

          <label className="mt-3 flex items-start gap-2 rounded-md border border-border bg-surface p-2.5">
            <input
              type="checkbox"
              checked={programmaticOnly}
              disabled={busy !== null}
              onChange={(event) => onProgrammaticOnly(event.target.checked)}
              className="mt-0.5 accent-[#ff7659]"
            />
            <span>
              <span className="block text-[12px] font-medium">Renderizar sem imagens geradas</span>
              <span className="block text-[10px] leading-relaxed text-muted">
                Usa apenas gradientes, tipografia e animações locais.
              </span>
            </span>
          </label>

          <dl className="mt-3 space-y-1.5 text-[11px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Imagens seleccionadas</dt>
              <dd className="tabular-nums">
                {effectivePlateCount}/{idea.assets.length}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Custo das imagens</dt>
              <dd className="tabular-nums">{usd(programmaticOnly ? 0 : assetCost)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-t border-border pt-1.5">
              <dt className="text-muted">Gasto até agora</dt>
              <dd className="tabular-nums">{usd(idea.spent_usd)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Limite por vídeo</dt>
              <dd className="tabular-nums">{usd(cap)}</dd>
            </div>
          </dl>

          <Button className="mt-3 w-full" onClick={onApproveAssets} disabled={busy !== null}>
            {busy === "approve-assets"
              ? "A aprovar…"
              : programmaticOnly || effectivePlateCount === 0
                ? "Aprovar e renderizar sem imagens"
                : liveImages
                  ? `Aprovar imagens e renderizar — até ${usd(assetCost)}`
                  : "Aprovar e renderizar (sem custo)"}
          </Button>
          <Button
            variant="ghost"
            className="mt-1.5 w-full"
            onClick={onReject}
            disabled={busy !== null}
          >
            {busy === "reject" ? "A rejeitar…" : "Rejeitar plano"}
          </Button>
          <p className="mt-2 text-[10px] leading-relaxed text-muted">
            {liveImages
              ? "Cada imagem é uma chamada real, tentada uma única vez. Se falhar, o processo pára e o gasto fica registado."
              : "Simulação: as imagens são geradas localmente, sem custo."}
          </p>
        </section>
      )}

      {idea && working && (
        <section aria-labelledby="idea-progress-title" className="rounded-lg border border-border bg-surface p-3.5">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-accent">Em curso</p>
            <StatusPill status={idea.status} />
          </div>
          <h2 id="idea-progress-title" className="mt-1 text-[15px] font-semibold">
            {stageLabel(idea.stage)}
          </h2>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            O trabalho continua em segundo plano. Podes fechar esta página.
          </p>

          <ProgressBar
            current={idea.progress?.current ?? 0}
            total={idea.progress?.total ?? 0}
          />

          {idea.stage === "generating_assets" && idea.assets.length > 0 && (
            <ul className="mt-3 space-y-1">
              {idea.assets.map((asset) => (
                <li
                  key={asset.asset_id}
                  className="flex items-center justify-between gap-2 font-mono text-[10px]"
                >
                  <span className="truncate text-muted">{asset.asset_id}</span>
                  <span
                    className={
                      asset.status === "generated"
                        ? "text-success"
                        : asset.status === "failed"
                          ? "text-danger"
                          : "text-muted"
                    }
                  >
                    {ASSET_LABELS[asset.status]}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {idea.can_cancel && (
            <Button
              variant="danger"
              className="mt-3 w-full"
              onClick={onCancel}
              disabled={busy !== null}
            >
              {busy === "cancel" ? "A cancelar…" : "Cancelar"}
            </Button>
          )}
        </section>
      )}

      {idea && idea.status === "completed" && idea.render && (
        <section aria-labelledby="idea-result-title" className="rounded-lg border border-success/30 bg-success/[0.04] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-success">Vídeo pronto</p>
            <span className="font-mono text-[10px] text-muted">v{idea.render.version}</span>
          </div>
          <h2 id="idea-result-title" className="mt-1 text-[15px] font-semibold">
            {idea.storyboard?.project_title ?? "Vídeo renderizado"}
          </h2>

          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-[10px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Resolução</dt>
              <dd>
                {idea.render.width}×{idea.render.height}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">FPS</dt>
              <dd>{idea.render.fps}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Frames</dt>
              <dd>{idea.render.frame_count}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Duração</dt>
              <dd>{idea.render.duration_seconds.toFixed(2)}s</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Tamanho</dt>
              <dd>{formatBytes(Number((idea.render.qa?.output as { bytes?: number } | undefined)?.bytes))}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">SHA-256</dt>
              <dd title={idea.render.sha256}>{shortHash(idea.render.sha256)}</dd>
            </div>
          </dl>

          <p className="mt-2 rounded border border-border bg-raised/40 px-2 py-1.5 text-[11px] leading-relaxed text-muted">
            Verificação aprovada: resolução, duração e fotogramas confirmados.
          </p>

          <a
            href={idea.render.url}
            download
            className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-[#14110C] transition-colors hover:bg-[#ff8a70] focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          >
            Descarregar MP4
          </a>
          <div className="mt-1.5 grid grid-cols-2 gap-1.5">
            <Button variant="secondary" onClick={onRerender} disabled={busy !== null}>
              {busy === "render" ? "A repetir…" : "Renderizar de novo"}
            </Button>
            <Button variant="ghost" onClick={onNewIdea} disabled={busy !== null}>
              Novo vídeo
            </Button>
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-muted">
            O ficheiro só fica disponível depois de verificado.
          </p>
        </section>
      )}

      {idea && idea.storyboard && idea.can_render && (
        <section
          aria-labelledby="idea-scenes-title"
          className="rounded-lg border border-border bg-surface p-3.5"
        >
          <h2 id="idea-scenes-title" className="text-[15px] font-semibold">
            Cenas
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            Edita o texto ou elimina cenas. As imagens já geradas são
            reutilizadas — sem custo. Depois de guardar, prime{" "}
            <span className="font-medium text-foreground">Renderizar de novo</span>.
          </p>
          <ul className="mt-3 space-y-2">
            {idea.storyboard.scenes.map((scene, index) => (
              <li
                key={scene.scene_id}
                className="rounded-md border border-border bg-raised/30 p-2.5"
              >
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 font-mono text-[10px] text-accent">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <p className="min-w-0 flex-1 truncate text-[12px] font-medium">
                    {scene.on_screen_text[0] ?? scene.narrative_purpose}
                  </p>
                  {(idea.storyboard?.scenes.length ?? 0) > 1 && (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => onDeleteScene(scene.scene_id)}
                      aria-label={`Eliminar cena ${index + 1}`}
                      title="Eliminar esta cena (a duração é redistribuída)"
                      className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted hover:border-danger/50 hover:text-danger disabled:opacity-40"
                    >
                      eliminar
                    </button>
                  )}
                </div>
                <p className="mt-0.5 font-mono text-[10px] text-muted">
                  {(scene.duration_ms / 1000).toFixed(1)}s ·{" "}
                  {scene.animation_sequence.length} animações
                </p>
                <SceneTextEditor
                  key={`${idea.idea_id}:${idea.storyboard_hash ?? ""}:${scene.scene_id}`}
                  scene={scene}
                  busy={busy !== null}
                  onSave={onSaveSceneText}
                />
                <SceneTimelineControls
                  key={`tl:${idea.idea_id}:${idea.storyboard_hash ?? ""}:${scene.scene_id}`}
                  scene={scene}
                  index={index}
                  total={(idea.storyboard?.scenes.length ?? 0)}
                  busy={busy !== null}
                  canSplit={scene.duration_ms >= 2000 && (idea.storyboard?.scenes.length ?? 0) < 12}
                  onTrimScene={onTrimScene}
                  onSplitScene={onSplitScene}
                  onMoveScene={onMoveScene}
                  onSetTransition={onSetTransition}
                  onSetTransitionMs={onSetTransitionMs}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {idea?.storyboard && (idea.can_approve_assets || idea.can_render) && (
        <OverlaySection
          key={`ov:${idea.idea_id}:${idea.storyboard_hash ?? ""}`}
          overlays={(idea.storyboard?.overlays ?? []).map((overlay) => ({
            overlay_id: overlay.overlay_id,
            kind: overlay.kind,
            text: overlay.text,
            asset_id: overlay.asset_id,
            start_ms: overlay.start_ms,
            end_ms: overlay.end_ms,
          }))}
          totalMs={idea.storyboard?.scenes.reduce((sum, scene) => sum + scene.duration_ms, 0) ?? 0}
          busy={busy !== null}
          plates={plates}
          onAdd={onAddOverlay}
          onUpdateText={onUpdateOverlayText}
          onDelete={onDeleteOverlay}
        />
      )}

      {idea && failed && (
        <section aria-labelledby="idea-failure-title" className="rounded-lg border border-danger/40 bg-danger/[0.05] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-danger">
              {idea.status === "rejected" ? "Plano rejeitado" : "Falhou"}
            </p>
            <StatusPill status={idea.status} />
          </div>
          <h2 id="idea-failure-title" className="mt-1 text-[15px] font-semibold">
            {idea.status === "rejected" ? "Nada foi gerado" : "O vídeo não foi entregue"}
          </h2>
          {idea.error && (
            <>
              <p className="mt-2 break-words font-mono text-[10px] text-danger">{idea.error.code}</p>
              <p className="mt-1 break-words text-[12px] leading-relaxed text-muted">
                {idea.error.message}
              </p>
            </>
          )}
          <p className="mt-2 text-[10px] leading-relaxed text-muted">
            Os vídeos com falhas de verificação nunca ficam disponíveis para download.
          </p>
          <div className="mt-3 grid gap-1.5">
            {idea.can_render && (
              <Button variant="secondary" onClick={onRerender} disabled={busy !== null}>
                {busy === "render" ? "A repetir…" : "Tentar renderizar de novo"}
              </Button>
            )}
            <Button variant="ghost" onClick={onNewIdea} disabled={busy !== null}>
              Começar um novo vídeo
            </Button>
          </div>
        </section>
      )}

      {idea && (
        <section aria-labelledby="idea-costs-title" className="rounded-md border border-border bg-surface p-3">
          <p id="idea-costs-title" className="font-mono text-[10px] tracking-[0.16em] text-muted">
            Custos
          </p>
          <dl className="mt-2 space-y-1 font-mono text-[10px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Gasto real</dt>
              <dd className="tabular-nums text-foreground">{usd(idea.spent_usd)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Estimativa atual</dt>
              <dd className="tabular-nums text-foreground">{usd(idea.estimate?.total_usd ?? 0)}</dd>
            </div>
            <div className="flex justify-between gap-2 border-t border-border pt-1">
              <dt className="text-muted">Limite por vídeo</dt>
              <dd className="tabular-nums text-foreground">{usd(cap)}</dd>
            </div>
          </dl>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <ModeBadge label="Director" mode={modes.director} extra={directorEffort} />
            <ModeBadge label="Imagens" mode={modes.image} />
          </div>
          {!liveDirector && !liveImages && (
            <p className="mt-2 text-[10px] leading-relaxed text-muted">
              Tudo simulado localmente: custo real $0.00.
            </p>
          )}
        </section>
      )}

      {idea && idea.history.length > 0 && (
        <details className="rounded-md border border-border bg-surface p-3">
          <summary className="cursor-pointer font-mono text-[10px] tracking-[0.16em] text-muted">
            Histórico ({idea.history.length})
          </summary>
          <ol className="mt-2 space-y-1.5">
            {idea.history.slice(-6).reverse().map((entry, index) => (
              <li key={`${entry.at}-${index}`} className="flex gap-2 font-mono text-[10px]">
                <span className="shrink-0 text-muted">
                  {new Date(entry.at).toLocaleTimeString("pt-PT", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
                <span className="min-w-0">
                  <span className="text-foreground">{entry.stage}</span>
                  {entry.note && (
                    <span className="block truncate text-muted" title={entry.note}>
                      {entry.note}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
