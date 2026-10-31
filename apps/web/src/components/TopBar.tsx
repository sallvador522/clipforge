"use client";

import { Button } from "./ui/button";

interface Props {
  projectName: string;
  aiMode: string | null;
  liveTranscription: boolean;
  apiError: string | null;
  resolution: string | null;
  durationLabel: string | null;
  jobStatus: string | null;
  canExport: boolean;
  exporting: boolean;
  onExport: () => void;
  exportError: string | null;
}

export function TopBar({
  projectName, aiMode, liveTranscription, apiError, resolution, durationLabel, jobStatus, canExport, exporting, onExport, exportError,
}: Props) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-surface px-4">
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-[6px] bg-accent">
          <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden>
            <path d="M1 1.5v9l8-4.5-8-4.5Z" fill="#14110C" />
          </svg>
        </span>
        <span className="text-sm font-extrabold tracking-wide">CLIPFORGE</span>
        <span className="hidden font-mono text-[11px] text-muted sm:inline">CINEMATIC AI EDITING STUDIO</span>
      </div>

      <div className="mx-auto flex min-w-0 items-center gap-3">
        <span className="max-w-40 truncate text-sm font-medium sm:max-w-56" title={projectName}>{projectName}</span>
        <span className="hidden items-center gap-1.5 whitespace-nowrap font-mono text-[11px] text-muted lg:flex">
          <span className={`h-1.5 w-1.5 rounded-full ${jobStatus === "failed" ? "bg-danger" : jobStatus === "completed" ? "bg-success" : jobStatus ? "bg-accent" : "bg-muted"}`} />
          {apiError ? "API offline" : jobStatus ? `Job ${jobStatus}` : "Local project — not saved to cloud"}
        </span>
      </div>

      <div className="flex items-center gap-4">
        <span className="hidden font-mono text-[11px] text-muted lg:inline">
          {resolution ?? "—"} {durationLabel ? `· ${durationLabel}` : ""} · AI {aiMode ?? "…"}
          {liveTranscription ? " · ASR live" : " · ASR mock"}
        </span>
        <div className="relative">
          <Button onClick={onExport} disabled={!canExport || exporting} className="h-8 shrink-0 whitespace-nowrap px-3.5 text-[13px]">
            {exporting ? "Exporting…" : "Export MP4"}
          </Button>
          {exportError && (
            <p className="absolute right-0 top-full z-10 mt-1 w-64 rounded-md border border-danger/40 bg-surface p-2 text-xs text-danger" role="alert">
              {exportError}
            </p>
          )}
        </div>
      </div>
    </header>
  );
}
