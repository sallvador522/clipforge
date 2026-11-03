"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  answerClarification,
  ApiClientError,
  approvePlan,
  checkHealth,
  createProject,
  deleteAsset,
  downloadUrl,
  getJob,
  getPlan,
  getProject,
  getResult,
  listAssets,
  rejectPlan,
  renameProject,
  submitConsent,
  subjectPreviewUrl,
  submitTranscript,
  transcribeRecording,
  uploadAsset,
  uploadVideo,
} from "@/lib/api";
import type { AssetData, JobResponse, JobResultData, PlanReviewData, ProjectData, TranscriptData } from "@/lib/types";
import {
  approveAssets as approveIdeaAssets,
  approveStoryboard as approveIdeaStoryboard,
  cancelIdea,
  createIdea,
  getIdea,
  getIdeaConfig,
  rejectIdea,
  rerenderIdea,
} from "@/lib/ideas";
import type { IdeaConfigData, IdeaPayload } from "@/lib/idea-types";
import { IdeaPreview } from "./IdeaPreview";
import { IdeaStatusPanel } from "./IdeaStatusPanel";
import { TopBar } from "./TopBar";
import { MediaPanel, type SourceMeta } from "./MediaPanel";
import { Viewer } from "./Viewer";
import { AssistantPanel, type TranscribeStatus } from "./AssistantPanel";
import { ConsentDialog } from "./ConsentDialog";
import { PlanReviewDialog } from "./PlanReviewDialog";
import { Timeline } from "./Timeline";

const TERMINAL = new Set(["completed", "failed", "rejected", "unsupported"]);
const REVIEW_WAIT = new Set(["awaiting_approval", "awaiting_clarification"]);
// Idea-to-video on the same route: while the platform is empty (no clip,
// no edit job) the assistant routes the confirmed instruction into an idea
// job instead of an edit. Active worker states are polled; terminal idea
// states stop the poll and allow a fresh creation from the same draft.
const IDEA_POLL = new Set(["queued", "processing"]);
const IDEA_TERMINAL = new Set(["completed", "failed", "rejected"]);
const IDEA_STORAGE_KEY = "clipforge.idea.last";

