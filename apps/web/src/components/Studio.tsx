"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError, checkHealth, downloadUrl, getJob, getResult, submitVoice, uploadVideo } from "@/lib/api";
import type { JobResponse, JobResultData } from "@/lib/types";
import { VOICE_FIXTURES } from "@/lib/fixtures";
import { TopBar } from "./TopBar";
import { MediaPanel, type SourceMeta } from "./MediaPanel";
import { Viewer } from "./Viewer";
import { AssistantPanel } from "./AssistantPanel";
import { Timeline } from "./Timeline";

const TERMINAL = new Set(["completed", "failed"]);

export function Studio() {
  const [apiMode, setApiMode] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [localMeta, setLocalMeta] = useState<SourceMeta | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const [job, setJob] = useState<JobResponse | null>(null);
  const [result, setResult] = useState<JobResultData | null>(null);
  const [fixtureId, setFixtureId] = useState(VOICE_FIXTURES[2].id);
  const [submitting, setSubmitting] = useState(false);
  const [voiceSubmitted, setVoiceSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const primaryRef = useRef<HTMLVideoElement | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    checkHealth()
      .then((h) => {
        setApiMode(h.ai_mode);
        setApiError(null);
      })
      .catch((e) => setApiError(e instanceof ApiClientError ? e.message : "Backend unreachable."));
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollJob = useCallback(
    (jobId: string) => {
      stopPolling();
      pollRef.current = window.setInterval(async () => {
        try {
          const latest = await getJob(jobId);
          setJob(latest);
          if (TERMINAL.has(latest.status)) {
            stopPolling();
            if (latest.status === "completed") setResult(await getResult(jobId));
          }
        } catch (e) {
          stopPolling();
          setError(e instanceof ApiClientError ? e.message : "Lost contact with the API while polling.");
        }
      }, 1500);
    },
    [stopPolling],
  );

  function handleFile(selected: File) {
    setFile(selected);
    setError(null);
    setLocalMeta(null);
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    const url = URL.createObjectURL(selected);
    setOriginalUrl(url);
    setCurrentTime(0);
    setPlaying(false);
    // Local metadata straight from the file itself (the API re-probes on upload).
    const probe = document.createElement("video");
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      setLocalMeta({
        width: probe.videoWidth,
        height: probe.videoHeight,
        duration: probe.duration || 0,
        hasAudio: null, // browsers cannot report this reliably; the API probe is authoritative
      });
      URL.revokeObjectURL(probe.src);
    };
    probe.src = url;
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadProgress(0);
    setError(null);
    try {
      const created = await uploadVideo(file, setUploadProgress);
      setJob(created);
      setApiError(null);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleSubmitVoice() {
    if (!job) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await submitVoice(job.job_id, fixtureId);
      setJob(updated);
      setVoiceSubmitted(true);
      pollJob(job.job_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not submit the instruction.");
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    stopPolling();
    setFile(null);
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    setOriginalUrl(null);
    setLocalMeta(null);
    setJob(null);
    setResult(null);
    setVoiceSubmitted(false);
    setUploadProgress(null);
    setError(null);
    setExportError(null);
    setCurrentTime(0);
    setDuration(0);
    setPlaying(false);
  }

  const handleSeek = useCallback((time: number) => {
    const video = primaryRef.current;
    if (video) video.currentTime = time;
    setCurrentTime(time);
  }, []);

  const handleTogglePlay = useCallback(() => {
    const video = primaryRef.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => {});
    else video.pause();
  }, []);

  const resultReady = Boolean(job?.status === "completed" && result?.render_status === "verified" && result?.rendered);
  const editedUrl = job && resultReady ? downloadUrl(job.job_id) : null;

  async function handleExport() {
    if (!job || !resultReady) return;
    setExporting(true);
    setExportError(null);
    try {
      const response = await fetch(downloadUrl(job.job_id));
      if (!response.ok) throw new Error(`Export failed (${response.status}) — the verified file may have been removed.`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `clipforge-${job.job_id}.mp4`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  const jobMeta = job
    ? {
        width: job.source_info.width,
        height: job.source_info.height,
        duration_seconds: job.source_info.duration_seconds,
        has_audio: job.source_info.has_audio,
        frame_count: job.source_info.frame_count,
        fps: job.source_info.fps,
      }
    : null;
  const effectiveDuration = duration || jobMeta?.duration_seconds || localMeta?.duration || 0;
  const resolution = jobMeta ? `${jobMeta.width}×${jobMeta.height}` : localMeta ? `${localMeta.width}×${localMeta.height}` : null;

  return (
    <main className="flex min-h-screen flex-col bg-background lg:h-screen lg:overflow-hidden">
      <h1 className="sr-only">ClipForge — cinematic AI video editing studio</h1>
      <a href="#viewer" className="sr-only focus:not-sr-only focus:bg-accent focus:px-3 focus:py-1.5 focus:text-sm focus:font-semibold focus:text-[#14110C]">
        Skip to video viewer
      </a>
      <TopBar
        projectName={file ? file.name.replace(/\.[^.]+$/, "") : "Untitled project"}
        aiMode={apiMode}
        apiError={apiError}
        resolution={resolution}
        durationLabel={effectiveDuration ? `${effectiveDuration.toFixed(1)}s` : null}
        jobStatus={job?.status ?? null}
        canExport={resultReady}
        exporting={exporting}
        onExport={handleExport}
        exportError={exportError}
      />

      {apiError && (
        <div className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px]" role="alert">
          <span className="font-medium text-danger">API offline.</span> {apiError} Start the backend, then reload.
        </div>
      )}
      {error && (
        <div className="flex items-center gap-3 border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px]" role="alert">
          <span>
            <span className="font-medium text-danger">Something went wrong:</span> {error}
          </span>
          <button type="button" onClick={reset} className="ml-auto shrink-0 font-medium text-danger underline">
            Start over
          </button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)_328px] xl:grid-cols-[264px_minmax(0,1fr)_344px]">
        <div className="order-3 border-t border-border lg:order-1 lg:border-r lg:border-t-0">
          <MediaPanel
            file={file}
            originalUrl={originalUrl}
            localMeta={localMeta}
            jobMeta={jobMeta}
            jobId={job?.job_id ?? null}
            uploading={uploading}
            uploadProgress={uploadProgress}
            jobCreated={Boolean(job)}
            onFile={handleFile}
            onUpload={handleUpload}
            onReplace={reset}
          />
        </div>

        <div className="order-1 flex min-h-[52vh] flex-col lg:order-2 lg:min-h-0">
          <Viewer
            originalUrl={originalUrl}
            editedUrl={editedUrl}
            resultReady={resultReady}
            primaryRef={primaryRef}
            currentTime={currentTime}
            duration={effectiveDuration}
            playing={playing}
            onTogglePlay={handleTogglePlay}
            onSeek={handleSeek}
            onTimeUpdate={(t, d) => {
              setCurrentTime(t);
              if (d > 0) setDuration(d);
            }}
            onPlayState={setPlaying}
            onFileDrop={handleFile}
          />
          <Timeline
            file={file}
            duration={effectiveDuration}
            currentTime={currentTime}
            hasAudio={jobMeta ? jobMeta.has_audio : null}
            onSeek={handleSeek}
          />
        </div>

        <div className="order-2 border-t border-border lg:border-l lg:border-t-0">
          <AssistantPanel
            job={job}
            result={result}
            fixtureId={fixtureId}
            onSelectFixture={setFixtureId}
            canSubmit={Boolean(job && job.status === "queued" && !job.ready)}
            submitting={submitting}
            submitted={voiceSubmitted}
            onSubmit={handleSubmitVoice}
            onRetry={reset}
          />
        </div>
      </div>
    </main>
  );
}
