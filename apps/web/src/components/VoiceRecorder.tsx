"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { VOICE_FIXTURES } from "@/lib/fixtures";
import { Button } from "./ui/button";

type RecorderState = "idle" | "recording" | "recorded" | "unsupported" | "denied";

interface Props {
  selectedFixtureId: string;
  onSelectFixture: (id: string) => void;
  canSubmit: boolean;
  submitting: boolean;
  submitted: boolean;
  onSubmit: () => void;
}

export function VoiceRecorder({ selectedFixtureId, onSelectFixture, canSubmit, submitting, submitted, onSubmit }: Props) {
  const reduceMotion = useReducedMotion();
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [micFallback, setMicFallback] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (timerRef.current) window.clearInterval(timerRef.current);
  }, []);

  async function startRecording() {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        setAudioUrl(URL.createObjectURL(blob));
        setState("recorded");
      };
      recorderRef.current = recorder;
      setSeconds(0);
      recorder.start();
      setState("recording");
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch {
      setState("denied");
    }
  }

  function stopRecording() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    recorderRef.current?.stop();
  }

  const selected = VOICE_FIXTURES.find((f) => f.id === selectedFixtureId);
  const readyToSubmit = (state === "recorded" || micFallback) && Boolean(selected);

  return (
    <section aria-label="Voice instruction" className="space-y-3">
      <h2 className="font-mono text-xs tracking-widest text-muted uppercase">02 — Voice instruction</h2>
      <div className="rounded-lg border border-border bg-surface p-5">
        <div className="flex items-center gap-4">
          {state !== "recording" ? (
            <Button onClick={startRecording} disabled={submitted} aria-label="Start recording">
              Record instruction
            </Button>
          ) : (
            <Button variant="danger" onClick={stopRecording} aria-label="Stop recording">
              Stop
            </Button>
          )}
          <div className="flex items-center gap-2" aria-live="polite">
            {state === "recording" && (
              <motion.span
                className="inline-block h-3 w-3 rounded-full bg-danger"
                animate={reduceMotion ? undefined : { opacity: [1, 0.25, 1], scale: [1, 0.8, 1] }}
                transition={{ duration: 1.2, repeat: Infinity }}
              />
            )}
            <span className="font-mono text-sm text-muted">
              {state === "recording" && `Recording… 00:${String(seconds).padStart(2, "0")}`}
              {state === "recorded" && `Recorded 00:${String(seconds).padStart(2, "0")} — ready`}
              {state === "idle" && "Microphone idle"}
              {state === "unsupported" && "MediaRecorder is not available in this browser"}
              {state === "denied" && "Microphone permission was denied"}
            </span>
          </div>
        </div>

        {audioUrl && state === "recorded" && (
          <audio controls src={audioUrl} className="mt-4 w-full" aria-label="Your recorded instruction" />
        )}

        {(state === "unsupported" || state === "denied") && !micFallback && (
          <button type="button" className="mt-3 text-sm text-accent underline" onClick={() => setMicFallback(true)}>
            Continue without a microphone (mock command only)
          </button>
        )}

        <div className="mt-5 space-y-2">
          <p className="font-mono text-xs text-muted">
            MOCK MODE — simulated transcription. Speak your instruction, then confirm the matching command below.
            The backend transcript appears in the result after processing.
          </p>
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Mock voice command">
            {VOICE_FIXTURES.map((fixture) => (
              <button
                key={fixture.id}
                type="button"
                role="radio"
                aria-checked={fixture.id === selectedFixtureId}
                disabled={submitted}
                onClick={() => onSelectFixture(fixture.id)}
                className={`rounded-md border p-3 text-left transition-colors ${
                  fixture.id === selectedFixtureId ? "border-accent bg-raised" : "border-border hover:border-muted"
                }`}
              >
                <span className="block text-sm font-medium">{fixture.label}</span>
                <span className="mt-1 block font-mono text-xs text-muted">“{fixture.transcript}”</span>
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5">
          <Button onClick={onSubmit} disabled={!canSubmit || !readyToSubmit || submitting || submitted}>
            {submitted ? "Instruction submitted" : submitting ? "Submitting…" : "Submit instruction & start editing"}
          </Button>
          {!readyToSubmit && !submitted && (
            <p className="mt-2 font-mono text-xs text-muted">Record first (or use the no-microphone fallback), with a command selected.</p>
          )}
        </div>
      </div>
    </section>
  );
}
