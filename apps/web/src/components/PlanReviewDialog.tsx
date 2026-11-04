"use client";

import { useEffect, useState } from "react";
import { subjectPreviewUrl } from "@/lib/api";
import type { PlanCapabilityData, PlanReviewData } from "@/lib/types";
import { Button } from "./ui/button";

type Decision = "approve" | "reject" | "clarify" | null;

interface Props {
  review: PlanReviewData;
  submitting: Decision;
  error: string | null;
  selectedSubjects: string[];
  onToggleSubject: (objectId: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onClarify: (answer: string) => void;
  onClose: () => void;
}

function capabilityLabel(capability: PlanCapabilityData | undefined): string {
  if (!capability) return "desconhecida";
  if (capability.status === "available_mock") return "Simulação";
  if (capability.status === "available_local") return "Local";
  if (capability.status === "available_live") return "Direto";
  if (capability.status === "planned") return "Em breve";
  return "Indisponível";
}

function describeStrategy(strategy: string): string {
  const map: Record<string, string> = {
    largest_subject: "Assunto principal",
    named_subject: "Pessoa indicada",
    foreground: "Primeiro plano",
  };
  return map[strategy] ?? strategy.replace(/_/g, " ");
}

function describeOutcome(outcome: string): string {
  const map: Record<string, string> = {
    plan_ready: "Pronto a aprovar",
    needs_clarification: "Precisa de resposta",
    unsupported: "Não suportado",
  };
  return map[outcome] ?? outcome;
}

function describeApproval(status: string): string {
  if (status === "required") return "Precisa de aprovação";
  if (status === "not_required") return "Sem aprovação";
  return status;
}

function formatParam(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function PlanReviewDialog({
  review,
  submitting,
  error,
  selectedSubjects,
  onToggleSubject,
  onApprove,
  onReject,
  onClarify,
  onClose,
}: Props) {
  const [answer, setAnswer] = useState("");
  const plan = review.plan;
  const capabilityById = new Map(review.capabilities.map((c) => [c.capability_id, c]));
  const awaitingApproval = review.status === "awaiting_approval";
  const awaitingClarification = review.status === "awaiting_clarification";
  const unsupported = review.status === "unsupported" || plan?.outcome === "unsupported";
  const rejected = review.status === "rejected";
  const hasDetection = review.segmentation !== null;
  const noSubjects = review.no_subjects || (hasDetection && review.subjects.length === 0);
  const needsSelection = hasDetection && review.subjects.length > 0 && selectedSubjects.length === 0;
  const canApprove = awaitingApproval && !noSubjects && !needsSelection;

  function toggleSubject(objectId: string) {
    onToggleSubject(objectId);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!plan) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
        <div className="w-full max-w-md rounded-lg border border-border bg-surface p-5">
          <p className="text-sm font-semibold">Plano indisponível</p>
          <p className="mt-1 text-[13px] text-muted">{review.error?.message ?? "Não há plano guardado para este trabalho."}</p>
          <Button className="mt-4" onClick={onClose}>Fechar</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/75 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="plan-review-title">
      <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-xl border border-border bg-surface shadow-2xl sm:rounded-lg">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-surface px-4 py-3">
          <div>
            <p className="text-[11px] text-accent">Plano do Muse — revê antes de avançar</p>
            <h2 id="plan-review-title" className="mt-1 text-lg font-semibold">O que o Muse vai fazer</h2>
            <p className="mt-1 text-[12px] text-muted">Ainda não foi alterado nada. O teu original está intacto.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar revisão do plano"
            className="rounded-md border border-border px-2 py-1 font-mono text-[11px] text-muted hover:border-muted hover:text-foreground"
          >
            ESC
          </button>
        </header>

        <div className="space-y-5 px-4 py-4">
          <section aria-label="Resumo do plano" className="rounded-md border border-border bg-raised p-3">
            <p className="text-[13px] font-medium">{plan.interpreted_intention}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{plan.summary_explanation}</p>
            <dl className="mt-3 grid gap-2 text-[12px] sm:grid-cols-2">
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Assunto</dt>
                <dd className="truncate text-right" title={plan.subject.description}>{plan.subject.description}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Estratégia</dt>
                <dd className="text-right">{describeStrategy(plan.subject.strategy)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Resultado</dt>
                <dd className="text-right">{describeOutcome(plan.outcome)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Aprovação</dt>
                <dd className="text-right">{describeApproval(plan.approval_status)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Formato</dt>
                <dd className="text-right">{plan.target.format} · {plan.target.resolution} · {plan.target.aspect_ratio}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Áudio</dt>
                <dd className="text-right">{plan.target.preserve_audio ? "mantido" : "não pedido"}</dd>
              </div>
            </dl>
          </section>

          {hasDetection && (
            <section aria-label="Pessoas detectadas" className="rounded-md border border-accent/40 bg-accent/5 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-mono text-[10px] tracking-wider text-accent">
                    Pessoas detectadas — escolhe quem fica nítido
                  </p>
                  <p className="mt-1 text-[12px] text-muted">
                    {review.segmentation?.is_mock
                      ? "Simulação: detecção de demonstração, sem análise real."
                      : "Detecção real de pessoas."}
                  </p>
                </div>
                <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[9px] text-muted">
                  {review.segmentation?.frame_count ?? 0} fotogramas
                </span>
              </div>

              {noSubjects ? (
                <div className="mt-3 rounded border border-danger/40 bg-danger/10 p-2.5" role="alert">
                  <p className="text-[13px] font-medium text-danger">Nenhuma pessoa detectada</p>
                  <p className="mt-1 text-[12px] text-muted">
                    Não há quem manter nítido — esta edição não pode avançar. Tenta um clipe com uma pessoa visível.
                  </p>
                </div>
              ) : (
                <>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {review.subjects.map((subject) => {
                      const selected = selectedSubjects.includes(subject.object_id);
                      return (
                        <button
                          key={subject.object_id}
                          type="button"
                          aria-pressed={selected}
                          onClick={() => toggleSubject(subject.object_id)}
                          className={`overflow-hidden rounded-md border text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                            selected ? "border-accent bg-accent/10" : "border-border bg-raised hover:border-muted"
                          }`}
                        >
                          <div className="relative aspect-video bg-black/40">
                            <img
                              src={subjectPreviewUrl(review.job_id, subject.object_id)}
                              alt={`Pré-visualização da pessoa detectada ${subject.object_id}`}
                              className="h-full w-full object-contain"
                              loading="lazy"
                            />
                            <span className={`absolute right-2 top-2 rounded border px-1.5 py-0.5 font-mono text-[9px] ${selected ? "border-accent bg-accent text-[#14110C]" : "border-border bg-black/70 text-muted"}`}>
                              {selected ? "Manter" : "Escolher"}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-2 px-2.5 py-2">
                            <div>
                              <p className="text-[12px] font-medium">Pessoa {subject.object_id.slice(0, 8)}</p>
                              <p className="font-mono text-[9px] text-muted">
                                fotogramas {subject.first_frame ?? "?"}–{subject.last_frame ?? "?"} · {subject.frames_detected} com detecção
                              </p>
                            </div>
                            <span className="font-mono text-[9px] text-muted">{subject.label}</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-2 font-mono text-[10px] text-muted">
                    A selecção identifica pessoas neste vídeo, não reconhece identidades.
                    {needsSelection ? " Selecciona pelo menos uma pessoa para aprovar." : ""}
                  </p>
                </>
              )}
            </section>
          )}

          <section aria-label="Passos propostos">
            <div className="flex items-baseline justify-between">
              <h3 className="text-[11px] font-medium text-muted">Passos ({plan.operations.length})</h3>
              <p className="text-[10px] text-muted">por ordem</p>
            </div>
            <ol className="mt-2 space-y-2">
              {plan.operations.map((operation, index) => {
                const capability = capabilityById.get(operation.capability_id);
                const label = capabilityLabel(capability);
                const params = Object.entries(operation.params).filter(([key, value]) => key !== "type" && value !== null && value !== undefined);
                return (
                  <li key={operation.operation_id} className="rounded-md border border-border bg-background/40 p-3">
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border font-mono text-[10px] text-muted">
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-[13px] font-medium">{operation.title}</p>
                          <span className={`rounded border px-1.5 py-0.5 font-mono text-[9px] ${label === "Direto" ? "border-success/50 text-success" : label === "Indisponível" || label === "Em breve" ? "border-danger/50 text-danger" : "border-accent/40 text-accent"}`}>
                            {label}
                          </span>
                          {capability?.simulated && <span className="text-[10px] text-muted">Simulação</span>}
                          {capability?.requires_approval && <span className="text-[10px] text-accent">Precisa de aprovação</span>}
                        </div>
                        <p className="mt-1 font-mono text-[10px] text-muted">{operation.capability_id}</p>
                        <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{operation.explanation}</p>
                        {params.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-muted">
                            {params.map(([key, value]) => (
                              <span key={key}><span className="text-foreground/60">{key}</span>: {formatParam(value)}</span>
                            ))}
                          </div>
                        )}
                        <p className="mt-1.5 font-mono text-[10px] text-muted">→ {operation.expected_output}</p>
                        {operation.dependencies.length > 0 && (
                          <p className="mt-1 font-mono text-[10px] text-muted">depends on: {operation.dependencies.join(", ")}</p>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>

          <section aria-label="Verificação" className="rounded-md border border-border p-3">
            <p className="text-[11px] text-muted">Verificação</p>
            <p className="mt-1 text-[12px]">O resultado é verificado antes de ser entregue.</p>
          </section>

          {plan.unsupported_capabilities.length > 0 && (
            <section className="rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
              <p className="text-[13px] font-medium text-danger">Função indisponível</p>
              <p className="mt-1 text-[13px]">Esta versão não faz: {plan.unsupported_capabilities.join(", ")}.</p>
              <p className="mt-1 text-[12px] text-muted">{plan.summary_explanation}</p>
            </section>
          )}

          {awaitingClarification && (
            <section className="rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
              <p className="font-mono text-[10px] tracking-wider text-accent">Preciso de uma resposta</p>
              <p className="mt-1 text-[15px]">{review.clarification_question ?? plan.clarification_questions[0] ?? "Diz ao Muse quem deve ficar nítido"}</p>
              <label htmlFor="clarification-answer" className="mt-3 block font-mono text-[10px] text-muted">A tua resposta</label>
              <textarea
                id="clarification-answer"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={2}
                maxLength={300}
                disabled={submitting !== null}
                className="mt-1 w-full resize-none rounded-md border border-border bg-raised p-2 text-sm outline-none focus:border-accent disabled:opacity-60"
                placeholder="ex.: o senhor da esquerda; manter as duas pessoas nítidas…"
              />
              <Button className="mt-2" onClick={() => onClarify(answer.trim())} disabled={!answer.trim() || submitting !== null}>
                {submitting === "clarify" ? "A reconstruir…" : "Responder e reconstruir"}
              </Button>
              <p className="mt-2 font-mono text-[10px] text-muted">Nada é gerado sem a tua aprovação do novo plano.</p>
            </section>
          )}

          {rejected && (
            <section className="rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
              <p className="text-[13px] font-medium text-danger">Plano rejeitado</p>
              <p className="mt-1 text-[13px]">Nada foi gerado. O teu original está intacto.</p>
            </section>
          )}

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 p-3 text-[13px] text-danger" role="alert">
              {error}
            </div>
          )}
        </div>

        <footer className="sticky bottom-0 flex flex-wrap items-center justify-between gap-2 border-t border-border bg-surface px-4 py-3">
          <p className="font-mono text-[10px] text-muted">
            {awaitingApproval
              ? noSubjects
                ? "Sem pessoas detectadas: não é possível aprovar."
                : needsSelection
                  ? "Selecciona pelo menos uma pessoa detectada."
                  : hasDetection
                    ? `${selectedSubjects.length} pessoa${selectedSubjects.length === 1 ? "" : "s"} seleccionada${selectedSubjects.length === 1 ? "" : "s"}. Revê antes de gerar.`
                    : "Revê antes de alterar o vídeo."
              : unsupported
                ? "Não há plano suportado."
                : rejected
                  ? "Rejeitado — original intacto."
                  : "Responde para continuar."}
          </p>
          <div className="flex gap-2">
            {awaitingApproval && (
              <>
                <Button variant="ghost" onClick={onReject} disabled={submitting !== null}>
                  {submitting === "reject" ? "A rejeitar…" : "Rejeitar plano"}
                </Button>
                <Button onClick={onApprove} disabled={submitting !== null || !canApprove}>
                  {submitting === "approve" ? "A aprovar…" : hasDetection ? "Aprovar selecção e gerar" : "Aprovar e gerar"}
                </Button>
              </>
            )}
            {!awaitingApproval && (
              <Button variant="secondary" onClick={onClose}>Fechar</Button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
