"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError, checkHealth, downloadUrl, getJob, getResult, submitVoice, uploadVideo } from "@/lib/api";
import type { JobResponse, JobResultData } from "@/lib/types";
import { VOICE_FIXTURES } from "@/lib/fixtures";
import { UploadPanel } from "./UploadPanel";
import { VoiceRecorder } from "./VoiceRecorder";
import { JobStatusPanel } from "./JobStatusPanel";
import { ComparePreview } from "./ComparePreview";
import { Button } from "./ui/button";

const TERMINAL = new Set(["completed", "failed"]);

export function Studio() {
  const [apiMode, setApiMode] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const [job, setJob] = useState<JobResponse | null>(null);
  const [result, setResult] = useState<JobResultData | null>(null);
  const [fixtureId, setFixtureId] = useState(VOICE_FIXTURES[2].id);
  const [submitting, setSubmitting] = useState(false);
  const [voiceSubmitted, setVoiceSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
            if (latest.status === "completed") {
              setResult(await getResult(jobId));
            }
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
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    setOriginalUrl(URL.createObjectURL(selected));
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
    setJob(null);
    setResult(null);
    setVoiceSubmitted(false);
    setUploadProgress(null);
    setError(null);
  }

  const resultReady = Boolean(job?.status === "completed" && result?.render_status === "verified" && result?.rendered);
  const isWorking = Boolean(job && !TERMINAL.has(job.status));

  return (
    <main className="mx-auto w-full max-w-6xl px-5 pb-16 sm:px-8">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border py-6">
        <div>
          <p className="font-mono text-xs tracking-[0.3em] text-accent">CLIPFORGE STUDIO</p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight sm:text-4xl">Your voice. Your vision. Your video.</h1>
        </div>
        <div className="font-mono text-xs text-muted" aria-live="polite">
          {apiError ? (
            <span className="text-danger">API offline — {apiError}</span>
          ) : apiMode ? (
            <span>
              API connected · AI mode: <span className="text-accent">{apiMode}</span> (simulated providers, real rendering)
            </span>
          ) : (
            "Connecting to API…"
          )}
        </div>
      </header>

      {error && (
        <div className="mt-5 rounded-md border border-danger/40 bg-danger/10 p-4" role="alert">
          <p className="text-sm font-medium text-danger">Something went wrong</p>
          <p className="mt-1 text-sm">{error}</p>
          <Button variant="danger" className="mt-3" onClick={reset}>
            Start over
          </Button>
        </div>
      )}

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="space-y-10">
          <UploadPanel
            fileName={file?.name ?? null}
            fileSize={file?.size ?? null}
            uploading={uploading}
            uploadProgress={uploadProgress}
            jobCreated={Boolean(job)}
            onFile={handleFile}
            onUpload={handleUpload}
          />
          <VoiceRecorder
            selectedFixtureId={fixtureId}
            onSelectFixture={setFixtureId}
            canSubmit={Boolean(job && job.status === "queued" && !job.ready)}
            submitting={submitting}
            submitted={voiceSubmitted}
            onSubmit={handleSubmitVoice}
          />
          {(job || isWorking) && (
            <Button variant="ghost" onClick={reset} className="px-0">
              Start a new session
            </Button>
          )}
        </div>

        <div className="space-y-8">
          <ComparePreview
            originalUrl={originalUrl}
            resultUrl={job && resultReady ? downloadUrl(job.job_id) : null}
            resultReady={resultReady}
            downloadJobId={job && resultReady ? job.job_id : null}
          />
          <JobStatusPanel job={job} result={result} />
          {!job && (
            <div className="rounded-lg border border-border bg-surface p-6">
              <p className="text-lg font-semibold">Edit with your voice</p>
              <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-muted">
                <li>Upload a short clip (up to 10 s, 720p).</li>
                <li>Record what you want changed and confirm the matching command.</li>
                <li>Watch the real job stages, then preview and download the verified MP4.</li>
              </ol>
              <p className="mt-3 font-mono text-xs text-muted">
                Development build: transcription, planning, segmentation and backgrounds are deterministic mocks (ADR-004).
                Rendering and downloads are real.
              </p>
            </div>
          )}
        </div>
      </div>

      <footer className="mt-14 border-t border-border pt-4 font-mono text-xs text-muted">
        ClipForge · mock AI mode · local rendering · originals preserved · no external AI calls
      </footer>
    </main>
  );
}
