"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { JobResponse, PlanReviewData } from "@/lib/types";
import { Button } from "./ui/button";

export interface ChatMessage {
  id: string;
  role: "user" | "muse";
  text: string;
}

type RecorderState = "idle" | "recording" | "recorded" | "unsupported" | "denied";
export type TranscribeStatus = "idle" | "uploading" | "transcribing" | "done" | "error";

const STAGE_LABEL: Record<string, string> = {
  transcribing: "A transcrever",
  planning: "A planear",
  replanning: "A planear",
  segmenting: "A analisar o vídeo",
  awaiting_consent: "A aguardar autorização",
  awaiting_approval: "A aguardar revisão",
  awaiting_clarification: "Preciso de uma resposta",
  approved: "Aprovado — a gerar",
  preparing_masks: "A preparar",
  preparing_background: "A preparar",
  rendering: "A gerar o vídeo",
  verifying: "A verificar",
  completed: "Concluído",
  pipeline_completed: "Concluído",
};

interface Props {
  messages: ChatMessage[];
  emptyPlatform: boolean;
  job: JobResponse | null;
  resultReady: boolean;
  planReview: PlanReviewData | null;
  onOpenPlanReview: () => void;
  onRejectPlan: () => void;
  decisionBusy: boolean;
  liveAvailable: boolean;
  /** ADR-053: true = respostas reescritas pelo Muse Spark (pago); false = router local sem custo. */
  chatLive?: boolean;
  working?: boolean;
  recorded: boolean;
  recordingName: string | null;
  onRecordingReady: (blob: Blob, filename: string) => void;
  onRecordingCleared: () => void;
  transcribeStatus: TranscribeStatus;
  transcribeProgress: number | null;
  transcriptionError: string | null;
  draft: string;
  onDraftChange: (value: string) => void;
  onTranscribe: () => void;
  canConfirm: boolean;
  confirming: boolean;
  onConfirmTranscript: () => void;
  onRetry: () => void;
  consentWaiting: boolean;
  onConsentContinue: () => void;
  confirmLabel?: string;
  /** Duration pills only make sense when the send creates a new idea. */
  showDurationChoices?: boolean;
  /** Duração escolhida para a próxima ideia (o backend aceita 5–60 s). */
  pendingDuration: number;
  onDurationChange: (seconds: number) => void;
  /** Duração detetada no rascunho (nula se override manual ou sem número). */
  detectedDuration: number | null;
  /** Proposta do /api/chat a aguardar confirmação explícita. */
  pendingChat?: {
    intent: string;
    reply: string;
    needs_confirmation: boolean;
    pending_text: string | null;
    pending_kind: "edit" | "idea" | "tools" | "transcript" | null;
    pending_tool_calls?: { tool: string; params: Record<string, unknown> }[];
    pending_estimate?: { blocks: number; audio_seconds: number; billed_seconds: number; estimated_usd: number } | null;
    pending_segment?: { start_s: number; end_s: number } | null;
    pending_idea_options?: {
      style: string;
      duration_seconds: number;
      aspect_ratio: string;
    } | null;
  } | null;
  chatBusy?: boolean;
  /** Director interview: one question + quick-reply chips (empty platform). */
  interviewCard?: {
    question: string;
    chips: { label: string; value: string }[];
  } | null;
  onInterviewChip?: (value: string) => void;
  /** Attach a video file straight from the chat (same upload path). */
  onAttachVideo?: (file: File) => void;
  /** Trecho ativo da timeline (o Director usa-o como âmbito). */
  segment?: { start_s: number; end_s: number } | null;
  onClearSegment?: () => void;
  onConfirmChat?: () => void;
  onAdjustChat?: () => void;
  onCancelChat?: () => void;
}

const DURATION_CHOICES = [15, 20, 25, 30, 60];

