"use client";

import { useRef, useState } from "react";
import { Button } from "./ui/button";

interface Props {
  fileName: string | null;
  fileSize: number | null;
  uploading: boolean;
  uploadProgress: number | null;
  jobCreated: boolean;
  onFile: (file: File) => void;
  onUpload: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function UploadPanel({ fileName, fileSize, uploading, uploadProgress, jobCreated, onFile, onUpload }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <section aria-label="Upload video" className="space-y-3">
      <h2 className="font-mono text-xs tracking-widest text-muted uppercase">01 — Source video</h2>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) onFile(file);
        }}
        className={`rounded-lg border border-dashed p-5 transition-colors ${dragging ? "border-accent bg-raised" : "border-border bg-surface"}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mp4,.mov,.webm,.mkv"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
          }}
        />
        {fileName ? (
          <div className="space-y-3">
            <p className="truncate text-sm font-medium">{fileName}</p>
            <p className="font-mono text-xs text-muted">
              {fileSize !== null ? formatBytes(fileSize) : ""} · MP4/MOV/WebM/MKV · max 10 s · 720p · 30 FPS (validated by the API)
            </p>
            {uploading && uploadProgress !== null && (
              <div>
                <div className="h-1.5 overflow-hidden rounded bg-border">
                  <div className="h-full bg-accent transition-[width]" style={{ width: `${uploadProgress}%` }} />
                </div>
                <p className="mt-1 font-mono text-xs text-muted">Uploading… {uploadProgress}%</p>
              </div>
            )}
            <div className="flex gap-2">
              <Button onClick={onUpload} disabled={uploading || jobCreated}>
                {jobCreated ? "Uploaded — job created" : uploading ? "Uploading…" : "Upload & create job"}
              </Button>
              <Button variant="ghost" onClick={() => inputRef.current?.click()} disabled={uploading || jobCreated}>
                Choose different file
              </Button>
            </div>
          </div>
        ) : (
          <button type="button" onClick={() => inputRef.current?.click()} className="w-full text-left">
            <p className="text-sm font-medium">Drop a video here, or click to choose</p>
            <p className="mt-1 font-mono text-xs text-muted">MP4 / MOV / WebM / MKV · up to 10 seconds · 720p · validated server-side before a job is created</p>
          </button>
        )}
      </div>
    </section>
  );
}
