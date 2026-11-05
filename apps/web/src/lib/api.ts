import type { AssetData, JobResponse, JobResultData, PlanReviewData, ProjectData, TranscriptData } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiClientError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ApiClientError> {
  try {
    const body = await response.json();
    if (body?.error?.code) return new ApiClientError(response.status, body.error.code, body.error.message);
  } catch {
    /* fall through to generic */
  }
  return new ApiClientError(response.status, "http_error", `Request failed (${response.status}).`);
}

/** PT-AO user-facing error text. Raw backend messages are English and
 * technical — never show them to judges. Maps known API codes, falls back
 * to the caller-supplied PT message for everything else. */
export function friendlyApiError(e: unknown, fallback: string): string {
  if (e instanceof ApiClientError) {
    switch (e.code) {
      case "api_unreachable":
        return "Sem ligação à API. Inicia o backend e recarrega.";
      case "empty_file":
        return "O ficheiro chegou vazio. Escolhe o ficheiro outra vez.";
      case "unsupported_extension":
      case "unsupported_media":
      case "invalid_mime":
        return "Formato não suportado. Usa MP4, MOV, WebM, MP3, WAV, PNG, JPG, SVG ou texto.";
      case "file_too_large":
      case "media_too_long":
      case "upload_too_large":
        return "Ficheiro demasiado grande. O limite é 30 min em 720p.";
      case "upload_timeout":
        return "O envio demorou demasiado. Tenta de novo.";
      case "project_not_found":
      case "asset_not_found":
      case "job_not_found":
        return "Não encontrei esse elemento. Recarrega o projecto.";
      case "live_budget_exhausted":
      case "live_call_limit":
        return "Limite de uso atingido. Tenta mais tarde.";
      case "edit_window":
      case "timeline_locked":
      case "conflict":
        return "O vídeo já está noutra fase. Recarrega para ver o estado actual.";
      case "bad_response":
        return "Resposta ilegível da API. Recarrega e tenta de novo.";
      case "chunks_missing":
        return "Faltam partes do envio. A retomar automaticamente…";
      case "size_mismatch":
        return "O ficheiro chegou diferente do enviado. Tenta de novo.";
      case "assembly_failed":
        return "Não consegui juntar as partes. Tenta de novo.";
      case "upload_not_found":
        return "Sessão de envio expirada. Escolhe o ficheiro outra vez.";
      default:
        return fallback;
    }
  }
  return fallback;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiClientError(0, "api_unreachable", `Cannot reach the ClipForge API at ${API_BASE}. Is the backend running?`);
  }
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

export interface TranscriptionConfig {
  ai_mode: string;
  transcribe_mode: "mock" | "live";
  director_mode?: "mock" | "live";
  segmentation_mode?: "mock" | "live";
  image_mode?: "mock" | "live";
  chat_mode?: "mock" | "live";
  live_transcription_available: boolean;
  live_image_available?: boolean;
  live_chat_available?: boolean;
}

/** Real upload with real progress events (XMLHttpRequest; fetch cannot report upload progress). */
function xhrUpload<T>(
  path: string,
  form: FormData,
  onProgress: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.timeout = 60_000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () =>
      reject(new ApiClientError(0, "api_unreachable", `Cannot reach the ClipForge API at ${API_BASE}. Is the backend running?`));
    xhr.ontimeout = () => reject(new ApiClientError(0, "upload_timeout", "The upload timed out. Try again."));
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
        else reject(new ApiClientError(xhr.status, body?.error?.code ?? "http_error", body?.error?.message ?? `Request failed (${xhr.status}).`));
      } catch {
        reject(new ApiClientError(xhr.status, "bad_response", "The API returned an unreadable response."));
      }
    };
    xhr.send(form);
  });
}

/** Pending chunked upload, persisted by the Studio so an interrupted send
 * can resume after reload by re-selecting the same file. */
export interface PendingUpload {
  upload_id: string;
  filename: string;
  total_bytes: number;
  total_chunks: number;
  chunk_bytes: number;
  project_id: string | null;
}