export function Studio() {
  const [liveAvailable, setLiveAvailable] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [localMeta, setLocalMeta] = useState<SourceMeta | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  // P0 project workspace: the project persists across reloads via the backend;
  // only the project id is kept in localStorage.
  const [project, setProject] = useState<ProjectData | null>(null);
  const [assets, setAssets] = useState<AssetData[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetsError, setAssetsError] = useState<string | null>(null);
  const [assetUploading, setAssetUploading] = useState<string | null>(null);
  const [assetProgress, setAssetProgress] = useState<number | null>(null);
  const [projectBusy, setProjectBusy] = useState(false);

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
  const [consentReason, setConsentReason] = useState<string | null>(null);
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([]);
  const planAutoOpenedForRef = useRef<string | null>(null);
  const consentAutoOpenedForRef = useRef<string | null>(null);
  const selectionKeyRef = useRef<string | null>(null);
  const uploadingRef = useRef(false);
  const handleTranscribeRef = useRef<() => void>(() => {});

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
  const [socialFormat, setSocialFormat] = useState<"reels" | "youtube">("reels");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [idea, setIdea] = useState<IdeaPayload | null>(null);
  const [ideaConfig, setIdeaConfig] = useState<IdeaConfigData | null>(null);
  const [ideaBusy, setIdeaBusy] = useState<string | null>(null);
  const [ideaError, setIdeaError] = useState<string | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [programmaticOnly, setProgrammaticOnly] = useState(false);

  const primaryRef = useRef<HTMLVideoElement | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    checkHealth()
      .then((h) => {
        setLiveAvailable(h.live_transcription_available);
        setApiError(null);
      })
      .catch((e) => setApiError(e instanceof ApiClientError ? e.message : "Backend unreachable."));
    // Restore the persisted project workspace (backend is source of truth;
    // localStorage holds only the id).
    const storedId = typeof window !== "undefined" ? window.localStorage.getItem("clipforge.projectId") : null;
    if (storedId) {
      setAssetsLoading(true);
      getProject(storedId)
        .then((p) => {
          setProject(p);
          return listAssets(p.project_id);
        })
        .then((l) => {
          setAssets(l.assets);
          setAssetsError(null);
        })
        .catch(() => {
          window.localStorage.removeItem("clipforge.projectId");
          setProject(null);
          setAssets([]);
        })
        .finally(() => setAssetsLoading(false));
    }
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const refreshAssets = useCallback(async (projectId: string) => {
    setAssetsLoading(true);
    try {
      const [p, l] = await Promise.all([getProject(projectId), listAssets(projectId)]);
      setProject(p);
      setAssets(l.assets);
      setAssetsError(null);
    } catch (e) {
      setAssetsError(e instanceof ApiClientError ? e.message : "Could not load project assets.");
    } finally {
      setAssetsLoading(false);
    }
  }, []);

  const ensureProject = useCallback(async (): Promise<ProjectData> => {
    if (project) return project;
    setProjectBusy(true);
    try {
      const created = await createProject(file ? file.name.replace(/\.[^.]+$/, "") : "Untitled project");
      setProject(created);
      setAssets([]);
      window.localStorage.setItem("clipforge.projectId", created.project_id);
      return created;
    } finally {
      setProjectBusy(false);
    }
  }, [project, file]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const rememberIdea = useCallback((ideaId: string) => {
    window.localStorage.setItem(IDEA_STORAGE_KEY, ideaId);
    const url = new URL(window.location.href);
    url.searchParams.set("idea", ideaId);
    window.history.replaceState({}, "", url.toString());
  }, []);

  const loadIdea = useCallback(
    async (ideaId: string) => {
      try {
        const data = await getIdea(ideaId);
        setIdea(data);
        setApiError(null);
        rememberIdea(ideaId);
      } catch {
        window.localStorage.removeItem(IDEA_STORAGE_KEY);
      }
    },
    [rememberIdea],
  );

  // Restore an in-flight idea (deep link ?idea= or last session).
  useEffect(() => {
    const fromUrl = new URL(window.location.href).searchParams.get("idea");
    const stored = window.localStorage.getItem(IDEA_STORAGE_KEY);
    const ideaId = fromUrl || stored;
    if (ideaId) void loadIdea(ideaId);
  }, [loadIdea]);

  // Poll only while the idea worker owns the job.
  useEffect(() => {
    if (!idea || !IDEA_POLL.has(idea.status)) return;
    const ideaId = idea.idea_id;
    const timer = window.setInterval(() => {
      void getIdea(ideaId)
        .then((data) => {
          setIdea(data);
          setApiError(null);
        })
        .catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [idea?.idea_id, idea?.status]);

  // Reset the plate selection whenever a new plan arrives.
  useEffect(() => {
    if (!idea?.storyboard || idea.stage !== "awaiting_plan_approval") return;
    setSelectedAssets(
      idea.assets.filter((asset) => asset.status !== "skipped").map((asset) => asset.asset_id),
    );
    setProgrammaticOnly(!idea.options.use_generated_images);
  }, [idea?.storyboard_hash, idea?.stage]);

  const ideaModes = idea?.modes ?? ideaConfig?.modes;

  const storyboardCost = useMemo(() => {
    if ((ideaModes?.director ?? "mock") !== "live") return 0;
    return idea?.estimate?.storyboard_usd ?? ideaConfig?.prices.storyboard_usd ?? 0.002;
  }, [ideaConfig?.prices.storyboard_usd, idea?.estimate?.storyboard_usd, ideaModes?.director]);

  const assetCost = useMemo(() => {
    if ((ideaModes?.image ?? "mock") !== "live") return 0;
    const unit = ideaConfig?.prices.image_usd ?? 0.01;
    return Number((selectedAssets.length * unit).toFixed(6));
  }, [ideaConfig?.prices.image_usd, ideaModes?.image, selectedAssets.length]);

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
          } else if (latest.status === "awaiting_consent") {
            // The director planned first; SAM needs explicit consent before it
            // may see the video. Fetch the plan for context and ask once per
            // job — polling continues so authorization resumes the job.
            try {
              const review = await getPlan(jobId);
              setPlanReview((current) => (current?.job_id === jobId ? current : review));
              const intent = review.plan?.interpreted_intention ?? review.legacy_plan?.raw_transcript ?? null;
              setConsentReason(intent);
            } catch {
              // Plan may not be persisted yet; the next poll retries.
            }
            if (consentAutoOpenedForRef.current !== jobId) {
              consentAutoOpenedForRef.current = jobId;
              setConsentOpen(true);
            }
          } else if (REVIEW_WAIT.has(latest.status)) {
            stopPolling();
            const review = await getPlan(jobId);
            const planKey = `${review.job_id}:${review.plan?.request_id ?? ""}`;
            setPlanReview(review);
            // Auto-open once per plan; closing it to inspect the preview must
            // not pop it back open on the next tick.
            if (planAutoOpenedForRef.current !== planKey) {
              planAutoOpenedForRef.current = planKey;
              setPlanDialogOpen(true);
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

  async function uploadFileObject(f: File) {
    // Idempotent: exactly one job per selection. Extra selects while an
    // upload is in flight — or after a job exists — are ignored, so no AI
    // request can ever be triggered by uploading alone.
    if (uploadingRef.current || job) return;
    uploadingRef.current = true;
    setFile(f);
    setError(null);
    setLocalMeta(null);
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    const url = URL.createObjectURL(f);
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
    setUploading(true);
    setUploadProgress(0);
    try {
      // The session clip joins the persistent project: reuse it or create one,
      // then register the source as a project asset server-side (no extra AI).
      const active = await ensureProject();
      const created = await uploadVideo(f, setUploadProgress, active.project_id);
      setJob(created);
      if (created.project_id && created.project_id !== active.project_id) {
        window.localStorage.setItem("clipforge.projectId", created.project_id);
      }
      setApiError(null);
      void refreshAssets(created.project_id ?? active.project_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      uploadingRef.current = false;
    }
  }

  async function handleImportFiles(files: File[]) {
    if (files.length === 0) return;
    setError(null);
    try {
      const active = await ensureProject();
      for (const f of files) {
        setAssetUploading(f.name);
        setAssetProgress(0);
        try {
          await uploadAsset(active.project_id, f, setAssetProgress);
        } finally {
          setAssetUploading(null);
          setAssetProgress(null);
        }
      }
      await refreshAssets(active.project_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Asset import failed.");
    }
  }

  async function handleDeleteAsset(assetId: string) {
    if (!project) return;
    try {
      await deleteAsset(project.project_id, assetId);
      await refreshAssets(project.project_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not remove the asset.");
    }
  }

  async function handleRenameProject(title: string) {
    if (!project) return;
    setProjectBusy(true);
    try {
      const updated = await renameProject(project.project_id, title);
      setProject(updated);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not rename the project.");
    } finally {
      setProjectBusy(false);
    }
  }

  function handleFile(selected: File) {
    setError(null);
    void uploadFileObject(selected);
  }

  function sendInstruction() {
    if (!draft.trim()) return;
    setError(null);
    if (job) {
      void submitInstruction();
      return;
    }
    // No clip, no edit job: the platform is empty, so the confirmed
    // instruction becomes a new video idea instead of an edit.
    void handleCreateIdea();
  }

  async function submitInstruction() {
    if (!job || !draft.trim()) return;
    setSubmitting(true);
    setError(null);
    setConsentError(null);
    try {
      const updated = await submitTranscript(
        job.job_id,
        draft.trim(),
        transcript?.session_id ?? null,
      );
      setJob(updated);
      setVoiceSubmitted(true);
      pollJob(job.job_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not send the instruction.");
    } finally {
      setSubmitting(false);
    }
  }

  async function runIdea(label: string, action: () => Promise<IdeaPayload>) {
    setIdeaBusy(label);
    setIdeaError(null);
    try {
      const data = await action();
      setIdea(data);
      rememberIdea(data.idea_id);
    } catch (e) {
      setIdeaError(e instanceof ApiClientError ? e.message : "Erro inesperado.");
    } finally {
      setIdeaBusy(null);
    }
  }

  async function handleCreateIdea() {
    const text = draft.trim();
    if (!text || ideaBusy) return;
    setIdeaBusy("create");
    setError(null);
    try {
      const cfg = ideaConfig ?? (await getIdeaConfig());
      setIdeaConfig(cfg);
      setApiError(null);
      const data = await createIdea(text, cfg.defaults);
      setIdea(data);
      rememberIdea(data.idea_id);
    } catch (e) {
      // No idea panel exists yet to show this: surface it in the top banner.
      setError(e instanceof ApiClientError ? e.message : "Não foi possível criar o vídeo da ideia.");
    } finally {
      setIdeaBusy(null);
    }
  }

  function handleApproveStoryboard() {
    if (!idea) return;
    void runIdea("approve-storyboard", () => approveIdeaStoryboard(idea.idea_id, storyboardCost));
  }

  function handleApproveAssets() {
    if (!idea) return;
    const ids = programmaticOnly ? [] : selectedAssets;
    void runIdea("approve-assets", () =>
      approveIdeaAssets(idea.idea_id, {
        asset_ids: ids,
        max_cost_usd: programmaticOnly ? 0 : assetCost,
        programmatic_only: programmaticOnly || ids.length === 0,
      }),
    );
  }

  function handleRerenderIdea() {
    if (!idea?.storyboard_hash) return;
    void runIdea("render", () => rerenderIdea(idea.idea_id, idea.storyboard_hash as string));
  }

  function handleCancelIdea() {
    if (!idea) return;
    void runIdea("cancel", () => cancelIdea(idea.idea_id));
  }

  function handleRejectIdea() {
    if (!idea) return;
    void runIdea("reject", () => rejectIdea(idea.idea_id));
  }

  function handleNewIdea() {
    setIdea(null);
    setSelectedAssets([]);
    setProgrammaticOnly(false);
    setIdeaError(null);
    setIdeaBusy(null);
    window.localStorage.removeItem(IDEA_STORAGE_KEY);
    const url = new URL(window.location.href);
    url.searchParams.delete("idea");
    window.history.replaceState({}, "", url.toString());
  }

  function declineConsent() {
    if (submitting) return;
    // "Not now" pauses consent; the job stays in awaiting_consent — no SAM
    // call was or will be made until the user explicitly authorizes.
    setConsentOpen(false);
    setConsentError(null);
  }

  function reopenConsent() {
    setConsentError(null);
    setConsentOpen(true);
  }

  async function handleAuthorizeConsent() {
    if (!job) return;
    setSubmitting(true);
    setConsentError(null);
    try {
      // Exactly one consent grant: the backend persists the source-bound
      // record and re-queues the job; the worker resumes the stored plan.
      const updated = await submitConsent(job.job_id);
      setJob(updated);
      setConsentOpen(false);
      pollJob(job.job_id);
    } catch (e) {
      setConsentError(e instanceof ApiClientError ? e.message : "Could not record consent.");
    } finally {
      setSubmitting(false);
    }
  }

  function toggleSubject(objectId: string) {
    setSelectedSubjects((current) =>
      current.includes(objectId) ? current.filter((id) => id !== objectId) : [...current, objectId],
    );
  }

  async function handleApprovePlan() {
    if (!job || !planReview) return;
    if (planReview.subjects.length > 0 && selectedSubjects.length === 0) return;
    setDecisionSubmitting("approve");
    setDecisionError(null);
    try {
      const updated = await approvePlan(job.job_id, undefined, selectedSubjects);
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
    setSelectedSubjects([]);
    selectionKeyRef.current = null;
    planAutoOpenedForRef.current = null;
    consentAutoOpenedForRef.current = null;
    setConsentOpen(false);
    setConsentError(null);
    setConsentReason(null);
    uploadingRef.current = false;
    setIdea(null);
    setSelectedAssets([]);
    setProgrammaticOnly(false);
    setIdeaError(null);
    setIdeaBusy(null);
    window.localStorage.removeItem(IDEA_STORAGE_KEY);
    const resetUrl = new URL(window.location.href);
    resetUrl.searchParams.delete("idea");
    window.history.replaceState({}, "", resetUrl.toString());
  }

  // Auto-transcription: stopping a recording sends the audio straight to the

  // Auto-transcription: stopping a recording sends the audio straight to the
  // provider — transcription is a service, not a destination, so there is no
  // Transcribe button. In mock mode recordings are never transcribed.
  handleTranscribeRef.current = handleTranscribe;
  useEffect(() => {
    if (recording && liveAvailable && transcribeStatus === "idle") {
      handleTranscribeRef.current();
    }
  }, [recording, liveAvailable, transcribeStatus]);

  // Shared subject selection: initialized once per plan (auto-select a lone
  // subject), then toggled from the preview chips or the review cards.
  useEffect(() => {
    if (!planReview) return;
    const planKey = `${planReview.job_id}:${planReview.plan?.request_id ?? ""}`;
    if (selectionKeyRef.current === planKey) return;
    selectionKeyRef.current = planKey;
    setSelectedSubjects(
      planReview.selected_subject_ids.length > 0
        ? [...planReview.selected_subject_ids]
        : planReview.subjects.length === 1
          ? [planReview.subjects[0].object_id]
          : [],
    );
  }, [planReview]);

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
  const editedUrl = job && resultReady ? downloadUrl(job.job_id, "original") : null;

  async function handleExport() {
    if (!job || !resultReady) return;
    setExporting(true);
    setExportError(null);
    try {
      const response = await fetch(downloadUrl(job.job_id, socialFormat));
      if (!response.ok) {
        let detail = `Export failed (${response.status}) — the verified file may have been removed.`;
        try {
          const body = await response.json();
          if (body?.error?.message) detail = body.error.message;
        } catch {
          /* keep generic message */
        }
        throw new Error(detail);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `clipforge-${job.job_id}-${socialFormat}.mp4`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
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

  return (
    <main className="flex min-h-screen flex-col bg-background lg:h-screen lg:overflow-hidden">
      <h1 className="sr-only">ClipForge — cinematic AI video editing studio</h1>
      <a href="#viewer" className="sr-only focus:not-sr-only focus:bg-accent focus:px-3 focus:py-1.5 focus:text-sm focus:font-semibold focus:text-[#14110C]">
        Skip to video viewer
      </a>
      <TopBar
        projectName={project?.title ?? (file ? file.name.replace(/\.[^.]+$/, "") : "Untitled project")}
        apiError={apiError}
        jobStatus={job?.status ?? null}
        selectedFormat={socialFormat}
        onSelectFormat={setSocialFormat}
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
            onFile={handleFile}
            onReplace={reset}
            project={project}
            assets={assets}
            assetsLoading={assetsLoading}
            assetsError={assetsError}
            assetUploading={assetUploading}
            assetProgress={assetProgress}
            projectBusy={projectBusy}
            onImportFiles={(files) => void handleImportFiles(files)}
            onDeleteAsset={(assetId) => void handleDeleteAsset(assetId)}
            onRenameProject={(title) => void handleRenameProject(title)}
          />
        </div>

        <div className="order-1 flex min-h-[52vh] flex-col lg:order-2 lg:h-full lg:min-h-0">
          {idea && !job ? (
            <IdeaPreview idea={idea} busy={ideaBusy} />
          ) : (
            <>
              <Viewer
            originalUrl={originalUrl}
            editedUrl={editedUrl}
            resultReady={resultReady}
            displayFormat={socialFormat}
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
            subjects={
              planReview && job
                ? planReview.subjects.map((subject) => ({
                    object_id: subject.object_id,
                    previewUrl: subjectPreviewUrl(job.job_id, subject.object_id),
                    selected: selectedSubjects.includes(subject.object_id),
                  }))
                : null
            }
            selectionVisible={job?.status === "awaiting_approval"}
            onToggleSubject={toggleSubject}
          />
          <Timeline
            file={file}
            duration={effectiveDuration}
            currentTime={currentTime}
            hasAudio={jobMeta ? jobMeta.has_audio : null}
            onSeek={handleSeek}
          />
            </>
          )}
        </div>

        <div className="order-2 min-h-0 border-t border-border lg:overflow-y-auto lg:border-l lg:border-t-0">
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
            canConfirm={
              job
                ? Boolean(job.status === "queued" && !job.ready)
                : !idea || IDEA_TERMINAL.has(idea.status)
            }
            confirming={submitting || ideaBusy === "create"}
            submitted={voiceSubmitted}
            onConfirmTranscript={sendInstruction}
            onRetry={reset}
            reviewOpen={planDialogOpen}
            consentWaiting={job?.status === "awaiting_consent" && !consentOpen}
            onConsentContinue={reopenConsent}
            confirmLabel={
              !job && (!idea || IDEA_TERMINAL.has(idea.status))
                ? "Create video from this idea"
                : undefined
            }
            emptyPlatform={!job && !file && !uploading}
          />
          {idea && (
            <div className="border-t border-border">
              <IdeaStatusPanel
                idea={idea}
                config={ideaConfig}
                busy={ideaBusy}
                error={ideaError}
                selectedAssets={selectedAssets}
                programmaticOnly={programmaticOnly}
                storyboardCost={storyboardCost}
                assetCost={assetCost}
                onToggleAsset={(assetId) =>
                  setSelectedAssets((current) =>
                    current.includes(assetId)
                      ? current.filter((id) => id !== assetId)
                      : [...current, assetId],
                  )
                }
                onProgrammaticOnly={setProgrammaticOnly}
                onApproveStoryboard={handleApproveStoryboard}
                onApproveAssets={handleApproveAssets}
                onCancel={handleCancelIdea}
                onReject={handleRejectIdea}
                onRerender={handleRerenderIdea}
                onNewIdea={handleNewIdea}
              />
            </div>
          )}
        </div>
      </div>

      {consentOpen && (
        <ConsentDialog
          submitting={submitting}
          error={consentError}
          reason={consentReason}
          onAuthorize={() => void handleAuthorizeConsent()}
          onDecline={declineConsent}
        />
      )}

      {planReview && planDialogOpen && (
        <PlanReviewDialog
          key={planReview.plan?.request_id ?? planReview.job_id}
          review={planReview}
          submitting={decisionSubmitting}
          error={decisionError}
          selectedSubjects={selectedSubjects}
          onToggleSubject={toggleSubject}
          onApprove={handleApprovePlan}
          onReject={handleRejectPlan}
          onClarify={handleClarifyPlan}
          onClose={() => setPlanDialogOpen(false)}
        />
      )}
    </main>
  );
}
