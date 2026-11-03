"use client";

/* Right column of the idea workspace: the two approvals, live progress,
 * deterministic QA and the verified result. Nothing here renders video; the
 * worker does. This panel only records decisions and explains state honestly.
 */

import type { IdeaAssetData, IdeaConfigData, IdeaPayload } from "@/lib/idea-types";
import { Button } from "./ui/button";

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
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.1em] ${
        live ? "border-accent/50 text-accent" : "border-border text-muted"
      }`}
      title={live ? "Provider real; cada passo exige aprovação de custo" : "Simulado localmente, sem custo"}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-accent" : "bg-muted"}`} />
      {label} {live ? "LIVE" : "MOCK"}
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
  return (
    <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.1em] ${tone}`}>
      {status.replace("_", " ").toUpperCase()}
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
          <p className="font-mono text-[10px] tracking-[0.16em] text-accent">COMO FUNCIONA</p>
          <h2 id="idea-how-title" className="mt-1 text-[15px] font-semibold">
            Três passos, dois consentimentos
          </h2>
          <ol className="mt-3 space-y-3">
            {[
              ["01", "Plano", "O director escreve um storyboard com cenas, texto e animações permitidas."],
              ["02", "Imagens", "Reves cada plate e escolhes quais gerar; o resto fica programático."],
              ["03", "Render", "O worker captura as cenas, codifica com FFmpeg e verifica o MP4."],
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
            <ModeBadge label="DIRECTOR" mode={modes.director} extra={directorEffort} />
            <ModeBadge label="IMAGENS" mode={modes.image} />
          </div>
          <p className="mt-2 font-mono text-[10px] text-muted">
            Limite por vídeo: {usd(cap)} · sem retries automáticos
          </p>
        </section>
      )}

      {idea && idea.can_approve_storyboard && (
        <section
          aria-labelledby="approve-plan-title"
          className="rounded-lg border border-accent/30 bg-accent/[0.04] p-3.5"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-accent">APROVAÇÃO 1 DE 2</p>
            <ModeBadge label="DIRECTOR" mode={modes.director} extra={directorEffort} />
          </div>
          <h2 id="approve-plan-title" className="mt-1 text-[15px] font-semibold">
            Aprovar o plano
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            {liveDirector
              ? "Esta aprovação autoriza uma única chamada real ao director. Sem retries, sem fallback."
              : "O plano é simulado localmente. Não há chamada a modelos nem custo."}
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
            Nada é gerado antes desta aprovação. O custo real fica registado no job.
          </p>
        </section>
      )}

      {idea && idea.can_approve_assets && idea.storyboard && (
        <section aria-labelledby="approve-assets-title">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-accent">APROVAÇÃO 2 DE 2</p>
            <ModeBadge label="IMAGENS" mode={modes.image} />
          </div>
          <h2 id="approve-assets-title" className="mt-1 text-[15px] font-semibold">
            Rever o plano
          </h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            Desmarca as cenas que devem ficar programáticas. Só as plates marcadas são geradas.
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
                  </div>
                  {plates.length > 0 ? (
                    <ul className="mt-2 space-y-1.5">
                      {plates.map((plate) => {
                        const checked = Boolean(
                          !programmaticOnly && selectedAssets.includes(plate.asset_id),
                        );
                        const roleLabel =
                          plate.role === "foreground" ? "FRENTE" : "FUNDO";
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
                                <span className="flex items-center gap-1.5 font-mono text-[10px] text-foreground">
                                  {plate.asset_id}
                                  <span className="rounded border border-border px-1 py-px text-[9px] tracking-[0.08em] text-accent">
                                    {roleLabel}
                                  </span>
                                  <span className="text-muted">
                                    {liveImages ? `· ${usd(config?.prices.image_usd ?? 0.01)}` : "· mock"}
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

          <dl className="mt-3 space-y-1.5 font-mono text-[11px]">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Plates selecionadas</dt>
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
              ? "Cada plate é uma chamada real, tentada uma única vez. Se falhar, o job para e o gasto fica registado."
              : "Modo simulado: as plates são imagens locais de demonstração, sem custo."}
          </p>
        </section>
      )}

      {idea && working && (
        <section aria-labelledby="idea-progress-title" className="rounded-lg border border-border bg-surface p-3.5">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-accent">EM CURSO</p>
            <StatusPill status={idea.status} />
          </div>
          <h2 id="idea-progress-title" className="mt-1 text-[15px] font-semibold">
            {stageLabel(idea.stage)}
          </h2>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            O worker corre num processo separado. Podes fechar esta página; o job continua.
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
            <p className="font-mono text-[10px] tracking-[0.16em] text-success">VÍDEO PRONTO</p>
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

          <p className="mt-2 rounded border border-border bg-raised/40 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-muted">
            QA: {String(idea.render.qa?.captured ?? "—")} frames capturados ·{" "}
            {String(idea.render.qa?.black ?? "—")} pretos ·{" "}
            {String(idea.render.qa?.frozen_frames ?? "—")} congelados ·{" "}
            {String(idea.render.qa?.capture_fps ?? "—")} fps de captura
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
            O ficheiro só é entregue depois de verificado com ffprobe: stream de vídeo, duração e
            contagem de frames.
          </p>
        </section>
      )}

      {idea && failed && (
        <section aria-labelledby="idea-failure-title" className="rounded-lg border border-danger/40 bg-danger/[0.05] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] tracking-[0.16em] text-danger">
              {idea.status === "rejected" ? "PLANO REJEITADO" : "JOB FALHOU"}
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
            Qualquer MP4 que tenha falhado a QA fica em quarentena e nunca é servido para download.
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
            CUSTOS
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
            <ModeBadge label="DIRECTOR" mode={modes.director} extra={directorEffort} />
            <ModeBadge label="IMAGENS" mode={modes.image} />
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
            HISTÓRICO ({idea.history.length})
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