export async function abortChunkedUpload(uploadId: string): Promise<void> {
  try {
    await requestJson<{ deleted: boolean }>(`/api/uploads/chunked/${encodeURIComponent(uploadId)}`, {
      method: "DELETE",
    });
  } catch {
    /* already gone or expired: disk cleanup is best-effort server-side */
  }
}

/** ADR-058 resumable chunked upload: init → PUT raw chunks (retry ×3,
 * resume via server status) → complete. Progress is real bytes, failures
 * surface friendly codes, and no job exists until complete succeeds.
 * Pass `resume` (from a previous interrupted send of the same file) to skip
 * re-sending chunks the server already holds; `onUploadId` persists the
 * session for cross-reload resume. */
export async function uploadVideoChunked(
  file: File,
  onProgress: (percent: number) => void,
  projectId?: string | null,
  chunkBytes: number = 8 * 1024 * 1024,
  resume?: PendingUpload | null,
  onUploadId?: (pending: PendingUpload) => void,
): Promise<JobResponse> {
  const totalChunks = Math.max(1, Math.ceil(file.size / chunkBytes));
  let uploadId: string;
  if (
    resume &&
    resume.filename === file.name &&
    resume.total_bytes === file.size &&
    resume.chunk_bytes === chunkBytes
  ) {
    uploadId = resume.upload_id;
    try {
      await requestJson<{ received: number[] }>(
        `/api/uploads/chunked/${encodeURIComponent(uploadId)}`,
      );
    } catch {
      uploadId = "";
    }
  } else {
    uploadId = "";
  }
  if (!uploadId) {
    const init = await requestJson<{ upload_id: string; total_chunks: number; received: number[] }>(
      "/api/uploads/chunked",
      {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          total_bytes: file.size,
          total_chunks: totalChunks,
          ...(projectId ? { project_id: projectId } : {}),
        }),
      },
    );
    uploadId = init.upload_id;
    onUploadId?.({
      upload_id: uploadId,
      filename: file.name,
      total_bytes: file.size,
      total_chunks: totalChunks,
      chunk_bytes: chunkBytes,
      project_id: projectId ?? null,
    });
  }
  let received = new Set<number>();
  try {
    const status = await requestJson<{ received: number[] }>(
      `/api/uploads/chunked/${encodeURIComponent(uploadId)}`,
    );
    received = new Set(status.received ?? []);
  } catch {
    /* fresh upload: nothing received yet */
  }
  let done = 0;
  for (const i of received) done += chunkLen(file.size, chunkBytes, i);
  const report = () => onProgress(file.size ? Math.min(100, Math.round((done / file.size) * 100)) : 0);
  report();
  for (let i = 0; i < totalChunks; i++) {
    if (received.has(i)) continue;
    const start = i * chunkBytes;
    const blob = file.slice(start, Math.min(file.size, start + chunkBytes));
    await putChunk(uploadId, i, blob, (loaded) => {
      onProgress(file.size ? Math.min(100, Math.round(((done + loaded) / file.size) * 100)) : 0);
    });
    done += blob.size;
    report();
  }
  return requestJson<JobResponse>(`/api/uploads/chunked/${encodeURIComponent(uploadId)}/complete`, {
    method: "POST",
  });
}

function chunkLen(total: number, chunkBytes: number, index: number): number {
  return Math.max(0, Math.min(total - index * chunkBytes, chunkBytes));
}

