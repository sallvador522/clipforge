"use client";

import { useEffect, useState } from "react";
import type { PlanCapabilityData, PlanReviewData } from "@/lib/types";
import { Button } from "./ui/button";

type Decision = "approve" | "reject" | "clarify" | null;

interface Props {
  review: PlanReviewData;
  submitting: Decision;
  error: string | null;
  onApprove: () => void;
  onReject: () => void;
  onClarify: (answer: string) => void;
  onClose: () => void;
}

function capabilityLabel(capability: PlanCapabilityData | undefined): string {
  if (!capability) return "UNKNOWN";
  if (capability.status === "available_mock") return "MOCK";
  if (capability.status === "available_local") return "LOCAL";
  if (capability.status === "available_live") return "LIVE";
  if (capability.status === "planned") return "PLANNED";
  return "UNAVAILABLE";
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
          <p className="text-sm font-semibold">Plan unavailable</p>
          <p className="mt-1 text-[13px] text-muted">{review.error?.message ?? "The API has no persisted plan for this job."}</p>
          <Button className="mt-4" onClick={onClose}>Close</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/75 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="plan-review-title">
      <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-xl border border-border bg-surface shadow-2xl sm:rounded-lg">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-surface px-4 py-3">
          <div>
            <p className="font-mono text-[10px] tracking-wider text-accent">DIRECTOR PLAN — REVIEW BEFORE EXECUTION</p>
            <h2 id="plan-review-title" className="mt-1 text-lg font-semibold">What ClipForge intends to do</h2>
            <p className="mt-1 text-[12px] text-muted">No video changes have been made yet. Your original is intact.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close plan review"
            className="rounded-md border border-border px-2 py-1 font-mono text-[11px] text-muted hover:border-muted hover:text-foreground"
          >
            ESC
          </button>
        </header>

        <div className="space-y-5 px-4 py-4">
          <section aria-label="Plan summary" className="rounded-md border border-border bg-raised p-3">
            <p className="text-[13px] font-medium">{plan.interpreted_intention}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{plan.summary_explanation}</p>
            <dl className="mt-3 grid gap-2 font-mono text-[11px] sm:grid-cols-2">
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Subject</dt>
                <dd className="truncate text-right" title={plan.subject.description}>{plan.subject.description}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Strategy</dt>
                <dd className="text-right">{plan.subject.strategy.replaceAll("_", " ")}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Outcome</dt>
                <dd className="text-right">{plan.outcome}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Capability approval</dt>
                <dd className="text-right">{plan.approval_status}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Output</dt>
                <dd className="text-right">{plan.target.format} · {plan.target.resolution} · {plan.target.aspect_ratio}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Audio</dt>
                <dd className="text-right">{plan.target.preserve_audio ? "preserved" : "not requested"}</dd>
              </div>
            </dl>
          </section>

          <section aria-label="Proposed operations">
            <div className="flex items-baseline justify-between">
              <h3 className="font-mono text-[11px] tracking-wider text-muted">OPERATIONS — {plan.operations.length}</h3>
              <p className="font-mono text-[10px] text-muted">order matters</p>
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
                          <span className={`rounded border px-1.5 py-0.5 font-mono text-[9px] ${label === "LIVE" ? "border-success/50 text-success" : label === "UNAVAILABLE" || label === "PLANNED" ? "border-danger/50 text-danger" : "border-accent/40 text-accent"}`}>
                            {label}
                          </span>
                          {capability?.simulated && <span className="font-mono text-[9px] text-muted">SIMULATED</span>}
                          {capability?.requires_approval && <span className="font-mono text-[9px] text-accent">APPROVAL</span>}
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

          <section aria-label="Verification" className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-border p-3">
              <p className="font-mono text-[10px] tracking-wider text-muted">REQUIRED PROVIDERS</p>
              <p className="mt-1 text-[12px]">{plan.required_providers.join(", ") || "local only"}</p>
            </div>
            <div className="rounded-md border border-border p-3">
              <p className="font-mono text-[10px] tracking-wider text-muted">VERIFICATION</p>
              <p className="mt-1 text-[12px]">{plan.verification_requirements.map((v) => v.check).join(" · ") || "standard output checks"}</p>
            </div>
          </section>

          {plan.unsupported_capabilities.length > 0 && (
            <section className="rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
              <p className="text-[13px] font-medium text-danger">Unavailable capability</p>
              <p className="mt-1 text-[13px]">This build cannot perform: {plan.unsupported_capabilities.join(", ")}.</p>
              <p className="mt-1 text-[12px] text-muted">{plan.summary_explanation}</p>
            </section>
          )}

          {awaitingClarification && (
            <section className="rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
              <p className="font-mono text-[10px] tracking-wider text-accent">CLARIFICATION NEEDED — ROUND {review.clarification_count + 1}</p>
              <p className="mt-1 text-[15px]">{review.clarification_question ?? plan.clarification_questions[0] ?? "Tell ClipForge who should stay sharp."}</p>
              <label htmlFor="clarification-answer" className="mt-3 block font-mono text-[10px] text-muted">YOUR ANSWER</label>
              <textarea
                id="clarification-answer"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={2}
                maxLength={300}
                disabled={submitting !== null}
                className="mt-1 w-full resize-none rounded-md border border-border bg-raised p-2 text-sm outline-none focus:border-accent disabled:opacity-60"
                placeholder="e.g. the man on the left, keep both people sharp…"
              />
              <Button className="mt-2" onClick={() => onClarify(answer.trim())} disabled={!answer.trim() || submitting !== null}>
                {submitting === "clarify" ? "Rebuilding plan…" : "Answer & rebuild plan"}
              </Button>
              <p className="mt-2 font-mono text-[10px] text-muted">No rendering happens until you approve the revised plan.</p>
            </section>
          )}

          {rejected && (
            <section className="rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
              <p className="text-[13px] font-medium text-danger">Plan rejected</p>
              <p className="mt-1 text-[13px]">No rendering was started. Your original video is untouched.</p>
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
              ? plan.approval_status === "required"
                ? "This plan includes a capability that requires approval."
                : "Review is required before any video changes."
              : unsupported
                ? "No supported edit plan is available."
                : rejected
                  ? "Rejected — original preserved."
                  : "Answer the clarification to continue."}
          </p>
          <div className="flex gap-2">
            {awaitingApproval && (
              <>
                <Button variant="ghost" onClick={onReject} disabled={submitting !== null}>
                  {submitting === "reject" ? "Rejecting…" : "Reject plan"}
                </Button>
                <Button onClick={onApprove} disabled={submitting !== null}>
                  {submitting === "approve" ? "Approving…" : "Approve & render"}
                </Button>
              </>
            )}
            {!awaitingApproval && (
              <Button variant="secondary" onClick={onClose}>Close</Button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
