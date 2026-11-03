"use client";

import { Button } from "./ui/button";
import type { ExportFormat } from "@/lib/api";

type SocialFormat = Exclude<ExportFormat, "original">;

interface Props {
  projectName: string;
  apiError: string | null;
  jobStatus: string | null;
  selectedFormat: SocialFormat;
  onSelectFormat: (format: SocialFormat) => void;
  canExport: boolean;
  exporting: boolean;
  onExport: () => void;
  exportError: string | null;
}

const FORMATS: { format: SocialFormat; label: string }[] = [
  { format: "youtube", label: "YouTube 16:9" },
  { format: "reels", label: "Reels 9:16" },
];

export function TopBar({
  projectName, apiError, jobStatus, selectedFormat, onSelectFormat,
  canExport, exporting, onExport, exportError,
}: Props) {
  return (
    <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface px-4 py-1">
      <div className="flex shrink-0 items-center gap-2.5">
        <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-[6px] bg-accent">
          <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden>
            <path d="M1 1.5v9l8-4.5-8-4.5Z" fill="#14110C" />
          </svg>
        </span>
        <span className="text-sm font-extrabold tracking-wide">CLIPFORGE</span>
        <span className="hidden font-mono text-[11px] text-muted xl:inline">CINEMATIC AI EDITING STUDIO</span>
      </div>

      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="max-w-32 truncate text-sm font-medium md:max-w-40" title={projectName}>{projectName}</span>
        <span className="hidden items-center gap-1.5 whitespace-nowrap font-mono text-[11px] text-muted lg:flex">
          <span className={`h-1.5 w-1.5 rounded-full ${jobStatus === "failed" ? "bg-danger" : jobStatus === "completed" ? "bg-success" : jobStatus ? "bg-accent" : "bg-muted"}`} />
          {apiError ? "API offline" : jobStatus ? `Job ${jobStatus}` : "Local project — not saved to cloud"}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <div role="radiogroup" aria-label="Formato de exportação" className="flex items-center gap-1 rounded-full border border-border bg-raised p-1">
          {FORMATS.map((opt) => {
            const active = selectedFormat === opt.format;
            return (
              <button
                key={opt.format}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => onSelectFormat(opt.format)}
                className={`whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                  active ? "bg-accent text-[#14110C]" : "text-muted hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
        <div className="relative">
          <Button onClick={onExport} disabled={!canExport || exporting} className="h-8 shrink-0 whitespace-nowrap px-3.5 text-[13px]">
            {exporting ? "Exportando…" : selectedFormat === "reels" ? "Baixar Reels" : "Baixar YouTube"}
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
