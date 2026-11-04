"use client";

import { useEffect, useRef, useState } from "react";
import { assetFileUrl, TIMELINE_ASSET_MIME } from "@/lib/api";
import type { AssetData, ProjectData } from "@/lib/types";

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00.0";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}

/** Compact badge like professional editors: 0:06 */
export function formatBadge(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds - m * 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export interface SourceMeta {
  width: number;
  height: number;
  duration: number;
  hasAudio: boolean | null;
}

interface Props {
  file: File | null;
  originalUrl: string | null;
  localMeta: SourceMeta | null;
  jobMeta: { width: number; height: number; duration_seconds: number; has_audio: boolean; frame_count: number; fps: number } | null;
  uploading: boolean;
  uploadProgress: number | null;
  onFile: (file: File) => void;
  onReplace: () => void;
  // P0 project workspace
  project: ProjectData | null;
  assets: AssetData[];
  assetsLoading: boolean;
  assetsError: string | null;
  assetUploading: string | null;
  assetProgress: number | null;
  onImportFiles: (files: File[]) => void;
  onDeleteAsset: (assetId: string) => void;
  // ADR-044: library selection drives the right-hand Properties tab.
  onSelectAsset: (assetId: string | null) => void;
  selectedAssetId: string | null;
}

function AssetThumb({ asset, projectId }: { asset: AssetData; projectId: string }) {
  const url = assetFileUrl(projectId, asset.asset_id);
  if (asset.kind === "video") {
    return (
      <video src={url} muted playsInline preload="metadata" className="h-10 w-16 shrink-0 rounded-md bg-black object-cover" aria-hidden />
    );
  }
  if (asset.kind === "image" || asset.kind === "graphics") {
    // Sanitized server-side; served as an image, never inline HTML.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="" aria-hidden className="h-10 w-16 shrink-0 rounded-md bg-black object-cover" loading="lazy" />;
  }
  return (
    <span className="flex h-9 w-14 shrink-0 items-center justify-center rounded-[4px] bg-black text-muted" aria-hidden>
      {asset.kind === "audio" ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M11 5 6 9H3v6h3l5 4V5ZM15 9a4 4 0 0 1 0 6" /></svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5h14M5 10h14M5 15h9M5 20h6" /></svg>
      )}
    </span>
  );
}

