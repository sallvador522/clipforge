"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { VOICE_FIXTURES, matchFixtureByText } from "@/lib/fixtures";
import type { JobResponse, JobResultData } from "@/lib/types";
import { Button } from "./ui/button";

type RecorderState = "idle" | "recording" | "recorded" | "unsupported" | "denied";

const STEPS = [
  { key: "transcribing", label: "Transcribe voice" },
  { key: "planning", label: "Build editing plan" },
  { key: "segmenting", label: "Segment subject (mock masks)" },
  { key: "rendering", label: "Render — FFmpeg + OpenCV" },
  { key: "verifying", label: "Verify output file" },
  { key: "completed", label: "Done — verified MP4" },
];
const STAGE_INDEX: Record<string, number> = {
  transcribing: 0, planning: 1, segmenting: 2, preparing_background: 2, rendering: 3, verifying: 4,
  completed: 5, pipeline_completed: 5,
};

interface Props {
  job: JobResponse | null;
  result: JobResultData | null;
  fixtureId: string;
  onSelectFixture: (id: string) => void;
  canSubmit: boolean;
  submitting: boolean;
  submitted: boolean;
  onSubmit: () => void;
  onRetry: () => void;
}

export function AssistantPanel({ job, result, fixtureId, onSelectFixture, canSubmit, submitting, submitted, onSubmit, onRetry }: Props) {
  const [recState, setRecState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [micFallback, setMicFallback] = useState(false);
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
      // Real input level drives the microphone ring — never a fake waveform.
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
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        setAudioUrl(URL.createObjectURL(blob));
        setRecState("recorded");
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

  function applyTypedInstruction() {
    const match = matchFixtureByText(typedText);
    if (!match) {
      setTypeNotice("The mock editor doesn't recognise that phrasing yet. Try “blur the background”, “keep me sharp”, or “replace the background with a studio”.");
      return;
    }
    setTypeNotice(null);
    onSelectFixture(match.id);
    setMicFallback(true); // typed instruction is the accessible alternative to the microphone
  }

  const selected = VOICE_FIXTURES.find((f) => f.id === fixtureId);
  const readyToSubmit = (recState === "recorded" || micFallback) && Boolean(selected);
  const transcript = result?.transcript ?? job?.result?.transcript ?? null;
  const plan = result?.plan ?? job?.result?.plan ?? null;
  const stageIndex = job ? STAGE_INDEX[job.stage] ?? (job.status === "queued" ? -1 : 0) : -1;

  return (
    <section aria-label="AI editing assistant" className="flex min-h-0 flex-col bg-surface lg:h-full">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="font-mono text-[11px] font-medium tracking-wider text-muted">AI ASSISTANT</h2>
        <span className="rounded border border-accent/50 px-1.5 py-0.5 font-mono text-[10px] text-accent">MOCK MODE</span>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        <div>
          <p className="text-[15px] font-semibold leading-snug">Tell ClipForge what to change.</p>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">
            Speak an instruction, review what was recognised, then confirm. Transcription is simulated in mock mode — the
            transcript returned by the backend appears below after processing.
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
            <p className="mt-1 font-mono text-[11px] text-muted">The ring reacts to your actual voice level.</p>
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

        {(recState === "unsupported" || recState === "denied") && !micFallback && (
          <button type="button" className="text-sm text-accent underline" onClick={() => setMicFallback(true)}>
            Continue without a microphone
          </button>
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
              onKeyDown={(e) => e.key === "Enter" && applyTypedInstruction()}
              placeholder="e.g. blur the background"
              disabled={submitted}
              className="min-w-0 flex-1 rounded-md border border-border bg-raised px-2.5 py-2 text-sm outline-none placeholder:text-muted/60 focus:border-accent"
            />
            <Button variant="secondary" onClick={applyTypedInstruction} disabled={submitted || !typedText.trim()}>
              Use
            </Button>
          </div>
          {typeNotice && (
            <p className="text-[13px] text-accent" role="status">{typeNotice}</p>
          )}
        </div>

        <div className="space-y-2">
          <p className="font-mono text-[11px] text-muted">CONFIRM THE RECOGNISED COMMAND (SIMULATED)</p>
          <div className="grid gap-1.5" role="radiogroup" aria-label="Recognised voice command">
            {VOICE_FIXTURES.map((fixture) => (
              <button
                key={fixture.id}
                type="button"
                role="radio"
                aria-checked={fixture.id === fixtureId}
                disabled={submitted}
                onClick={() => onSelectFixture(fixture.id)}
                className={`rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                  fixture.id === fixtureId ? "border-accent bg-raised" : "border-border hover:border-muted"
                }`}
              >
                <span className="block text-[13px] font-medium">{fixture.label}</span>
                <span className="block font-mono text-[11px] text-muted">“{fixture.transcript}”</span>
              </button>
            ))}
          </div>
          <Button onClick={onSubmit} disabled={!canSubmit || !readyToSubmit || submitting || submitted} className="w-full">
            {job?.status === "completed"
              ? "Editing complete — preview & export"
              : submitted
                ? "Editing in progress…"
                : submitting
                  ? "Submitting…"
                  : "Confirm & start editing"}
          </Button>
          {!job && <p className="font-mono text-[11px] text-muted">Upload a clip first — the job is created in the Media panel.</p>}
          {job && !readyToSubmit && !submitted && (
            <p className="font-mono text-[11px] text-muted">Record (or type) an instruction, with a command confirmed, to enable editing.</p>
          )}
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
              <p className="mt-1.5 text-sm">
                Status:{" "}
                <span className={job.status === "failed" ? "text-danger" : job.status === "completed" ? "text-success" : "text-accent"}>
                  {job.status}
                </span>{" "}
                <span className="font-mono text-[11px] text-muted">({job.stage})</span>
              </p>
              <ol className="mt-2.5 space-y-1.5">
                {STEPS.map((step, i) => {
                  const done = job.status === "completed" || i < stageIndex;
                  const active = job.status !== "completed" && job.status !== "failed" && i === stageIndex;
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

              {job.status === "failed" && job.error && (
                <div className="mt-3 rounded-md border border-danger/40 bg-danger/10 p-3" role="alert">
                  <p className="font-mono text-[11px] text-danger">{job.error.code}</p>
                  <p className="mt-1 text-[13px]">{job.error.message}</p>
                  <Button variant="danger" className="mt-2.5" onClick={onRetry}>Start a new session</Button>
                </div>
              )}

              {result?.requires_clarification && plan?.subject.clarification_question && (
                <div className="mt-3 rounded-md border border-accent/40 bg-accent/10 p-3" role="status">
                  <p className="text-[13px] font-medium">One clarification before editing:</p>
                  <p className="mt-1 text-[15px]">“{plan.subject.clarification_question}”</p>
                  <p className="mt-1 font-mono text-[11px] text-muted">Start a new session and name who stays sharp.</p>
                </div>
              )}

              {transcript && (
                <div className="mt-3 border-t border-border pt-3">
                  <p className="font-mono text-[11px] text-muted">TRANSCRIPTION {transcript.is_mock ? "(MOCK)" : ""}</p>
                  <p className="mt-1 text-sm">“{transcript.text}”</p>
                  {plan && (
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      plan: {plan.intent} · {plan.operations.map((o) => o.type).join(", ") || "no operations"}
                    </p>
                  )}
                  {result?.rendered && (
                    <p className="mt-1 font-mono text-[11px] text-muted">
                      render: {result.rendered.mode} · {result.rendered.width}×{result.rendered.height} · {result.rendered.frame_count} frames ·{" "}
                      {result.rendered.duration_seconds.toFixed(2)}s · audio {result.rendered.has_audio ? "preserved" : "none in source"}
                    </p>
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