function putChunk(
  uploadId: string,
  index: number,
  blob: Blob,
  onChunkProgress: (loaded: number) => void,
): Promise<void> {
  const url = `${API_BASE}/api/uploads/chunked/${encodeURIComponent(uploadId)}/${index}`;
  const attempts = 3;
  const attempt = (n: number): Promise<void> =>
    new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", url);
      xhr.timeout = 120_000;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onChunkProgress(event.loaded);
      };
      xhr.onerror = () =>
        reject(new ApiClientError(0, "api_unreachable", `Cannot reach the ClipForge API at ${API_BASE}. Is the backend running?`));
      xhr.ontimeout = () => reject(new ApiClientError(0, "upload_timeout", "O envio demorou demasiado. A retomar…"));
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText || "{}");
          if (xhr.status >= 200 && xhr.status < 300) resolve();
          else
            reject(
              new ApiClientError(
                xhr.status,
                body?.error?.code ?? "http_error",
                body?.error?.message ?? `Request failed (${xhr.status}).`,
              ),
            );
        } catch {
          reject(new ApiClientError(xhr.status, "bad_response", "The API returned an unreadable response."));
        }
      };
      xhr.send(blob);
    }).catch((e) => {
      // Retry idempotent chunk PUTs (same bytes, same index); surface the
      // last error so the Studio banner stays truthful.
      if (n < attempts) return new Promise<void>((res) => { setTimeout(() => res(), 500 * n); }).then(() => attempt(n + 1));
      throw e;
    });
  return attempt(1);
}

export function createProject(title?: string): Promise<ProjectData> {
  return requestJson<ProjectData>("/api/projects", {
    method: "POST",
    body: JSON.stringify({ title: title ?? "Untitled project" }),
  });
}

export function listProjects(): Promise<{ projects: ProjectData[] }> {
  return requestJson<{ projects: ProjectData[] }>("/api/projects");
}

export function getProject(projectId: string): Promise<ProjectData> {
  return requestJson<ProjectData>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function renameProject(projectId: string, title: string): Promise<ProjectData> {
  return requestJson<ProjectData>(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function listAssets(projectId: string): Promise<{ assets: AssetData[] }> {
  return requestJson<{ assets: AssetData[] }>(`/api/projects/${encodeURIComponent(projectId)}/assets`);
}

export function uploadAsset(
  projectId: string,
  file: File,
  onProgress: (percent: number) => void,
): Promise<AssetData> {
  const form = new FormData();
  form.append("file", file);
  return xhrUpload<AssetData>(`/api/projects/${encodeURIComponent(projectId)}/assets`, form, onProgress);
}

export function deleteAsset(projectId: string, assetId: string): Promise<{ deleted: boolean }> {
  return requestJson<{ deleted: boolean }>(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}`, {
    method: "DELETE",
  });
}

export function assetFileUrl(projectId: string, assetId: string): string {
  return `${API_BASE}/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/file`;
}

/** ADR-057 native video understanding. One explicit approved analysis per call. */
export interface VideoAnalysisData {
  analysis_id: string;
  project_id: string;
  asset_id: string;
  source_sha256: string;
  provider: string;
  model: string;
  provider_response_id: string | null;
  video_duration_s: number | null;
  created_at: string;
  raw_text: string;
  overall_summary: string | null;
  visual_style: string | null;
  subjects: string[];
  objects_seen: string[];
  scenes: { index: number; start_s: number | null; end_s: number | null; approximate: boolean; description: string | null; main_subject: string | null; main_action: string | null; composition_note: string | null; editing_opportunity: string | null }[];
  important_moments: { at_s: number | null; approximate: boolean; label: string }[];
  composition_observations: string[];
  editing_opportunities: string[];
  uncertainties: string[];
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number;
  is_mock: boolean;
  file_reused: boolean;
}

export interface VideoAnalysisResult {
  analysis: VideoAnalysisData;
  video_mode: "mock" | "live";
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number; cost_usd?: number; estimated_cost_usd?: number; file_reused?: boolean; response_id?: string | null; file_id?: string | null };
}

export function getVideoAnalysis(projectId: string, assetId: string): Promise<{ analysis: VideoAnalysisData }> {
  return requestJson<{ analysis: VideoAnalysisData }>(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/analysis`);
}

export function analyzeVideo(
  projectId: string,
  assetId: string,
  body: { instruction?: string; approved_cost_usd: number },
): Promise<VideoAnalysisResult> {
  return requestJson<VideoAnalysisResult>(`/api/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/analyze`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * One explicit transcription request per call. Mock mode requires the selected
 * mock command because mocks never interpret audio; live mode uses the audio.
 */
export function transcribeRecording(
  blob: Blob,
  filename: string,
  opts: { onProgress: (percent: number) => void },
): Promise<TranscriptData> {
  const form = new FormData();
  form.append("file", blob, filename);
  return xhrUpload<TranscriptData>("/api/transcribe", form, opts.onProgress);
}

export function submitVoice(jobId: string, audioFixtureId: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/voice`, {
    method: "POST",
    body: JSON.stringify({ audio_fixture_id: audioFixtureId }),
  });
}

export function submitTranscript(
  jobId: string,
  transcript: string,
  transcriptionSessionId: string | null,
  subjectDetectionConsent?: boolean,
): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/voice`, {
    method: "POST",
    body: JSON.stringify({
      transcript,
      transcription_session_id: transcriptionSessionId ?? undefined,
      ...(subjectDetectionConsent === undefined
        ? {}
        : { subject_detection_consent: subjectDetectionConsent }),
    }),
  });
}

export function submitConsent(jobId: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/consent`, {
    method: "POST",
    body: JSON.stringify({ subject_detection_consent: true }),
  });
}

export function getJob(jobId: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}`);
}

export function getResult(jobId: string): Promise<JobResultData> {
  return requestJson<JobResultData>(`/api/jobs/${jobId}/result`);
}

export function getPlan(jobId: string): Promise<PlanReviewData> {
  return requestJson<PlanReviewData>(`/api/jobs/${jobId}/plan`);
}

export function approvePlan(
  jobId: string,
  note?: string,
  subjectIds?: string[],
): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/approve`, {
    method: "POST",
    body: JSON.stringify({
      note: note?.trim() || null,
      subject_ids: subjectIds && subjectIds.length > 0 ? subjectIds : null,
    }),
  });
}

export function subjectPreviewUrl(jobId: string, objectId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/subjects/${encodeURIComponent(objectId)}/preview`;
}

/** ADR-041 upload trim. Both null clears the trim. */
export function setTrim(
  jobId: string,
  start: number | null,
  end: number | null,
): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/trim`, {
    method: "POST",
    body: JSON.stringify({ start_s: start, end_s: end }),
  });
}

/** ADR-041 upload audio: gain + fades on the preserved original audio. */
export function setUploadAudio(
  jobId: string,
  body: { gain_db: number; fade_in_s: number; fade_out_s: number },
): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/audio`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function rejectPlan(jobId: string, note?: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/reject`, {
    method: "POST",
    body: JSON.stringify({ note: note?.trim() || null }),
  });
}

export function answerClarification(jobId: string, answer: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/clarify`, {
    method: "POST",
    body: JSON.stringify({ answer: answer.trim() }),
  });
}

