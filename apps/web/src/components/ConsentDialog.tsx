"use client";

import { useEffect, useState } from "react";
import { Button } from "./ui/button";

interface Props {
  submitting: boolean;
  error: string | null;
  reason: string | null;
  onAuthorize: () => void;
  onDecline: () => void;
}

export function ConsentDialog({ submitting, error, reason, onAuthorize, onDecline }: Props) {
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onDecline();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onDecline]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/75 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sam-consent-title"
      aria-describedby="sam-consent-copy"
    >
      <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-xl border border-border bg-surface shadow-2xl sm:rounded-lg">
        <header className="border-b border-border px-4 py-3">
          <p className="text-[11px] tracking-wide text-accent">
            Análise externa de vídeo
          </p>
          <h2 id="sam-consent-title" className="mt-1 text-lg font-semibold">
            Autorização para identificar pessoas
          </h2>
        </header>

        <div id="sam-consent-copy" className="space-y-4 px-4 py-4">
          {reason && (
            <p className="rounded-md border border-accent/40 bg-accent/10 p-3 text-[14px] leading-relaxed">
              {reason} Para isso, o ClipForge precisa de identificar as pessoas no teu vídeo.
            </p>
          )}
          <p className="text-[14px] leading-relaxed">
            Para identificar as pessoas no teu vídeo, o ClipForge precisa de enviar uma
            cópia temporária, sem áudio, para a Meta através do SAM 3.1.
          </p>
          <p className="text-[14px] leading-relaxed">
            O vídeo original não será modificado. Solicitamos que a cópia enviada expire
            automaticamente após uma hora e tentamos eliminá-la assim que o processamento
            terminar.
          </p>
          <p className="text-[14px] leading-relaxed">
            Esta análise acontece antes de apresentarmos o teu plano de edição. Ao
            continuar, autorizas este processamento externo do vídeo.
          </p>

          <label
            htmlFor="sam-consent-checkbox"
            className="flex cursor-pointer items-start gap-3 rounded-md border border-border bg-raised p-3"
          >
            <input
              id="sam-consent-checkbox"
              type="checkbox"
              checked={authorized}
              onChange={(event) => setAuthorized(event.target.checked)}
              disabled={submitting}
              className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
            />
            <span className="text-[13px] leading-relaxed">
              Li a informação acima e autorizo o envio da cópia sem áudio para a Meta
              através do SAM 3.1.
              <span className="mt-1 block font-mono text-[10px] text-muted">
                Se recusares, nenhum vídeo é enviado e a edição não começa.
              </span>
            </span>
          </label>

          {error && (
            <div
              className="rounded-md border border-danger/40 bg-danger/10 p-3 text-[13px] text-danger"
              role="alert"
            >
              {error}
            </div>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" onClick={onDecline} disabled={submitting}>
            Not now
          </Button>
          <Button onClick={onAuthorize} disabled={!authorized || submitting}>
            {submitting ? "A autorizar…" : "Autorizar e continuar"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