export function AssistantPanel({
  messages, emptyPlatform, job, resultReady, planReview, onOpenPlanReview,
  onRejectPlan, decisionBusy, liveAvailable, chatLive, working, recorded, recordingName,
  onRecordingReady, onRecordingCleared, transcribeStatus, transcribeProgress,
  transcriptionError, draft, onDraftChange, onTranscribe,
  canConfirm, confirming, onConfirmTranscript, onRetry,
  consentWaiting, onConsentContinue, confirmLabel, showDurationChoices,
  pendingDuration, onDurationChange, detectedDuration,
  pendingChat, chatBusy, onConfirmChat, onAdjustChat, onCancelChat,
  segment, onClearSegment,
  interviewCard, onInterviewChip, onAttachVideo,
}: Props) {
  const [recState, setRecState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const rafRef = useRef<number>(0);
  const listRef = useRef<HTMLDivElement>(null);
  const attachRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => () => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    cancelAnimationFrame(rafRef.current);
  }, []);

  // Keep the newest message visible.
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages.length, job?.status, job?.stage]);

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

  function discardRecording() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    setAudioUrl(null);
    setRecState("idle");
    onRecordingCleared();
  }

  const busyTranscribe = transcribeStatus === "uploading" || transcribeStatus === "transcribing";
  // Honest busy: a job only counts as working while the worker can own it
  // (processing, or queued with an instruction/render request attached).
  // A restored queued job without `ready` is idle — never claim otherwise.
  const jobWorking = Boolean(
    job && (job.status === "processing" || (job.status === "queued" && job.ready)),
  );
  const headerBusy = confirming || busyTranscribe || jobWorking || recState === "recording" || Boolean(working);
  const planSummary =
    planReview?.plan?.interpreted_intention ??
    planReview?.legacy_plan?.raw_transcript ??
    "Plano pronto para revisão.";
  const showPlanCard = Boolean(job && job.status === "awaiting_approval" && planReview);
  const showClarifyCard = Boolean(job && job.status === "awaiting_clarification" && planReview);
  const showResultCard = Boolean(job && job.status === "completed" && resultReady);
  const showFailedCard = Boolean(job && (job.status === "failed" || job.status === "unsupported") && job.error);
  const showRejectedCard = Boolean(job && job.status === "rejected");
  const showWorkingLine = Boolean(
    jobWorking && !showPlanCard && !showClarifyCard && !consentWaiting,
  );

  return (
    <section aria-label="Muse — director criativo" className="flex min-h-0 flex-1 flex-col bg-surface">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
        <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-full bg-accent">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d="M12 3v18M5 8l14 8M19 8L5 16" stroke="#14110C" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <h2 className="text-[13px] font-semibold">Muse</h2>
          <p className="truncate text-[11px] text-muted">
            {headerBusy ? "A trabalhar…" : chatLive ? "Ao vivo · Muse Spark" : "Disponível"}
          </p>
        </div>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${headerBusy ? "animate-pulse bg-accent" : "bg-muted"}`} aria-hidden />
      </div>

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3" aria-live="polite" aria-label="Conversa com o Muse">
        {messages.length === 0 && (
          <div className="flex flex-col items-center px-6 py-8 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent/15 text-accent" aria-hidden>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M12 3v18M5 8l14 8M19 8L5 16" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
              </svg>
            </span>
            <p className="mt-3 text-[14px] font-semibold">Edita a conversar</p>
            <p className="mt-1 max-w-[240px] text-[12px] leading-relaxed text-muted">
              {emptyPlatform
                ? "Descreve o vídeo que queres criar e eu trato do resto."
                : "Descreve a alteração com a tua voz ou por escrito."}
            </p>
            <p className="mt-2 font-mono text-[10px] text-muted/80">
              Nada acontece sem a tua confirmação.
            </p>
          </div>
        )}

        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[92%] rounded-lg px-4 py-2.5 text-[13px] leading-relaxed ${
                  m.role === "user"
                    ? "bg-accent/15 text-foreground"
                    : "border border-border bg-raised/50 text-foreground"
                }`}
              >
                <p className={`mb-0.5 text-[11px] ${m.role === "user" ? "text-right text-accent" : "text-muted"}`}>
                  {m.role === "user" ? "Tu" : "Muse"}
                </p>
                <p className="whitespace-pre-wrap break-words">{m.text}</p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {consentWaiting && (
          <div className="rounded-lg border border-accent/40 bg-accent/[0.07] p-3" role="status">
            <p className="text-[13px] font-semibold">Preciso da tua autorização</p>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              Para continuar, tenho de analisar as pessoas do vídeo. Nada foi enviado até agora.
            </p>
            <Button className="mt-2 w-full" onClick={onConsentContinue}>
              Continuar com a detecção
            </Button>
          </div>
        )}

        {showPlanCard && (
          <div className="rounded-lg border border-accent/40 bg-accent/[0.07] p-3" role="status">
            <p className="text-[13px] font-semibold">Plano pronto para revisão</p>
            <p className="mt-1 line-clamp-4 text-[12px] leading-relaxed text-muted">{planSummary}</p>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <Button variant="secondary" onClick={onOpenPlanReview}>
                Rever plano
              </Button>
              <Button variant="ghost" onClick={onRejectPlan} disabled={decisionBusy}>
                Rejeitar
              </Button>
            </div>
          </div>
        )}

        {showClarifyCard && (
          <div className="rounded-lg border border-accent/40 bg-accent/[0.07] p-3" role="status">
            <p className="text-[13px] font-semibold">Tenho uma pergunta</p>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              Preciso de um esclarecimento para afinar o plano.
            </p>
            <Button variant="secondary" className="mt-2 w-full" onClick={onOpenPlanReview}>
              Responder
            </Button>
          </div>
        )}

        {pendingChat?.needs_confirmation && pendingChat.pending_text && (
          <div className="rounded-lg border border-accent/40 bg-accent/[0.07] p-3" role="status">
            <p className="text-[13px] font-semibold">Posso executar?</p>
            <p className="mt-1 line-clamp-4 text-[12px] leading-relaxed text-muted">
              «{pendingChat.pending_text}» — nada foi executado ainda.
            </p>
            {pendingChat.pending_tool_calls && pendingChat.pending_tool_calls.length > 0 && (
              <ul className="mt-1.5 space-y-1">
                {pendingChat.pending_tool_calls.map((call, i) => (
                  <li key={i} className="rounded border border-border/70 bg-black/30 px-2 py-1 font-mono text-[10px] text-muted">
                    {call.tool}
                  </li>
                ))}
              </ul>
            )}
            {pendingChat.pending_estimate && (
              <p className="mt-1.5 font-mono text-[10px] text-muted">
                {pendingChat.pending_estimate.blocks} bloco(s) ·{" "}
                {pendingChat.pending_estimate.billed_seconds}s · ≈$
                {pendingChat.pending_estimate.estimated_usd.toFixed(4)} — só executo se confirmares.
              </p>
            )}
            {pendingChat.pending_idea_options && (
              <p className="mt-1.5 font-mono text-[10px] text-muted">
                {pendingChat.pending_idea_options.style} · {pendingChat.pending_idea_options.duration_seconds}s ·{" "}
                {pendingChat.pending_idea_options.aspect_ratio === "9:16" ? "vertical 9:16" : "horizontal 16:9"}
              </p>
            )}
            {pendingChat.pending_segment && pendingChat.pending_segment.end_s > pendingChat.pending_segment.start_s && (
              <p className="mt-1.5 font-mono text-[10px] text-muted">
                Trecho {pendingChat.pending_segment.start_s.toFixed(1)}s–
                {pendingChat.pending_segment.end_s.toFixed(1)}s — aplico como recorte ao executar.
              </p>
            )}
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <Button variant="secondary" onClick={onConfirmChat} disabled={chatBusy || confirming}>
                Executar
              </Button>
              <Button variant="ghost" onClick={onAdjustChat} disabled={chatBusy}>
                Ajustar
              </Button>
            </div>
            <button
              type="button"
              onClick={onCancelChat}
              disabled={chatBusy}
              className="mt-1.5 w-full text-center text-[11px] text-muted underline underline-offset-2 hover:text-danger disabled:opacity-40"
            >
              Cancelar
            </button>
          </div>
        )}

        {interviewCard && interviewCard.chips.length > 0 && (
          <div className="rounded-lg border border-border bg-raised/40 p-3" role="group" aria-label={interviewCard.question}>
            <p className="text-[12px] font-medium">{interviewCard.question}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {interviewCard.chips.map((chip) => (
                <button
                  key={chip.value}
                  type="button"
                  onClick={() => onInterviewChip?.(chip.value)}
                  disabled={chatBusy}
                  className="rounded-full border border-accent/50 px-2.5 py-1 text-[11px] text-foreground transition-colors hover:bg-accent hover:text-[#14110C] focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
                >
                  {chip.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {chatBusy && (
          <div className="flex items-center gap-2 px-1 text-[12px] text-muted" role="status">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
            O Muse está a responder…
          </div>
        )}

        {showWorkingLine && job && (
          <div className="flex items-center gap-2 px-1 text-[12px] text-muted" role="status">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
            {STAGE_LABEL[job.stage] ?? "A trabalhar…"}
          </div>
        )}

        {showResultCard && (
          <div className="rounded-lg border border-success/40 bg-success/[0.06] p-3" role="status">
            <p className="text-[13px] font-semibold text-success">Vídeo pronto e verificado</p>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              Usa Exportar no topo para descarregar.
            </p>
          </div>
        )}

        {showFailedCard && job?.error && (
          <div className="rounded-lg border border-danger/40 bg-danger/[0.06] p-3" role="alert">
            <p className="text-[13px] font-semibold text-danger">Não consegui concluir</p>
            <p className="mt-1 break-words text-[12px] leading-relaxed text-muted">{job.error.message}</p>
            <Button variant="danger" className="mt-2 w-full" onClick={onRetry}>
              Recomeçar
            </Button>
          </div>
        )}

        {showRejectedCard && (
          <div className="rounded-lg border border-border bg-raised/40 p-3" role="status">
            <p className="text-[13px] font-semibold">Plano rejeitado</p>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              O teu vídeo original ficou intacto.
            </p>
            <Button variant="secondary" className="mt-2 w-full" onClick={onRetry}>
              Recomeçar
            </Button>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface p-4">
        {recState === "recorded" && (
          <div className="mb-2">
            {audioUrl && (
              <audio controls src={audioUrl} className="w-full rounded-md border border-border bg-raised" style={{ colorScheme: "dark" }} aria-label="A tua gravação" />
            )}
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[11px] text-muted">
                {liveAvailable
                  ? transcribeStatus === "done"
                    ? chatBusy
                      ? "Transcrição pronta — o Muse está a responder…"
                      : "Transcrição pronta — enviada ao Muse."
                    : "A enviar a gravação para transcrição…"
                  : "Gravação guardada. Neste servidor a voz está em simulação."}
              </span>
              <button
                type="button"
                onClick={discardRecording}
                disabled={busyTranscribe}
                className="text-[12px] text-muted underline underline-offset-2 hover:text-danger disabled:opacity-40"
              >
                Descartar
              </button>
            </div>
            {!liveAvailable && (
              <p className="mt-1 text-[11px] leading-relaxed text-muted">
                Escreve o pedido abaixo — em simulação o áudio não é transcrito.
              </p>
            )}
          </div>
        )}

        {busyTranscribe && (
          <div className="mb-2" role="status">
            <div className="h-1 overflow-hidden rounded bg-border">
              <div className="h-full bg-accent transition-[width]" style={{ width: `${transcribeProgress ?? 0}%` }} />
            </div>
            <p className="mt-1 text-[11px] text-muted">A transcrever… {transcribeProgress ?? 0}%</p>
          </div>
        )}

        {transcriptionError && (
          <div className="mb-2 rounded-md border border-danger/40 bg-danger/10 p-2.5" role="alert">
            <p className="text-[12px] font-medium text-danger">A transcrição falhou</p>
            <p className="mt-0.5 text-[12px] text-muted">{transcriptionError}</p>
            {recorded && (
              <Button variant="danger" className="mt-2" onClick={onTranscribe} disabled={busyTranscribe}>
                Tentar de novo
              </Button>
            )}
          </div>
        )}

        {confirmLabel && showDurationChoices && (
          <div className="mb-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Escolher a duração do vídeo">
            <span className="text-[11px] text-muted">Duração:</span>
            {DURATION_CHOICES.map((seconds) => {
              const active = pendingDuration === seconds;
              return (
                <button
                  key={seconds}
                  type="button"
                  onClick={() => onDurationChange(seconds)}
                  aria-pressed={active}
                  className={`rounded-full px-2.5 py-0.5 font-mono text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                    active
                      ? "bg-accent font-semibold text-[#14110C]"
                      : "border border-border text-muted hover:text-foreground"
                  }`}
                >
                  {seconds}s
                </button>
              );
            })}
          </div>
        )}
        {confirmLabel && showDurationChoices && detectedDuration != null && detectedDuration !== pendingDuration && (
          <p className="mb-2 font-mono text-[10px] text-muted">
            Detetei {detectedDuration}s no teu texto — é essa a duração usada. Toca numa pill para mudar.
          </p>
        )}

        <div className="flex items-end gap-2">
          {onAttachVideo && (
            <>
              <input
                ref={attachRef}
                type="file"
                accept="video/*"
                className="hidden"
                aria-label="Anexar vídeo ao chat"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) onAttachVideo(f);
                }}
              />
              <button
                type="button"
                onClick={() => attachRef.current?.click()}
                disabled={chatBusy}
                aria-label="Anexar vídeo"
                title="Anexar vídeo (começar a trabalhar nele)"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-raised hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="m21 12-8.5 8.5a5.5 5.5 0 0 1-7.8-7.8L12 5.5a3.7 3.7 0 0 1 5.2 5.2l-7.1 7.1a1.85 1.85 0 0 1-2.6-2.6L14 8.7" />
                </svg>
              </button>
            </>
          )}
          <button
            type="button"
            onClick={recState === "recording" ? stopRecording : startRecording}
            disabled={busyTranscribe || chatBusy}
            aria-label={recState === "recording" ? "Parar gravação" : "Gravar mensagem de voz"}
            title={recState === "recording" ? "Parar (a transcrever e enviar ao Muse ao parar)" : "Gravar voz"}
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40 ${
              recState === "recording" ? "bg-danger" : "bg-accent hover:bg-[#ff8a70]"
            }`}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
              <rect x="9" y="3" width="6" height="11" rx="3" fill="#14110C" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="#14110C" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <div className="min-w-0 flex-1 rounded-xl border border-border bg-raised px-2.5 pb-1.5 pt-2 focus-within:border-accent">
            {segment && segment.end_s > segment.start_s && (
              <span className="mb-1.5 inline-flex items-center gap-1.5 rounded-[6px] border border-accent/50 bg-accent/10 px-2 py-0.5 font-mono text-[10px] tabular-nums text-foreground">
                Trecho {segment.start_s.toFixed(1)}s–{segment.end_s.toFixed(1)}s · o Director usa esta janela
                <button
                  type="button"
                  onClick={() => onClearSegment?.()}
                  aria-label="Limpar trecho selecionado"
                  title="Limpar trecho"
                  className="flex h-4 w-4 items-center justify-center rounded text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
                </button>
              </span>
            )}
            <textarea
              value={draft}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
                e.preventDefault();
                if (!canConfirm || confirming || !draft.trim()) return;
                onConfirmTranscript();
              }}
              rows={2}
              maxLength={1000}
              aria-label="Mensagem para o Muse"
              placeholder={emptyPlatform ? "Descreve o vídeo que queres criar…" : "Descreve a alteração…"}
              className="w-full resize-none bg-transparent text-[13px] leading-relaxed outline-none placeholder:text-muted/60 disabled:opacity-70"
            />
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="truncate text-[10px] text-muted/70">
                Enter para enviar · Shift+Enter nova linha
              </span>
              <button
                type="button"
                onClick={onConfirmTranscript}
                disabled={!canConfirm || confirming || !draft.trim()}
                aria-label="Enviar para o Muse"
                title="Enviar (Enter)"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-[#14110C] transition-colors hover:bg-[#ff8a70] focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
              >
                {confirming ? (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#14110C]/40 border-t-[#14110C]" aria-hidden />
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path d="M12 19V5m0 0-6 6m6-6 6 6" stroke="#14110C" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className="text-[11px] text-muted" aria-live="polite">
            {recState === "recording" && `A gravar… 00:${String(seconds).padStart(2, "0")} — prime para parar`}
            {recState === "recorded" && !liveAvailable && "Revê o texto e envia."}
            {recState === "recorded" && liveAvailable && transcribeStatus !== "done" && "A transcrever…"}
            {recState === "recorded" && liveAvailable && transcribeStatus === "done" && "Enviado ao Muse."}
            {recState === "unsupported" && "Gravação indisponível neste navegador."}
            {recState === "denied" && "Microfone bloqueado pelo navegador."}
            {recState === "idle" && (liveAvailable ? "Voz transcrita e enviada ao Muse." : "Voz em simulação — sem custo.")}
          </span>
          {draft.trim() && (
            <span className="shrink-0 font-mono text-[10px] text-muted">{draft.trim().length}/1000</span>
          )}
        </div>
      </div>
    </section>
  );
}
