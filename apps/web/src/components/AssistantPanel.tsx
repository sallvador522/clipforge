"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { JobResponse, JobResultData, PlanReviewData, TranscriptData } from "@/lib/types";
import { Button } from "./ui/button";

type RecorderState = "idle" | "recording" | "recorded" | "unsupported" | "denied";
export type TranscribeStatus = "idle" | "uploading" | "transcribing" | "done" | "error";
type TranscriptSource = "live" | "mock-audio" | "mock-fixture" | "typed" | null;

const STEPS = [
  { key: "instruction", label: "Listening to your instruction" },
  { key: "planning", label: "Understanding what you want" },
  { key: "detecting", label: "Detecting people in your video" },
  { key: "review", label: "Reviewing your plan" },
  { key: "rendering", label: "Bringing your video to life" },
  { key: "verifying", label: "Verifying your video" },
  { key: "completed", label: "Done — verified MP4" },
];
const STAGE_INDEX: Record<string, number> = {
  transcribing: 0, planning: 1, replanning: 1,
  segmenting: 2, awaiting_consent: 2,
  awaiting_approval: 3, awaiting_clarification: 3,
  approved: 4, preparing_masks: 4, preparing_background: 4, rendering: 4,
  verifying: 5, completed: 6, pipeline_completed: 6,
};
const STATUS_LABEL: Record<string, string> = {
  queued: "Getting ready",
  processing: "Working on it",
  awaiting_consent: "Waiting for your consent",
  awaiting_approval: "Ready for your review",
  awaiting_clarification: "Needs your answer",
  completed: "Done",
  failed: "Failed",
  rejected: "Rejected",
  unsupported: "Not supported",
};

interface Props {
  job: JobResponse | null;
  result: JobResultData | null;
  planReview: PlanReviewData | null;
  onOpenPlanReview: () => void;
  liveAvailable: boolean;
  recorded: boolean;
  recordingName: string | null;
  onRecordingReady: (blob: Blob, filename: string) => void;
  onRecordingCleared: () => void;
  transcribeStatus: TranscribeStatus;
  transcribeProgress: number | null;
  transcriptionError: string | null;
  transcript: TranscriptData | null;
  transcriptSource: TranscriptSource;
  draft: string;
  onDraftChange: (value: string) => void;
  onTranscribe: () => void;
  onTypedInstruction: (text: string) => void;
  canConfirm: boolean;
  confirming: boolean;
  submitted: boolean;
  onConfirmTranscript: () => void;
  onRetry: () => void;
  reviewOpen: boolean;
  consentWaiting: boolean;
  onConsentContinue: () => void;
  /** Overrides the confirm button label when no edit job exists (idea flow). */
  confirmLabel?: string;
  /** True when the session has no clip and no edit job: confirming creates a new video. */
  emptyPlatform?: boolean;
}

