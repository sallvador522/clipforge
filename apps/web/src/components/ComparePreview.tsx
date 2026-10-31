"use client";

import { useState } from "react";
import { downloadUrl } from "@/lib/api";
import { Button } from "./ui/button";

interface Props {
  originalUrl: string | null;
  resultUrl: string | null;
  resultReady: boolean;
  downloadJobId: string | null;
}

type Mode = "before" | "after" | "compare";

export function ComparePreview({ originalUrl, resultUrl, resultReady, downloadJobId }: Props) {
  const [mode, setMode] = useState<Mode>("compare");
  const [split, setSplit] = useState(50);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // The API is cross-origin to the studio, where the `download` attribute is
  // ignored (the browser would navigate away). Fetch a Blob and save it instead.
  async function handleDownload() {
    if (!downloadJobId) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const response = await fetch(downloadUrl(downloadJobId));
      if (!response.ok) throw new Error(`Download failed (${response.status}). The result may no longer be verified on the server.`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `clipforge-${downloadJobId}.mp4`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  }

  if (!originalUrl) return null;

  return (
    <section aria-label="Preview" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-mono text-xs tracking-widest text-muted uppercase">Preview</h2>
        <div className="flex gap-1" role="tablist" aria-label="Preview mode">
          {(["before", "compare", "after"] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              disabled={m !== "before" && !resultReady}
              onClick={() => setMode(m)}
              className={`rounded px-3 py-1 font-mono text-xs capitalize transition-colors ${
                mode === m ? "bg-accent text-[#14110c] font-semibold" : "text-muted hover:text-foreground disabled:opacity-30"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div className="relative overflow-hidden rounded-lg border border-border bg-black">
        {mode === "before" && <video controls src={originalUrl} className="aspect-video w-full" />}
        {mode === "after" && resultReady && resultUrl && <video controls src={resultUrl} className="aspect-video w-full" />}
        {mode === "compare" && (
          <div className="relative">
            <video controls src={originalUrl} className="aspect-video w-full" aria-label="Original video" />
            {resultReady && resultUrl ? (
              <div className="pointer-events-none absolute inset-0" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
                <video muted src={resultUrl} className="aspect-video w-full" aria-label="Edited video" />
              </div>
            ) : (
              <div className="absolute inset-y-0 right-0 flex w-1/2 items-center justify-center bg-black/60">
                <p className="px-4 text-center font-mono text-xs text-muted">Edited preview appears here after verified rendering</p>
              </div>
            )}
          </div>
        )}
      </div>

      {mode === "compare" && resultReady && (
        <label className="flex items-center gap-3 font-mono text-xs text-muted">
          Before / after split
          <input
            type="range"
            min={0}
            max={100}
            value={split}
            onChange={(e) => setSplit(Number(e.target.value))}
            className="w-full"
            aria-label="Before after split position"
          />
          <span>{split}%</span>
        </label>
      )}

      {resultReady && downloadJobId && (
        <div>
          <Button className="w-full sm:w-auto" onClick={handleDownload} disabled={downloading}>
            {downloading ? "Downloading…" : "Download verified MP4"}
          </Button>
          {downloadError && (
            <p className="mt-2 text-sm text-danger" role="alert">
              {downloadError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
