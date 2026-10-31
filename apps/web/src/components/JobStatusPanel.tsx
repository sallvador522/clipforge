"use client";

import { motion, useReducedMotion } from "motion/react";
import type { JobResponse, JobResultData } from "@/lib/types";

const STAGE_LABELS: Record<string, string> = {
  awaiting_voice: "Waiting for your voice instruction",
  queued: "Queued for the editing worker",
  processing: "Worker picked up the job",
  transcribing: "Transcribing voice (mock provider)",
  planning: "Building the editing plan",
  segmenting: "Segmenting the subject (mock masks)",
  preparing_background: "Preparing background (mock asset)",
  rendering: "Rendering video — FFmpeg + OpenCV",
  verifying: "Verifying the rendered file",
  completed: "Completed and verified",
  pipeline_completed: "Completed",
  clarification_needed: "Clarification needed",
  unsupported_intent: "Instruction not supported yet",
  failed: "Failed",
};

const STAGE_ORDER = ["transcribing", "planning", "segmenting", "rendering", "verifying", "completed"];

interface Props {
  job: JobResponse | null;
  result: JobResultData | null;
}

export function JobStatusPanel({ job, result }: Props) {
  const reduceMotion = useReducedMotion();
  if (!job) return null;

  const stageLabel = STAGE_LABELS[job.stage] ?? job.stage;
  const currentIndex = STAGE_ORDER.indexOf(job.stage === "pipeline_completed" ? "completed" : job.stage);
  const transcript = result?.transcript ?? job.result?.transcript ?? null;
  const plan = result?.plan ?? job.result?.plan ?? null;

  return (
    <motion.section
      aria-label="Job status"
      className="space-y-3"
      initial={reduceMotion ? undefined : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 260, damping: 26 }}
    >
      <h2 className="font-mono text-xs tracking-widest text-muted uppercase">03 — Processing</h2>
      <div className="rounded-lg border border-border bg-surface p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-base font-semibold">
            Status: <span className={job.status === "failed" ? "text-danger" : job.status === "completed" ? "text-success" : "text-accent"}>{job.status}</span>
          </p>
          <p className="font-mono text-xs text-muted">
            job {job.job_id.slice(0, 12)}… · attempts {job.attempts}
          </p>
        </div>
        <p className="mt-1 font-mono text-xs text-muted" aria-live="polite">
          Stage: {stageLabel} <span className="text-border">|</span> raw stage: {job.stage}
        </p>

        {job.status !== "completed" && job.status !== "failed" && (
          <ol className="mt-4 flex flex-wrap gap-x-4 gap-y-1" aria-label="Pipeline stages">
            {STAGE_ORDER.map((stage, i) => (
              <li
                key={stage}
                className={`font-mono text-xs ${i < currentIndex ? "text-success" : i === currentIndex ? "text-accent" : "text-muted/60"}`}
              >
                {i < currentIndex ? "✓ " : i === currentIndex ? "● " : "○ "}
                {STAGE_LABELS[stage]}
              </li>
            ))}
          </ol>
        )}

        {job.status === "failed" && job.error && (
          <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
            <p className="font-mono text-xs text-danger">{job.error.code}</p>
            <p className="mt-1 text-sm">{job.error.message}</p>
            <p className="mt-1 text-sm text-muted">Your original upload is preserved. Start a new session to retry.</p>
          </div>
        )}

        {result?.requires_clarification && plan?.subject.clarification_question && (
          <div className="mt-4 rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
            <p className="text-sm font-medium">The editor needs one clarification:</p>
            <p className="mt-1 text-base">“{plan.subject.clarification_question}”</p>
            <p className="mt-1 font-mono text-xs text-muted">Start a new session and name the person to keep sharp.</p>
          </div>
        )}

        {transcript && (
          <div className="mt-4 border-t border-border pt-3">
            <p className="font-mono text-xs text-muted uppercase">Transcription {transcript.is_mock ? "(mock provider)" : ""}</p>
            <p className="mt-1 text-base">“{transcript.text}”</p>
            <p className="font-mono text-xs text-muted">
              {transcript.language} · confidence {transcript.confidence.toFixed(2)} · {transcript.provider_name}
            </p>
          </div>
        )}

        {plan && (
          <div className="mt-3">
            <p className="font-mono text-xs text-muted uppercase">Editing plan</p>
            <p className="mt-1 font-mono text-xs">
              intent: {plan.intent} · operations: {plan.operations.map((o) => o.type).join(", ") || "none"} · audio preserved:{" "}
              {String(plan.preserve_audio)}
            </p>
          </div>
        )}

        {result?.rendered && (
          <div className="mt-3">
            <p className="font-mono text-xs text-muted uppercase">Verified render</p>
            <p className="mt-1 font-mono text-xs">
              {result.rendered.mode} · {result.rendered.width}×{result.rendered.height} · {result.rendered.frame_count} frames ·{" "}
              {result.rendered.duration_seconds.toFixed(2)}s · {(result.rendered.file_size_bytes / 1024).toFixed(0)} KB · audio:{" "}
              {result.rendered.has_audio ? "present (original)" : "none in source"}
            </p>
          </div>
        )}
      </div>
    </motion.section>
  );
}
