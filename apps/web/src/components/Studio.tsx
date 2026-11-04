"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  answerClarification,
  ApiClientError,
  approvePlan,
  assetFileUrl,
  checkHealth,
  createProject,
  deleteAsset,
  downloadUrl,
  executeTool,
  getClipTexts,
  getColour,
  getJob,
  getPlan,
  getProject,
  getResult,
  getTimeline,
  listAssets,
  newClipId,
  putClipTexts,
  putColour,
  putTimeline,
  rejectPlan,
  renameProject,
  renderTimeline,
  setTrim,
  setUploadAudio,
  sendChat,
  submitConsent,
  subjectPreviewUrl,
  submitTranscript,
  transcribeRecording,
  uploadAsset,
  uploadVideo,
} from "@/lib/api";
import type { AssetData, JobResponse, JobResultData, PlanReviewData, ProjectData, TimelineClipData, TimelineData, TimelineTrack, TranscriptData } from "@/lib/types";
import type { ChatData, ChatInterview, ChatToolCall } from "@/lib/api";
import {
  applyRefinement,
  approveAssets as approveIdeaAssets,
  approveStoryboard as approveIdeaStoryboard,
  cancelIdea,
  createIdea,
  deleteSceneFromBoard,
  detectDurationSeconds,
  directIdea,
  getIdea,
  getIdeaConfig,
  moveSceneInBoard,
  patchStoryboard as patchIdeaStoryboard,
  rejectIdea,
  rejectRefinement,
  reorderSceneInBoard,
  rerenderIdea,
  splitSceneFromBoard,
  trimSceneFromBoard,
  updateSceneText,
} from "@/lib/ideas";
import type { IdeaConfigData, IdeaPayload } from "@/lib/idea-types";
import { IdeaPreview, type IdeaPreviewHandle } from "./IdeaPreview";
import { IdeaStatusPanel } from "./IdeaStatusPanel";
import { TopBar } from "./TopBar";
import { MediaPanel, type SourceMeta } from "./MediaPanel";
import { Viewer } from "./Viewer";
import { AssistantPanel, type ChatMessage, type TranscribeStatus } from "./AssistantPanel";
import { ConsentDialog } from "./ConsentDialog";
import { PlanReviewDialog } from "./PlanReviewDialog";
import { Timeline } from "./Timeline";
import { EditorRail } from "./EditorRail";
import { PropertiesPanel } from "./PropertiesPanel";
import { RightPanel } from "./RightPanel";
import { TextPanel } from "./TextPanel";
import {
  CLIP_TEXT_STYLES,
  clampOverlay,
  defaultOverlayAt,
  newClipTextId,
  storageKeyFor,
  type ClipTextOverlay,
  type ClipTextStyleId,
} from "@/lib/textOverlays";

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
  /** ADR-053: true quando /health diz chat_mode=live (Muse Spark reescreve as respostas). */
  const [chatLive, setChatLive] = useState(false);
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
  // ADR-044: the job survives reloads via localStorage (the backend owns it);
  // the session File object does not — the preview falls back to the
  // registered session asset served by the API.
  const JOB_STORAGE_KEY = "clipforge.jobId";
  const restoredJobRef = useRef(false);
  // ADR-044: library selection drives the right-hand Properties tab.
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
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

  // Session chat log. Real events only, newest last; cleared on full reset.
  // No persistence: reloading starts a fresh conversation (stated in the UI).
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const messageSeq = useRef(0);
  const lastSentRef = useRef<{ text: string; at: number } | null>(null);
  const notifiedRef = useRef<Set<string>>(new Set());

  const notifyOnce = useCallback((key: string, role: "user" | "muse", text: string) => {
    if (notifiedRef.current.has(key)) return;
    notifiedRef.current.add(key);
    messageSeq.current += 1;
    const id = `${Date.now()}-${messageSeq.current}`;
    setMessages((current) => [...current.slice(-100), { id, role, text }]);
  }, []);

  function pushUserMessage(text: string) {
    const now = Date.now();
    const last = lastSentRef.current;
    if (last && last.text === text && now - last.at < 2000) return;
    lastSentRef.current = { text, at: now };
    messageSeq.current += 1;
    const id = `${now}-${messageSeq.current}`;
    setMessages((current) => [...current.slice(-100), { id, role: "user", text }]);
  }

  function pushMuseMessage(text: string) {
    messageSeq.current += 1;
    const id = `${Date.now()}-${messageSeq.current}`;
    setMessages((current) => [...current.slice(-100), { id, role: "muse", text }]);
  }

  // Conversational Muse: actionable turns wait here until the user presses
  // Executar. The server never executes from /api/chat; execution reuses the
  // existing voice/ideas endpoints so the approval/consent gates are unchanged.
  const [pendingChat, setPendingChat] = useState<ChatData | null>(null);
  const [chatBusy, setChatBusy] = useState(false);

  const [draft, setDraft] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  // ADR-044 multitrack assembly: explicit user arrangement, server-validated.
  const [assembly, setAssembly] = useState<TimelineData | null>(null);
  const [assemblyError, setAssemblyError] = useState<string | null>(null);
  // ADR-051 output canvas: preserve the primary source by default; the user
  // explicitly chooses landscape/portrait instead.
  const [timelineFormat, setTimelineFormat] = useState<"source" | "landscape" | "portrait">("source");
  const [renderingTimeline, setRenderingTimeline] = useState(false);
  const [socialFormat, setSocialFormat] = useState<"reels" | "youtube">("reels");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  // Fase 1 preview-only clip texts (ADR-045): local-only, no backend.
  // Max 5 styles, anime.js overlay in Viewer + T1 lane in Timeline.
  const [leftTab, setLeftTab] = useState<"assets" | "text">("assets");
  const [clipTexts, setClipTexts] = useState<ClipTextOverlay[]>([]);
  const [selectedTextId, setSelectedTextId] = useState<string | null>(null);
  // ADR-047: persisted colour grade + backend sync for texts/colour.
  const [colour, setColour] = useState({ contrast: 1, brightness: 0, saturation: 1 });
  const [colourBusy, setColourBusy] = useState(false);
  const [colourNote, setColourNote] = useState<string | null>(null);
  const [textsNote, setTextsNote] = useState<string | null>(null);
  const persistTimer = useRef<number | null>(null);

  function toBackendTexts(list: ClipTextOverlay[]) {
    return list.map((t) => ({
      overlay_id: t.id,
      text: t.text,
      style: t.style,
      start_s: t.start,
      duration_s: t.duration,
      x: t.x,
      y: t.y,
      scale: t.scale,
      color: t.color,
      weight: t.weight,
    }));
  }

  function fromBackendTexts(list: { overlay_id: string; text: string; style: string; start_s: number; duration_s: number; x: number; y: number; scale: number; color: string; weight: string }[]): ClipTextOverlay[] {
    return list
      .filter((t) => t && typeof t.overlay_id === "string")
      .slice(0, 20)
      .map((t) =>
        clampOverlay(
          {
            id: t.overlay_id,
            text: typeof t.text === "string" ? t.text : "",
            style: (t.style as ClipTextOverlay["style"]) ?? "rise",
            start: t.start_s ?? 0,
            duration: t.duration_s ?? 2.5,
            x: t.x ?? 0.5,
            y: t.y ?? 0.78,
            scale: t.scale ?? 1,
            color: t.color ?? "#FFFFFF",
            weight: (t.weight as ClipTextOverlay["weight"]) ?? "bold",
          },
          Math.max(0.5, effectiveDuration || 6),
        ),
      );
  }

  const persistTexts = useCallback(
    (next: ClipTextOverlay[], jobId: string | null) => {
      if (!jobId) return;
      if (persistTimer.current) window.clearTimeout(persistTimer.current);
      persistTimer.current = window.setTimeout(() => {
        void putClipTexts(jobId, toBackendTexts(next)).then(
          () => setTextsNote(null),
          (e) => {
            const msg = e instanceof ApiClientError ? e.message : "Não consegui guardar o texto.";
            // 409 = edit window closed (director flow mid-review): local stays, honest note.
            setTextsNote(msg);
          },
        );
      }, 600);
    },
    [],
  );

  async function refreshTextsFromBackend(jobId: string) {
    try {
      const [textsRes, colourRes] = await Promise.all([
        getClipTexts(jobId).catch(() => null),
        getColour(jobId).catch(() => null),
      ]);
      if (textsRes) {
        setClipTexts(fromBackendTexts(textsRes.texts));
        setTextsNote(null);
      }
      if (colourRes?.colour) {
        setColour({
          contrast: colourRes.colour.contrast,
          brightness: colourRes.colour.brightness,
          saturation: colourRes.colour.saturation,
        });
        setColourNote(null);
      }
    } catch {
      /* keep local state on network failure */
    }
  }

  const [idea, setIdea] = useState<IdeaPayload | null>(null);
  const [ideaConfig, setIdeaConfig] = useState<IdeaConfigData | null>(null);
  const [ideaBusy, setIdeaBusy] = useState<string | null>(null);
  const [ideaError, setIdeaError] = useState<string | null>(null);
  // Duração escolhida antes de criar a ideia (a trava dos 20 s fixos saiu
  // daqui: o backend aceita 5–60 s, o Studio usava sempre o default).
  const [pendingDuration, setPendingDuration] = useState(20);
  // Override manual nas pills: quando o utilizador toca, a deteção
  // automática do texto deixa de se aplicar a essa criação.
  const [durationTouched, setDurationTouched] = useState(false);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [programmaticOnly, setProgrammaticOnly] = useState(false);

  const primaryRef = useRef<HTMLVideoElement | null>(null);
  const pollRef = useRef<number | null>(null);

  // ADR-044: asset name/duration lookups for timeline blocks and trim clamps.
  const assetNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const a of assets) map[a.asset_id] = a.original_filename;
    return map;
  }, [assets]);

  const assetDurations = useMemo(() => {
    const map: Record<string, number> = {};
    for (const a of assets) {
      if (a.duration_seconds) map[a.asset_id] = a.duration_seconds;
    }
    return map;
  }, [assets]);

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

  // ADR-047 clip texts: persisted on the job. The backend is source of
  // truth; localStorage is a cache for the session File lifecycle and a
  // migration path for pre-backend overlays.
  useEffect(() => {
    const jobId = job?.job_id ?? null;
    if (!jobId) {
      try {
        const raw = window.localStorage.getItem(storageKeyFor(null));
        if (!raw) {
          setClipTexts([]);
          setSelectedTextId(null);
          return;
        }
        const parsed = JSON.parse(raw) as ClipTextOverlay[];
        if (!Array.isArray(parsed)) {
          setClipTexts([]);
          return;
        }
        const prog = Math.max(0.5, job?.source_info.duration_seconds ?? duration ?? 6);
        setClipTexts(
          parsed
            .filter((t) => t && typeof t.id === "string" && typeof t.text === "string")
            .slice(0, 20)
            .map((t) => clampOverlay(t, prog)),
        );
      } catch {
        setClipTexts([]);
      }
      setSelectedTextId(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [textsRes, colourRes] = await Promise.all([
          getClipTexts(jobId).catch(() => null),
          getColour(jobId).catch(() => null),
        ]);
        if (cancelled) return;
        if (textsRes && textsRes.texts.length > 0) {
          setClipTexts(fromBackendTexts(textsRes.texts));
          setTextsNote(null);
        } else {
          // Legacy migration: pre-backend local overlays go up once.
          try {
            const raw = window.localStorage.getItem(storageKeyFor(jobId));
            if (raw) {
              const parsed = JSON.parse(raw) as ClipTextOverlay[];
              if (Array.isArray(parsed) && parsed.length > 0) {
                const prog = Math.max(0.5, job?.source_info.duration_seconds ?? duration ?? 6);
                const migrated = parsed
                  .filter((t) => t && typeof t.id === "string" && typeof t.text === "string")
                  .slice(0, 20)
                  .map((t) => clampOverlay(t, prog));
                if (migrated.length > 0) {
                  setClipTexts(migrated);
                  persistTexts(migrated, jobId);
                } else {
                  setClipTexts([]);
                }
              } else {
                setClipTexts([]);
              }
            } else {
              setClipTexts([]);
            }
          } catch {
            setClipTexts([]);
          }
        }
        if (colourRes?.colour) {
          setColour({
            contrast: colourRes.colour.contrast,
            brightness: colourRes.colour.brightness,
            saturation: colourRes.colour.saturation,
          });
        }
      } catch {
        /* keep local state */
      }
    })();
    setSelectedTextId(null);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id]);

  useEffect(() => {
    try {
      const key = storageKeyFor(job?.job_id ?? null);
      window.localStorage.setItem(key, JSON.stringify(clipTexts.slice(0, 20)));
    } catch {
      /* storage full — preview state stays in memory */
    }
  }, [clipTexts, job?.job_id]);

  function handleAddClipText(style: ClipTextStyleId) {
    const prog = Math.max(
      1,
      (job && assembly && assembly.timeline.clips.length > 0
        ? assembly.program_duration_s
        : effectiveDuration) || 6,
    );
    const overlay = defaultOverlayAt(currentTime, prog, style);
    const next = [...clipTexts.slice(0, 19), overlay];
    setClipTexts(next);
    persistTexts(next, job?.job_id ?? null);
    setSelectedTextId(overlay.id);
    setLeftTab("text");
  }

  function applyTextPatch(id: string, patch: Partial<ClipTextOverlay>) {
    const prog = Math.max(
      0.5,
      (job && assembly && assembly.timeline.clips.length > 0
        ? assembly.program_duration_s
        : effectiveDuration) || 6,
    );
    const next = clipTexts.map((t) => {
      if (t.id !== id) return t;
      const merged: ClipTextOverlay = {
        ...t,
        text: typeof patch.text === "string" ? patch.text.slice(0, 140) : t.text,
        style: (patch.style as ClipTextOverlay["style"]) ?? t.style,
        start: patch.start ?? t.start,
        duration: patch.duration !== undefined ? Math.min(8, Math.max(0.5, patch.duration)) : t.duration,
        x: patch.x ?? t.x,
        y: patch.y ?? t.y,
        scale: patch.scale !== undefined ? Math.min(1.6, Math.max(0.7, patch.scale)) : t.scale,
        color:
          typeof patch.color === "string" && /^#[0-9a-fA-F]{6}$/.test(patch.color)
            ? patch.color.toUpperCase()
            : t.color ?? "#FFFFFF",
        weight: patch.weight === "normal" ? "normal" : patch.weight === "bold" ? "bold" : t.weight ?? "bold",
      };
      return clampOverlay(merged, prog);
    });
    setClipTexts(next);
    persistTexts(next, job?.job_id ?? null);
  }

  function handleUpdateClipText(id: string, patch: Partial<ClipTextOverlay>) {
    applyTextPatch(id, patch);
  }

  function handleMoveClipText(id: string, newStart: number) {
    const prog = Math.max(
      0.5,
      (job && assembly && assembly.timeline.clips.length > 0
        ? assembly.program_duration_s
        : effectiveDuration) || 6,
    );
    const next = clipTexts.map((t) =>
      t.id === id ? clampOverlay({ ...t, start: newStart }, prog) : t,
    );
    setClipTexts(next);
    persistTexts(next, job?.job_id ?? null);
  }

  function handleTrimClipText(id: string, edge: "start" | "end", newT: number) {
    const prog = Math.max(
      0.5,
      (job && assembly && assembly.timeline.clips.length > 0
        ? assembly.program_duration_s
        : effectiveDuration) || 6,
    );
    const next = clipTexts.map((t) => {
      if (t.id !== id) return t;
      let start = t.start;
      let end = t.start + t.duration;
      if (edge === "start") start = newT;
      else end = newT;
      if (end - start < 0.5) {
        if (edge === "start") start = end - 0.5;
        else end = start + 0.5;
      }
      start = Math.min(Math.max(0, start), Math.max(0, prog - 0.3));
      end = Math.min(Math.max(start + 0.5, end), prog + 0.001);
      return clampOverlay({ ...t, start, duration: end - start }, prog);
    });
    setClipTexts(next);
    persistTexts(next, job?.job_id ?? null);
  }

  function handleRemoveClipText(id: string) {
    const next = clipTexts.filter((t) => t.id !== id);
    setClipTexts(next);
    persistTexts(next, job?.job_id ?? null);
    setSelectedTextId((current) => (current === id ? null : current));
  }

  const selectedClipText = clipTexts.find((t) => t.id === selectedTextId) ?? null;
  const timelineClipTexts = clipTexts.map((t) => ({
    id: t.id,
    title: t.text || "(sem texto)",
    start: t.start,
    duration: t.duration,
  }));

  // ADR-044: load the explicit arrangement whenever the job changes.
  useEffect(() => {
    if (!job) {
      setAssembly(null);
      setAssemblyError(null);
      return;
    }
    let cancelled = false;
    void getTimeline(job.job_id)
      .then((data) => {
        if (!cancelled) {
          setAssembly(data);
          setAssemblyError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setAssembly(null);
      });
    return () => {
      cancelled = true;
    };
  }, [job?.job_id]);

  useEffect(() => {
    checkHealth()
      .then((h) => {
        setLiveAvailable(h.live_transcription_available);
        setChatLive(h.live_chat_available === true || h.chat_mode === "live");
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

  const refreshAssets = useCallback(async (projectId: string): Promise<AssetData[]> => {
    setAssetsLoading(true);
    try {
      const [p, l] = await Promise.all([getProject(projectId), listAssets(projectId)]);
      setProject(p);
      setAssets(l.assets);
      setAssetsError(null);
      return l.assets;
    } catch (e) {
      setAssetsError(e instanceof ApiClientError ? e.message : "Could not load project assets.");
      return [];
    } finally {
      setAssetsLoading(false);
    }
  }, []);

  const [ideaTime, setIdeaTime] = useState(0);
  const ideaPreviewRef = useRef<IdeaPreviewHandle | null>(null);

  // Idea scenes for the timeline lanes (offsets in seconds, cumulative).
  // thumbUrl reuses the already-generated plate (mock or live) when present.
  // Animations carry per-step offsets so the FX lane mirrors the validated
  // storyboard — read-only visualisation, never an editing operation.
  const ideaScenes = useMemo(() => {
    const board = idea?.storyboard;
    if (!board) return null;
    let offset = 0;
    return board.scenes.map((scene) => {
      const entry = {
        id: scene.scene_id,
        title: scene.on_screen_text[0] ?? scene.narrative_purpose,
        lines: scene.on_screen_text,
        start: offset / 1000,
        duration: scene.duration_ms / 1000,
        thumbUrl:
          idea?.assets.find((a) => a.scene_ids.includes(scene.scene_id) && a.url)?.url ?? null,
        animations: (scene.animation_sequence ?? []).map((step) => ({
          primitive: step.primitive,
          target: step.target,
          start: step.start_ms / 1000,
          duration: step.duration_ms / 1000,
        })),
        transitionIn: scene.transition_in ?? null,
        transitionOut: scene.transition_out ?? null,
      };
      offset += scene.duration_ms;
      return entry;
    });
  }, [idea?.storyboard, idea?.assets]);

  const ideaActiveSceneId = useMemo(() => {
    if (!ideaScenes) return null;
    let current: string | null = null;
    for (const scene of ideaScenes) {
      if (ideaTime + 0.001 >= scene.start) current = scene.id;
    }
    return current;
  }, [ideaScenes, ideaTime]);

  // ADR-040 multitrack: global overlays as global-time blocks.
  const ideaOverlays = useMemo(() => {
    const overlays = idea?.storyboard?.overlays;
    if (!overlays) return null;
    return overlays.map((overlay) => ({
      id: overlay.overlay_id,
      title: overlay.text || overlay.asset_id || overlay.overlay_id,
      start: overlay.start_ms / 1000,
      duration: Math.max(0.01, (overlay.end_ms - overlay.start_ms) / 1000),
    }));
  }, [idea?.storyboard]);

  // Plates available for image overlays: generated only, never new spend.
  const overlayPlates = useMemo(
    () =>
      (idea?.assets ?? [])
        .filter((asset) => asset.status === "generated")
        .map((asset) => ({
          asset_id: asset.asset_id,
          label: `${asset.asset_id} · ${asset.role === "foreground" ? "frente" : "fundo"}`,
        })),
    [idea?.assets],
  );

  // A new plan resets the shared playhead.
  useEffect(() => {
    setIdeaTime(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idea?.storyboard_hash]);

  // When the idea render verifies, pull the generated assets into Recursos.
  const refreshedIdeaRef = useRef<string | null>(null);
  useEffect(() => {
    if (!idea || idea.status !== "completed" || !idea.project_id) return;
    const key = `${idea.idea_id}:completed`;
    if (refreshedIdeaRef.current === key) return;
    refreshedIdeaRef.current = key;
    void refreshAssets(idea.project_id).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idea?.idea_id, idea?.status, idea?.project_id]);

  const ensureProject = useCallback(async (): Promise<ProjectData> => {
    if (project) return project;
    setProjectBusy(true);
    try {
      const created = await createProject(file ? file.name.replace(/\.[^.]+$/, "") : "Projecto sem título");
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

  // Legenda honesta no chat: mostra o que seria detetado do rascunho atual,
  // mas só quando o automático se aplicaria (sem override manual).
  const detectedDuration = useMemo(
    () => (durationTouched ? null : detectDurationSeconds(draft)),
    [draft, durationTouched],
  );

  const storyboardCost = useMemo(() => {    if ((ideaModes?.director ?? "mock") !== "live") return 0;
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

  // ADR-044: restore the persisted job after reload so library assets stay
  // draggable and the timeline stays live without re-uploading. The preview
  // falls back to the registered session asset (served by the API); the
  // local File object cannot survive a reload.
  useEffect(() => {
    if (restoredJobRef.current) return;
    restoredJobRef.current = true;
    const storedId = typeof window !== "undefined" ? window.localStorage.getItem(JOB_STORAGE_KEY) : null;
    if (!storedId) return;
    void (async () => {
      try {
        const record = await getJob(storedId);
        setJob(record);
        setApiError(null);
        if (record.project_id) {
          const lib = await refreshAssets(record.project_id);
          const session = lib.find((a) => a.original_filename === record.original_filename);
          if (session) {
            setOriginalUrl(assetFileUrl(record.project_id, session.asset_id));
            setLocalMeta({
              width: record.source_info.width,
              height: record.source_info.height,
              duration: record.source_info.duration_seconds,
              hasAudio: record.source_info.has_audio,
            });
          }
        }
        if (["processing", "awaiting_approval", "awaiting_clarification", "awaiting_consent"].includes(record.status) || (record.status === "queued" && record.ready)) {
          pollJob(record.job_id);
        }
      } catch {
        window.localStorage.removeItem(JOB_STORAGE_KEY);
      }
    })();
  }, [pollJob, refreshAssets]);

  // ADR-044: the selected library asset, shown in the Properties tab.
  const selectedAsset = useMemo(
    () => assets.find((a) => a.asset_id === selectedAssetId) ?? null,
    [assets, selectedAssetId],
  );

  // ADR-044: the session asset id, used to auto-place the upload on V1.
  const sessionAssetId = useMemo(
    () => (job ? assets.find((a) => a.original_filename === job.original_filename)?.asset_id ?? null : null),
    [assets, job?.original_filename],
  );

  // ADR-044: first sight of an empty timeline on a fresh, instruction-free
  // job places the whole session clip on V1 — what the user sees in the
  // preview is what lands on the timeline. Once per job, silent on failure
  // (the user can always drag it manually).
  const autoPlacedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!job || !assembly || job.status !== "queued" || job.ready || result) return;
    if (assembly.timeline.clips.length > 0 || autoPlacedRef.current === job.job_id) return;
    const sessionDuration = job.source_info.duration_seconds || localMeta?.duration || 0;
    if (!sessionAssetId || !(sessionDuration >= 0.5)) return;
    autoPlacedRef.current = job.job_id;
    void (async () => {
      try {
        const data = await putTimeline(job.job_id, [
          {
            clip_id: newClipId(),
            asset_id: sessionAssetId,
            track: "V1",
            timeline_start_s: 0,
            source_in_s: 0,
            source_out_s: round3(Math.min(sessionDuration, 900)),
          },
        ]);
        setAssembly(data);
      } catch {
        autoPlacedRef.current = null; // retry on next relevant change, still silent
      }
    })();
  }, [job, assembly, result, sessionAssetId, localMeta?.duration]);

  function handleSelectAsset(assetId: string | null) {
    setSelectedAssetId(assetId);
  }

  async function uploadFileObject(f: File): Promise<JobResponse | null> {
    // Idempotent: exactly one job per selection. Extra selects while an
    // upload is in flight — or after a job exists — are ignored, so no AI
    // request can ever be triggered by uploading alone.
    if (uploadingRef.current || job) return null;
    uploadingRef.current = true;
    setFile(f);
    setError(null);
    setLocalMeta(null);
    setSelectedAssetId(null);
    if (originalUrl && originalUrl.startsWith("blob:")) URL.revokeObjectURL(originalUrl);
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
      window.localStorage.setItem(JOB_STORAGE_KEY, created.job_id);
      if (created.project_id && created.project_id !== active.project_id) {
        window.localStorage.setItem("clipforge.projectId", created.project_id);
      }
      setApiError(null);
      void refreshAssets(created.project_id ?? active.project_id);
      return created;
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Upload failed.");
      return null;
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
      if (selectedAssetId === assetId) setSelectedAssetId(null);
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

  // ADR-036: with a storyboard on screen, a confirmed instruction (voice or
  // typed) is a refinement of THAT video, not a new idea.
  const ideaDirectable = Boolean(
    idea?.storyboard &&
      (idea.can_approve_assets || idea.can_render || IDEA_TERMINAL.has(idea.status)),
  );

  // Director interview answers (empty platform): resent every turn until
  // the proposal is executed or cancelled. Server merges free-text parsing
  // over these; the server stays the source of truth for the flow.
  const [interviewAnswers, setInterviewAnswers] = useState<{
    style?: "cinematic" | "documentary" | "product" | "bold";
    duration_s?: number;
    aspect?: "9:16" | "16:9";
  }>({});
  // Original topic sentence: chips refine the slots but the proposal always
  // creates this brief. Reset on Executar/Cancelar or a fresh interview.
  const [interviewBrief, setInterviewBrief] = useState<string | null>(null);
  const [interviewCard, setInterviewCard] = useState<{
    question: string;
    chips: { label: string; value: string }[];
  } | null>(null);

  async function sendInstruction() {
    const text = draft.trim();
    if (!text || chatBusy || submitting || ideaBusy) return;
    // A new turn replaces any unconfirmed proposal: the server is the source
    // of truth for intent, the local card is just the last proposal.
    setPendingChat(null);
    setError(null);
    pushUserMessage(text);
    setDraft("");
    setChatBusy(true);
    try {
      // Fresh interview when nothing is in flight; otherwise the original
      // brief travels on and free text only refines the slots.
      const fresh = !interviewCard && Object.keys(interviewAnswers).length === 0;
      const brief = fresh ? text : (interviewBrief ?? text);
      if (fresh) setInterviewBrief(text);
      const history = messages.slice(-12).map((m) => ({ role: m.role, text: m.text }));
      const chat = await sendChat(text, job?.job_id ?? null, project?.project_id ?? null, selectedTextId, { ...interviewAnswers, brief }, idea?.idea_id ?? null, history);
      pushMuseMessage(chat.reply);
      setPendingChat(chat.needs_confirmation ? chat : null);
      if (chat.intent === "idea_interview" && chat.interview) {
        setInterviewAnswers(chat.interview.answered ?? {});
        if (chat.interview.brief) setInterviewBrief(chat.interview.brief);
        setInterviewCard(buildInterviewCard(chat.reply, chat.interview));
      } else {
        setInterviewCard(null);
        if (chat.intent !== "idea_proposal") {
          setInterviewAnswers({});
          setInterviewBrief(null);
        }
      }
      if (chat.select_text_id) setSelectedTextId(chat.select_text_id);
    } catch (e) {
      pushMuseMessage("Não consegui responder agora. Tenta de novo.");
      setError(e instanceof ApiClientError ? e.message : "Não consegui responder. Tenta de novo.");
    } finally {
      setChatBusy(false);
    }
  }

  function buildInterviewCard(question: string, interview: ChatInterview): {
    question: string;
    chips: { label: string; value: string }[];
  } | null {
    const need = interview.needed[0];
    if (need === "style" && interview.options.styles) {
      return { question, chips: interview.options.styles.map((s) => ({ label: s.label, value: s.label })) };
    }
    if (need === "duration_s" && interview.options.durations) {
      return { question, chips: interview.options.durations.map((d) => ({ label: `${d}s`, value: `${d} segundos` })) };
    }
    if (need === "aspect" && interview.options.aspects) {
      return {
        question,
        chips: interview.options.aspects.map((a) => ({
          label: a === "9:16" ? "Vertical 9:16" : "Horizontal 16:9",
          value: a === "9:16" ? "vertical" : "horizontal",
        })),
      };
    }
    return null;
  }

  async function sendInterviewChip(value: string) {
    if (chatBusy || submitting || ideaBusy) return;
    setPendingChat(null);
    setError(null);
    pushUserMessage(value);
    setChatBusy(true);
    try {
      const history = messages.slice(-12).map((m) => ({ role: m.role, text: m.text }));
      const chat = await sendChat(value, job?.job_id ?? null, project?.project_id ?? null, selectedTextId, { ...interviewAnswers, ...(interviewBrief ? { brief: interviewBrief } : {}) }, idea?.idea_id ?? null, history);
      pushMuseMessage(chat.reply);
      setPendingChat(chat.needs_confirmation ? chat : null);
      if (chat.intent === "idea_interview" && chat.interview) {
        setInterviewAnswers(chat.interview.answered ?? {});
        if (chat.interview.brief) setInterviewBrief(chat.interview.brief);
        setInterviewCard(buildInterviewCard(chat.reply, chat.interview));
      } else {
        setInterviewCard(null);
        if (chat.intent !== "idea_proposal") {
          setInterviewAnswers({});
          setInterviewBrief(null);
        }
      }
      if (chat.select_text_id) setSelectedTextId(chat.select_text_id);
    } catch (e) {
      pushMuseMessage("Não consegui responder agora. Tenta de novo.");
      setError(e instanceof ApiClientError ? e.message : "Não consegui responder. Tenta de novo.");
    } finally {
      setChatBusy(false);
    }
  }

  /** Chat video attach: the same upload path as Recursos, announced in chat. */
  async function handleAttachVideo(file: File) {
    if (uploading || uploadingRef.current || chatBusy) return;
    setError(null);
    pushUserMessage(`[vídeo anexado: ${file.name}]`);
    const created = await uploadFileObject(file);
    if (!created) {
      pushMuseMessage("Não consegui carregar o vídeo — verifica o formato (MP4/MOV/WebM/MKV) e tenta de novo.");
    } else {
      pushMuseMessage(`Vídeo "${created.original_filename}" pronto. Descreve a alteração — por voz ou por escrito — e eu trato do resto.`);
    }
  }

  async function executePendingTools(calls: ChatToolCall[], jobId: string) {
    const outcomes: string[] = [];
    for (const call of calls) {
      try {
        const { result } = await executeTool(jobId, call.tool, call.params as Record<string, unknown>);
        if (call.tool === "text.update" || call.tool === "text.create") {
          const item = (result.updated ?? result.created) as { overlay_id?: string } | undefined;
          if (item?.overlay_id) setSelectedTextId(item.overlay_id);
          outcomes.push(`${call.tool}: ok`);
        } else if (call.tool === "colour.set") {
          const c = result.colour as { contrast: number; brightness: number; saturation: number };
          setColour({ contrast: c.contrast, brightness: c.brightness, saturation: c.saturation });
          outcomes.push(`cor: contraste ${c.contrast.toFixed(2)}, brilho ${c.brightness.toFixed(2)}, saturação ${c.saturation.toFixed(2)}`);
        } else if (call.tool === "text.delete") {
          outcomes.push("texto removido");
        } else if (call.tool === "captions.create") {
          const created = (result.created ?? []) as { overlay_id?: string }[];
          if (created.length > 0) setSelectedTextId(created[0].overlay_id ?? null);
          const timing = (result.timing as string | undefined) ?? "tempo uniforme inicial";
          outcomes.push(`legendas: ${created.length} ${created.length === 1 ? "linha" : "linhas"} (${timing})`);
        } else if (call.tool === "captions.create_from_turns") {
          const created = (result.created ?? []) as { overlay_id?: string }[];
          if (created.length > 0) setSelectedTextId(created[0].overlay_id ?? null);
          outcomes.push(`legendas por turnos: ${created.length} ${created.length === 1 ? "linha" : "linhas"} (tempos reais do modelo)`);
        } else if (call.tool === "captions.translate") {
          const created = (result.created ?? []) as { overlay_id?: string }[];
          if (created.length > 0) setSelectedTextId(created[0].overlay_id ?? null);
          const tr = result.translation as { estimated_cost_usd?: number } | undefined;
          const cost = typeof tr?.estimated_cost_usd === "number" ? ` (~$${tr.estimated_cost_usd.toFixed(4)})` : "";
          outcomes.push(`legendas traduzidas: ${created.length} ${created.length === 1 ? "linha" : "linhas"}${cost} (tempo uniforme inicial)`);
        } else if (call.tool === "captions.cover") {
          outcomes.push(result.caption_cover ? "cobertura da faixa: ligada" : "cobertura da faixa: desligada");
        } else {
          outcomes.push(`${call.tool}: ok`);
        }
      } catch (e) {
        const msg = e instanceof ApiClientError ? e.message : "falhou";
        outcomes.push(`${call.tool}: ${msg}`);
        pushMuseMessage(`A ferramenta ${call.tool} falhou: ${msg}. Nada mais foi alterado por este passo.`);
        break;
      }
    }
    await refreshTextsFromBackend(jobId);
    pushMuseMessage(`Executei: ${outcomes.join(" · ")}. Revê no palco e nas Propriedades — o Montar inclui as alterações.`);
  }

  async function handleConfirmChatExecute() {
    const pending = pendingChat;
    if (!pending?.pending_text || submitting || ideaBusy || chatBusy) return;
    const text = pending.pending_text;
    // ADR-047 tool proposals execute really, one validated call at a time.
    if (pending.pending_kind === "tools" && pending.pending_tool_calls && pending.pending_tool_calls.length > 0) {
      if (!job) {
        setPendingChat(null);
        return;
      }
      const calls = pending.pending_tool_calls;
      setPendingChat(null);
      setChatBusy(true);
      try {
        await executePendingTools(calls, job.job_id);
      } finally {
        setChatBusy(false);
      }
      return;
    }
    setPendingChat(null);
    setInterviewCard(null);
    if (job) {
      setInterviewAnswers({});
      setInterviewBrief(null);
      await submitInstructionWith(text);
      return;
    }
    if (ideaDirectable) {
      setInterviewAnswers({});
      setInterviewBrief(null);
      await handleDirectIdeaWith(text);
      return;
    }
    // Director interview resolution travels with the confirmed proposal.
    const ideaOptions = pending.pending_idea_options ?? null;
    setInterviewAnswers({});
    setInterviewBrief(null);
    await handleCreateIdeaWith(text, ideaOptions);
  }

  function handleCancelChat() {
    setPendingChat(null);
    setInterviewCard(null);
    setInterviewAnswers({});
    setInterviewBrief(null);
  }

  function handleAdjustChat() {
    const pending = pendingChat;
    setPendingChat(null);
    if (pending?.pending_text) setDraft(pending.pending_text);
  }

  async function handleDirectIdeaWith(text: string) {
    if (!idea || !text.trim() || ideaBusy) return;
    setIdeaBusy("direct");
    setIdeaError(null);
    try {
      const data = await directIdea(idea.idea_id, text.trim(), storyboardCost);
      setIdea(data);
      rememberIdea(data.idea_id);
      setDraft("");
    } catch (e) {
      setIdeaError(e instanceof ApiClientError ? e.message : "Não consegui preparar o ajuste.");
    } finally {
      setIdeaBusy(null);
    }
  }

  async function handleDirectIdea() {
    await handleDirectIdeaWith(draft);
  }

  function handleApplyRefinement() {
    if (!idea) return;
    void runIdea("apply-refinement", () => applyRefinement(idea.idea_id));
  }

  function handleRejectRefinement() {
    if (!idea) return;
    void runIdea("reject-refinement", () => rejectRefinement(idea.idea_id));
  }

  async function submitInstructionWith(text: string) {
    if (!job || !text.trim()) return;
    setSubmitting(true);
    setError(null);
    setConsentError(null);
    try {
      const updated = await submitTranscript(
        job.job_id,
        text.trim(),
        transcript?.session_id ?? null,
      );
      setJob(updated);
      setVoiceSubmitted(true);
      pollJob(job.job_id);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Não consegui enviar. Tenta de novo.");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitInstruction() {
    await submitInstructionWith(draft);
  }

  async function runIdea(label: string, action: () => Promise<IdeaPayload>) {
    setIdeaBusy(label);
    setIdeaError(null);
    try {
      const data = await action();
      setIdea(data);
      rememberIdea(data.idea_id);
    } catch (e) {
      setIdeaError(e instanceof ApiClientError ? e.message : "Algo correu mal. Tenta de novo.");
    } finally {
      setIdeaBusy(null);
    }
  }

  async function handleCreateIdeaWith(
    text: string,
    interviewOptions?: {
      style: "cinematic" | "documentary" | "product" | "bold";
      duration_seconds: number;
      aspect_ratio: "9:16" | "16:9";
    } | null,
  ) {
    const clean = text.trim();
    if (!clean || ideaBusy) return;
    setIdeaBusy("create");
    setError(null);
    try {
      const cfg = ideaConfig ?? (await getIdeaConfig());
      setIdeaConfig(cfg);
      setApiError(null);
      // Ideas live in a project so generated plates, subtitles and the
      // final MP4 can be published back into Recursos on render.
      const active = project ?? (await ensureProject());
      // Precedence: director-interview answers (explicit) > manual pill >
      // text detection > product default. All local, no cost, visible.
      const options = { ...cfg.defaults, duration_seconds: pendingDuration };
      if (interviewOptions) {
        options.duration_seconds = interviewOptions.duration_seconds;
        options.aspect_ratio = interviewOptions.aspect_ratio;
        options.style_preset = interviewOptions.style;
        setPendingDuration(interviewOptions.duration_seconds);
      } else {
        // Automático: "25 segundos" no texto vence o default; a pill tocada
        // manualmente vence a deteção. Local, sem custo, visível no chat.
        const auto = durationTouched ? null : detectDurationSeconds(clean);
        const duration = auto ?? pendingDuration;
        if (auto != null) setPendingDuration(auto);
        options.duration_seconds = duration;
      }
      const data = await createIdea(clean, options, active.project_id);
      setIdea(data);
      rememberIdea(data.idea_id);
      setDraft("");
    } catch (e) {
      // No idea panel exists yet to show this: surface it in the top banner.
      setError(e instanceof ApiClientError ? e.message : "Não foi possível criar o vídeo da ideia.");
    } finally {
      setIdeaBusy(null);
    }
  }

  async function handleCreateIdea() {
    await handleCreateIdeaWith(draft);
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

  function handlePushBoard(board: Parameters<typeof patchIdeaStoryboard>[1]) {
    if (!idea?.storyboard_hash) return;
    const expectedHash = idea.storyboard_hash;
    void runIdea("edit-scenes", () => patchIdeaStoryboard(idea.idea_id, board, expectedHash));
  }

  function handleSaveSceneText(sceneId: string, lines: string[]) {
    if (!idea?.storyboard) return;
    handlePushBoard(updateSceneText(idea.storyboard, sceneId, lines));
  }

  function handleTrimScene(sceneId: string, durationMs: number) {
    if (!idea?.storyboard) return;
    handlePushBoard(trimSceneFromBoard(idea.storyboard, sceneId, durationMs));
  }

  function handleSplitScene(sceneId: string) {
    if (!idea?.storyboard) return;
    const scene = idea.storyboard.scenes.find((entry) => entry.scene_id === sceneId);
    if (!scene) return;
    // Divide na posição atual do playhead quando está dentro da cena (com
    // 1.2 s de margem); senão divide ao meio. Sempre explícito, sem custo.
    let offset = 0;
    for (const entry of idea.storyboard.scenes) {
      if (entry.scene_id === sceneId) break;
      offset += entry.duration_ms;
    }
    const playheadMs = Math.round(ideaTime * 1000);
    const inside = playheadMs - offset;
    const atMs =
      inside > 1200 && inside < scene.duration_ms - 1200 ? inside : Math.round(scene.duration_ms / 2);
    const board = splitSceneFromBoard(idea.storyboard, sceneId, atMs);
    if (!board) {
      setIdeaError("Não foi possível dividir: a cena precisa de pelo menos 2 s (1 s por metade).");
      return;
    }
    handlePushBoard(board);
  }

  function handleMoveScene(sceneId: string, direction: -1 | 1) {
    if (!idea?.storyboard) return;
    handlePushBoard(moveSceneInBoard(idea.storyboard, sceneId, direction));
  }

  function handleReorderScene(dragId: string, targetId: string, before: boolean) {
    if (!idea?.storyboard) return;
    handlePushBoard(reorderSceneInBoard(idea.storyboard, dragId, targetId, before));
  }

  function handleSetTransition(sceneId: string, transition: string) {
    if (!idea?.storyboard) return;
    handlePushBoard({
      ...idea.storyboard,
      scenes: idea.storyboard.scenes.map((scene) =>
        scene.scene_id === sceneId ? { ...scene, transition_out: transition } : scene,
      ),
    });
  }

  function handleSetTransitionMs(sceneId: string, ms: number) {
    if (!idea?.storyboard) return;
    const clamped = Math.min(1000, Math.max(200, Math.round(ms)));
    handlePushBoard({
      ...idea.storyboard,
      scenes: idea.storyboard.scenes.map((scene) =>
        scene.scene_id === sceneId ? { ...scene, transition_ms: clamped } : scene,
      ),
    });
  }

  function handleAddOverlay(text: string, startMs: number, endMs: number, kind: "text" | "image", assetId?: string) {
    if (!idea?.storyboard) return;
    if (kind === "image" && !assetId) {
      setIdeaError("Escolhe uma plate gerada para a sobreposição de imagem.");
      return;
    }
    const existing = new Set((idea.storyboard.overlays ?? []).map((o) => o.overlay_id));
    let n = (idea.storyboard.overlays?.length ?? 0) + 1;
    let overlay_id = `overlay_${n}`;
    while (existing.has(overlay_id)) {
      n += 1;
      overlay_id = `overlay_${n}`;
    }
    handlePushBoard({
      ...idea.storyboard,
      overlays: [
        ...(idea.storyboard.overlays ?? []),
        {
          overlay_id,
          kind,
          text: kind === "image" ? "" : text,
          asset_id: kind === "image" ? (assetId as string) : null,
          start_ms: Math.max(0, startMs),
          end_ms: Math.max(startMs + 1, endMs),
          style: {
            family: "sans",
            weight: 800,
            size_scale: 1,
            color: "#FFFFFF",
            align: "center",
            valign: "lower",
            letter_spacing_em: 0,
          },
        },
      ],
    });
  }

  function handleUpdateOverlayText(overlayId: string, text: string) {
    if (!idea?.storyboard?.overlays) return;
    handlePushBoard({
      ...idea.storyboard,
      overlays: idea.storyboard.overlays.map((overlay) =>
        overlay.overlay_id === overlayId ? { ...overlay, text } : overlay,
      ),
    });
  }

  function handleDeleteOverlay(overlayId: string) {
    if (!idea?.storyboard?.overlays) return;
    handlePushBoard({
      ...idea.storyboard,
      overlays: idea.storyboard.overlays.filter((overlay) => overlay.overlay_id !== overlayId),
    });
  }

  function handleDeleteScene(sceneId: string) {
    if (!idea?.storyboard || !idea.storyboard_hash) return;
    if (idea.storyboard.scenes.length <= 1) return;
    const scene = idea.storyboard.scenes.find((entry) => entry.scene_id === sceneId);
    const label = scene?.on_screen_text[0] ?? sceneId;
    if (
      typeof window !== "undefined" &&
      !window.confirm(`Eliminar a cena "${label}"? A duração é redistribuída e o vídeo terá de ser renderizado de novo.`)
    ) {
      return;
    }
    const board = deleteSceneFromBoard(idea.storyboard, sceneId);
    handlePushBoard(board);
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
    setDurationTouched(false);
    setPendingChat(null);
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

  function reset() {
    stopPolling();
    setMessages([]);
    notifiedRef.current.clear();
    lastSentRef.current = null;
    setPlanReview(null);
    setPlanDialogOpen(false);
    setDecisionSubmitting(null);
    setDecisionError(null);
    setConsentOpen(false);
    setConsentError(null);
    setFile(null);
    if (originalUrl && originalUrl.startsWith("blob:")) URL.revokeObjectURL(originalUrl);
    setOriginalUrl(null);
    setLocalMeta(null);
    setJob(null);
    setSelectedAssetId(null);
    setLeftTab("assets");
    setClipTexts([]);
    setSelectedTextId(null);
    setColour({ contrast: 1, brightness: 0, saturation: 1 });
    setColourNote(null);
    setTextsNote(null);
    window.localStorage.removeItem(JOB_STORAGE_KEY);
    setResult(null);
    setVoiceSubmitted(false);
    setAssembly(null);
    setAssemblyError(null);
    setRenderingTimeline(false);
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
    setPendingChat(null);
    setChatBusy(false);
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
    setDurationTouched(false);
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

  // Session chat log: real edit-job events, newest last, once each.
  useEffect(() => {
    if (!job) return;
    const key = `${job.job_id}:${job.status}:${job.stage}:${job.error?.code ?? ""}`;
    if (job.status === "awaiting_approval") {
      notifyOnce(key, "muse", "Plano pronto para revisão. Revê e decide abaixo.");
    } else if (job.status === "awaiting_consent") {
      notifyOnce(key, "muse", "Preciso da tua autorização para analisar as pessoas do vídeo antes de continuar.");
    } else if (job.status === "awaiting_clarification") {
      notifyOnce(key, "muse", "Tenho uma pergunta para afinar o plano.");
    } else if (job.status === "completed") {
      notifyOnce(key, "muse", "Vídeo pronto e verificado. Usa Exportar no topo para descarregar.");
    } else if (job.status === "rejected") {
      notifyOnce(key, "muse", "Plano rejeitado. O teu vídeo original ficou intacto.");
    } else if ((job.status === "failed" || job.status === "unsupported") && job.error) {
      notifyOnce(key, "muse", `Não consegui concluir: ${job.error.message}`);
    }
  }, [job?.job_id, job?.status, job?.stage, job?.error?.code, notifyOnce]);

  // Session chat log: real idea-job events, newest last, once each.
  useEffect(() => {
    if (!idea) return;
    const key = `${idea.idea_id}:${idea.status}:${idea.stage}:${idea.error?.code ?? ""}`;
    if (idea.stage === "awaiting_storyboard_cost") {
      notifyOnce(key, "muse", "Boa ideia. Aprova o custo do plano para eu começar.");
    } else if (idea.stage === "planning") {
      notifyOnce(key, "muse", "A planear o teu vídeo…");
    } else if (idea.stage === "awaiting_plan_approval") {
      notifyOnce(key, "muse", "Plano pronto. Revê as cenas e escolhe as imagens.");
    } else if (idea.stage === "generating_assets") {
      notifyOnce(key, "muse", "A gerar as imagens…");
    } else if (idea.stage === "rendering") {
      notifyOnce(key, "muse", "A montar as cenas…");
    } else if (idea.stage === "encoding" || idea.stage === "verifying_frames" || idea.stage === "verifying_output") {
      notifyOnce(key, "muse", "A finalizar o vídeo…");
    } else if (idea.status === "completed") {
      notifyOnce(key, "muse", "Vídeo pronto e verificado. Podes descarregar abaixo.");
    } else if (idea.status === "rejected") {
      notifyOnce(key, "muse", "Plano rejeitado. Nada foi gerado.");
    } else if (idea.status === "failed" && idea.error) {
      notifyOnce(key, "muse", `Não consegui concluir: ${idea.error.message}`);
    }
  }, [idea?.idea_id, idea?.status, idea?.stage, idea?.error?.code, notifyOnce]);

  // Refinement proposals arrive as chat turns (approval stays explicit).
  useEffect(() => {
    if (idea?.pending_patch) {
      notifyOnce(
        `patch:${idea.idea_id}:${idea.pending_patch.summary}`,
        "muse",
        `Preparei um ajuste: ${idea.pending_patch.summary} Revê e aprova abaixo — ainda não mudei nada.`,
      );
    } else if (idea?.pending_clarification_question) {
      notifyOnce(
        `refine-q:${idea.idea_id}:${idea.pending_clarification_question}`,
        "muse",
        idea.pending_clarification_question,
      );
    }
  }, [idea?.pending_patch, idea?.pending_clarification_question, idea?.idea_id, notifyOnce]);

  // Transcription finished: invite review (sending stays explicit).
  useEffect(() => {
    if (transcribeStatus !== "done" || !transcript) return;
    notifyOnce(
      `transcript:${transcript.session_id}`,
      "muse",
      "Transcrevi o teu áudio. Revê o texto e envia quando estiveres pronto.",
    );
  }, [transcribeStatus, transcript?.session_id, notifyOnce]);

  const studioStatus = useMemo((): { text: string | null; tone: "idle" | "working" | "attention" | "done" } => {
    if (uploading) return { text: "A enviar vídeo…", tone: "working" };
    if (job) {
      if (job.status === "queued") return { text: "Na fila", tone: "working" };
      if (job.status === "processing") {
        if (job.stage === "planning" || job.stage === "replanning") return { text: "A planear", tone: "working" };
        if (job.stage === "rendering") return { text: "A gerar", tone: "working" };
        if (job.stage === "verifying") return { text: "A verificar", tone: "working" };
        return { text: "A trabalhar", tone: "working" };
      }
      if (job.status === "awaiting_approval") return { text: "A aguardar revisão", tone: "working" };
      if (job.status === "awaiting_consent") return { text: "A aguardar autorização", tone: "working" };
      if (job.status === "awaiting_clarification") return { text: "Preciso de uma resposta", tone: "working" };
      if (job.status === "completed") return { text: "Concluído", tone: "done" };
      if (job.status === "rejected") return { text: "Rejeitado", tone: "idle" };
      return { text: "Falhou", tone: "attention" };
    }
    if (idea) {
      if (idea.status === "completed") return { text: "Concluído", tone: "done" };
      if (idea.status === "failed") return { text: "Falhou", tone: "attention" };
      if (idea.status === "rejected") return { text: "Rejeitado", tone: "idle" };
      if (idea.status === "awaiting_approval") return { text: "A aguardar aprovação", tone: "working" };
      return { text: "A trabalhar", tone: "working" };
    }
    return { text: null, tone: "idle" as const };
  }, [job?.status, job?.stage, idea?.status, idea?.stage, uploading]);

  // Right-column tabs: approvals live in Propriedades, answers in Muse.
  const ideaNeedsReview = Boolean(
    idea && (idea.can_approve_storyboard || idea.can_approve_assets || idea.pending_patch),
  );
  const rightSwitchTo = useMemo<"props" | "muse" | null>(() => {
    if (job?.status === "awaiting_approval") return "props";
    if (job?.status === "awaiting_clarification") return "muse";
    if (idea?.pending_clarification_question) return "muse";
    if (ideaNeedsReview) return "props";
    // ADR-047: a fresh Muse proposal (incl. tool calls) pulls the chat tab.
    if (pendingChat) return "muse";
    return null;
  }, [job?.status, idea?.pending_clarification_question, ideaNeedsReview, pendingChat]);

  const rightSwitchKey = useMemo<string | null>(() => {
    if (pendingChat) return `chat:${pendingChat.intent}:${pendingChat.reply.slice(0, 40)}`;
    if (job) return `job:${job.job_id}:${job.status}:${job.stage}`;
    if (idea) return `idea:${idea.idea_id}:${idea.status}:${idea.stage}`;
    return null;
  }, [pendingChat, job?.job_id, job?.status, job?.stage, idea?.idea_id, idea?.status, idea?.stage]);

  const propsAttention = useMemo(
    () =>
      job?.status === "awaiting_approval" ||
      job?.status === "awaiting_consent" ||
      ideaNeedsReview,
    [job?.status, ideaNeedsReview],
  );

  const museAttention = useMemo(
    () =>
      job?.status === "awaiting_clarification" ||
      job?.status === "failed" ||
      job?.status === "unsupported" ||
      idea?.status === "failed" ||
      Boolean(idea?.pending_clarification_question),
    [job?.status, idea?.status, idea?.pending_clarification_question],
  );

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

  // ADR-041 upload trim window (absolute seconds in the original file).
  const clipTrimWindow =
    job && job.trim_start_s != null && job.trim_end_s != null
      ? {
          start: job.trim_start_s,
          end: job.trim_end_s,
          original: job.original_duration_s ?? job.source_info.duration_seconds,
        }
      : null;
  const canEditClip = Boolean(job && job.status === "queued" && !job.ready);

  async function handleSaveTrim(start: number, end: number) {
    if (!job) return;
    setJob(await setTrim(job.job_id, start, end));
  }

  async function handleClearTrim() {
    if (!job) return;
    setJob(await setTrim(job.job_id, null, null));
  }

  async function handleSaveAudio(gain: number, fadeIn: number, fadeOut: number) {
    if (!job) return;
    setJob(await setUploadAudio(job.job_id, { gain_db: gain, fade_in_s: fadeIn, fade_out_s: fadeOut }));
  }

  async function handleSaveColour(next: { contrast: number; brightness: number; saturation: number }) {
    if (!job) return;
    setColourBusy(true);
    setColourNote(null);
    try {
      const res = await putColour(job.job_id, next);
      setColour({
        contrast: res.colour.contrast,
        brightness: res.colour.brightness,
        saturation: res.colour.saturation,
      });
    } catch (e) {
      setColourNote(e instanceof ApiClientError ? e.message : "Não consegui guardar a cor.");
    } finally {
      setColourBusy(false);
    }
  }

  function round3(value: number): number {
    return Math.round(value * 1000) / 1000;
  }

  async function pushAssembly(clips: TimelineClipData[]) {
    if (!job) return;
    setAssemblyError(null);
    try {
      const data = await putTimeline(job.job_id, clips);
      setAssembly(data);
    } catch (e) {
      setAssemblyError(e instanceof ApiClientError ? e.message : "Não consegui guardar a timeline.");
      try {
        setAssembly(await getTimeline(job.job_id));
      } catch {
        /* keep the stale arrangement on screen */
      }
    }
  }

  // ADR-044 smart drop: the user drops on ANY lane and the timeline routes
  // the asset by kind — video tries V1 then V2, audio tries A1 then A2, text
  // becomes a T1 overlay. Nothing is ever refused by track; only a truly
  // occupied stretch reports back (honest, actionable).
  function handleSmartDrop(
    at: number,
    asset: { asset_id: string; kind: string; duration: number; name?: string },
  ) {
    if (!job || !assembly) return;
    if (asset.kind === "text") {
      void handleTextDrop(at, asset);
      return;
    }
    const wantVideo = asset.kind === "video";
    if (!wantVideo && asset.kind !== "audio") return;
    if (!(asset.duration > 0)) {
      setAssemblyError("Este asset não tem duração mensurável.");
      return;
    }
    const dur = Math.max(0.5, Math.min(asset.duration, 900 - Math.max(0, at)));
    const tracks: TimelineTrack[] = wantVideo ? ["V1", "V2"] : ["A1", "A2"];
    const clips = assembly.timeline.clips;
    for (const track of tracks) {
      const start = Math.max(0, Math.min(at, 900 - dur));
      const end = start + dur;
      const clash = clips.some(
        (c) =>
          c.track === track &&
          start < c.timeline_start_s + (c.source_out_s - c.source_in_s) - 1e-9 &&
          end > c.timeline_start_s + 1e-9,
      );
      if (!clash && start + dur <= 900 + 1e-9) {
        void pushAssembly([
          ...clips,
          {
            clip_id: newClipId(),
            asset_id: asset.asset_id,
            track,
            timeline_start_s: round3(start),
            source_in_s: 0,
            source_out_s: round3(dur),
          },
        ]);
        return;
      }
    }
    setAssemblyError("Sem espaço livre aqui — move ou apara um clipe.");
  }

  // Text assets become T1 overlays (preview-only per ADR-045): the file
  // content seeds the overlay text, placed at the drop position.
  async function handleTextDrop(
    at: number,
    asset: { asset_id: string; kind: string; duration: number; name?: string },
  ) {
    if (!job) return;
    const prog = Math.max(
      1,
      (assembly && assembly.timeline.clips.length > 0 ? assembly.program_duration_s : effectiveDuration) || 6,
    );
    let text = asset.name ?? "Texto";
    try {
      const res = await fetch(assetFileUrl(project?.project_id ?? "", asset.asset_id));
      if (res.ok) {
        const raw = (await res.text()).slice(0, 4000);
        const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(0, 3);
        if (lines.length > 0) text = lines.join(" / ").slice(0, 140);
      }
    } catch {
      /* keep the filename as text */
    }
    const overlay = clampOverlay(
      {
        id: newClipTextId(),
        text,
        style: "rise" as ClipTextStyleId,
        start: Math.max(0, Math.min(at, Math.max(0, prog - 0.2))),
        duration: 2.5,
        x: 0.5,
        y: 0.78,
        scale: 1,
        color: "#FFFFFF",
        weight: "bold",
      },
      prog,
    );
    setClipTexts((current) => [...current.slice(0, 19), overlay]);
    setSelectedTextId(overlay.id);
    setLeftTab("text");
  }

  function handleMoveClip(clipId: string, newStart: number) {
    if (!job || !assembly) return;
    void pushAssembly(
      assembly.timeline.clips.map((c) =>
        c.clip_id === clipId
          ? {
              ...c,
              timeline_start_s: Math.max(
                0,
                Math.min(round3(newStart), 900 - (c.source_out_s - c.source_in_s)),
              ),
            }
          : c,
      ),
    );
  }

  function handleTrimClip(clipId: string, edge: "start" | "end", newT: number) {
    if (!job || !assembly) return;
    const target = assembly.timeline.clips.find((c) => c.clip_id === clipId);
    if (!target) return;
    const srcDur = assetDurations[target.asset_id] ?? Infinity;
    const dur = target.source_out_s - target.source_in_s;
    let start = target.timeline_start_s;
    let inn = target.source_in_s;
    let out = target.source_out_s;
    if (edge === "start") {
      const dt = newT - start;
      start = start + dt;
      inn = inn + dt;
    } else {
      out = out + (newT - (start + dur));
    }
    // Clamp: source bounds, minimum length, program bounds.
    if (inn < 0) {
      start -= inn;
      inn = 0;
    }
    if (out > srcDur) out = srcDur;
    if (out - inn < 0.5) {
      if (edge === "start") inn = out - 0.5;
      else out = inn + 0.5;
    }
    if (start < 0) {
      inn -= start;
      start = 0;
    }
    if (start + (out - inn) > 900) {
      if (edge === "start") {
        const over = start + (out - inn) - 900;
        start -= over;
        inn -= over;
      } else {
        out -= start + (out - inn) - 900;
      }
    }
    if (inn < 0 || out - inn < 0.5 || start < 0 || start + (out - inn) > 900 + 1e-9) return;
    void pushAssembly(
      assembly.timeline.clips.map((c) =>
        c.clip_id === clipId
          ? { ...c, timeline_start_s: round3(start), source_in_s: round3(inn), source_out_s: round3(out) }
          : c,
      ),
    );
  }

  function handleRemoveClip(clipId: string) {
    if (!job || !assembly) return;
    void pushAssembly(assembly.timeline.clips.filter((c) => c.clip_id !== clipId));
  }

  async function handleRenderTimeline() {
    if (!job || renderingTimeline) return;
    setRenderingTimeline(true);
    setAssemblyError(null);
    try {
      const updated = await renderTimeline(job.job_id, timelineFormat);
      setJob(updated);
      pollJob(job.job_id);
    } catch (e) {
      setAssemblyError(e instanceof ApiClientError ? e.message : "Não consegui renderizar a timeline.");
    } finally {
      setRenderingTimeline(false);
    }
  }

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

  return (
    <main className="flex min-h-screen flex-col bg-background lg:h-screen lg:overflow-hidden">
      <h1 className="sr-only">ClipForge — estúdio de edição de vídeo</h1>
      <a href="#viewer" className="sr-only focus:not-sr-only focus:bg-accent focus:px-3 focus:py-1.5 focus:text-sm focus:font-semibold focus:text-[#14110C]">
        Saltar para a pré-visualização
      </a>
      <TopBar
        projectName={project?.title ?? (file ? file.name.replace(/\.[^.]+$/, "") : "Projecto sem nome")}
        apiError={apiError}
        statusText={studioStatus.text}
        statusTone={studioStatus.tone}
        canExport={resultReady}
        exporting={exporting}
        onExport={handleExport}
        exportError={exportError}
        onRenameProject={(title) => void handleRenameProject(title)}
      />

      {apiError && (
        <div className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px]" role="alert">
          <span className="font-medium text-danger">Sem ligação à API.</span> {apiError} Inicia o backend e recarrega.
        </div>
      )}
      {error && (
        <div className="flex items-center gap-3 border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px]" role="alert">
          <span>
            <span className="font-medium text-danger">Algo correu mal:</span> {error}
          </span>
          <button type="button" onClick={reset} className="ml-auto shrink-0 font-medium text-danger underline">
            Recomeçar
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-2 bg-canvas p-2">
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)_360px] lg:grid-rows-[minmax(0,1fr)_auto] xl:grid-cols-[316px_minmax(0,1fr)_380px]">
        <div className="order-3 flex min-h-0 overflow-hidden rounded-lg border border-border bg-surface lg:order-1 lg:col-start-1 lg:row-start-1">
          <EditorRail active={leftTab} onSelect={setLeftTab} />
          {leftTab === "text" ? (
            <TextPanel
              texts={clipTexts}
              selectedId={selectedTextId}
              canAdd={Boolean(file || job)}
              onAdd={handleAddClipText}
              onSelect={setSelectedTextId}
              onDelete={handleRemoveClipText}
              onSeekText={handleSeek}
            />
          ) : (
          <MediaPanel
            file={file}
            originalUrl={originalUrl}
            localMeta={localMeta}
            jobMeta={jobMeta}
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
            onImportFiles={(files) => void handleImportFiles(files)}
            onDeleteAsset={(assetId) => void handleDeleteAsset(assetId)}
            onSelectAsset={handleSelectAsset}
            selectedAssetId={selectedAssetId}
          />
          )}
        </div>

        <div className="order-1 flex min-h-[52vh] flex-col overflow-hidden rounded-lg border border-border bg-canvas lg:order-2 lg:col-start-2 lg:row-start-1 lg:h-full lg:min-h-0">
          {idea && !job ? (
            <IdeaPreview ref={ideaPreviewRef} idea={idea} busy={ideaBusy} onTimeUpdate={setIdeaTime} />
          ) : (
            <Viewer
            originalUrl={originalUrl}
            editedUrl={editedUrl}
            resultReady={resultReady}
            displayFormat={socialFormat}
            onFormatChange={setSocialFormat}
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
            clipTexts={idea && !job ? [] : clipTexts}
            selectedTextId={selectedTextId}
            onSelectText={setSelectedTextId}
            onMoveText={(id, x, y) => handleUpdateClipText(id, { x, y })}
            onCommitText={(id, text) => handleUpdateClipText(id, { text })}
          />
          )}
        </div>

        <div className="order-2 flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface lg:order-3 lg:col-start-3 lg:row-start-1 lg:row-span-2">
          <RightPanel
            switchTo={rightSwitchTo}
            switchKey={rightSwitchKey}
            revealKey={selectedAssetId ?? selectedTextId}
            propsBadge={propsAttention || selectedTextId !== null}
            museBadge={museAttention}
            properties={
            <PropertiesPanel
              fileName={file?.name ?? null}
              statusText={studioStatus.text}
              meta={jobMeta}
              planSummary={planReview?.plan?.interpreted_intention ?? null}
              resultReady={resultReady}
              hasPlan={Boolean(planReview)}
              onOpenPlanReview={() => setPlanDialogOpen(true)}
              selectedText={
                selectedClipText
                  ? {
                      id: selectedClipText.id,
                      text: selectedClipText.text,
                      style: selectedClipText.style,
                      start: selectedClipText.start,
                      duration: selectedClipText.duration,
                      x: selectedClipText.x,
                      y: selectedClipText.y,
                      scale: selectedClipText.scale,
                      color: selectedClipText.color ?? "#FFFFFF",
                      weight: selectedClipText.weight ?? "bold",
                      styleOptions: CLIP_TEXT_STYLES.map((s) => ({ id: s.id, label: s.label })),
                    }
                  : null
              }
              onUpdateText={(patch) =>
                selectedClipText &&
                handleUpdateClipText(selectedClipText.id, {
                  text: patch.text,
                  style: patch.style as ClipTextOverlay["style"],
                  start: patch.start,
                  duration: patch.duration,
                  scale: patch.scale,
                  color: patch.color,
                  weight: patch.weight as ClipTextOverlay["weight"],
                })
              }
              onDeleteText={() => selectedClipText && handleRemoveClipText(selectedClipText.id)}
              colourEdit={
                job
                  ? {
                      contrast: colour.contrast,
                      brightness: colour.brightness,
                      saturation: colour.saturation,
                      busy: colourBusy,
                      onSave: handleSaveColour,
                      note: colourNote ?? textsNote,
                    }
                  : null
              }
              selectedAsset={
                selectedAsset
                  ? {
                      asset_id: selectedAsset.asset_id,
                      original_filename: selectedAsset.original_filename,
                      kind: selectedAsset.kind,
                      duration_seconds: selectedAsset.duration_seconds,
                      size_bytes: selectedAsset.size_bytes,
                      width: selectedAsset.width,
                      height: selectedAsset.height,
                      audio_codec: selectedAsset.audio_codec,
                      provenance: selectedAsset.provenance,
                    }
                  : null
              }
              onClearSelection={() => handleSelectAsset(null)}
              clipEdit={
                job
                  ? {
                      canEdit: canEditClip,
                      busy: uploading,
                      duration: effectiveDuration || undefined,
                      trim: job.trim_start_s != null && job.trim_end_s != null
                        ? { start: job.trim_start_s, end: job.trim_end_s, originalDuration: job.original_duration_s ?? job.source_info?.duration_seconds ?? 0 }
                        : null,
                      audio: { gainDb: job.audio_gain_db ?? 0, fadeIn: job.audio_fade_in_s ?? 0, fadeOut: job.audio_fade_out_s ?? 0 },
                      hasAudio: jobMeta?.has_audio ?? localMeta?.hasAudio ?? null,
                      onSaveTrim: (start, end) => handleSaveTrim(start, end),
                      onClearTrim: () => handleClearTrim(),
                      onSaveAudio: (gain, fadeIn, fadeOut) => handleSaveAudio(gain, fadeIn, fadeOut),
                    }
                  : null
              }
              activeScene={
                ideaScenes && ideaActiveSceneId
                  ? (() => {
                      const s = ideaScenes.find((scene) => scene.id === ideaActiveSceneId);
                      return s ? { title: s.title, start: s.start, duration: s.duration, lines: s.lines ?? [], transitionOut: s.transitionOut ?? null } : null;
                    })()
                  : null
              }
            >
              {idea ? (
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
                  onSaveSceneText={handleSaveSceneText}
                  onDeleteScene={handleDeleteScene}
                  onApplyRefinement={handleApplyRefinement}
                  onRejectRefinement={handleRejectRefinement}
                  onTrimScene={handleTrimScene}
                  onSplitScene={handleSplitScene}
                  onMoveScene={handleMoveScene}
                  onSetTransition={handleSetTransition}
                  onSetTransitionMs={handleSetTransitionMs}
                  onAddOverlay={handleAddOverlay}
                  onUpdateOverlayText={handleUpdateOverlayText}
                  onDeleteOverlay={handleDeleteOverlay}
                  plates={overlayPlates}
                />
              ) : undefined}
            </PropertiesPanel>
            }
            muse={
            <AssistantPanel
            messages={messages}
            job={job}
            resultReady={resultReady}
            planReview={planReview}
            onOpenPlanReview={() => setPlanDialogOpen(true)}
            onRejectPlan={() => void handleRejectPlan()}
            decisionBusy={decisionSubmitting !== null}
            working={renderingTimeline}
            liveAvailable={liveAvailable}
            chatLive={chatLive}
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
            draft={draft}
            onDraftChange={setDraft}
            onTranscribe={handleTranscribe}
            canConfirm={
              pendingChat
                ? false
                : job
                  ? Boolean(job.status === "queued" && !job.ready)
                  : ideaDirectable || !idea || IDEA_TERMINAL.has(idea.status)
            }
            confirming={submitting || ideaBusy === "create" || ideaBusy === "direct" || chatBusy}
            submitted={voiceSubmitted}
            onConfirmTranscript={sendInstruction}
            onRetry={reset}
            consentWaiting={job?.status === "awaiting_consent" && !consentOpen}
            onConsentContinue={reopenConsent}
            confirmLabel={
              !job && ideaDirectable
                ? "Pedir ajuste ao Muse"
                : !job && (!idea || IDEA_TERMINAL.has(idea.status))
                  ? "Criar vídeo desta ideia"
                  : undefined
            }
            showDurationChoices={!job && !ideaDirectable && (!idea || IDEA_TERMINAL.has(idea.status))}
            emptyPlatform={!job && !file && !uploading}
            pendingDuration={pendingDuration}
            pendingChat={pendingChat}
            chatBusy={chatBusy}
            interviewCard={interviewCard}
            onInterviewChip={(value) => void sendInterviewChip(value)}
            onAttachVideo={(file) => void handleAttachVideo(file)}
            onConfirmChat={() => void handleConfirmChatExecute()}
            onAdjustChat={handleAdjustChat}
            onCancelChat={handleCancelChat}
            onDurationChange={(seconds) => {
              setPendingDuration(seconds);
              setDurationTouched(true);
            }}
            detectedDuration={detectedDuration}
          />
            }
          />
        </div>

        <div className="order-4 min-h-0 lg:col-span-2 lg:col-start-1 lg:row-start-2">
      {idea && !job && ideaScenes ? (
        <Timeline
          file={null}
          duration={idea.storyboard ? idea.storyboard.duration_seconds : 0}
          currentTime={ideaTime}
          hasAudio={false}
          onSeek={(t) => ideaPreviewRef.current?.seek(t * 1000)}
          scenes={ideaScenes}
          activeSceneId={ideaActiveSceneId}
          onSeekScene={(t) => ideaPreviewRef.current?.seek(t * 1000)}
          onReorderScene={(dragId, targetId, before) => handleReorderScene(dragId, targetId, before)}
          overlays={ideaOverlays}
          trackLabel={`${ideaScenes.length} cenas`}
        />
      ) : !idea || job ? (
        <Timeline
          file={file}
          duration={
            job && assembly && assembly.timeline.clips.length > 0
              ? Math.max(assembly.program_duration_s, 0.01)
              : effectiveDuration
          }
          currentTime={currentTime}
          hasAudio={jobMeta ? jobMeta.has_audio : null}
          onSeek={handleSeek}
          editedReady={resultReady}
          trim={clipTrimWindow}
          assembly={
            job && assembly
              ? {
                  clips: assembly.timeline.clips,
                  programDuration: assembly.program_duration_s,
                  rendering: renderingTimeline,
                  renderError: assemblyError,
                  canRender: assembly.timeline.clips.length > 0,
                  format: timelineFormat,
                  onFormatChange: setTimelineFormat,
                  onAddClip: handleSmartDrop,
                  onMoveClip: handleMoveClip,
                  onTrimClip: handleTrimClip,
                  onRemoveClip: handleRemoveClip,
                  onRender: () => void handleRenderTimeline(),
                }
              : null
          }
          assetNames={assetNames}
          sessionAssetId={sessionAssetId}
          projectId={project?.project_id ?? null}
          trackLabel={
            job && assembly && assembly.timeline.clips.length > 0
              ? `${assembly.timeline.clips.length} clipes`
              : undefined
          }
          clipTexts={timelineClipTexts}
          selectedTextId={selectedTextId}
          onSelectText={setSelectedTextId}
          onSeekText={handleSeek}
          onMoveText={handleMoveClipText}
          onTrimText={handleTrimClipText}
          onRemoveText={handleRemoveClipText}
        />
      ) : null}
        </div>
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