export function MediaPanel({
  file, originalUrl, localMeta, jobMeta,
  uploading, uploadProgress, onFile, onReplace,
  project, assets, assetsLoading, assetsError, assetUploading, assetProgress,
  onImportFiles, onDeleteAsset, onSelectAsset, selectedAssetId,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const libInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [libDragging, setLibDragging] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [textPreview, setTextPreview] = useState<string | null>(null);
  const [textPreviewError, setTextPreviewError] = useState<string | null>(null);

  const duration = jobMeta?.duration_seconds ?? localMeta?.duration;

  const preview = previewId ? assets.find((a) => a.asset_id === previewId) ?? null : null;

  useEffect(() => {
    setTextPreview(null);
    setTextPreviewError(null);
    if (!preview || !project || preview.kind !== "text") return;
    let cancelled = false;
    fetch(assetFileUrl(project.project_id, preview.asset_id))
      .then(async (r) => {
        if (!r.ok) throw new Error(`Preview failed (${r.status}).`);
        const text = await r.text();
        if (!cancelled) setTextPreview(text.slice(0, 4000));
      })
      .catch((e) => {
        if (!cancelled) setTextPreviewError(e instanceof Error ? e.message : "Preview failed.");
      });
    return () => { cancelled = true; };
  }, [preview, project]);

  function dropFiles(files: File[]) {
    if (files.length === 0) return;
    if (!file) {
      const f = files[0];
      if (f) onFile(f);
    } else {
      onImportFiles(files);
    }
  }

  const empty = !file && assets.length === 0;
  // ADR-044: the session card is draggable once the server has registered it
  // as an asset (same filename match used to dedupe the rows below).
  const sessionAssetId = file ? assets.find((a) => a.original_filename === file.name)?.asset_id ?? null : null;
  const sessionAssetDuration = sessionAssetId
    ? assets.find((a) => a.asset_id === sessionAssetId)?.duration_seconds ?? localMeta?.duration ?? null
    : null;
  // The session clip already has its own card above; the matching library
  // row (same filename, registered server-side on upload) would duplicate
  // it, so it stays hidden while the session file is present.
  const sessionName = file?.name ?? null;
  const rows = sessionName ? assets.filter((a) => a.original_filename !== sessionName) : assets;

  return (
    <section aria-label="Recursos" className="flex min-h-0 min-w-0 flex-1 flex-col bg-surface lg:h-full">
      <header className="flex h-11 shrink-0 items-center gap-1.5 border-b border-border px-2.5">
        <h2 className="text-[13px] font-semibold">Recursos</h2>
        {rows.length > 0 && <span className="rounded-full border border-border px-1.5 font-mono text-[9px] text-muted">{rows.length}</span>}
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => (file ? libInputRef.current?.click() : inputRef.current?.click())}
          className="flex h-7 items-center gap-1.5 rounded-[6px] border border-border bg-raised px-2.5 text-[12px] font-medium hover:border-muted focus-visible:outline-2 focus-visible:outline-accent"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 16V5m0 0 4 4m-4-4L8 9" /><path d="M4 19h16" /></svg>
          Importar
        </button>
      </header>

      <input
        ref={inputRef}
        type="file"
        aria-label="Escolher ficheiro de vídeo"
        accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      <input
        ref={libInputRef}
        type="file"
        multiple
        aria-label="Importar recursos do projecto"
        accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv,audio/wav,audio/mpeg,audio/mp4,audio/ogg,audio/webm,.wav,.mp3,.m4a,.ogg,.oga,.webm,.png,.jpg,.jpeg,.webp,.txt,.md,.srt,.vtt,.svg"
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onImportFiles(files);
          e.target.value = "";
        }}
      />

      <div
        className="min-h-0 flex-1 overflow-y-auto"
        onDragOver={(e) => { e.preventDefault(); setLibDragging(true); }}
        onDragLeave={() => setLibDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setLibDragging(false);
          dropFiles(Array.from(e.dataTransfer.files ?? []));
        }}
      >
        {empty ? (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            className={`mx-3 mt-2.5 flex w-[calc(100%-24px)] flex-col items-center justify-center rounded-md px-4 py-9 text-center transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
              dragging || libDragging ? "bg-accent/10 text-foreground" : "bg-raised/60 text-muted hover:bg-raised"
            }`}
          >
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="text-foreground/80"><path d="M12 15V4m0 0 4 4m-4-4L8 8" /><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" /></svg>
            <span className="mt-3 max-w-[210px] text-[12px] leading-relaxed">
              Arrasta vídeos, fotos e ficheiros áudio para aqui
            </span>
            <span className="mt-1.5 text-[10px] text-muted/80">ou clica · MP4 / MOV / WebM · máx 15 min · 720p</span>
          </button>
        ) : (
          <ul className="space-y-2 px-3 py-2.5">
            {file && (
              <li
                className={`overflow-hidden rounded-[6px] border bg-raised/50 transition-colors ${
                  sessionAssetId && sessionAssetDuration ? "cursor-grab border-accent/50 active:cursor-grabbing" : "border-border"
                }${selectedAssetId === sessionAssetId && sessionAssetId ? " outline-2 outline-accent" : ""}`}
                draggable={Boolean(sessionAssetId && sessionAssetDuration)}
                onClick={() => {
                  if (sessionAssetId) onSelectAsset(selectedAssetId === sessionAssetId ? null : sessionAssetId);
                }}
                role="button"
                tabIndex={0}
                aria-label={`Selecionar clipe da sessão ${file.name}`}
                onKeyDown={(e) => {
                  if ((e.key === "Enter" || e.key === " ") && sessionAssetId) {
                    e.preventDefault();
                    onSelectAsset(selectedAssetId === sessionAssetId ? null : sessionAssetId);
                  }
                }}
                onDragStart={(e) => {
                  if (!sessionAssetId || !sessionAssetDuration || !file) return;
                  e.dataTransfer.setData(
                    TIMELINE_ASSET_MIME,
                    JSON.stringify({ asset_id: sessionAssetId, kind: "video", duration: sessionAssetDuration, name: file.name }),
                  );
                  e.dataTransfer.effectAllowed = "copy";
                }}
                title={sessionAssetId ? "Arrasta para a timeline" : "A registar o clipe…"}
              >
                <div className="relative">
                  {originalUrl ? (
                    <video src={originalUrl} muted playsInline preload="metadata" className="aspect-video w-full bg-black" aria-label="Miniatura do clipe da sessão" />
                  ) : (
                    <div className="aspect-video w-full bg-black" />
                  )}
                  <span className="absolute bottom-1.5 right-1.5 rounded bg-black/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-foreground">
                    {duration !== undefined ? formatBadge(duration) : "…"}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 px-2.5 py-2">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
                  <p className="min-w-0 flex-1 truncate text-[12px] font-medium" title={file.name}>{file.name}</p>
                  {project && sessionAssetId && (
                    <a
                      href={assetFileUrl(project.project_id, sessionAssetId)}
                      download={file.name}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Descarregar ${file.name}`}
                      title="Descarregar ficheiro original"
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-border/60 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 4v11m0 0 4-4m-4 4-4-4" /><path d="M4 19h16" /></svg>
                    </a>
                  )}
                  <button
                    type="button"
                    onClick={onReplace}
                    disabled={uploading}
                    aria-label="Substituir clipe (nova sessão)"
                    title="Substituir (nova sessão)"
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-border/60 hover:text-foreground disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 4v6h6M20 20v-6h-6" /><path d="M20 9A8 8 0 0 0 5.6 5.6L4 7m0 8a8 8 0 0 0 14.4 3.4L20 17" /></svg>
                  </button>
                </div>
                {uploading && (
                  <div className="px-2 pb-2" role="status">
                    <div className="h-1 overflow-hidden rounded bg-border">
                      <div className="h-full bg-accent transition-[width]" style={{ width: `${uploadProgress ?? 0}%` }} />
                    </div>
                    <p className="mt-1 text-[11px] text-muted">A preparar o teu vídeo… {uploadProgress ?? 0}%</p>
                  </div>
                )}
              </li>
            )}
            {assetsLoading && (
              <li className="px-1 py-2 text-[12px] text-muted" role="status">A carregar recursos…</li>
            )}
            {assetsError && (
              <li className="px-1 py-2 text-[12px] text-danger" role="alert">{assetsError}</li>
            )}
            {assetUploading && (
              <li className="px-1" role="status">
                <div className="h-1 overflow-hidden rounded bg-border">
                  <div className="h-full bg-accent transition-[width]" style={{ width: `${assetProgress ?? 0}%` }} />
                </div>
                <p className="mt-1 truncate text-[11px] text-muted">A enviar {assetUploading}… {assetProgress ?? 0}%</p>
              </li>
            )}
            {project && rows.map((a) => {
              const expanded = previewId === a.asset_id;
              const arming = confirmDeleteId === a.asset_id;
              const selected = selectedAssetId === a.asset_id;
              const placeable =
                ((a.kind === "video" || a.kind === "audio") && (a.duration_seconds ?? 0) > 0) ||
                a.kind === "text";
              return (
                <li
                  key={a.asset_id}
                  aria-current={selected || undefined}
                  className={`group overflow-hidden rounded-[6px] border bg-raised/50 transition-colors ${expanded || selected ? "border-accent/50" : "border-border hover:border-muted"}${placeable ? " cursor-grab active:cursor-grabbing" : ""}${selected ? " outline-2 outline-accent" : ""}`}
                  draggable={placeable}
                  onDragStart={(e) => {
                    if (!placeable) return;
                    e.dataTransfer.setData(
                      TIMELINE_ASSET_MIME,
                      JSON.stringify({ asset_id: a.asset_id, kind: a.kind, duration: a.duration_seconds, name: a.original_filename }),
                    );
                    e.dataTransfer.effectAllowed = "copy";
                  }}
                  title={placeable ? "Arrasta para a timeline" : a.original_filename}
                >
                  <div className="flex h-12 items-center gap-2 px-2">
                    <AssetThumb asset={a} projectId={project.project_id} />
                    <button
                      type="button"
                      onClick={() => {
                        const isSelected = selectedAssetId === a.asset_id;
                        if (isSelected && expanded) {
                          onSelectAsset(null);
                          setPreviewId(null);
                        } else {
                          onSelectAsset(a.asset_id);
                          setPreviewId(a.asset_id);
                        }
                        setConfirmDeleteId(null);
                      }}
                      aria-expanded={expanded}
                      aria-label={`Selecionar ${a.original_filename} (mostra propriedades e pré-visualização)`}
                      title={a.original_filename}
                      className="min-w-0 flex-1 truncate text-left text-[12px] font-medium focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      {a.original_filename}
                    </button>
                    {a.duration_seconds ? (
                      <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted">{formatBadge(a.duration_seconds)}</span>
                    ) : null}
                    {a.provenance === "generated" && (
                      <span className="shrink-0 rounded border border-accent/40 px-1 py-px text-[9px] font-medium text-accent" title="Criado pelo Muse neste projecto">G</span>
                    )}
                    {arming ? (
                      <span className="flex shrink-0 items-center gap-0.5">
                        <button
                          type="button"
                          onClick={() => { onDeleteAsset(a.asset_id); setConfirmDeleteId(null); if (previewId === a.asset_id) setPreviewId(null); }}
                          aria-label={`Confirmar remoção de ${a.original_filename}`}
                          title="Confirmar remoção"
                          className="flex h-6 w-6 items-center justify-center rounded-md text-danger hover:bg-danger/10 focus-visible:outline-2 focus-visible:outline-accent"
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="m5 13 4 4L19 7" /></svg>
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          aria-label="Manter ficheiro"
                          title="Manter"
                          className="flex h-6 w-6 items-center justify-center rounded-md text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
                        </button>
                      </span>
                    ) : (
                      <>
                      <a
                        href={assetFileUrl(project.project_id, a.asset_id)}
                        download={a.original_filename}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`Descarregar ${a.original_filename}`}
                        title="Descarregar ficheiro original"
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted/70 transition-colors hover:bg-border/60 hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 4v11m0 0 4-4m-4 4-4-4" /><path d="M4 19h16" /></svg>
                      </a>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(a.asset_id)}
                        aria-label={`Remover ${a.original_filename}`}
                        title="Remover"
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted/50 transition-colors hover:bg-border/60 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
                      </button>
                      </>
                    )}
                  </div>
                  {expanded && (
                    <div className="border-t border-border bg-black/40 p-2">
                      {a.kind === "video" && (
                        <video src={assetFileUrl(project.project_id, a.asset_id)} controls playsInline preload="metadata" className="aspect-video w-full rounded bg-black" />
                      )}
                      {a.kind === "image" && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={assetFileUrl(project.project_id, a.asset_id)} alt={a.original_filename} className="max-h-40 w-full rounded object-contain bg-black" loading="lazy" />
                      )}
                      {a.kind === "audio" && (
                        <audio src={assetFileUrl(project.project_id, a.asset_id)} controls preload="metadata" className="w-full" style={{ colorScheme: "dark" }} />
                      )}
                      {a.kind === "graphics" && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={assetFileUrl(project.project_id, a.asset_id)} alt={a.original_filename} className="max-h-40 w-full rounded bg-white object-contain" loading="lazy" />
                      )}
                      {a.kind === "text" && (
                        textPreviewError ? (
                          <p className="text-[11px] text-danger" role="alert">{textPreviewError}</p>
                        ) : textPreview === null ? (
                          <p className="text-[11px] text-muted">A carregar pré-visualização…</p>
                        ) : (
                          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-black p-2 font-mono text-[10px] leading-relaxed">{textPreview}</pre>
                        )
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
