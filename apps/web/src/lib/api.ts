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
        return "Ficheiro demasiado grande. O limite é 15 min em 720p.";
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

export function uploadVideo(file: File, onProgress: (percent: number) => void, projectId?: string | null): Promise<JobResponse> {
  const form = new FormData();
  form.append("file", file);
  if (projectId) form.append("project_id", projectId);
  return xhrUpload<JobResponse>("/api/uploads", form, onProgress);
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

export interface ChatData {
  intent: "smalltalk" | "help" | "status" | "cancel" | "clarify" | "edit_proposal" | "idea_proposal" | "idea_interview" | string;
  reply: string;
  needs_confirmation: boolean;
  pending_text: string | null;
  pending_kind: "edit" | "idea" | "tools" | null;
  pending_tool_calls?: ChatToolCall[];
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
): Promise<ChatData> {
  return requestJson<ChatData>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      ...(jobId ? { job_id: jobId } : {}),
      ...(projectId ? { project_id: projectId } : {}),
      ...(ideaId ? { idea_id: ideaId } : {}),
      ...(selectedTextId ? { selected_text_id: selectedTextId } : {}),
      ...(interview && Object.keys(interview).length > 0 ? { interview } : {}),
      ...(history && history.length > 0 ? { history: history.slice(-12) } : {}),
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