export function AssistantPanel({
  job, result, planReview, onOpenPlanReview, liveAvailable, recorded, recordingName,
  onRecordingReady, onRecordingCleared, transcribeStatus, transcribeProgress, transcriptionError,
  transcript, transcriptSource, draft, onDraftChange, onTranscribe,
  onTypedInstruction, canConfirm, confirming, submitted, onConfirmTranscript, onRetry,
  reviewOpen, consentWaiting, onConsentContinue, confirmLabel, emptyPlatform,
}: Props) {
  const [recState, setRecState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [typedText, setTypedText] = useState("");
  const [typeNotice, setTypeNotice] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => () => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    cancelAnimationFrame(rafRef.current);
  }, []);

  async function startRecording() {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setRecState("unsupported");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128) / 128);
        setLevel(peak);
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();

      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = () => {
        cancelAnimationFrame(rafRef.current);
        setLevel(0);
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        setAudioUrl(URL.createObjectURL(blob));
        setRecState("recorded");
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        onRecordingReady(blob, `instruction.${ext}`);
      };
      recorderRef.current = recorder;
      setSeconds(0);
      recorder.start();
      setRecState("recording");
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch {
      setRecState("denied");
    }
  }

  function stopRecording() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    recorderRef.current?.stop();
  }

  function applyTyped() {
    if (!typedText.trim()) return;
    setTypeNotice(null);
    onTypedInstruction(typedText.trim());
  }

  const busy = transcribeStatus === "uploading" || transcribeStatus === "transcribing";
  const verified = Boolean(job?.status === "completed" && result?.render_status === "verified");
  const detected = Boolean(planReview?.segmentation || result?.segmentation);
  // No step is invented for failed or no-render terminal jobs; the explicit
  // notice/error below carries the real state instead.
  const hideSteps =
    job?.status === "failed" || job?.status === "rejected" || job?.status === "unsupported";
  const stageIndex = job
    ? job.status === "completed" && !verified
      ? 2
      : STAGE_INDEX[job.stage] ?? (job.status === "queued" ? -1 : 0)
    : -1;
  const plan = result?.plan ?? job?.result?.plan ?? null;
  const directorPlan = planReview?.plan ?? result?.director_plan ?? job?.result?.director_plan ?? null;

  return (
    <section aria-label="AI editing assistant" className="flex min-h-0 flex-col bg-surface lg:h-full">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="font-mono text-[11px] font-medium tracking-wider text-muted">AI ASSISTANT</h2>
        <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${liveAvailable ? "border-success/60 text-success" : "border-accent/50 text-accent"}`}>
          {liveAvailable ? "LIVE TRANSCRIPTION" : "MOCK TRANSCRIPTION"}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        <div>
          <p className="text-[15px] font-semibold leading-snug">
            {emptyPlatform ? "No clip yet — describe the video you want." : "Tell ClipForge what to change."}
          </p>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">
            {emptyPlatform
              ? "Record or type your idea, then send it. ClipForge plans it, you approve each cost, and the Studio renders a verified MP4."
              : "Record or type your instruction, then send it. Only the confirmed sentence reaches the editing planner."}
          </p>
        </div>

        <div className="flex items-center gap-4">
          <motion.button
            type="button"
            onClick={recState === "recording" ? stopRecording : startRecording}
            disabled={submitted}
            aria-label={recState === "recording" ? "Stop recording" : "Start voice recording"}
            className={`relative flex h-16 w-16 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground disabled:opacity-40 ${
              recState === "recording" ? "bg-danger" : "bg-accent hover:bg-[#FF8A70]"
            }`}
            animate={{ scale: recState === "recording" ? 1 + level * 0.25 : 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 18 }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
              <rect x="9" y="3" width="6" height="11" rx="3" fill="#14110C" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="#14110C" strokeWidth="2" strokeLinecap="round" />
            </svg>
            {recState === "recording" && (
              <span className="absolute -bottom-5 font-mono text-[11px] tabular-nums text-danger">
                00:{String(seconds).padStart(2, "0")}
              </span>
            )}
          </motion.button>
          <div aria-live="polite">
            <p className="text-sm font-medium">
              {recState === "recording" && "Listening… tap to stop"}
              {recState === "recorded" && `Recorded 00:${String(seconds).padStart(2, "0")}`}
              {recState === "idle" && "Tap the microphone and speak"}
              {recState === "unsupported" && "MediaRecorder unavailable in this browser"}
              {recState === "denied" && "Microphone permission denied"}
            </p>
            {recState === "recording" && (
              <div className="mt-1.5 h-1 w-32 overflow-hidden rounded bg-border" aria-hidden>
                <div className="h-full bg-danger transition-[width] duration-100" style={{ width: `${Math.round(level * 100)}%` }} />
              </div>
            )}
            <p className="mt-1 font-mono text-[11px] text-muted">
              {recorded && recordingName ? `Audio captured: ${recordingName}` : "The ring reacts to your actual voice level."}
            </p>
          </div>
        </div>

        {audioUrl && recState === "recorded" && (
          <audio
            controls
            src={audioUrl}
            className="w-full rounded-md border border-border bg-raised"
            style={{ colorScheme: "dark" }}
            aria-label="Your recorded instruction"
          />
        )}

        {recState === "recorded" && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-muted">
                {liveAvailable
                  ? transcribeStatus === "done"
                    ? "Transcript ready below — review and send it."
                    : "Sending your recording for transcription…"
                  : "Recording kept locally — mock mode never transcribes audio."}
              </span>
              <Button
                variant="ghost"
                onClick={() => {
                  setAudioUrl(null);
                  setRecState("idle");
                  onRecordingCleared();
                }}
                disabled={busy || submitted}
              >
                Discard recording
              </Button>
            </div>
            {!liveAvailable && (
              <p className="font-mono text-[11px] text-muted">
                This server is in mock mode, so recorded audio is not transcribed. Use the typed instruction below, or
                enable <span className="text-foreground">CLIPFORGE_TRANSCRIBE_MODE=live</span>.
              </p>
            )}
          </div>
        )}

        {transcribeStatus === "uploading" && transcribeProgress !== null && (
          <div>
            <div className="h-1 overflow-hidden rounded bg-border">
              <div className="h-full bg-accent transition-[width]" style={{ width: `${transcribeProgress}%` }} />
            </div>
            <p className="mt-1 font-mono text-[11px] text-muted">Sending audio to the local API… {transcribeProgress}%</p>
          </div>
        )}

        {transcriptionError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
            <p className="text-[13px] font-medium text-danger">Transcription failed</p>
            <p className="mt-1 text-[13px]">{transcriptionError}</p>
            <div className="mt-2 flex gap-2">
              {recorded && (
                <Button variant="danger" onClick={onTranscribe} disabled={busy}>
                  Retry transcription
                </Button>
              )}
              <p className="self-center font-mono text-[11px] text-muted">No retry happens automatically.</p>
            </div>
          </div>
        )}

        {(transcript || draft) && (
          <div className="space-y-2 border-t border-border pt-4">
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-[11px] text-muted">RECOGNISED INSTRUCTION — REVIEW & CONFIRM</p>
              {transcript?.is_mock && <span className="rounded border border-accent/50 px-1.5 py-0.5 font-mono text-[10px] text-accent">MOCK</span>}
              {transcriptSource === "typed" && <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted">TYPED</span>}
            </div>
            <textarea
              value={draft}
              onChange={(e) => onDraftChange(e.target.value)}
              rows={3}
              maxLength={500}
              disabled={submitted}
              aria-label="Transcript to confirm"
              className="w-full resize-none rounded-md border border-border bg-raised p-2.5 text-sm outline-none focus:border-accent disabled:opacity-70"
            />
            <p className="font-mono text-[11px] text-muted">
              {transcript?.provider_name ?? (transcriptSource === "typed" ? "typed by you" : "pending")}
              {transcript?.session_id ? ` · session ${transcript.session_id}` : ""}
              {transcript?.audio_duration_ms ? ` · ${transcript.audio_duration_ms} ms audio` : ""}
              {transcript?.confidence != null ? ` · confidence ${transcript.confidence.toFixed(2)}` : ""}
            </p>
            <Button onClick={onConfirmTranscript} disabled={!canConfirm || confirming || submitted || !draft.trim()} className="w-full">
              {submitted ? "Editing in progress…" : confirming ? "Sending…" : (confirmLabel ?? "Send to ClipForge")}
            </Button>
            {!job && (
              <p className="font-mono text-[11px] text-muted">
                {emptyPlatform
                  ? "No clip in this session — sending creates a new video from your idea."
                  : "Upload a clip first — the job is created in the Media panel."}
              </p>
            )}
          </div>
        )}

        <div className="space-y-2">
          <label htmlFor="typed-instruction" className="font-mono text-[11px] text-muted">
            OR TYPE THE INSTRUCTION
          </label>
          <div className="flex gap-2">
            <input
              id="typed-instruction"
              name="instruction"
              autoComplete="off"
              value={typedText}
              onChange={(e) => setTypedText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applyTyped()}
              placeholder="e.g. blur the background"
              disabled={submitted}
              className="min-w-0 flex-1 rounded-md border border-border bg-raised px-2.5 py-2 text-sm outline-none placeholder:text-muted/60 focus:border-accent"
            />
            <Button variant="secondary" onClick={applyTyped} disabled={submitted || !typedText.trim()}>
              Use
            </Button>
          </div>
          {typeNotice && <p className="text-[13px] text-accent" role="status">{typeNotice}</p>}
          <p className="font-mono text-[11px] text-muted">Typed text is used verbatim; it is not transcription.</p>
        </div>

        <AnimatePresence>
          {job && (
            <motion.div
              key="progress"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="border-t border-border pt-4"
            >
              <div className="flex items-baseline justify-between">
                <p className="font-mono text-[11px] text-muted">JOB PROGRESS</p>
                <p className="font-mono text-[11px] text-muted">{job.job_id.slice(0, 8)}… · try {job.attempts}</p>
              </div>
              <p className="mt-1.5 text-sm font-medium">Status:{" "}
                <span className={job.status === "failed" || job.status === "rejected" || job.status === "unsupported" ? "text-danger" : verified ? "text-success" : "text-accent"}>
                  {STATUS_LABEL[job.status] ?? job.status}
                </span>{" "}
                <span className="font-mono text-[11px] text-muted">({job.stage})</span>
              </p>
              {planReview && !reviewOpen && (job.status === "awaiting_approval" || job.status === "awaiting_clarification") && (
                <button type="button" onClick={onOpenPlanReview} className="mt-1 font-mono text-[11px] text-accent underline underline-offset-2 hover:text-foreground">
                  Review plan
                </button>
              )}
              {consentWaiting && (
                <div className="mt-3 rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
                  <p className="text-[13px] font-medium">Your plan needs people detection first.</p>
                  <p className="mt-1 text-[12px] text-muted">Consent to the external SAM check to continue — nothing has been sent yet.</p>
                  <Button className="mt-2" onClick={onConsentContinue}>Continue with subject detection</Button>
                </div>
              )}
              {job.status === "awaiting_approval" && (
                <div className="mt-3 rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
                  <p className="text-[13px] font-medium">Plan ready for your review.</p>
                  <p className="mt-1 text-[12px] text-muted">No video changes have been made. Approve the plan to render.</p>
                </div>
              )}
              {job.status === "awaiting_clarification" && (
                <div className="mt-3 rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
                  <p className="text-[13px] font-medium">ClipForge needs one clarification.</p>
                  <p className="mt-1 text-[12px] text-muted">Answer the question to rebuild the plan; no rendering has started.</p>
                </div>
              )}
              {job.status === "rejected" && (
                <div className="mt-3 rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
                  <p className="text-[13px] font-medium text-danger">Plan rejected</p>
                  <p className="mt-1 text-[12px]">No rendering was started. Your original video is untouched.</p>
                  <Button variant="secondary" className="mt-2" onClick={onRetry}>Start a new session</Button>
                </div>
              )}
              {job.status === "unsupported" && (
                <div className="mt-3 rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
                  <p className="text-[13px] font-medium text-danger">
                    {job.error?.code === "NoSubjectsDetected" ? "No people detected" : "Request not supported"}
                  </p>
                  <p className="mt-1 text-[12px]">
                    {job.error?.code === "NoSubjectsDetected"
                      ? job.error.message
                      : planReview?.plan?.summary_explanation ?? "This build cannot perform the requested edit."}
                  </p>
                </div>
              )}

              {!hideSteps && (
                <ol className="mt-2.5 space-y-1.5">
                  {STEPS.map((step, i) => {
                    const done = verified || (i < stageIndex && (i !== 2 || detected));
                    const active = !verified && job.status !== "failed" && i === stageIndex;
                    return (
                      <li key={step.key} className={`flex items-center gap-2 text-[13px] ${done ? "text-success" : active ? "text-foreground" : "text-muted/60"}`}>
                        <span className={`flex h-4 w-4 items-center justify-center rounded-full border font-mono text-[9px] ${done ? "border-success" : active ? "border-accent" : "border-border"}`}>
                          {done ? "✓" : active ? "●" : ""}
                        </span>
                        {step.label}
                      </li>
                    );
                  })}
                </ol>
              )}

              {job.status === "failed" && job.error && (
                <div className="mt-3 rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
                  <p className="font-mono text-[11px] text-danger">{job.error.code}</p>
                  <p className="mt-1 text-[13px]">{job.error.message}</p>
                  <Button variant="danger" className="mt-2.5" onClick={onRetry}>Start a new session</Button>
                </div>
              )}

              {result?.transcript && (
                <div className="mt-3 border-t border-border pt-3">
                  <p className="font-mono text-[11px] text-muted">PLANNED FROM {result.transcript.is_mock ? "MOCK TRANSCRIPT" : "CONFIRMED TRANSCRIPT"}</p>
                  <p className="mt-1 text-sm">“{result.transcript.text}”</p>
                  {plan && (
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      plan: {plan.intent} · {plan.operations.map((o) => o.type).join(", ") || "no operations"}
                    </p>
                  )}
                  {directorPlan && (
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      director: {directorPlan.operations.map((o) => o.title).join(" · ") || "no operations"}
                    </p>
                  )}
                  {result?.rendered && (
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      render: {result.rendered.mode} · {result.rendered.width}×{result.rendered.height} · {result.rendered.frame_count} frames ·{" "}
                      {result.rendered.duration_seconds.toFixed(2)}s · audio {result.rendered.has_audio ? "preserved" : "none in source"}
                    </p>
                  )}
                  {result && (
                    <div className="mt-2 border-t border-border pt-2 font-mono text-[11px] leading-relaxed text-muted">
                      <p>MODELS USED (from this job&apos;s execution record):</p>
                      <p>
                        voice:{" "}
                        {result.transcript == null
                          ? "not called"
                          : result.transcript.provider_name === "user-confirmed"
                            ? "not called (typed instruction)"
                            : result.transcript.is_mock
                              ? `mock fixture (${result.transcript.provider_name})`
                              : `${result.transcript.provider_name} — LIVE`}
                      </p>
                      <p>
                        director:{" "}
                        {directorPlan == null
                          ? "not called"
                          : result.director_usage != null
                            ? "Muse Spark — LIVE"
                            : "deterministic mock"}
                      </p>
                      <p>
                        segmentation:{" "}
                        {result.segmentation == null
                          ? "not called"
                          : result.segmentation.is_mock
                            ? `synthetic mock (${result.segmentation.provider_name})`
                            : `${result.segmentation.provider_name} ${result.segmentation.model ?? ""} — LIVE`}
                      </p>
                      <p>
                        background:{" "}
                        {result.background == null
                          ? "not called"
                          : result.background.is_mock
                            ? "local mock asset"
                            : "Muse Image — LIVE"}
                      </p>
                      <p>render: local FFmpeg/OpenCV (never billed)</p>
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  );
}
