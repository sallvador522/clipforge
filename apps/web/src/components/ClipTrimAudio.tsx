"use client";

import { useEffect, useState } from "react";
import { friendlyApiError } from "@/lib/api";
import { Button } from "./ui/button";

/**
 * ADR-041 corte + áudio do clipe (só antes da voz). Valores absolutos no
 * original; o worker materializa a cópia e re-probeia. Sem custo, sem drag:
 * numérico e explícito; a timeline sombrea o intervalo escolhido.
 */
export interface ClipTrim {
  start: number | null;
  end: number | null;
  originalDuration: number;
}

export interface ClipAudio {
  gainDb: number;
  fadeIn: number;
  fadeOut: number;
}

export function ClipTrimAudio({
  duration,
  trim,
  audio,
  hasAudio,
  busy,
  onSaveTrim,
  onClearTrim,
  onSaveAudio,
}: {
  duration: number;
  trim: ClipTrim | null;
  audio: ClipAudio | null;
  hasAudio: boolean | null;
  busy: boolean;
  onSaveTrim: (start: number, end: number) => Promise<unknown>;
  onClearTrim: () => Promise<unknown>;
  onSaveAudio: (gain: number, fadeIn: number, fadeOut: number) => Promise<unknown>;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [gain, setGain] = useState("0");
  const [fadeIn, setFadeIn] = useState("0");
  const [fadeOut, setFadeOut] = useState("0");
  const [localBusy, setLocalBusy] = useState<"trim" | "audio" | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setStart(trim?.start != null ? String(trim.start) : "");
    setEnd(trim?.end != null ? String(trim.end) : "");
  }, [trim?.start, trim?.end]);
  useEffect(() => {
    setGain(String(audio?.gainDb ?? 0));
    setFadeIn(String(audio?.fadeIn ?? 0));
    setFadeOut(String(audio?.fadeOut ?? 0));
  }, [audio?.gainDb, audio?.fadeIn, audio?.fadeOut]);

  async function run(kind: "trim" | "audio", action: () => Promise<unknown>) {
    setLocalError(null);
    setLocalBusy(kind);
    try {
      await action();
    } catch (e) {
      setLocalError(friendlyApiError(e, "Falhou. Tenta de novo."));
    } finally {
      setLocalBusy(null);
    }
  }

  const startN = Number.parseFloat(start);
  const endN = end.trim() === "" ? duration : Number.parseFloat(end);
  const trimValid =
    Number.isFinite(startN) && Number.isFinite(endN) &&
    startN >= 0 && endN > startN && endN <= duration + 1e-6 && endN - startN >= 0.5;
  const gainN = Number.parseFloat(gain);
  const fadeInN = Number.parseFloat(fadeIn || "0");
  const fadeOutN = Number.parseFloat(fadeOut || "0");
  const audioValid =
    Number.isFinite(gainN) && gainN >= -20 && gainN <= 12 &&
    Number.isFinite(fadeInN) && fadeInN >= 0 &&
    Number.isFinite(fadeOutN) && fadeOutN >= 0 &&
    fadeInN + fadeOutN <= duration;
  const disabled = busy || localBusy !== null;

  return (
    <div className="mt-2 rounded-[6px] border border-border/60 bg-raised/30 p-2">
      <p className="text-[11px] font-medium text-muted">Corte e áudio</p>
      <div className="mt-1.5 flex items-center gap-1.5">
        <label className="flex min-w-0 flex-1 items-center gap-1 text-[11px] text-muted">
          Início
          <input
            value={start}
            disabled={disabled}
            onChange={(e) => setStart(e.target.value)}
            inputMode="decimal"
            placeholder="0.0"
            aria-label="Início do corte em segundos"
            className="w-full rounded border border-border bg-raised px-1 py-0.5 font-mono text-[11px] tabular-nums"
          />
        </label>
        <label className="flex min-w-0 flex-1 items-center gap-1 text-[11px] text-muted">
          Fim
          <input
            value={end}
            disabled={disabled}
            onChange={(e) => setEnd(e.target.value)}
            inputMode="decimal"
            placeholder={duration ? duration.toFixed(1) : undefined}
            aria-label="Fim do corte em segundos (vazio = fim)"
            className="w-full rounded border border-border bg-raised px-1 py-0.5 font-mono text-[11px] tabular-nums"
          />
        </label>
        <Button
          variant="secondary"
          className="px-2 py-0.5 text-[11px]"
          disabled={disabled || !trimValid}
          onClick={() => void run("trim", () => onSaveTrim(Math.max(0, startN), Math.min(duration, endN)))}
        >
          {localBusy === "trim" ? "…" : "Cortar"}
        </Button>
        {trim?.start != null && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => void run("trim", onClearTrim)}
            aria-label="Limpar corte"
            title="Repõe o clipe completo"
            className="shrink-0 text-[12px] text-muted underline underline-offset-2 hover:text-danger disabled:opacity-40"
          >
            limpar
          </button>
        )}
      </div>
      {hasAudio !== false && (
        <div className="mt-1.5 space-y-1.5 border-t border-border/60 pt-1.5">
          <div className="flex items-center gap-2">
            <label htmlFor="clip-gain" className="shrink-0 text-[11px] text-muted">Volume</label>
            <input
              id="clip-gain"
              type="range"
              min={-20}
              max={12}
              step={0.5}
              value={Number.isFinite(gainN) ? gainN : 0}
              disabled={disabled}
              onChange={(e) => setGain(e.target.value)}
              className="min-w-0 flex-1"
              aria-label="Ganho de áudio em decibéis"
            />
            <span className="w-14 shrink-0 text-right font-mono text-[11px] tabular-nums">
              {Number.isFinite(gainN) ? `${gainN.toFixed(1)} dB` : "—"}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <label className="flex min-w-0 flex-1 items-center gap-1 text-[11px] text-muted">
              Fade in
              <input
                value={fadeIn}
                disabled={disabled}
                onChange={(e) => setFadeIn(e.target.value)}
                inputMode="decimal"
                aria-label="Fade de entrada em segundos"
                className="w-full rounded border border-border bg-raised px-1 py-0.5 font-mono text-[11px] tabular-nums"
              />
            </label>
            <label className="flex min-w-0 flex-1 items-center gap-1 text-[11px] text-muted">
              Fade out
              <input
                value={fadeOut}
                disabled={disabled}
                onChange={(e) => setFadeOut(e.target.value)}
                inputMode="decimal"
                aria-label="Fade de saída em segundos"
                className="w-full rounded border border-border bg-raised px-1 py-0.5 font-mono text-[11px] tabular-nums"
              />
            </label>
            <Button
              variant="secondary"
              className="px-2 py-0.5 text-[11px]"
              disabled={disabled || !audioValid}
              onClick={() => void run("audio", () => onSaveAudio(gainN, Math.max(0, fadeInN), Math.max(0, fadeOutN)))}
            >
              {localBusy === "audio" ? "…" : "Aplicar"}
            </Button>
          </div>
        </div>
      )}
      {trim?.start != null && trim?.end != null && (
        <p className="mt-1 font-mono text-[10px] text-accent">
          corte {trim.start.toFixed(1)}s → {trim.end.toFixed(1)}s · aplica-se ao render
        </p>
      )}
      {localError && (
        <p className="mt-1 text-[11px] text-danger" role="alert">{localError}</p>
      )}
    </div>
  );
}
