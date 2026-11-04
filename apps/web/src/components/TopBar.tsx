"use client";

import { useState } from "react";
import { Button } from "./ui/button";

interface Props {
  projectName: string;
  apiError: string | null;
  statusText: string | null;
  statusTone: "idle" | "working" | "attention" | "done";
  canExport: boolean;
  exporting: boolean;
  onExport: () => void;
  exportError: string | null;
  onRenameProject: (title: string) => void;
  canRename: boolean;
}

const TONE_DOT: Record<Props["statusTone"], string> = {
  idle: "bg-muted",
  working: "bg-accent",
  attention: "bg-danger",
  done: "bg-success",
};

export function TopBar({
  projectName, apiError, statusText, statusTone,
  canExport, exporting, onExport, exportError, onRenameProject, canRename,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  function commit() {
    if (draft.trim()) onRenameProject(draft.trim());
    setEditing(false);
  }

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 bg-transparent px-4">
      <div className="flex shrink-0 items-center gap-2">
        <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-[6px] bg-accent">
          <svg width="10" height="12" viewBox="0 0 10 12" fill="none" aria-hidden>
            <path d="M1 1.5v9l8-4.5-8-4.5Z" fill="#14110C" />
          </svg>
        </span>
        <span className="text-[13px] font-extrabold tracking-wide">CLIPFORGE</span>
      </div>

      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        {editing ? (
          <input
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
            onBlur={commit}
            maxLength={80}
            aria-label="Nome do projecto"
            className="w-40 rounded-[6px] border border-border bg-raised px-1.5 py-0.5 text-[13px] outline-none focus:border-accent md:w-48"
          />
        ) : (
          <button
            type="button"
            onClick={() => { setDraft(projectName); setEditing(true); }}
            disabled={!canRename}
            title={canRename ? "Mudar o nome do projecto" : "Importa um clipe para dar nome ao projecto"}
            aria-label={canRename ? `Mudar o nome do projecto (actual: ${projectName})` : "Nome do projecto (disponível após importar um clipe)"}
            className="max-w-40 truncate text-left text-[13px] font-medium hover:text-accent focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-default disabled:opacity-70 disabled:hover:text-foreground md:max-w-48"
          >
            {projectName}
          </button>
        )}
        <span className="hidden items-center gap-1.5 whitespace-nowrap text-[11px] text-muted md:flex">
          <span className={`h-1.5 w-1.5 rounded-full ${apiError ? "bg-danger" : TONE_DOT[statusTone]}`} />
          {apiError ? "Sem ligação à API" : (statusText ?? "Pronto")}
        </span>
      </div>

      <div className="relative shrink-0">
        <Button onClick={onExport} disabled={!canExport || exporting} className="h-8 shrink-0 whitespace-nowrap rounded-[6px] px-3.5 text-[12px]">
          {exporting ? "A exportar…" : "Exportar"}
        </Button>
        {exportError && (
          <p className="absolute right-0 top-full z-10 mt-1 w-64 rounded-md border border-danger/40 bg-surface p-2 text-xs text-danger" role="alert">
            {exportError}
          </p>
        )}
      </div>
    </header>
  );
}