export type ExportFormat = "original" | "reels" | "youtube";

export function downloadUrl(jobId: string, format: ExportFormat = "original"): string {
  return format === "original"
    ? `${API_BASE}/api/jobs/${jobId}/download`
    : `${API_BASE}/api/jobs/${jobId}/download?format=${format}`;
}

/** ADR-044 multitrack timeline assembly. Full replacement; server re-validates. */export interface TimelineClipData {
  clip_id: string;
  asset_id: string;
  track: "V1" | "V2" | "A1" | "A2";
  timeline_start_s: number;
  source_in_s: number;
  source_out_s: number;
}

export interface TimelineData {
  timeline: { clips: TimelineClipData[] };
  program_duration_s: number;
}

export function newClipId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return "clip_" + Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function getTimeline(jobId: string): Promise<TimelineData> {
  return requestJson<TimelineData>(`/api/jobs/${jobId}/timeline`);
}

export function putTimeline(jobId: string, clips: TimelineClipData[]): Promise<TimelineData> {
  return requestJson<TimelineData>(`/api/jobs/${jobId}/timeline`, {
    method: "PUT",
    body: JSON.stringify({ timeline: { clips } }),
  });
}

export type TimelineFormat = "source" | "landscape" | "portrait";

export function renderTimeline(jobId: string, format?: TimelineFormat): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/timeline/render`, {
    method: "POST",
    body: JSON.stringify({ format: format ?? "source" }),
  });
}

/** Drag-and-drop payload from Recursos rows/cards onto timeline lanes. */
export const TIMELINE_ASSET_MIME = "application/x-clipforge-asset";

export interface TimelineDragAsset {
  asset_id: string;
  kind: string;
  /** Media seconds (video/audio). Text assets carry 0/unknown. */
  duration: number;
  name: string;
}

export function readTimelineDrag(dataTransfer: DataTransfer): TimelineDragAsset | null {
  try {
    const raw = dataTransfer.getData(TIMELINE_ASSET_MIME);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<TimelineDragAsset>;
    if (typeof parsed.asset_id !== "string" || typeof parsed.kind !== "string") return null;
    const duration = typeof parsed.duration === "number" && Number.isFinite(parsed.duration)
      ? parsed.duration
      : 0;
    return {
      asset_id: parsed.asset_id,
      kind: parsed.kind,
      duration,
      name: typeof parsed.name === "string" ? parsed.name : parsed.asset_id,
    };
  } catch {
    return null;
  }
}

export async function checkHealth(): Promise<TranscriptionConfig> {
  return requestJson<TranscriptionConfig>("/health");
}

/** Conversational Muse turn. Side-effect free: the server never creates
 * jobs/ideas or calls providers here. Actionable intents return
 * needs_confirmation + pending_text (+ pending_tool_calls for edit-track
 * tools); the Studio executes via the existing voice/ideas/tools endpoints
 * only after the user presses Executar. */
export interface ChatToolCall {
  tool: string;
  params: Record<string, unknown>;
}

export interface ChatInterview {
  needed: string[];
  answered: {
    style?: "cinematic" | "documentary" | "product" | "bold";
    duration_s?: number;
    aspect?: "9:16" | "16:9";
  };
  /** Original topic sentence echoed by the server; chips never replace it. */
  brief?: string | null;
  options: {
    styles?: { id: string; label: string }[];
    durations?: number[];
    aspects?: string[];
  };
}

export interface ChatSegment {
  start_s: number;
  end_s: number;
}

export interface ChatData {
  intent: "smalltalk" | "help" | "status" | "cancel" | "clarify" | "edit_proposal" | "idea_proposal" | "idea_interview" | string;
  reply: string;
  needs_confirmation: boolean;
  pending_text: string | null;
  pending_kind: "edit" | "idea" | "tools" | "transcript" | null;
  pending_tool_calls?: ChatToolCall[];
  /** ADR-060 chunked source-transcription cost approval (blocks + USD). */
  pending_estimate?: { blocks: number; audio_seconds: number; billed_seconds: number; estimated_usd: number } | null;
  /** Timeline trecho the proposal is scoped to (validated server-side). */
  pending_segment?: ChatSegment | null;
  select_text_id?: string | null;
  /** ADR-053: "mock" = router local (sem custo); "live" = Muse Spark reescreveu a resposta (1 slot `chat` no ledger). */
  chat_mode?: "mock" | "live";
  chat_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number; cost_usd: number } | null;
  /** Resolved director-interview options: only present on a complete proposal. */
  pending_idea_options?: {
    style: "cinematic" | "documentary" | "product" | "bold";
    duration_seconds: number;
    aspect_ratio: "9:16" | "16:9";
  } | null;
  interview?: ChatInterview | null;
}

export interface SourceTranscriptStatus {
  status: "idle" | "estimate" | "running" | "completed" | "failed";
  needs_confirmation?: boolean;
  estimate?: { blocks: number; audio_seconds: number; billed_seconds: number; estimated_usd: number; window?: { start_s: number; end_s: number } };
  window?: { start_s: number; end_s: number };
  transcript?: string | null;
  turns?: { turn_id: number; start_ms: number; end_ms: number; text: string; speaker?: string | null }[];
  is_mock?: boolean;
  error?: { code: string; message: string } | null;
}

export function requestSourceTranscript(
  jobId: string,
  confirmed: boolean,
  segment?: { start_s: number; end_s: number } | null,
): Promise<SourceTranscriptStatus> {
  return requestJson<SourceTranscriptStatus>(`/api/jobs/${encodeURIComponent(jobId)}/source-transcript`, {
    method: "POST",
    body: JSON.stringify({
      confirmed,
      ...(segment ? { start_s: segment.start_s, end_s: segment.end_s } : {}),
    }),
  });
}

export function getSourceTranscript(jobId: string): Promise<SourceTranscriptStatus> {
  return requestJson<SourceTranscriptStatus>(`/api/jobs/${encodeURIComponent(jobId)}/source-transcript`);
}

export function sendChat(
  message: string,
  jobId?: string | null,
  projectId?: string | null,
  selectedTextId?: string | null,
  interview?: {
    style?: "cinematic" | "documentary" | "product" | "bold";
    duration_s?: number;
    aspect?: "9:16" | "16:9";
    brief?: string;
  } | null,
  ideaId?: string | null,
  history?: { role: "user" | "muse"; text: string }[] | null,
  segment?: ChatSegment | null,
  /** ADR-061: the library asset selected in Recursos (validated server-side). */
  selectedAssetId?: string | null,
): Promise<ChatData> {
  return requestJson<ChatData>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      ...(jobId ? { job_id: jobId } : {}),
      ...(projectId ? { project_id: projectId } : {}),
      ...(ideaId ? { idea_id: ideaId } : {}),
      ...(selectedTextId ? { selected_text_id: selectedTextId } : {}),
      ...(selectedAssetId ? { selected_asset_id: selectedAssetId } : {}),
      ...(interview && Object.keys(interview).length > 0 ? { interview } : {}),
      ...(history && history.length > 0 ? { history: history.slice(-12) } : {}),
      ...(segment ? { segment } : {}),
    }),
  });
}

/** ADR-047 selectable text overlays: full replacement, server re-validates. */
export interface ClipTextData {
  overlay_id: string;
  text: string;
  style: string;
  start_s: number;
  duration_s: number;
  x: number;
  y: number;
  scale: number;
  color: string;
  weight: string;
}

export function getClipTexts(jobId: string): Promise<{ texts: ClipTextData[] }> {
  return requestJson<{ texts: ClipTextData[] }>(`/api/jobs/${jobId}/texts`);
}

export function putClipTexts(jobId: string, texts: ClipTextData[]): Promise<{ texts: ClipTextData[] }> {
  return requestJson<{ texts: ClipTextData[] }>(`/api/jobs/${jobId}/texts`, {
    method: "PUT",
    body: JSON.stringify({ texts }),
  });
}

/** ADR-047 local colour grade. Identity = no visible change. */
export interface ColourData {
  contrast: number;
  brightness: number;
  saturation: number;
}

export function getColour(jobId: string): Promise<{ colour: ColourData }> {
  return requestJson<{ colour: ColourData }>(`/api/jobs/${jobId}/colour`);
}

export function putColour(jobId: string, colour: ColourData): Promise<{ colour: ColourData }> {
  return requestJson<{ colour: ColourData }>(`/api/jobs/${jobId}/colour`, {
    method: "PUT",
    body: JSON.stringify(colour),
  });
}

/** ADR-049 burned-in subtitle cover: fixed-geometry bottom-band blur. */
export function getCaptionCover(jobId: string): Promise<{ caption_cover: boolean }> {
  return requestJson<{ caption_cover: boolean }>(`/api/jobs/${jobId}/caption-cover`);
}

export function putCaptionCover(jobId: string, enabled: boolean): Promise<{ caption_cover: boolean }> {
  return requestJson<{ caption_cover: boolean }>(`/api/jobs/${jobId}/caption-cover`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

/** ADR-047 Muse tools: validated, real execution after confirmation. */
export interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export function listTools(jobId: string): Promise<{ tools: ToolDefinition[] }> {
  return requestJson<{ tools: ToolDefinition[] }>(`/api/jobs/${jobId}/tools`);
}

export function executeTool(
  jobId: string,
  tool: string,
  params: Record<string, unknown>,
): Promise<{ tool: string; result: Record<string, unknown> }> {
  return requestJson<{ tool: string; result: Record<string, unknown> }>(
    `/api/jobs/${jobId}/tools/execute`,
    { method: "POST", body: JSON.stringify({ tool, params }) },
  );
}
