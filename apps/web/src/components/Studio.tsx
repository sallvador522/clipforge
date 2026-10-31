"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError, checkHealth, downloadUrl, getJob, getResult, submitTranscript, transcribeRecording, uploadVideo } from "@/lib/api";
import type { JobResponse, JobResultData, TranscriptData } from "@/lib/types";
import { VOICE_FIXTURES } from "@/lib/fixtures";
import { TopBar } from "./TopBar";
import { MediaPanel, type SourceMeta } from "./MediaPanel";
import { Viewer } from "./Viewer";
import { AssistantPanel, type TranscribeStatus } from "./AssistantPanel";
import { Timeline } from "./Timeline";

const TERMINAL = new Set(["completed", "failed"]);

export function Studio() {
  const [apiMode, setApiMode] = useState<string | null>(null);
  const [liveAvailable, setLiveAvailable] = useState(false);
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

  const [recording, setRecording] = useState<{ blob: Blob; filename: string } | null>(null);
  const [transcribeStatus, setTranscribeStatus] = useState<TranscribeStatus>("idle");
  const [transcribeProgress, setTranscribeProgress] = useState<number | null>(null);
  const [transcriptionError, setTranscriptionError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptData | null>(null);
  const [transcriptSource, setTranscriptSource] = useState<"live" | "mock-audio" | "mock-fixture" | "typed" | null>(null);
  const [draft, setDraft] = useState("");

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
        setLiveAvailable(h.live_transcription_available);
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
      // Detach before revoking so the hidden probe never requests a revoked blob.
      const probeSrc = probe.src;
      probe.removeAttribute("src");
      probe.load();
      URL.revokeObjectURL(probeSrc);
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
    if (!job || !draft.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await submitTranscript(job.job_id, draft.trim(), transcript?.session_id ?? null);
      setJob(updated);
      setVoiceSubmitted(true);
      pollJob(job.job_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not submit the confirmed transcript.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTranscribe() {
    if (!recording || transcribeStatus === "uploading" || transcribeStatus === "transcribing") return;
    // One explicit request per click. No automatic retry of a billable call.
    setTranscriptionError(null);
    setTranscribeStatus("uploading");
    setTranscribeProgress(0);
    try {
      const data = await transcribeRecording(recording.blob, recording.filename, {
        mockFixtureId: liveAvailable ? undefined : fixtureId,
        onProgress: (pct) => {
          setTranscribeProgress(pct);
          if (pct >= 100) setTranscribeStatus("transcribing");
        },
      });
      setTranscript(data);
      setDraft(data.text);
      setTranscriptSource(liveAvailable ? "live" : "mock-audio");
      setTranscribeStatus("done");
    } catch (e) {
      setTranscribeStatus("error");
      setTranscriptionError(e instanceof ApiClientError ? e.message : "Transcription failed.");
    }
  }

  function handleUseMockTranscript() {
    const fixture = VOICE_FIXTURES.find((f) => f.id === fixtureId);
    if (!fixture) return;
    setTranscript({
      text: fixture.transcript,
      language: "pt-BR",
      confidence: null,
      provider_name: "mock-fixture",
      is_mock: true,
      session_id: null,
      audio_duration_ms: null,
      transcribe_mode: "mock",
    });
    setDraft(fixture.transcript);
    setTranscriptSource("mock-fixture");
    setTranscriptionError(null);
    setTranscribeStatus("done");
  }

  function handleTypedInstruction(text: string) {
    setTranscript(null);
    setDraft(text);
    setTranscriptSource("typed");
    setTranscriptionError(null);
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
    setRecording(null);
    setTranscribeStatus("idle");
    setTranscribeProgress(null);
    setTranscriptionError(null);
    setTranscript(null);
    setTranscriptSource(null);
    setDraft("");
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
        liveTranscription={liveAvailable}
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

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)_328px] lg:grid-rows-[minmax(0,1fr)] xl:grid-cols-[264px_minmax(0,1fr)_344px]">
        <div className="order-3 min-h-0 border-t border-border lg:order-1 lg:overflow-hidden lg:border-r lg:border-t-0">
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

        <div className="order-1 flex min-h-[52vh] flex-col lg:order-2 lg:h-full lg:min-h-0">
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

        <div className="order-2 min-h-0 border-t border-border lg:overflow-hidden lg:border-l lg:border-t-0">
          <AssistantPanel
            job={job}
            result={result}
            liveAvailable={liveAvailable}
            fixtureId={fixtureId}
            onSelectFixture={setFixtureId}
            recorded={Boolean(recording)}
            recordingName={recording?.filename ?? null}
            onRecordingReady={(blob, filename) => {
              setRecording({ blob, filename });
              setTranscript(null);
              setTranscriptSource(null);
              setDraft("");
              setTranscriptionError(null);
              setTranscribeStatus("idle");
            }}
            onRecordingCleared={() => {
              setRecording(null);
              setTranscribeStatus("idle");
              setTranscriptionError(null);
            }}
            transcribeStatus={transcribeStatus}
            transcribeProgress={transcribeProgress}
            transcriptionError={transcriptionError}
            transcript={transcript}
            transcriptSource={transcriptSource}
            draft={draft}
            onDraftChange={setDraft}
            onTranscribe={handleTranscribe}
            onUseMockTranscript={handleUseMockTranscript}
            onTypedInstruction={handleTypedInstruction}
            canConfirm={Boolean(job && job.status === "queued" && !job.ready)}
            confirming={submitting}
            submitted={voiceSubmitted}
            onConfirmTranscript={handleSubmitVoice}
            onRetry={reset}
          />
        </div>
      </div>
    </main>
  );
}
