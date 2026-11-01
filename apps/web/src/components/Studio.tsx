"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  answerClarification,
  ApiClientError,
  approvePlan,
  checkHealth,
  downloadUrl,
  getJob,
  getPlan,
  getResult,
  rejectPlan,
  submitTranscript,
  transcribeRecording,
  uploadVideo,
} from "@/lib/api";
import type { JobResponse, JobResultData, PlanReviewData, TranscriptData } from "@/lib/types";
import { TopBar } from "./TopBar";
import { MediaPanel, type SourceMeta } from "./MediaPanel";
import { Viewer } from "./Viewer";
import { AssistantPanel, type TranscribeStatus } from "./AssistantPanel";
import { ConsentDialog } from "./ConsentDialog";
import { PlanReviewDialog } from "./PlanReviewDialog";
import { Timeline } from "./Timeline";

const TERMINAL = new Set(["completed", "failed", "rejected", "unsupported"]);
const REVIEW_WAIT = new Set(["awaiting_approval", "awaiting_clarification"]);

export function Studio() {
  const [apiMode, setApiMode] = useState<string | null>(null);
  const [liveAvailable, setLiveAvailable] = useState(false);
  const [liveBilling, setLiveBilling] = useState(false);
  const [billingDismissed, setBillingDismissed] = useState(false);
  const [segmentationMode, setSegmentationMode] = useState<"mock" | "live" | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [localMeta, setLocalMeta] = useState<SourceMeta | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const [job, setJob] = useState<JobResponse | null>(null);
  const [result, setResult] = useState<JobResultData | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [voiceSubmitted, setVoiceSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planReview, setPlanReview] = useState<PlanReviewData | null>(null);
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const [decisionSubmitting, setDecisionSubmitting] = useState<"approve" | "reject" | "clarify" | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [consentOpen, setConsentOpen] = useState(false);
  const [consentError, setConsentError] = useState<string | null>(null);

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
        setSegmentationMode(h.segmentation_mode ?? "mock");
        setLiveBilling(
          h.live_transcription_available ||
            h.director_mode === "live" ||
            h.segmentation_mode === "live" ||
            h.live_image_available === true,
        );
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
          if (latest.status === "completed") {
            stopPolling();
            setResult(await getResult(jobId));
            setPlanReview(null);
            setPlanDialogOpen(false);
          } else if (TERMINAL.has(latest.status)) {
            stopPolling();
            setResult(null);
            try {
              setPlanReview(await getPlan(jobId));
            } catch {
              setPlanReview(null);
            }
          } else if (REVIEW_WAIT.has(latest.status)) {
            stopPolling();
            const review = await getPlan(jobId);
            setPlanReview(review);
            setPlanDialogOpen(true);
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

  function requestConfirmTranscript() {
    if (!job || !draft.trim() || segmentationMode === null) return;
    setError(null);
    if (segmentationMode === "live") {
      setConsentError(null);
      setConsentOpen(true);
      return;
    }
    void submitConfirmedTranscript(undefined);
  }

  async function submitConfirmedTranscript(subjectDetectionConsent?: boolean) {
    if (!job || !draft.trim()) return;
    setSubmitting(true);
    setError(null);
    setConsentError(null);
    try {
      const updated = await submitTranscript(
        job.job_id,
        draft.trim(),
        transcript?.session_id ?? null,
        subjectDetectionConsent,
      );
      setJob(updated);
      setVoiceSubmitted(true);
      setConsentOpen(false);
      pollJob(job.job_id);
    } catch (e) {
      const message = e instanceof ApiClientError ? e.message : "Could not submit the confirmed transcript.";
      if (subjectDetectionConsent === true) setConsentError(message);
      else setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  function declineConsent() {
    if (submitting) return;
    setConsentOpen(false);
    setConsentError(null);
  }

  async function handleApprovePlan(subjectIds: string[]) {
    if (!job || !planReview) return;
    setDecisionSubmitting("approve");
    setDecisionError(null);
    try {
      const updated = await approvePlan(job.job_id, undefined, subjectIds);
      setJob(updated);
      // Keep the detection metadata visible to the truthful step tracker while
      // rendering; the dialog is closed and the plan is cleared on completion.
      setPlanReview((current) =>
        current ? { ...current, status: updated.status, stage: updated.stage } : current,
      );
      setPlanDialogOpen(false);
      pollJob(job.job_id);
    } catch (e) {
      setDecisionError(e instanceof ApiClientError ? e.message : "Could not approve the plan.");
    } finally {
      setDecisionSubmitting(null);
    }
  }

  async function handleRejectPlan() {
    if (!job || !planReview) return;
    setDecisionSubmitting("reject");
    setDecisionError(null);
    try {
      const updated = await rejectPlan(job.job_id);
      setJob(updated);
      setPlanReview(null);
      setPlanDialogOpen(false);
    } catch (e) {
      setDecisionError(e instanceof ApiClientError ? e.message : "Could not reject the plan.");
    } finally {
      setDecisionSubmitting(null);
    }
  }

  async function handleClarifyPlan(answer: string) {
    if (!job || !planReview || !answer.trim()) return;
    setDecisionSubmitting("clarify");
    setDecisionError(null);
    try {
      const updated = await answerClarification(job.job_id, answer);
      setJob(updated);
      setPlanReview(null);
      setPlanDialogOpen(false);
      pollJob(job.job_id);
    } catch (e) {
      setDecisionError(e instanceof ApiClientError ? e.message : "Could not submit the clarification.");
    } finally {
      setDecisionSubmitting(null);
    }
  }

  async function handleTranscribe() {
    if (!recording || !liveAvailable) return;
    if (transcribeStatus === "uploading" || transcribeStatus === "transcribing") return;
    // One explicit request per click. No automatic retry of a billable call.
    setTranscriptionError(null);
    setTranscribeStatus("uploading");
    setTranscribeProgress(0);
    try {
      const data = await transcribeRecording(recording.blob, recording.filename, {
        onProgress: (pct) => {
          setTranscribeProgress(pct);
          if (pct >= 100) setTranscribeStatus("transcribing");
        },
      });
      setTranscript(data);
      setDraft(data.text);
      setTranscriptSource("live");
      setTranscribeStatus("done");
    } catch (e) {
      setTranscribeStatus("error");
      setTranscriptionError(e instanceof ApiClientError ? e.message : "Transcription failed.");
    }
  }

  function handleTypedInstruction(text: string) {
    setTranscript(null);
    setDraft(text);
    setTranscriptSource("typed");
    setTranscriptionError(null);
  }

  function reset() {
    stopPolling();
    setPlanReview(null);
    setPlanDialogOpen(false);
    setDecisionSubmitting(null);
    setDecisionError(null);
    setConsentOpen(false);
    setConsentError(null);
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
      {liveBilling && !billingDismissed && (
        <div role="note" aria-label="Live billing notice" className="border-b border-accent/40 bg-accent/10 px-4 py-2 text-[12px] leading-relaxed">
          <span className="font-mono text-[10px] tracking-wider text-accent">JUDGE MODE — LIVE AI · </span>
          Voice transcription (Muse Voice), planning (Muse Spark), subject detection (SAM 3.1) and
          background generation (Muse Image) run on <strong>your own Meta account and may incur charges</strong>.
          Each model runs only when you request it; rendering is local and free.
          <button type="button" onClick={() => setBillingDismissed(true)} className="ml-3 font-mono text-[11px] text-muted underline underline-offset-2 hover:text-foreground">
            Dismiss
          </button>
        </div>
      )}
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
            planReview={planReview}
            onOpenPlanReview={() => setPlanDialogOpen(true)}
            liveAvailable={liveAvailable}
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
            onTypedInstruction={handleTypedInstruction}
            canConfirm={Boolean(job && job.status === "queued" && !job.ready && segmentationMode !== null)}
            confirming={submitting}
            submitted={voiceSubmitted}
            onConfirmTranscript={requestConfirmTranscript}
            onRetry={reset}
          />
        </div>
      </div>

      {consentOpen && (
        <ConsentDialog
          submitting={submitting}
          error={consentError}
          onAuthorize={() => void submitConfirmedTranscript(true)}
          onDecline={declineConsent}
        />
      )}

      {planReview && planDialogOpen && (
        <PlanReviewDialog
          key={planReview.plan?.request_id ?? planReview.job_id}
          review={planReview}
          submitting={decisionSubmitting}
          error={decisionError}
          onApprove={handleApprovePlan}
          onReject={handleRejectPlan}
          onClarify={handleClarifyPlan}
          onClose={() => setPlanDialogOpen(false)}
        />
      )}
    </main>
  );
}
