"use client";

import { useEffect, useRef, useState } from "react";
import { assetFileUrl } from "@/lib/api";
import type { AssetData, ProjectData } from "@/lib/types";
import { Button } from "./ui/button";

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
  jobId: string | null;
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
  projectBusy: boolean;
  onImportFiles: (files: File[]) => void;
  onDeleteAsset: (assetId: string) => void;
  onRenameProject: (title: string) => void;
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00.0";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(1).padStart(4, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

type Filter = "all" | "video" | "audio" | "image" | "text" | "graphics";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "video", label: "Video" },
  { key: "audio", label: "Audio" },
  { key: "image", label: "Images" },
  { key: "text", label: "Text" },
  { key: "graphics", label: "Graphics" },
];

function kindLabel(kind: string): string {
  switch (kind) {
    case "video": return "VID";
    case "audio": return "AUD";
    case "image": return "IMG";
    case "text": return "TXT";
    case "graphics": return "SVG";
    default: return kind.slice(0, 3).toUpperCase();
  }
}

function assetMetaLine(a: AssetData): string {
  const bits: string[] = [];
  if (a.duration_seconds) bits.push(formatTime(a.duration_seconds));
  if (a.width && a.height) bits.push(`${a.width}×${a.height}`);
  if (a.kind === "audio" && a.audio_codec) bits.push(a.audio_codec);
  if (a.kind === "text" && a.cue_count != null) bits.push(`${a.cue_count} cues`);
  else if (a.kind === "text" && a.text_lines != null) bits.push(`${a.text_lines} lines`);
  if (a.kind === "graphics") bits.push(a.sanitized ? "sanitized" : "svg");
  bits.push(formatBytes(a.size_bytes));
  return bits.join(" · ");
}

