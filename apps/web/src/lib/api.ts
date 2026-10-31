import type { JobResponse, JobResultData, TranscriptData } from "./types";

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
  live_transcription_available: boolean;
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

export function uploadVideo(file: File, onProgress: (percent: number) => void): Promise<JobResponse> {
  const form = new FormData();
  form.append("file", file);
  return xhrUpload<JobResponse>("/api/uploads", form, onProgress);
}

/**
 * One explicit transcription request per call. Mock mode requires the selected
 * mock command because mocks never interpret audio; live mode uses the audio.
 */
export function transcribeRecording(
  blob: Blob,
  filename: string,
  opts: { mockFixtureId?: string; onProgress: (percent: number) => void },
): Promise<TranscriptData> {
  const form = new FormData();
  form.append("file", blob, filename);
  if (opts.mockFixtureId) form.append("mock_fixture_id", opts.mockFixtureId);
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
): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}/voice`, {
    method: "POST",
    body: JSON.stringify({
      transcript,
      transcription_session_id: transcriptionSessionId ?? undefined,
    }),
  });
}

export function getJob(jobId: string): Promise<JobResponse> {
  return requestJson<JobResponse>(`/api/jobs/${jobId}`);
}

export function getResult(jobId: string): Promise<JobResultData> {
  return requestJson<JobResultData>(`/api/jobs/${jobId}/result`);
}

export function downloadUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/download`;
}

export async function checkHealth(): Promise<TranscriptionConfig> {
  return requestJson<TranscriptionConfig>("/health");
}
