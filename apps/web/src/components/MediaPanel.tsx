"use client";

import { useRef, useState } from "react";
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
  jobCreated: boolean;
  onFile: (file: File) => void;
  onUpload: () => void;
  onReplace: () => void;
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

export function MediaPanel({
  file, originalUrl, localMeta, jobMeta, jobId, uploading, uploadProgress, jobCreated, onFile, onUpload, onReplace,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const width = jobMeta?.width ?? localMeta?.width;
  const height = jobMeta?.height ?? localMeta?.height;
  const duration = jobMeta?.duration_seconds ?? localMeta?.duration;
  const hasAudio = jobMeta?.has_audio ?? localMeta?.hasAudio;

  return (
    <section aria-label="Media" className="flex min-h-0 flex-col bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="font-mono text-[11px] font-medium tracking-wider text-muted">MEDIA</h2>
        <span className="font-mono text-[11px] text-muted">{file ? "1 clip" : "empty"}</span>
      </div>

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
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) onFile(f);
          }}
          className={`m-3 flex flex-1 flex-col items-center justify-center rounded-lg border border-dashed p-4 text-center transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
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
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <div className="overflow-hidden rounded-md border border-accent/60">
            {originalUrl && (
              <video src={originalUrl} muted playsInline preload="metadata" className="aspect-video w-full bg-black" aria-label="Source thumbnail" />
            )}
            <div className="bg-raised px-2.5 py-2">
              <p className="truncate text-[13px] font-medium" title={file.name}>{file.name}</p>
              <p className="font-mono text-[11px] text-accent">SOURCE — selected</p>
            </div>
          </div>

          <dl className="mt-3 space-y-1.5 font-mono text-[11px]">
            {[
              ["Duration", duration !== undefined ? formatTime(duration) : "reading…"],
              ["Resolution", width && height ? `${width} × ${height}` : "reading…"],
              ["Frames / FPS", jobMeta ? `${jobMeta.frame_count} @ ${jobMeta.fps.toFixed(0)}` : "after upload"],
              ["Audio", hasAudio === null || hasAudio === undefined ? "reading…" : hasAudio ? "present" : "none"],
              ["Size", formatBytes(file.size)],
              ["Job", jobId ? `${jobId.slice(0, 12)}…` : "not created"],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <dt className="text-muted">{k}</dt>
                <dd className="truncate">{v}</dd>
              </div>
            ))}
          </dl>

          {uploading && uploadProgress !== null && (
            <div className="mt-3">
              <div className="h-1 overflow-hidden rounded bg-border">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${uploadProgress}%` }} />
              </div>
              <p className="mt-1 font-mono text-[11px] text-muted">Uploading… {uploadProgress}%</p>
            </div>
          )}

          <div className="mt-4 flex flex-col gap-2">
            <Button onClick={onUpload} disabled={uploading || jobCreated} className="w-full">
              {jobCreated ? "Uploaded — job created" : uploading ? "Uploading…" : "Upload & create job"}
            </Button>
            <Button variant="ghost" onClick={onReplace} disabled={uploading} className="w-full">
              Replace media (new session)
            </Button>
          </div>
          <p className="mt-3 font-mono text-[11px] leading-relaxed text-muted">
            The API re-validates the file server-side before creating a job. Your original is always preserved.
          </p>
        </div>
      )}
    </section>
  );
}