export function MediaPanel({
  file, originalUrl, localMeta, jobMeta, jobId, uploading, uploadProgress, onFile, onReplace,
  project, assets, assetsLoading, assetsError, assetUploading, assetProgress,
  projectBusy, onImportFiles, onDeleteAsset, onRenameProject,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const libInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [libDragging, setLibDragging] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [textPreview, setTextPreview] = useState<string | null>(null);
  const [textPreviewError, setTextPreviewError] = useState<string | null>(null);

  const width = jobMeta?.width ?? localMeta?.width;
  const height = jobMeta?.height ?? localMeta?.height;
  const duration = jobMeta?.duration_seconds ?? localMeta?.duration;
  const hasAudio = jobMeta?.has_audio ?? localMeta?.hasAudio;

  const q = query.trim().toLowerCase();
  const visible = assets.filter((a) => {
    if (filter !== "all" && a.kind !== filter) return false;
    if (q && !a.original_filename.toLowerCase().includes(q)) return false;
    return true;
  });
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

  function startRename() {
    setTitleDraft(project?.title ?? "");
    setEditingTitle(true);
  }

  function commitRename() {
    if (titleDraft.trim()) onRenameProject(titleDraft.trim());
    setEditingTitle(false);
  }

  return (
    <section aria-label="Project asset library" className="flex min-h-0 flex-col bg-surface lg:h-full">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="font-mono text-[11px] font-medium tracking-wider text-muted">ASSET LIBRARY</h2>
        <span className="font-mono text-[11px] text-muted">{assets.length} asset{assets.length === 1 ? "" : "s"}</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Project identity */}
        <div className="border-b border-border px-3 py-2.5">
          {editingTitle ? (
            <div className="flex gap-1.5">
              <input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setEditingTitle(false); }}
                maxLength={80}
                aria-label="Project title"
                className="min-w-0 flex-1 rounded-md border border-border bg-raised px-2 py-1 text-[13px] outline-none focus:border-accent"
              />
              <Button variant="secondary" onClick={commitRename} disabled={projectBusy}>Save</Button>
            </div>
          ) : (
            <button type="button" onClick={startRename} title="Rename project" className="block w-full truncate text-left text-[13px] font-semibold hover:text-accent">
              {project?.title ?? "No project yet — import to create one"}
            </button>
          )}
          <p className="mt-0.5 font-mono text-[10px] text-muted">
            {project ? `${project.project_id.slice(0, 13)}… · persists across reloads` : "Creating a project happens automatically on import"}
          </p>
        </div>

        {/* Session clip (existing single-video workflow, preserved) */}
        <input
          ref={inputRef}
          type="file"
          aria-label="Choose a video file"
          accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />
        {!file ? (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files?.[0];
              if (f) onFile(f);
            }}
            className={`m-3 flex flex-col items-center justify-center rounded-lg border border-dashed p-4 text-center transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
              dragging ? "border-accent bg-raised" : "border-border hover:border-muted"
            }`}
          >
            <span className="text-sm font-medium">Import a clip</span>
            <span className="mt-1 font-mono text-[11px] leading-relaxed text-muted">
              Drop a video or click to choose
              <br />
              MP4 / MOV / WebM / MKV · ≤10 s · 720p · 30 FPS
            </span>
          </button>
        ) : (
          <div className="border-b border-border p-3">
            <p className="font-mono text-[10px] tracking-wider text-muted">SESSION CLIP — EDITING SOURCE</p>
            <div className="mt-1.5 overflow-hidden rounded-md border border-accent/60">
              {originalUrl && (
                <video src={originalUrl} muted playsInline preload="metadata" className="aspect-video w-full bg-black" aria-label="Source thumbnail" />
              )}
              <div className="bg-raised px-2.5 py-2">
                <p className="truncate text-[13px] font-medium" title={file.name}>{file.name}</p>
                <p className="font-mono text-[11px] text-accent">SOURCE — selected</p>
              </div>
            </div>
            <dl className="mt-2.5 space-y-1.5 font-mono text-[11px]">
              {[
                ["Duration", duration !== undefined ? formatTime(duration) : "reading…"],
                ["Resolution", width && height ? `${width} × ${height}` : "reading…"],
                ["Frames / FPS", jobMeta ? `${jobMeta.frame_count} @ ${jobMeta.fps.toFixed(0)}` : "after upload"],
                ["Audio", hasAudio === null || hasAudio === undefined ? "reading…" : hasAudio ? "present" : "none"],
                ["Size", formatBytes(file.size)],
                ["Job", jobId ? `${jobId.slice(0, 12)}…` : uploading ? "creating…" : "not created"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <dt className="text-muted">{k}</dt>
                  <dd className="truncate">{v}</dd>
                </div>
              ))}
            </dl>
            {uploading && (
              <div className="mt-3" role="status">
                <div className="h-1 overflow-hidden rounded bg-border">
                  <div className="h-full bg-accent transition-[width]" style={{ width: `${uploadProgress ?? 0}%` }} />
                </div>
                <p className="mt-1 font-mono text-[11px] text-muted">Preparing your video… {uploadProgress ?? 0}%</p>
              </div>
            )}
            <div className="mt-3 flex flex-col gap-2">
              <Button variant="ghost" onClick={onReplace} disabled={uploading} className="w-full">
                Replace media (new session)
              </Button>
            </div>
          </div>
        )}

        {/* Library import */}
        <div className="px-3 pt-3">
          <input
            ref={libInputRef}
            type="file"
            multiple
            aria-label="Import project assets"
            accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv,audio/wav,audio/mpeg,audio/mp4,audio/ogg,audio/webm,.wav,.mp3,.m4a,.ogg,.oga,.webm,.png,.jpg,.jpeg,.webp,.txt,.md,.srt,.vtt,.svg"
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length > 0) onImportFiles(files);
              e.target.value = "";
            }}
          />
          <div
            role="button"
            tabIndex={0}
            aria-label="Import assets (multiple files)"
            onClick={() => libInputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter") libInputRef.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setLibDragging(true); }}
            onDragLeave={() => setLibDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setLibDragging(false);
              const files = Array.from(e.dataTransfer.files ?? []);
              if (files.length > 0) onImportFiles(files);
            }}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed p-3 text-center focus-visible:outline-2 focus-visible:outline-accent ${
              libDragging ? "border-accent bg-raised" : "border-border hover:border-muted"
            }`}
          >
            <span className="text-[13px] font-medium">Import assets</span>
            <span className="mt-0.5 font-mono text-[10px] leading-relaxed text-muted">
              Multiple files · video / audio / image / text / SVG
            </span>
          </div>
          {assetUploading && (
            <div className="mt-2" role="status">
              <div className="h-1 overflow-hidden rounded bg-border">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${assetProgress ?? 0}%` }} />
              </div>
              <p className="mt-1 truncate font-mono text-[10px] text-muted">Uploading {assetUploading}… {assetProgress ?? 0}%</p>
            </div>
          )}
        </div>

        {/* Filters + search */}
        <div className="px-3 pt-3">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Asset type filter">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                aria-pressed={filter === f.key}
                className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                  filter === f.key ? "border-accent bg-accent/15 text-accent" : "border-border text-muted hover:border-muted hover:text-foreground"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search assets…"
            aria-label="Search assets"
            className="mt-2 w-full rounded-md border border-border bg-raised px-2.5 py-1.5 text-[13px] outline-none placeholder:text-muted/60 focus:border-accent"
          />
        </div>

        {/* Asset list */}
        <div className="p-3">
          {assetsLoading ? (
            <p className="font-mono text-[11px] text-muted" role="status">Loading assets…</p>
          ) : assetsError ? (
            <p className="font-mono text-[11px] text-danger" role="alert">{assetsError}</p>
          ) : visible.length === 0 ? (
            <p className="font-mono text-[11px] leading-relaxed text-muted">
              {assets.length === 0 ? "No assets yet. Imported files stay here after reload." : "No assets match this filter."}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {visible.map((a) => (
                <li key={a.asset_id} className="overflow-hidden rounded-md border border-border bg-raised">
                  <div className="flex items-center gap-2 px-2 py-1.5">
                    <span className="flex h-7 w-9 shrink-0 items-center justify-center rounded bg-black font-mono text-[9px] text-accent" aria-hidden>
                      {kindLabel(a.kind)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-medium" title={a.original_filename}>{a.original_filename}</p>
                      <p className="truncate font-mono text-[10px] text-muted">{assetMetaLine(a)}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setPreviewId(previewId === a.asset_id ? null : a.asset_id)}
                      aria-expanded={previewId === a.asset_id}
                      className="shrink-0 font-mono text-[10px] text-accent underline underline-offset-2 hover:text-foreground"
                    >
                      {previewId === a.asset_id ? "Hide" : "Preview"}
                    </button>
                    {confirmDeleteId === a.asset_id ? (
                      <span className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => { onDeleteAsset(a.asset_id); setConfirmDeleteId(null); if (previewId === a.asset_id) setPreviewId(null); }}
                          className="font-mono text-[10px] font-bold text-danger underline underline-offset-2"
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="font-mono text-[10px] text-muted underline underline-offset-2"
                        >
                          Keep
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(a.asset_id)}
                        className="shrink-0 font-mono text-[10px] text-muted underline underline-offset-2 hover:text-danger"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  {preview && preview.asset_id === a.asset_id && project && (
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
                        // Sanitized server-side; served as an image, never inline HTML.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={assetFileUrl(project.project_id, a.asset_id)} alt={a.original_filename} className="max-h-40 w-full rounded bg-white object-contain" loading="lazy" />
                      )}
                      {a.kind === "text" && (
                        textPreviewError ? (
                          <p className="font-mono text-[10px] text-danger" role="alert">{textPreviewError}</p>
                        ) : textPreview === null ? (
                          <p className="font-mono text-[10px] text-muted">Loading preview…</p>
                        ) : (
                          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-black p-2 font-mono text-[10px] leading-relaxed">{textPreview}</pre>
                        )
                      )}
                      <p className="mt-1 truncate font-mono text-[9px] text-muted" title={a.sha256}>
                        sha256 {a.sha256.slice(0, 16)}… · {a.provenance}
                      </p>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 font-mono text-[10px] leading-relaxed text-muted">
            Library assets never trigger AI processing. Only the session clip creates an editing job. SVG files are sanitized server-side and previewed as images.
          </p>
        </div>
      </div>
    </section>
  );
}
